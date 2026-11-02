/* Navigation only: reuse existing loaders, forms and mutation handlers. */
(() => {
  const tabs = [...document.querySelectorAll('[data-expense-view]')];
  if (!tabs.length) return;
  const wrapper = document.getElementById('card-review-detail');
  const overview = document.getElementById('expense-overview');
  const transactions = document.getElementById('expense-transactions');
  const panels = {saved: document.getElementById('saved-materials'), upload: document.getElementById('newupload'), rules: document.getElementById('rules')};
  const proposal = document.getElementById('rule-panel');
  if (proposal) panels.rules.querySelector('section').append(proposal);
  let current = 'cleanup';
  function syncTransactions() {
    const uploaded = document.getElementById('upload-results').childElementCount > 0 || location.hash === '#summary';
    transactions.hidden = current !== 'saved' && !(current === 'upload' && uploaded);
    const batch = typeof model !== 'undefined' ? model?.batch_id : null;
    document.querySelectorAll('[data-batch]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.batch === batch)));
  }
  new MutationObserver(syncTransactions).observe(document.getElementById('summary'), {childList: true});
  new MutationObserver(syncTransactions).observe(document.getElementById('upload-results'), {childList: true});
  function choose(view, focus = false, remember = false) {
    current = view;
    if (remember) {
      const hashes = {cleanup: 'expense-cleanup', saved: 'saved-materials', upload: 'newupload', rules: 'rules'};
      history.pushState(null, '', location.pathname + location.search + '#' + hashes[view]);
    }
    tabs.forEach(tab => {
      const active = tab.dataset.expenseView === view;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      if (focus && active) tab.focus();
    });
    overview.hidden = view !== 'cleanup';
    wrapper.open = view !== 'cleanup';
    Object.entries(panels).forEach(([key, panel]) => { panel.open = key === view; });
    syncTransactions();
    // The existing guarded loader fetches only on first entry to a card tool.
    if (view !== 'cleanup' && !document.getElementById('upload').disabled) startCardReview();
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
  Object.entries(panels).forEach(([view, panel]) => panel.addEventListener('toggle', () => {
    if (panel.open && current !== view) {
      if (view === 'upload' && ['cleanup', 'rules'].includes(current)) panel.open = false;
      else choose(view);
    }
  }));
  document.getElementById('batches').addEventListener('click', event => {
    const choice = event.target.closest('[data-batch]');
    if (!choice) return;
    document.querySelectorAll('[data-batch]').forEach(button => button.setAttribute('aria-pressed', String(button === choice)));
    const url = new URL(location.href);
    url.searchParams.set('batch', choice.dataset.batch);
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  });
  new MutationObserver(() => {
    if (current !== 'cleanup' && !document.getElementById('upload').disabled) startCardReview();
  }).observe(document.getElementById('upload'), {attributes: true, attributeFilter: ['disabled']});
  const initialView = () => {
    if (document.getElementById('upload').disabled && document.getElementById('upload-results').childElementCount) return 'upload';
    if (location.hash === '#expense-cleanup') return 'cleanup';
    if (location.hash === '#rules') return 'rules';
    if (location.hash === '#newupload' || location.hash === '#summary') return 'upload';
    if (new URLSearchParams(location.search).has('batch') || ['#preview', '#questions', '#saved-materials', '#ota-review'].includes(location.hash)) return 'saved';
    return 'cleanup';
  };
  window.addEventListener('hashchange', () => choose(initialView()));
  window.addEventListener('popstate', () => choose(initialView()));
  choose(initialView());
})();
