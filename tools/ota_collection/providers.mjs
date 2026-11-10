import {
  AGODA_PAGE_SIZE,
  AGODA_PHASE_DEFAULT,
  LIST_PAGE_LIMIT,
  STATUS,
  TRIP_COUNT,
} from './constants.mjs';
import { OtaError, isOtaError, statusForError } from './errors.mjs';

// Documented in the OTA portal procedure/SPEC §7 request templates only.
// No URL is invented: overrides may adjust these observed templates via opts.urls,
// and the origin may be overridden only to a documented host (opts.baseUrls/opts.origins).
export const PROVIDER_ACCESS = Object.freeze({
  agoda: Object.freeze({
    origin: 'https://www.agoda.com',
    hosts: ['www.agoda.com'],
    entry: '/ko-kr/account/bookings.html',
    urls: { list: '/api/ko-kr/mmbc/v2/GetBookingsList', detail: '/api/ko-kr/mmbc/eb/details' },
  }),
  trip: Object.freeze({
    origin: 'https://kr.trip.com',
    hosts: ['kr.trip.com', 'online.trip.com'],
    entry: '/account/signin',
    urls: {
      list: 'https://online.trip.com/restapi/soa2/26974/getAllOrders.json',
      detail: '/restapi/soa2/27453/GetOrderDetailOnline',
    },
  }),
  booking: Object.freeze({
    origin: 'https://secure.booking.com',
    hosts: ['secure.booking.com'],
    entry: '/mytrips.ko.html',
    urls: { list: '/dml/graphql?lang=ko' },
  }),
});

const AGODA_LOGIN_STATUSES = [401, 403];
const TRIP_LOGIN_STATUSES = [401, 403];
const BOOKING_LOGIN_STATUSES = [401, 403];

const AGODA_PHASES = ['Upcoming', 'Completed', 'Cancelled'];
// Negative lookahead also rejects a trailing newline (JS $ alone accepts it).
const AGODA_ID = /^\d{6,20}(?![\s\S])/;
const TRIP_ID = /^\d{8,20}(?![\s\S])/;

function validId(value, pattern) {
  if (typeof value !== 'string' && !(typeof value === 'number' && Number.isSafeInteger(value))) return false;
  return pattern.test(String(value));
}

function dig(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null) return value;
  }
  return undefined;
}

export function resolveAccess(name, opts = {}) {
  const descriptor = PROVIDER_ACCESS[typeof name === 'string' ? name : ''];
  if (!descriptor) return { error: 'UNKNOWN_PROVIDER', diagnostics: ['provider_unknown'] };
  let origin = descriptor.origin;
  const override = opts?.baseUrls?.[name] ?? opts?.origins?.[name];
  if (typeof override === 'string' && override.trim()) {
    try {
      const parsed = new URL(override);
      if (parsed.protocol !== 'https:' || !descriptor.hosts.includes(parsed.hostname)
        || parsed.username || parsed.password || parsed.port) {
        return { error: 'CONFIG', diagnostics: [`origin_override_not_documented:${parsed.hostname}`] };
      }
      origin = `${parsed.protocol}//${parsed.host}`;
    } catch {
      return { error: 'CONFIG', diagnostics: ['origin_override_invalid'] };
    }
  }
  const templates = { ...(descriptor.urls ?? {}) };
  if (descriptor.entry) templates.entry = descriptor.entry;
  if (opts.urls && typeof opts.urls === 'object' && Object.keys(opts.urls).length) {
    for (const [key, value] of Object.entries(opts.urls)) {
      if (templates[key] !== undefined && typeof value === 'string' && value.trim()) templates[key] = value;
    }
  }
  const urls = {};
  for (const [key, value] of Object.entries(templates)) {
    try {
      const parsed = new URL(value, origin);
      const observed = new URL(key === 'entry' ? descriptor.entry : descriptor.urls[key], descriptor.origin);
      if (parsed.origin !== observed.origin || parsed.pathname !== observed.pathname || parsed.username || parsed.password) {
        return { error: 'CONFIG', diagnostics: [`url_template_not_documented:${key}`] };
      }
      urls[key] = parsed.href;
    } catch {
      return { error: 'CONFIG', diagnostics: [`url_template_invalid:${key}`] };
    }
  }
  return {
    provider: name,
    origin,
    hosts: [...descriptor.hosts, new URL(origin).hostname],
    urls,
    error: null,
  };
}

export function assertAllowedUrl(href, access) {
  const provider = access?.provider ?? null;
  try {
    const parsed = new URL(href, access?.origin);
    const endpoint = Object.values(access?.urls ?? {}).some((value) => {
      const observed = new URL(value);
      return parsed.origin === observed.origin && parsed.pathname === observed.pathname;
    });
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || !endpoint) {
      throw new OtaError('URL_NOT_ALLOWED', { cls: 'config', diagnostic: `url_host:${parsed.hostname}`, provider });
    }
    return parsed.href;
  } catch (error) {
    if (isOtaError(error)) throw error;
    throw new OtaError('URL_NOT_ALLOWED', { cls: 'config', diagnostic: 'url_invalid', cause: error, provider });
  }
}

export async function enterProvider(ctx) {
  const access = ctx?.access;
  const navigation = {
    provider: ctx?.provider ?? null,
    origin: access?.origin ?? null,
    entry: access?.urls?.entry ?? null,
    verified: false,
    diagnostics: [],
    resume: [],
  };
  if (!access || access.error) {
    navigation.diagnostics.push('provider_access_config');
    return navigation;
  }
  if (typeof ctx.goto === 'function' && navigation.entry) {
    try {
      await ctx.goto(navigation.entry);
      navigation.verified = true;
    } catch (error) {
      throw new OtaError('NAVIGATION_FAILED', { diagnostic: 'page_navigation_failed',
        resume: 'navigation to the observed entry failed; no requests were sent', provider: ctx.provider });
    }
  } else if (navigation.entry) {
    navigation.diagnostics.push('page_navigation_unverified');
    navigation.resume.push('no goto capability supplied; request origin was not verified against the session page');
  }
  return navigation;
}

function loginOutcome(error) {
  if (isOtaError(error) && error.code === 'LOGIN_REQUIRED') {
    return { status: STATUS.LOGIN_REQUIRED, diagnostic: error.diagnostic ?? 'login_required', resume: error.resume ?? null, cls: 'auth' };
  }
  const status = isOtaError(error) ? statusForError(error) : 'FAILED';
  return {
    status,
    diagnostic: error?.diagnostic ?? error?.code ?? 'unknown_error',
    resume: error?.resume ?? null,
    cls: error?.cls ?? 'unknown',
  };
}

function isStopped(status) {
  return status === STATUS.LOGIN_REQUIRED || status === STATUS.INTERRUPTED;
}

function unattempted(entry) {
  return { item: entry, status: STATUS.SKIPPED, diagnostic: 'detail_not_attempted_after_stop',
    resume: null, file: null, record: null };
}

async function listWithBudget(ctx, loadPage, { pageLimit = LIST_PAGE_LIMIT } = {}) {
  const items = [];
  const diagnostics = [];
  const resume = [];
  let requests = 0;
  let cursor = null;
  let invalidItems = 0;
  const budget = ctx.budget;
  for (;;) {
    if (budget && typeof budget.listRequests === 'function' && budget.listRequests() >= pageLimit) {
      diagnostics.push(`list_limit_${pageLimit}_reached`);
      resume.push(`list request limit ${pageLimit} reached for this provider run; stopping is not an error state, and missing pages are not reported as complete`);
      return { status: STATUS.PARTIAL, items, diagnostics, resume, requests, cursor, invalidItems };
    }
    requests += 1;
    let page;
    try {
      page = await loadPage(cursor);
    } catch (error) {
      const failure = loginOutcome(error);
      if (failure.diagnostic) diagnostics.push(String(failure.diagnostic));
      if (failure.resume) resume.push(failure.resume);
      return { status: failure.status, items, diagnostics, resume, requests, cursor, invalidItems, cls: failure.cls };
    }
    if (!page || typeof page !== 'object') {
      diagnostics.push('page_result_invalid');
      resume.push('provider page result was not an object; verify the observed template');
      return { status: STATUS.CAPTURE_REQUIRED, items, diagnostics, resume, requests, cursor, invalidItems };
    }
    invalidItems += Number(page.invalidItems) || 0;
    if (invalidItems > 0) diagnostics.push('items_invalid');
    items.push(...(page.items ?? []));
    if (page.shapeError) {
      diagnostics.push(String(page.shapeError));
      resume.push('response shape not recognized; verify against the live response without guessing');
      return { status: STATUS.CAPTURE_REQUIRED, items, diagnostics, resume, requests, cursor, invalidItems };
    }
    if (page.resumeHold) {
      diagnostics.push(String(page.resumeHold));
      if (page.resume) resume.push(page.resume);
      return { status: STATUS.PARTIAL, items, diagnostics, resume, requests, cursor, invalidItems };
    }
    if (page.done) {
      return { status: invalidItems > 0 ? STATUS.PARTIAL : STATUS.OK, items, diagnostics, resume, requests, cursor, invalidItems };
    }
    if (page.hasMore === false || page.hasMore === undefined) {
      if (page.nextBodyObserved === false) {
        diagnostics.push('pagination_next_body_unobserved');
        if (page.resume) resume.push(page.resume);
        return { status: STATUS.PARTIAL, items, diagnostics, resume, requests, cursor, invalidItems };
      }
      return { status: invalidItems > 0 ? STATUS.PARTIAL : STATUS.OK, items, diagnostics, resume, requests, cursor, invalidItems };
    }
    cursor = page.next ?? null;
    if (cursor === null || cursor === undefined || cursor === '') {
      diagnostics.push('pagination_token_missing');
      resume.push('pagination continued but the next-page token was absent; completeness unverified');
      return { status: STATUS.PARTIAL, items, diagnostics, resume, requests, cursor: null, invalidItems };
    }
  }
}

function agodaListPage(ctx, url, body, phase) {
  return ctx.requestJson(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    json: { ...body, bookingPhase: phase, includeArchive: true },
    authStatuses: AGODA_LOGIN_STATUSES,
    provider: 'agoda',
  }).then(({ json }) => {
    const list = Array.isArray(json.bookings) ? json.bookings : Array.isArray(json?.data?.bookings) ? json.data.bookings : null;
    if (!list) return { items: [], done: false, hasMore: false, shapeError: 'response_shape' };
    const totalPages = json?.pagination?.totalPages;
    const pageIndex = Number(body.pageIndex);
    const items = [];
    let invalid = 0;
    for (const entry of list) {
      if (entry && typeof entry === 'object') {
        if (validId(entry.bookingId, AGODA_ID)) items.push(entry);
        else invalid += 1;
      } else {
        invalid += 1;
      }
    }
    if (!Number.isInteger(totalPages) || totalPages < 1) {
      return {
        items, invalidItems: invalid, done: false, hasMore: false, next: null, shapeError: null,
        resumeHold: 'pagination_total_pages_missing',
        resume: 'pagination.totalPages absent from response; page completeness unverified',
      };
    }
    return {
      items, invalidItems: invalid, hasMore: pageIndex < totalPages, next: pageIndex < totalPages ? pageIndex + 1 : null,
      done: pageIndex >= totalPages, shapeError: null, resumeHold: null, resume: null,
    };
  });
}

function tripListPage(ctx, url, cursor) {
  const body = { OrderStatusClassify: 'All', Count: TRIP_COUNT };
  // Only the caller's observed top-level request field may carry the opaque
  // response token. Never derive a request field from response field names.
  if (cursor !== null && cursor !== undefined) body[ctx.opts.tripOffsetField] = cursor;
  return ctx.requestJson(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    json: body,
    authStatuses: TRIP_LOGIN_STATUSES,
    provider: 'trip',
  }).then(({ json }) => {
    let list = null;
    if (Array.isArray(json?.OrderList)) list = json.OrderList;
    else if (Array.isArray(json?.data?.OrderList)) list = json.data.OrderList;
    else if (Array.isArray(json?.data)) list = json.data;
    if (!list) return { items: [], done: false, hasMore: false, shapeError: 'response_shape' };
    const rawCursor = dig(json?.Offset, json?.data?.Offset, json?.NextOffset, json?.nextOffset, json?.next_offset);
    const next = typeof rawCursor === 'string' && rawCursor.trim() ? rawCursor : (rawCursor === null || rawCursor === undefined ? null : String(rawCursor));
    const items = list.filter((entry) => entry && typeof entry === 'object' && validId(entry.OrderID, TRIP_ID));
    const invalid = list.length - items.length;
    if (items.length === 0) {
      return { items, invalidItems: invalid, done: true, hasMore: false, next: null, shapeError: null, resumeHold: null, resume: null };
    }
    if (!next && items.length >= TRIP_COUNT) {
      return {
        items, invalidItems: invalid, done: false, hasMore: false, next: null, shapeError: null,
        resumeHold: 'pagination_offset_missing_on_full_page',
        resume: 'Offset token absent on a full page; pagination cannot be verified from the response - counts may exceed what was collected',
      };
    }
    if (next) {
      const field = ctx?.opts?.tripOffsetField;
      if (typeof field !== 'string' || !field.trim()) {
        return {
          items, invalidItems: invalid, done: false, hasMore: false, next, shapeError: null, resumeHold: null,
          nextBodyObserved: false,
          resume: 'next-page request field not observed in a live request; not guessed, so the next page was not requested and completeness is unverified',
        };
      }
      return { items, invalidItems: invalid, done: false, hasMore: true, next, shapeError: null, resumeHold: null, nextBodyObserved: true, resume: null };
    }
    return { items, invalidItems: invalid, done: true, hasMore: false, next: null, shapeError: null, resumeHold: null, nextBodyObserved: null, resume: null };
  });
}

function extractTripSignature(entry) {
  const actions = Array.isArray(entry?.OrderActions) ? entry.OrderActions : [];
  for (const action of actions) {
    const href = typeof action === 'object' && action ? action.ActionURLH5 : null;
    if (typeof href !== 'string' || !href) continue;
    try {
      const param = new URL(href).searchParams.get('tripsignature');
      if (param) return param;
    } catch {
      const match = href.match(/[?&]tripsignature=([^&]+)/);
      if (match) return decodeURIComponent(match[1]);
    }
  }
  return null;
}

function walkOrderIds(node, found = new Set()) {
  if (node && typeof node === 'object') {
    if (Array.isArray(node)) {
      for (const value of node) walkOrderIds(value, found);
      return found;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key.toLowerCase() === 'orderid' && (typeof value === 'string' || typeof value === 'number') && String(value)) {
        found.add(String(value));
      } else {
        walkOrderIds(value, found);
      }
    }
  }
  return found;
}

function locateTrips(json) {
  const queue = [{ value: json, path: [], depth: 0 }];
  while (queue.length) {
    const { value, path, depth } = queue.shift();
    if (Array.isArray(value)) {
      const plausible = value.some((entry) => entry && typeof entry === 'object'
        && ['id', 'tripId', 'trip_id', 'tid'].some((key) => typeof entry[key] === 'string' || typeof entry[key] === 'number'));
      if (plausible) return { trips: value, path };
    }
    if (!value || typeof value !== 'object' || depth >= 5) continue;
    for (const [key, child] of Object.entries(value)) {
      queue.push({ value: child, path: [...path, key], depth: depth + 1 });
    }
  }
  return null;
}

export const providers = Object.freeze({
  agoda: {
    name: 'agoda',
    async run(ctx) {
      const access = ctx.access;
      if (!access || access.error) {
        return { listStatus: STATUS.INVALID, items: [], invalidItems: 0, outcomes: [], diagnostics: ['provider_access_config'], resume: ['fix provider URL configuration; no URL was guessed'], files: [] };
      }
      const phase = ctx.opts?.agodaBookingPhase ?? AGODA_PHASE_DEFAULT;
      if (!AGODA_PHASES.includes(phase)) {
        return { listStatus: STATUS.INVALID, items: [], invalidItems: 0, outcomes: [], diagnostics: ['option_invalid'], resume: ['bookingPhase must be Upcoming, Completed or Cancelled'], files: [] };
      }
      const page = await listWithBudget(ctx, (cursor) => agodaListPage(ctx, access.urls.list, { pageIndex: cursor ?? 1, pageSize: AGODA_PAGE_SIZE }, phase));
      const outcomes = [];
      let stopped = isStopped(page.status);
      const token = ctx.opts?.agodaDetailToken;
      for (const entry of page.items) {
        if (stopped) { outcomes.push(unattempted(entry)); continue; }
        const id = String(entry.bookingId);
        if (typeof token !== 'string' || !token.trim()) {
          outcomes.push({ item: entry, status: STATUS.CAPTURE_REQUIRED, diagnostic: 'detail_token_unobserved', resume: 'supply the token observed in a live details request; never guessed', file: null, record: null });
          continue;
        }
        try {
          const res = await ctx.requestJson(access.urls.detail, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            json: { BookingToken: entry.legacyBookingToken, isApp: false, token },
            authStatuses: AGODA_LOGIN_STATUSES,
            provider: 'agoda',
          });
          const details = res.json?.BookingDetails;
          if (!details || typeof details !== 'object') {
            ctx.countValidationFailure?.();
            outcomes.push({ item: entry, status: STATUS.CAPTURE_REQUIRED, diagnostic: 'detail_shape_missing', resume: 'details payload shape not recognized; verify against live response', file: null, record: null });
            continue;
          }
          // The importer contract requires the detail to attest the list booking id; a missing or different id is invalid, not success.
          const attested = String(details?.BookingQueryData?.CancellationReasonData?.BookingID ?? '');
          if (attested !== id) {
            ctx.countValidationFailure?.();
            outcomes.push({ item: entry, status: STATUS.INVALID, diagnostic: 'detail_identity_mismatch', resume: null, file: null, record: null });
            continue;
          }
          outcomes.push({
            item: entry,
            status: STATUS.OK,
            diagnostic: null,
            resume: null,
            file: `details/${id}.json`,
            record: { observed_at: new Date(ctx.clock()).toISOString(), list: entry, detail: res.json },
          });
        } catch (error) {
          const failure = loginOutcome(error);
          outcomes.push({ item: entry, status: failure.status, diagnostic: failure.diagnostic, resume: failure.resume, cls: failure.cls, file: null, record: null });
          stopped = isStopped(failure.status);
        }
      }
      return {
        provider: 'agoda',
        listStatus: page.status,
        items: page.items,
        invalidItems: page.invalidItems,
        outcomes,
        diagnostics: page.diagnostics,
        resume: page.resume,
      };
    },
  },

  trip: {
    name: 'trip',
    async run(ctx) {
      const access = ctx.access;
      if (!access || access.error) {
        return { listStatus: STATUS.INVALID, items: [], invalidItems: 0, outcomes: [], diagnostics: ['provider_access_config'], resume: ['fix provider URL configuration; no URL was guessed'], files: [] };
      }
      const page = await listWithBudget(ctx, (cursor) => tripListPage(ctx, access.urls.list, cursor));
      const outcomes = [];
      let stopped = isStopped(page.status);
      for (const entry of page.items) {
        if (stopped) { outcomes.push(unattempted(entry)); continue; }
        const orderId = String(entry.OrderID);
        const signature = extractTripSignature(entry);
        if (!signature) {
          outcomes.push({ item: entry, status: STATUS.CAPTURE_REQUIRED, diagnostic: 'tripsignature_missing', resume: 'capture the FrontHead.sign observed in the screen request; never guessed', file: null, record: null, orderId });
          continue;
        }
        try {
          const res = await ctx.requestJson(access.urls.detail, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            json: { orderId, FrontHead: { sign: signature } },
            authStatuses: TRIP_LOGIN_STATUSES,
            provider: 'trip',
          });
          const detail = res.json;
          const common = detail?.orderCommonInfo;
          const detailIds = walkOrderIds(detail);
          if (!common || typeof common !== 'object') {
            ctx.countValidationFailure?.();
            outcomes.push({ item: entry, status: STATUS.CAPTURE_REQUIRED, diagnostic: 'detail_shape_missing', resume: 'orderCommonInfo absent; verify against live response', file: null, record: null, orderId });
            continue;
          }
          if (String(common.orderId ?? '') !== orderId || detailIds.size !== 1 || !detailIds.has(orderId)) {
            ctx.countValidationFailure?.();
            outcomes.push({ item: entry, status: STATUS.INVALID, diagnostic: 'detail_identity_mismatch', resume: null, file: null, record: null, orderId });
            continue;
          }
          outcomes.push({
            item: entry,
            status: STATUS.OK,
            diagnostic: null,
            resume: null,
            file: `details/${orderId}.json`,
            record: { observed_at: new Date(ctx.clock()).toISOString(), order: entry, detail },
            orderId,
          });
        } catch (error) {
          const failure = loginOutcome(error);
          outcomes.push({ item: entry, status: failure.status, diagnostic: failure.diagnostic, resume: failure.resume, cls: failure.cls, file: null, record: null, orderId });
          stopped = isStopped(failure.status);
        }
      }
      return {
        provider: 'trip',
        listStatus: page.status,
        items: page.items,
        invalidItems: page.invalidItems,
        outcomes,
        files: page.items.length ? [{ file: 'orders.json', data: page.items }] : [],
        diagnostics: page.diagnostics,
        resume: page.resume,
      };
    },
  },

  booking: {
    name: 'booking',
    async run(ctx) {
      const access = ctx.access;
      if (!access || access.error) {
        return { listStatus: STATUS.INVALID, items: [], invalidItems: 0, outcomes: [], diagnostics: ['provider_access_config'], resume: ['fix provider URL configuration; no URL was guessed'], files: [] };
      }
      const query = ctx.opts?.bookingQuery;
      if (typeof query !== 'string' || !query.trim()) {
        return {
          listStatus: STATUS.CAPTURE_REQUIRED,
          items: [], invalidItems: 0, outcomes: [], diagnostics: ['template_unobserved'],
          resume: ['capture the UserTrips query text from a live screen request in this session; never guess the query'],
          files: [],
        };
      }
      let res;
      try {
        res = await ctx.requestJson(access.urls.list, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          json: { operationName: 'UserTrips', variables: {}, query },
          authStatuses: BOOKING_LOGIN_STATUSES,
          provider: 'booking',
        });
      } catch (error) {
        const failure = loginOutcome(error);
        return {
          listStatus: failure.status, items: [], invalidItems: 0, outcomes: [], files: [],
          diagnostics: [failure.diagnostic ?? 'request_failed'], resume: failure.resume ? [failure.resume] : [],
        };
      }
      const located = locateTrips(res.json);
      if (!located) {
        return {
          listStatus: STATUS.CAPTURE_REQUIRED,
          items: [], invalidItems: 0, outcomes: [], files: [],
          diagnostics: ['response_shape_unrecognized'],
          resume: ['response did not contain a recognizable trips array; read the captured response field names instead of guessing',
            'list detail via tab=bookings screen text and third-party confirm links has no stable template; unchanged and unsupported'],
        };
      }
      const items = [];
      let invalidItems = 0;
      for (const entry of located.trips) {
        if (!entry || typeof entry !== 'object') { invalidItems += 1; continue; }
        const id = dig(entry.id, entry.tripId, entry.trip_id, entry.tid);
        if (id === undefined || id === null || String(id).trim() === '') { invalidItems += 1; continue; }
        items.push({ id: String(id), raw: entry });
      }
      const diagnostics = [];
      const resume = [];
      let status = STATUS.OK;
      if (located.path.length > 0) {
        diagnostics.push('tolerant_locator');
        resume.push('trip fields were read with a tolerant locator; verify counts against the captured response');
        status = STATUS.PARTIAL;
      }
      if (invalidItems > 0) {
        diagnostics.push('items_invalid');
        status = STATUS.PARTIAL;
      }
      if (items.length === 0 && invalidItems === 0) {
        diagnostics.push('no_trips_in_located_array');
        status = items.length > 0 ? status : STATUS.CAPTURE_REQUIRED;
      }
      const more = dig(res.json?.data?.userTrips?.hasMore, res.json?.data?.userTrips?.hasNext,
        res.json?.data?.userTrips?.next, res.json?.data?.userTrips?.nextPage);
      if (more) {
        diagnostics.push('second_page_unsupported');
        resume.push('observed procedure reports the second cursor page request erroring; only the first page is collected and no success is claimed beyond it');
        status = STATUS.PARTIAL;
      }
      if (items.length > 0) {
        diagnostics.push('detail_unsupported');
        resume.push('booking trip detail not implemented: no stable template observed; screen text and partial confirm links are not treated as success');
        status = STATUS.PARTIAL;
      }
      const outcomes = items.map((item) => ({
        item,
        status: STATUS.SKIPPED,
        diagnostic: 'detail_unsupported',
        resume: 'booking trip detail not implemented: no stable template observed; screen text and partial confirm links are not treated as success',
        file: null,
        record: null,
      }));
      return { provider: 'booking', listStatus: status, items, invalidItems, outcomes, diagnostics, resume, files: [] };
    },
  },
});

export function providerNames() {
  return Object.keys(providers);
}

export function getProvider(name) {
  return providers[name] ?? null;
}

export { loginOutcome };
