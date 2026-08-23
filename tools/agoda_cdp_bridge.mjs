/*
 * Windows-native, loopback-only CDP helper for Agoda capture.
 *
 * This helper deliberately never reads browser cookies, storage, headers, or
 * network bodies.  It only evaluates the rendered Agoda DOM in a separately
 * launched headless Edge profile.  The parent process receives JSON over
 * stdout; callers should keep that stream private and write only normalized
 * staging records.
 */

// This is the historical Edge/CDP bridge.  Agoda collection is now owned by
// Paseo IAB; fail before opening a CDP socket or touching a browser session.
console.log(JSON.stringify({
  status: 'BLOCKED',
  failure_code: 'PASEO_IAB_ONLY',
  entrypoint: 'agoda_cdp_bridge',
  message: 'Use the Paseo IAB browser tool; the legacy Edge/CDP bridge is disabled.',
}));
process.exit(2);

const argv = process.argv.slice(2);

function option(name, fallback = undefined) {
  const index = argv.indexOf(name);
  return index >= 0 && index + 1 < argv.length ? argv[index + 1] : fallback;
}

const port = Number(option('--port', '9229'));
const operation = option('--operation', 'inspect');
const url = option('--url', 'https://www.agoda.com/ko-kr/');
const tab = option('--tab', '');
const bookingId = option('--booking-id', '');
const cardIndex = Number(option('--card-index', '-1'));
const pageNo = Number(option('--page-no', '1'));
const targetId = option('--target-id', '');
const waitMs = Math.max(250, Number(option('--wait-ms', '2500')));
const summaryOnly = argv.includes('--summary-only');

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('cdp_port_invalid');
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getTargets() {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  if (!response.ok) throw new Error('cdp_target_list_failed');
  return response.json();
}

function chooseTarget(targets) {
  const pages = targets.filter(
    (item) => item.type === 'page' && item.webSocketDebuggerUrl,
  );
  if (targetId) return pages.find((item) => item.id === targetId);
  const AgodaPage = pages.find((item) => /agoda\.com/i.test(item.url || ''));
  return AgodaPage || pages.find((item) => item.url === 'about:blank') || pages[0];
}

const targets = await getTargets();
const target = chooseTarget(targets);
if (!target?.webSocketDebuggerUrl) throw new Error('cdp_page_target_missing');

const socket = new WebSocket(target.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const settle = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) {
    settle.reject(new Error(message.error.message || 'cdp_command_failed'));
  } else {
    settle.resolve(message.result);
  }
});
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', () => reject(new Error('cdp_socket_error')), {
    once: true,
  });
});

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression, args = {}) {
  const names = Object.keys(args);
  if (names.some((name) => !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name))) {
    throw new Error('cdp_argument_name_invalid');
  }
  const globalObject = await command('Runtime.evaluate', {
    expression: 'globalThis',
    objectGroup: 'agoda-cdp-capture',
    returnByValue: false,
  });
  const objectId = globalObject.result?.objectId;
  if (!objectId) throw new Error('cdp_global_object_missing');
  const functionDeclaration = `function(${names.join(',')}) { return (${expression}); }`;
  const result = await command('Runtime.callFunctionOn', {
    objectId,
    functionDeclaration,
    objectGroup: 'agoda-cdp-capture',
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
    arguments: names.map((name) => ({ value: args[name] })),
  });
  if (result.exceptionDetails) throw new Error('cdp_runtime_evaluation_failed');
  return result.result?.value;
}

await command('Page.enable');
await command('Runtime.enable');

async function navigate(destination) {
  await command('Page.navigate', { url: destination });
  await sleep(waitMs);
}

async function waitForDom() {
  const deadline = Date.now() + Math.max(waitMs, 5000);
  while (Date.now() < deadline) {
    const ready = await evaluate('document.readyState');
    if (ready === 'interactive' || ready === 'complete') return;
    await sleep(250);
  }
  throw new Error('cdp_dom_ready_timeout');
}

const collectExpression = `(() => {
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const lines = (value) => String(value || '').split(/\\r?\\n/)
    .map(clean).filter(Boolean);
  const visible = (element) => {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && style.opacity !== '0' && rect.width > 0 && rect.height > 0;
  };
  const lower = (value) => clean(value).toLocaleLowerCase();
  const body = document.body ? document.body.innerText || '' : '';
  const bodyLower = lower(body);
  const customerServicePanelVisible = /아고다 고객 센터/i.test(body)
    && /요청 사항을 선택하거나 직접 입력해 주세요/i.test(body);
  const customerServiceControlPresent = Array.from(document.querySelectorAll(
    '[data-element-name="blp-booking-item-agoda-customer-service"],
     [data-element-name="iris-chat-prompt-button"], button, a, [role="button"]'
  )).some((element) => {
    if (!visible(element)) return false;
    const label = clean(element.innerText || element.getAttribute('aria-label') || '');
    const dataName = clean(element.getAttribute('data-element-name') || '');
    return dataName === 'blp-booking-item-agoda-customer-service'
      || dataName === 'iris-chat-prompt-button'
      || /고객센터|고객 센터|support|help|문의/i.test(label + ' ' + dataName);
  });
  const cardElements = Array.from(document.querySelectorAll('[class*="mmb-booking-card--"]'));
  const cards = cardElements.map((element, index) => {
    const className = String(element.className || '');
    const classMatch = className.match(/mmb-booking-card--([A-Za-z0-9_-]+)/);
    const text = lines(element.innerText || element.textContent || '');
    const joined = text.join(' ');
    const idMatch = joined.match(/(?:Manage booking|예약 관리|예약 확인\\/변경하기)\\D{0,20}(\\d{6,20})/i);
    const id = classMatch?.[1] || idMatch?.[1] || null;
    const status = text.find((value) => /^(Confirmed|Completed|Cancelled|Canceled|Pending|Refunded|Failed)$/i.test(value)) || 'unknown';
    const controls = Array.from(element.querySelectorAll('a,button,[role="button"]'));
    const manage = controls.find((control) => /manage booking|예약 관리|예약 확인\\/변경하기/i.test(clean(control.innerText || control.getAttribute('aria-label') || '')));
    const manageLabel = manage ? clean(manage.innerText || manage.getAttribute('aria-label') || '') : '';
    const manageIdMatch = manageLabel.match(/(?:Manage booking|예약 관리|예약 확인\\/변경하기)\\D{0,20}(\\d{6,20})/i);
    const hrefHasId = Boolean(id && manage?.href && new RegExp('(?:^|\\\\D)' + id + '(?:\\\\D|$)').test(manage.href));
    return {
      card_index: index,
      booking_id: id,
      status,
      values: text,
      manage_href: manage?.href || null,
      manage_id_attested: Boolean(id && ((manageIdMatch && manageIdMatch[1] === id) || hrefHasId)),
    };
  });
  const controls = Array.from(document.querySelectorAll('button,a,[role="tab"],[role="button"]'));
  const canonicalTab = (label) => {
    const value = clean(label).toLocaleLowerCase();
    if (value === 'upcoming' || value === '다가오는 예약') return 'Upcoming';
    if (value === 'completed' || value === '완료된 예약') return 'Completed';
    if (value === 'cancelled' || value === 'canceled' || value === '취소된 예약') return 'Cancelled';
    return null;
  };
  const isSelected = (control) => {
    const ariaSelected = control.getAttribute('aria-selected');
    const ariaCurrent = control.getAttribute('aria-current');
    const className = String(control.className || '').toLocaleLowerCase();
    return ariaSelected === 'true' || ariaCurrent === 'page' ||
      /(^|[\\s_-])(active|selected|current|on)([\\s_-]|$)/.test(className);
  };
  const tabs = controls.map((control) => {
    const label = clean(control.innerText || control.getAttribute('aria-label') || '');
    return {
      label,
      canonical: canonicalTab(label),
      selected: control.getAttribute('aria-selected') || null,
      current: control.getAttribute('aria-current') || null,
      active: isSelected(control),
    };
  }).filter((item) => item.canonical);
  const selectedTabs = tabs.filter((item) => item.selected === 'true' || item.active);
  const selectedTab = selectedTabs.length === 1 ? selectedTabs[0].canonical : null;
  const pageControls = controls.map((control) => {
    const label = clean(control.innerText || control.getAttribute('aria-label') || '');
    if (!/^\\d+$/.test(label)) return null;
    return {
      page: Number(label),
      selected: control.getAttribute('aria-selected') || null,
      current: control.getAttribute('aria-current') || null,
      active: isSelected(control),
    };
  }).filter(Boolean);
  const selectedPages = pageControls.filter((item) => item.selected === 'true' || item.current === 'page' || item.active);
  const selectedPage = selectedPages.length === 1
    ? selectedPages[0].page
    : (pageControls.length === 0 ? 1 : null);
  const nextControl = controls.find((control) => {
    const label = clean(control.innerText || control.getAttribute('aria-label') || control.getAttribute('title') || '');
    const rel = clean(control.getAttribute('rel') || '').toLocaleLowerCase();
    return rel === 'next' || /^(next|next page|다음|다음 페이지|›|»)$/.test(label.toLocaleLowerCase());
  });
  const nextDisabled = Boolean(nextControl && (
    nextControl.disabled ||
    nextControl.getAttribute('aria-disabled') === 'true' ||
    /(^|[\\s_-])disabled([\\s_-]|$)/i.test(String(nextControl.className || ''))
  ));
  const loginRequired = /sign[ -]?in|log[ -]?in|로그인|계정에 로그인/i.test(body);
  const authMarker = /my bookings|my reservations|upcoming bookings|completed bookings|다가오는 예약|완료된 예약/i.test(body);
  const errorMarker = /something went wrong|unable to load|network error|access denied|captcha|HTTP ERROR/i.test(bodyLower);
  return {
    url: location.href,
    title: document.title,
    ready_state: document.readyState,
    login_required: loginRequired,
    authenticated_page_marker: authMarker && !loginRequired,
    error_marker: errorMarker,
    card_count: cards.length,
    cards,
    tabs,
    selected_tab: selectedTab,
    selected_page: selectedPage,
    page_attested: selectedPages.length === 1 || pageControls.length === 0,
    page_values: Array.from(new Set(pageControls.map((item) => item.page))).sort((a, b) => a - b),
    has_next_page: Boolean(nextControl && !nextDisabled),
    next_page_control_present: Boolean(nextControl),
    identity_attested: cards.length === new Set(cards.map((item) => item.booking_id).filter(Boolean)).size &&
      cards.every((item) => item.booking_id && item.manage_id_attested),
    body_length: body.length,
    customer_service_panel_visible: customerServicePanelVisible,
    customer_service_control_present: customerServiceControlPresent,
  };
})()`;

async function collect() {
  await waitForDom();
  const result = await evaluate(collectExpression);
  if (!result || typeof result !== 'object') throw new Error('cdp_dom_summary_missing');
  if (summaryOnly) {
    return {
      url: result.url,
      title: result.title,
      ready_state: result.ready_state,
      login_required: result.login_required,
      authenticated_page_marker: result.authenticated_page_marker,
      error_marker: result.error_marker,
      card_count: result.card_count,
      tab_labels: result.tabs.map((item) => item.label),
      selected_tab: result.selected_tab,
      selected_page: result.selected_page,
      page_attested: result.page_attested,
      identity_attested: result.identity_attested,
      page_values: result.page_values,
      has_next_page: result.has_next_page,
      next_page_control_present: result.next_page_control_present,
      body_length: result.body_length,
      customer_service_panel_visible: result.customer_service_panel_visible,
      customer_service_control_present: result.customer_service_control_present,
    };
  }
  return result;
}

const detailCollectExpression = `(() => {
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const pageBody = document.body ? document.body.innerText || '' : '';
  const customerServicePanelVisible = /아고다 고객 센터/i.test(pageBody)
    && /요청 사항을 선택하거나 직접 입력해 주세요/i.test(pageBody);
  // The customer-support chat widget is mounted under document.body and can
  // contain unrelated historical booking IDs.  Scope detail capture to the
  // booking content root so those IDs cannot contaminate identity binding.
  const detailRoot = document.querySelector('#ebp-content');
  const body = detailRoot ? detailRoot.innerText || '' : '';
  const values = String(body).split(/\\r?\\n/).map(clean).filter(Boolean);
  const lowered = values.join(' ').toLocaleLowerCase();
  const loginRequired = /sign[ -]?in|log[ -]?in|로그인|계정에 로그인/i.test(lowered);
  const errorMarker = /something went wrong|unable to load|network error|access denied|captcha|http error/i.test(lowered);
  const detailMarker = values.some((value) => /^(booking id|예약\\s*번호|예약\\s*id)$/i.test(value))
    || /\\bbooking\\s*id\\b|예약\\s*번호|예약\\s*id/i.test(body);
  return {
    url: location.href,
    title: document.title,
    ready_state: document.readyState,
    login_required: loginRequired,
    error_marker: errorMarker,
    detail_marker: detailMarker,
    detail_scope_attested: Boolean(detailRoot && detailMarker),
    customer_service_panel_visible: customerServicePanelVisible,
    values,
    body_length: body.length,
  };
})()`;

async function collectDetail() {
  await waitForDom();
  const result = await evaluate(detailCollectExpression);
  if (!result || typeof result !== 'object' || !Array.isArray(result.values)) {
    throw new Error('cdp_detail_summary_missing');
  }
  if (summaryOnly) {
    return {
      url: result.url,
      title: result.title,
      ready_state: result.ready_state,
      login_required: result.login_required,
      error_marker: result.error_marker,
      detail_marker: result.detail_marker,
      detail_scope_attested: result.detail_scope_attested,
      customer_service_panel_visible: result.customer_service_panel_visible,
      value_count: result.values.length,
      body_length: result.body_length,
    };
  }
  return result;
}

async function clickTab(label) {
  const result = await evaluate(`((wanted) => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLocaleLowerCase();
    const aliases = {
      upcoming: ['upcoming', '다가오는 예약'],
      completed: ['completed', '완료된 예약'],
      cancelled: ['cancelled', 'canceled', '취소된 예약'],
    };
    const accepted = aliases[clean(wanted)] || [clean(wanted)];
    const controls = Array.from(document.querySelectorAll('button,a,[role="tab"],[role="button"]'));
    const control = controls.find((item) => accepted.includes(clean(item.innerText || item.getAttribute('aria-label') || '')));
    if (!control) return { ok: false, code: 'tab_control_missing' };
    control.click();
    return { ok: true };
  })(wanted)`, { wanted: label });
  if (!result?.ok) throw new Error(result?.code || 'tab_click_failed');
  await sleep(waitMs);
  return collect();
}

async function clickPage(page) {
  const result = await evaluate(`((wantedPage) => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    const controls = Array.from(document.querySelectorAll('button,a,[role="button"],[role="link"]'));
    const control = controls.find((item) => clean(item.innerText || item.getAttribute('aria-label') || '') === String(wantedPage));
    if (!control) return { ok: false, code: 'page_control_missing' };
    control.click();
    return { ok: true };
  })(wantedPage)`, { wantedPage: page });
  if (!result?.ok) throw new Error(result?.code || 'page_click_failed');
  await sleep(waitMs);
  return collect();
}

async function clickNextPage() {
  const result = await evaluate(`(() => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    const controls = Array.from(document.querySelectorAll('button,a,[role="button"],[role="link"]'));
    const control = controls.find((item) => {
      const label = clean(item.innerText || item.getAttribute('aria-label') || item.getAttribute('title') || '');
      const rel = clean(item.getAttribute('rel') || '').toLocaleLowerCase();
      return rel === 'next' || /^(next|next page|다음|다음 페이지|›|»)$/i.test(label);
    });
    if (!control) return { ok: false, code: 'next_page_control_missing' };
    if (control.disabled || control.getAttribute('aria-disabled') === 'true') {
      return { ok: false, code: 'next_page_control_disabled' };
    }
    control.click();
    return { ok: true };
  })()`);
  if (!result?.ok) throw new Error(result?.code || 'next_page_click_failed');
  await sleep(waitMs);
  return collect();
}

async function clickCard() {
  const result = await evaluate(`((wantedId, wantedIndex) => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    const pageBody = document.body ? document.body.innerText || '' : '';
    if (/아고다 고객 센터/i.test(pageBody)
      && /요청 사항을 선택하거나 직접 입력해 주세요/i.test(pageBody)) {
      return { ok: false, code: 'customer_service_panel_open' };
    }
    const cards = Array.from(document.querySelectorAll('[class*="mmb-booking-card--"]'));
    const card = cards.find((item, index) => {
      const classMatch = String(item.className || '').match(/mmb-booking-card--([A-Za-z0-9_-]+)/);
      const text = clean(item.innerText || item.textContent || '');
      const exactId = classMatch?.[1] === wantedId ||
        new RegExp('(?:^|\\\\D)' + wantedId + '(?:\\\\D|$)').test(text);
      return wantedId
        ? (exactId && (wantedIndex < 0 || index === wantedIndex))
        : index === wantedIndex;
    });
    if (!card) return { ok: false, code: 'card_missing' };
    const controls = Array.from(card.querySelectorAll('a,button,[role="button"]'));
    const manage = controls.find((item) =>
      item.getAttribute('data-element-name') === 'blp-booking-item-button-edit'
    ) || controls.find((item) =>
      /manage booking|예약 관리|예약 확인\\/변경하기/i.test(
        clean(item.innerText || item.getAttribute('aria-label') || '')
      )
    );
    if (!manage) return { ok: false, code: 'manage_booking_control_missing' };
    const manageText = clean(manage.innerText || manage.getAttribute('aria-label') || '');
    const manageData = clean(manage.getAttribute('data-element-name') || '');
    if (/고객센터|고객 센터|support|help|문의/i.test(manageText + ' ' + manageData)) {
      return { ok: false, code: 'customer_service_control_forbidden' };
    }
    manage.click();
    return { ok: true };
  })(wantedId, wantedIndex)`, { wantedId: bookingId, wantedIndex: cardIndex });
  if (!result?.ok) throw new Error(result?.code || 'card_click_failed');
  await sleep(waitMs);
  return collect();
}

async function inspectLinks() {
  return evaluate(`(() => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    return Array.from(document.querySelectorAll('a[href]')).map((anchor) => {
      try {
        const parsed = new URL(anchor.href, location.href);
        return {
          label: clean(anchor.innerText || anchor.getAttribute('aria-label') || ''),
          host: parsed.host,
          path: parsed.pathname,
        };
      } catch (_) {
        return null;
      }
    }).filter((item) => item && /agoda\\.com$/i.test(item.host)
      && /(booking|reservation|account|signin|login)/i.test(item.path))
      .slice(0, 80);
  })()`);
}

async function inspectControls() {
  return evaluate(`(() => {
    const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    return Array.from(document.querySelectorAll('button,[role="button"],[role="link"]'))
      .map((control) => ({
        label: clean(control.innerText || control.getAttribute('aria-label') || ''),
        role: control.getAttribute('role') || control.tagName.toLowerCase(),
      }))
      .filter((item) => item.label)
      .slice(0, 120);
  })()`);
}

let output;
if (operation === 'navigate-inspect') {
  await navigate(url);
  output = await collect();
} else if (operation === 'inspect') {
  output = await collect();
} else if (operation === 'select-tab') {
  output = await clickTab(tab);
} else if (operation === 'select-page') {
  output = await clickPage(pageNo);
} else if (operation === 'select-next-page') {
  output = await clickNextPage();
} else if (operation === 'open-card') {
  await clickCard();
  output = await collectDetail();
} else if (operation === 'click-card') {
  output = await clickCard();
} else if (operation === 'back') {
  await evaluate('history.back()');
  await sleep(waitMs);
  output = await collect();
} else if (operation === 'detail-inspect') {
  output = await collectDetail();
} else if (operation === 'inspect-links') {
  output = await inspectLinks();
} else if (operation === 'inspect-controls') {
  output = await inspectControls();
} else {
  throw new Error('cdp_operation_invalid');
}

console.log(JSON.stringify(output));
socket.close();
