/* Navigation only: reuse existing loaders, forms and mutation handlers. */
(() => {
  const allTabs = [...document.querySelectorAll('[data-expense-view]')];
  if (!allTabs.length) return;

  const wrapper = document.getElementById('card-review-detail');
  const overview = document.getElementById('expense-overview');
  const transactions = document.getElementById('expense-transactions');
  const uploadResults = document.getElementById('upload-results');
  const uploadButton = document.getElementById('upload');
  const panels = {
    saved: document.getElementById('saved-materials'),
    upload: document.getElementById('newupload'),
    rules: document.getElementById('rules'),
  };
  const panelForView = {cleanup: overview, ...panels};
  if (!wrapper || !overview) return;

  const tabs = allTabs.filter(tab => panelForView[tab.dataset.expenseView]);
  const availableViews = new Set(tabs.map(tab => tab.dataset.expenseView));
  if (!tabs.length) return;

  const proposal = document.getElementById('rule-panel');
  const rulesContent = panels.rules?.querySelector('section');
  if (proposal && rulesContent && !rulesContent.contains(proposal)) rulesContent.append(proposal);

  const hashes = {cleanup: 'expense-cleanup', saved: 'saved-materials', upload: 'newupload', rules: 'rules'};
  let current = 'cleanup';
  let seenLocation = locationKey();

  function locationKey() {
    return `${location.pathname}${location.search}${location.hash}`;
  }

  function supportedView(view) {
    return availableViews.has(view) ? view : 'cleanup';
  }

  function startReviewIfReady(view) {
    if (view !== 'cleanup' && typeof startCardReview === 'function'
        && (!uploadButton || !uploadButton.disabled)) startCardReview();
  }

  function syncTransactions() {
    if (transactions) {
      const uploaded = Boolean(uploadResults?.childElementCount) || location.hash === '#summary';
      transactions.hidden = current !== 'saved' && !(current === 'upload' && uploaded);
    }
    const batch = typeof model !== 'undefined' ? model?.batch_id : null;
    document.querySelectorAll('[data-batch]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.batch === batch)));
  }

  function observeIfPresent(id, options) {
    const target = document.getElementById(id);
    if (target && typeof MutationObserver !== 'undefined') {
      new MutationObserver(syncTransactions).observe(target, options);
    }
  }
  observeIfPresent('summary', {childList: true});
  observeIfPresent('upload-results', {childList: true});

  function choose(requestedView, focus = false, remember = false) {
    const view = supportedView(requestedView);
    if (remember) {
      const hash = hashes[view];
      if (hash && location.hash !== `#${hash}`) {
        history.pushState(null, '', `${location.pathname}${location.search}#${hash}`);
      }
      seenLocation = locationKey();
    }
    current = view;
    tabs.forEach(tab => {
      const active = tab.dataset.expenseView === view;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active) { const tools = tab.closest?.('.expense-tools'); if (tools) tools.open = true; }
      if (focus && active) tab.focus();
    });
    overview.hidden = view !== 'cleanup';
    wrapper.open = view !== 'cleanup';
    Object.entries(panels).forEach(([key, panel]) => {
      if (panel) panel.open = key === view;
    });
    syncTransactions();
    startReviewIfReady(view);
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => choose(tab.dataset.expenseView, false, true));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined) { event.preventDefault(); choose(tabs[next].dataset.expenseView, true, true); }
    });
  });

  // Existing upload/deep-link code can open a panel without clicking a tab.
  Object.entries(panels).forEach(([view, panel]) => {
    if (panel) panel.addEventListener('toggle', () => {
      if (panel.open && current !== view) {
        if (view === 'upload' && ['cleanup', 'rules'].includes(current)) panel.open = false;
        else choose(view);
      }
    });
  });

  const batches = document.getElementById('batches');
  if (batches) batches.addEventListener('click', event => {
    const choice = event.target.closest?.('[data-batch]');
    if (!choice) return;
    document.querySelectorAll('[data-batch]').forEach(button => button.setAttribute('aria-pressed', String(button === choice)));
    const url = new URL(location.href);
    url.searchParams.set('batch', choice.dataset.batch);
    history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    seenLocation = locationKey();
  });

  if (uploadButton && typeof MutationObserver !== 'undefined') {
    new MutationObserver(() => startReviewIfReady(current)).observe(uploadButton, {
      attributes: true,
      attributeFilter: ['disabled'],
    });
  }

  function initialView() {
    if (uploadButton?.disabled && uploadResults?.childElementCount) return supportedView('upload');
    if (location.hash === '#expense-cleanup') return supportedView('cleanup');
    if (location.hash === '#rules') return supportedView('rules');
    if (location.hash === '#newupload' || location.hash === '#summary') return supportedView('upload');
    if (new URLSearchParams(location.search).has('batch')
        || ['#preview', '#questions', '#saved-materials', '#ota-review'].includes(location.hash)) {
      return supportedView('saved');
    }
    return 'cleanup';
  }

  function syncFromLocation() {
    const nextLocation = locationKey();
    if (nextLocation === seenLocation) return;
    seenLocation = nextLocation;
    choose(initialView());
  }
  window.addEventListener('hashchange', syncFromLocation);
  window.addEventListener('popstate', syncFromLocation);
  choose(initialView());
})();
