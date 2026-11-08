(() => {
  const root = document.querySelector('[data-card-history-workspace]');
  if (!root) return;

  const csrf = root.dataset.csrf || '';
  const uploadPanel = document.getElementById('card-upload-panel');
  const coveragePanel = document.getElementById('card-coverage-panel');
  const uploadButton = document.getElementById('card-upload-open');
  const coverageButton = document.getElementById('card-coverage-open');
  const uploadInput = document.getElementById('card-upload-files');
  const uploadSubmit = document.getElementById('card-upload-submit');
  const uploadStatus = document.getElementById('card-upload-status');
  const uploadResults = document.getElementById('card-upload-results');
  const coverageRoot = document.getElementById('card-coverage-summary');
  const batchRoot = document.getElementById('card-upload-batch');
  const linkedTransaction = document.getElementById('card-linked-transaction');
  const jobKey = 'cost-card-upload-job';
  let selectedGap = null;

  const byId = id => document.getElementById(id);
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  };

  async function request(url, body, headers = {}) {
    let response;
    try {
      response = await fetch(url, body == null ? {cache: 'no-store', credentials: 'same-origin'} : {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: {'X-CSRF-Token': csrf, ...headers}, body
      });
    } catch {
      throw new Error('서버에 연결하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.');
    }
    let data;
    try { data = await response.json(); }
    catch { throw new Error(response.status === 401 ? '로그인한 뒤 다시 시도해 주세요.' :
      '응답을 읽지 못했습니다. 페이지를 새로고침해 다시 확인해 주세요.'); }
    if (!response.ok) throw new Error(data.message || data.code || '요청을 처리하지 못했습니다. 다시 시도해 주세요.');
    return data;
  }

  function query() { return new URLSearchParams(location.search); }
  function panelName() {
    const value = query().get('panel');
    return value === 'upload' || value === 'coverage' ? value : '';
  }
  function applyPanel(name) {
    const active = name === 'upload' || name === 'coverage' ? name : '';
    uploadPanel.hidden = active !== 'upload';
    coveragePanel.hidden = active !== 'coverage';
    uploadButton.setAttribute('aria-expanded', String(active === 'upload'));
    coverageButton.setAttribute('aria-expanded', String(active === 'coverage'));
    if (active === 'coverage') refreshCoverage();
    if (active === 'upload') {
      resumeUploads();
      showBatchDetail();
    }
  }
  function setPanel(name, {replace = false, focus = true} = {}) {
    const active = name === 'upload' || name === 'coverage' ? name : '';
    if (!active && root.dataset.cardUploadQuickView === 'true') {
      const destination = new URL(location.href);
      destination.searchParams.delete('panel');
      location.assign(destination.pathname + destination.search + destination.hash);
      return;
    }
    const url = new URL(location.href);
    if (name) url.searchParams.set('panel', name);
    else url.searchParams.delete('panel');
    if (replace) history.replaceState({}, '', url);
    else history.pushState({}, '', url);
    applyPanel(name);
    if (name && focus) {
      const target = name === 'upload' ? uploadPanel : coveragePanel;
      target.focus({preventScroll: true});
      target.scrollIntoView({block: 'nearest'});
    }
  }
  uploadButton.addEventListener('click', () => setPanel(panelName() === 'upload' ? '' : 'upload'));
  coverageButton.addEventListener('click', () => setPanel(panelName() === 'coverage' ? '' : 'coverage'));
  document.querySelectorAll('[data-card-panel-close]').forEach(button => {
    button.addEventListener('click', () => {
      const closed = button.dataset.cardPanelClose;
      setPanel('', {focus: false});
      (closed === 'coverage' ? coverageButton : uploadButton).focus();
    });
  });
  window.addEventListener('popstate', () => {
    if (root.dataset.cardUploadQuickView === 'true' && !panelName()) { location.reload(); return; }
    applyPanel(panelName());
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !panelName()) return;
    event.preventDefault();
    const active = panelName();
    setPanel('', {focus: false});
    (active === 'coverage' ? coverageButton : uploadButton).focus();
  });
  document.addEventListener('submit', event => {
    if (!event.target.matches('.card-all-filters')) return;
    const active = panelName();
    if (active && !event.target.elements.panel) {
      const field = document.createElement('input');
      field.type = 'hidden'; field.name = 'panel'; field.value = active;
      event.target.append(field);
    }
  });

  function currentGap() {
    const params = query();
    const cardId = params.get('gap_card') || '';
    const start = params.get('gap_start') || '';
    const end = params.get('gap_end') || '';
    if (!cardId || !/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return null;
    return {card_id: cardId, issuer: params.get('gap_issuer') || '',
      card_tail: params.get('gap_tail') || '', date_basis: params.get('gap_basis') || '', start, end};
  }
  function showGapContext() {
    selectedGap = currentGap();
    const context = byId('card-gap-context');
    if (!selectedGap) { context.hidden = true; context.textContent = ''; return; }
    context.hidden = false;
    context.textContent = `${selectedGap.issuer} · 끝${selectedGap.card_tail} · 거래일자 기준 ${selectedGap.start} ~ ${selectedGap.end} 자료를 추가합니다. 업로드 뒤 거래일자 공백을 다시 계산합니다.`;
  }
  function openGap(card, gap) {
    const url = new URL(location.href);
    url.searchParams.set('gap_card', card.card_id);
    url.searchParams.set('gap_start', gap.start);
    url.searchParams.set('gap_end', gap.end);
    url.searchParams.set('gap_issuer', card.issuer || '');
    url.searchParams.set('gap_tail', card.card_tail || '');
    url.searchParams.set('gap_basis', card.date_basis || '');
    history.pushState({}, '', url);
    showGapContext();
    setPanel('upload', {replace: true});
    uploadInput.focus({preventScroll: true});
  }
  showGapContext();

  function readJobs() {
    try {
      const saved = JSON.parse(localStorage.getItem(jobKey) || 'null');
      const jobs = Array.isArray(saved) ? saved : saved ? [saved] : [];
      return jobs.filter(job => job && job.status_url &&
        /^\/api\/imports\/upload-status\/[a-f0-9]{32}$/.test(job.status_url) &&
        /^batch-[a-f0-9]{24}$/.test(job.batch_id || ''));
    } catch { return []; }
  }
  function saveJob(job, finished = false) {
    try {
      const jobs = readJobs().filter(saved => saved.status_url !== job.status_url);
      if (!finished) jobs.push(job);
      if (jobs.length) localStorage.setItem(jobKey, JSON.stringify(jobs));
      else localStorage.removeItem(jobKey);
    } catch { /* The durable batch remains available from the saved file list. */ }
  }
  function resultEntry(name, message, state = 'pending') {
    const entry = node('li', 'card-upload-result');
    entry.dataset.state = state;
    entry.dataset.outcome = state;
    entry.append(node('strong', 'card-upload-result-name', name || '카드 파일'));
    entry.append(node('span', 'card-upload-result-state', message));
    uploadResults.hidden = false;
    uploadResults.append(entry);
    return entry;
  }
  function updateEntry(entry, message, state = 'pending', outcome = state) {
    entry.dataset.state = state;
    entry.dataset.outcome = outcome;
    entry.querySelector('.card-upload-result-state').textContent = message;
  }
  function batchLink(entry, batchId) {
    if (!/^batch-[a-f0-9]{24}$/.test(batchId || '')) return;
    const link = node('a', 'card-upload-result-link', '이 화면에서 처리 결과 보기');
    const params = new URLSearchParams(location.search);
    params.set('panel', 'upload'); params.set('batch', batchId);
    link.href = '/cards/all?' + params.toString();
    entry.append(link);
  }
  function uploadOutcome(result) {
    if (result.recovered_upload) return '저장된 업로드의 처리 상태를 확인했습니다.';
    const status = result.upload_summary && result.upload_summary.status;
    if (status === 'passed') return '분류 검사 통과';
    if (status === 'empty') return '거래 행이 없는 파일';
    if (status) return '분류 결과를 확인해 주세요.';
    return '파일 처리 결과를 확인했습니다.';
  }
  function showCoverageEvidence(entry, result, batchId) {
    if (batchId) {
      entry.append(node('p', 'card-upload-result-note', '거래일자가 확인되면 카드별 공백 현황에 반영됩니다.'));
    } else {
      entry.append(node('span', 'card-upload-result-note', '거래일자를 확인할 수 없습니다. 업로드 결과는 저장되어 있습니다.'));
    }
    if (selectedGap) {
      const gapNote = node('span', 'card-upload-result-note',
        '업로드 후 거래일자 공백 현황을 다시 계산합니다.');
      gapNote.dataset.gapCoverageOutcome = 'true';
      entry.append(gapNote);
    }
  }

  async function recoverUpload(job) {
    const state = await request(job.status_url + '?batch=' + encodeURIComponent(job.batch_id));
    const result = state.result;
    if (state.status !== 'saved' || result?.batch_id !== job.batch_id ||
        typeof result.recovery?.pending !== 'boolean') throw new Error('저장된 파일의 처리 결과를 다시 확인하고 있습니다.');
    if (result.recovery.pending) throw new Error('파일은 저장됐지만 처리 결과를 확인할 수 없습니다. 아래 처리 결과 링크에서 다시 확인해 주세요.');
    saveJob(job, true);
    return {...result, recovered_upload: true};
  }
  async function awaitUpload(job, entry) {
    saveJob(job);
    let failures = 0;
    const started = Date.now();
    while (true) {
      try {
        const response = await fetch(job.status_url, {cache: 'no-store', credentials: 'same-origin',
          signal: AbortSignal.timeout(10000)});
        if (response.status === 401 || response.status === 403) throw new Error('로그인 또는 업로드 권한을 확인해 주세요.');
        if (response.status === 404) {
          try { return await recoverUpload(job); }
          catch (error) { failures += 1; updateEntry(entry, error.message); }
        } else if (!response.ok) throw new Error('처리 상태를 다시 확인하고 있습니다.');
        else {
          const state = await response.json();
          if (state.status === 'done') {
            saveJob(job, true);
            return state.result || {};
          }
          if (state.status === 'error') {
            saveJob(job, true);
            const error = new Error(state.message || '파일 처리에 실패했습니다. 저장된 파일의 결과를 확인해 주세요.');
            error.cardUploadStatus = 'server-error';
            throw error;
          }
          failures = 0;
          updateEntry(entry, (state.message || '파일 처리 중') + ' · ' + Math.floor((Date.now() - started) / 1000) + '초');
        }
      } catch (error) {
        if (error.cardUploadStatus === 'server-error') throw error;
        if (error.message && /로그인|권한/.test(error.message)) {
          error.cardUploadStatus = 'unknown';
          throw error;
        }
        failures += 1;
        updateEntry(entry, error.message || '처리 상태를 다시 확인하고 있습니다.');
        if (failures >= 5) {
          const unknown = new Error('저장된 처리 상태를 확인하지 못했습니다. 다시 조회하거나 처리 결과를 확인해 주세요.');
          unknown.cardUploadStatus = 'unknown';
          throw unknown;
        }
      }
      await new Promise(resolve => setTimeout(resolve, Math.min(10000, failures ? 1000 * 2 ** failures : 1500)));
    }
  }
  async function showResult(entry, job, result) {
    updateEntry(entry, uploadOutcome(result), 'saved', 'saved');
    batchLink(entry, result.batch_id || job.batch_id);
    showCoverageEvidence(entry, result, result.batch_id || job.batch_id);
  }
  async function resumeUploads() {
    const jobs = readJobs();
    if (!jobs.length || uploadResults.dataset.resuming === 'true') return;
    uploadResults.dataset.resuming = 'true';
    const previousRetry = byId('card-upload-resume-retry');
    if (previousRetry) previousRetry.remove();
    if (panelName() !== 'upload') {
      const url = new URL(location.href); url.searchParams.set('panel', 'upload');
      history.replaceState({}, '', url);
      uploadPanel.hidden = false; coveragePanel.hidden = true;
      uploadButton.setAttribute('aria-expanded', 'true');
      coverageButton.setAttribute('aria-expanded', 'false');
    }
    uploadResults.replaceChildren();
    const note = byId('card-upload-resume-status');
    note.hidden = false;
    note.textContent = jobs.length + '개 파일의 저장된 처리 상태를 확인하고 있습니다.';
    const entries = jobs.map(job => resultEntry(job.filename, '저장된 처리 상태를 확인하고 있습니다.'));
    let cursor = 0;
    const worker = async () => {
      while (cursor < jobs.length) {
        const index = cursor++; const job = jobs[index];
        try { await showResult(entries[index], job, await awaitUpload(job, entries[index])); }
        catch (error) {
          const outcome = error.cardUploadStatus === 'server-error' ? 'server-error' : 'unknown';
          updateEntry(entries[index], error.message, 'error', outcome);
          batchLink(entries[index], job.batch_id);
        }
      }
    };
    await Promise.all(Array.from({length: Math.min(4, jobs.length)}, worker));
    const outcomes = entries.map(entry => entry.dataset.outcome);
    const saved = outcomes.filter(outcome => outcome === 'saved').length;
    const serverErrors = outcomes.filter(outcome => outcome === 'server-error').length;
    const unknown = outcomes.filter(outcome => outcome === 'unknown').length;
    note.textContent = `처리 상태 확인: 완료 ${saved}개 · 서버 오류 ${serverErrors}개 · 상태 미확인 ${unknown}개.`;
    delete uploadResults.dataset.resuming;
    if (unknown) {
      const retry = node('button', 'card-workspace-secondary', '미확인 상태 다시 조회');
      retry.id = 'card-upload-resume-retry';
      retry.type = 'button';
      retry.addEventListener('click', resumeUploads);
      uploadResults.after(retry);
    }
    await refreshCoverage();
  }

  uploadInput.addEventListener('change', () => {
    const files = [...uploadInput.files];
    byId('card-upload-selection').textContent = files.length ?
      files.length + '개 파일 선택 · ' + files.map(file => file.name).join(', ') : '선택된 파일 없음';
  });
  uploadSubmit.addEventListener('click', async () => {
    if (uploadSubmit.disabled) return;
    const files = [...uploadInput.files];
    if (!files.length) { uploadStatus.textContent = '업로드할 카드 파일을 선택해 주세요.'; uploadInput.focus(); return; }
    if (files.length > 100 || files.reduce((sum, file) => sum + file.size, 0) > 99 * 1024 * 1024) {
      uploadStatus.textContent = '한 번에 100개, 전체 99MB 이하로 나누어 선택해 주세요.'; return;
    }
    uploadSubmit.disabled = true; uploadInput.disabled = true;
    uploadResults.hidden = false; uploadResults.replaceChildren();
    uploadStatus.textContent = files.length + '개 파일을 안전하게 접수하고 있습니다. 접수 완료까지 이 페이지를 유지해 주세요.';
    const entries = files.map(file => resultEntry(file.name, '파일 접수 중'));
    try {
      const body = new FormData(); for (const file of files) body.append('files', file);
      const received = await request('/api/imports/upload-batch', body);
      if (!Array.isArray(received.files) || received.files.length !== files.length) {
        throw new Error('접수 결과를 확인하지 못했습니다. 저장된 카드 파일 목록에서 상태를 다시 확인해 주세요.');
      }
      for (const job of received.files) if (job.status_url) saveJob(job);
      uploadInput.value = '';
      byId('card-upload-selection').textContent = '선택된 파일 없음';
      uploadStatus.textContent = received.files.filter(job => job.status_url).length +
        '개 파일 접수 완료 · 분류가 백그라운드에서 진행됩니다.';
      await Promise.all(received.files.map(async (job, index) => {
        const entry = entries[index];
        if (!job.status_url) {
          updateEntry(entry, '접수 실패 · ' + (job.message || '파일을 접수하지 못했습니다.'), 'error');
          return;
        }
        try { await showResult(entry, job, await awaitUpload(job, entry)); }
        catch (error) { updateEntry(entry, error.message, 'error'); batchLink(entry, job.batch_id); }
      }));
      uploadStatus.textContent = '파일별 처리 결과를 확인해 주세요. 거래일자 공백 현황을 갱신했습니다.';
      await refreshCoverage();
    } catch (error) { uploadStatus.textContent = error.message; }
    finally { uploadSubmit.disabled = false; uploadInput.disabled = false; }
  });

  function cardText(card) {
    return [card.issuer, card.card_tail ? '끝' + card.card_tail : '', card.date_basis].filter(Boolean).join(' · ');
  }
  function fileStatus(status) {
    return ({parsed: '원본 저장됨', uploaded: '원본 저장됨', classified: '거래 분류됨',
      failed: '파일 읽기 오류', error: '파일 읽기 오류', queued: '업로드 중',
      processing: '파일 읽는 중'})[status] || '파일 정보';
  }
  function renderFile(file, parent) {
    const item = node('div', 'card-coverage-file');
    item.append(node('strong', '', file.filename || '이름 없는 원본'));
    item.append(node('p', 'card-workspace-muted',
      (file.transaction_start ? '거래일자: ' + file.transaction_start + ' ~ ' + file.transaction_end : '거래일자 없음') +
      ' · 원천 ' + (file.source_rows ?? 0) + '행 · 고유 거래 ' + (file.unique_transactions ?? 0) + '건' +
      (file.zero_rows ? ' · 거래 0건' : '') + ' · ' + fileStatus(file.status)));
    if (/^batch-[a-f0-9]{24}$/.test(file.batch_id || '')) {
      const actions = node('div', 'card-coverage-file-actions');
      const params = new URLSearchParams(location.search);
      params.set('panel', 'upload'); params.set('batch', file.batch_id); params.delete('review');
      const link = node('a', 'card-upload-result-link', '처리 결과');
      link.href = '/cards/all?' + params.toString(); actions.append(link);
      item.append(actions);
    }
    parent.append(item);
  }
  function renderCoverage(data) {
    coverageRoot.replaceChildren();
    if (!data.available) {
      coverageRoot.append(node('p', 'card-workspace-error', '거래일자 공백 기능을 사용할 수 없습니다. 카드 파일 업로드는 계속할 수 있습니다.'));
      return;
    }
    const overview = data.overview || {};
    const metrics = node('div', 'card-coverage-metrics');
    for (const [key, label] of [['card_count', '카드 그룹'], ['file_count', '업로드 파일'],
      ['gap_count', '거래일자 공백'], ['files_need_review', '거래일자 없는 파일']]) {
      const metric = node('div', 'card-coverage-metric');
      metric.append(node('strong', '', overview[key] ?? 0),
        node('span', '', label));
      metrics.append(metric);
    }
    coverageRoot.append(metrics);
    if (data.coverage_state === 'needs_transactions' && (data.files || []).length) {
      coverageRoot.append(node('p', 'card-coverage-guidance',
        '업로드 기록은 있지만 거래일자를 읽을 수 있는 파일이 없습니다. 거래가 포함된 카드 자료를 추가하면 공백을 계산합니다.'));
    } else if (data.coverage_state === 'transaction_dates') {
      coverageRoot.append(node('p', 'card-coverage-guidance',
        '카드별 첫 거래일부터 마지막 거래일까지 거래가 없는 날짜를 표시합니다. 정상적으로 사용하지 않은 날일 수 있으며, 자료 누락을 뜻하지는 않습니다. 카드사·끝4자리로 묶은 표시용 그룹입니다.'));
    }
    const cards = node('div', 'card-coverage-cards');
    for (const card of data.cards || []) {
      const box = node('section', 'card-coverage-card');
      box.append(node('h3', '', cardText(card)));
      box.append(node('p', 'card-workspace-muted', card.identity_scope === 'source_file' ?
        '파일 단위 식별 · 끝4자리가 같은 다른 카드와 합치지 않습니다.' : '거래일자 기준 카드 공백'));
      const gaps = card.gaps || [];
      box.append(node('p', 'card-coverage-state', gaps.length ? '거래일자 공백 ' + gaps.length + '곳' :
        '첫 거래일~마지막 거래일 사이 공백 없음'));
      const timeline = [...(card.periods || []).map(period => ({...period, missing: false})),
        ...gaps.map(period => ({...period, missing: true}))].sort((a, b) => a.start.localeCompare(b.start));
      const ranges = timeline.length > 12 ? node('details', 'card-coverage-files') : box;
      if (ranges !== box) {
        ranges.append(node('summary', '', '거래일자·공백 ' + timeline.length + '개 구간 보기'));
        box.append(ranges);
      }
      for (const period of timeline) {
        const line = node('div', 'card-coverage-period' + (period.missing ? ' is-missing' : ''));
        const label = node('span');
        label.append(document.createTextNode(period.missing ? '거래일자 공백 ' : '거래가 있는 날짜 '),
          node('span', 'card-coverage-dates', period.start), document.createTextNode(' ~ '),
          node('span', 'card-coverage-dates', period.end));
        line.append(label);
        if (period.missing) {
          const add = node('button', 'card-workspace-secondary', '이 기간 자료 추가'); add.type = 'button';
          add.addEventListener('click', () => openGap(card, period)); line.append(add);
        }
        ranges.append(line);
      }
      const files = node('details', 'card-coverage-files');
      files.append(node('summary', '', (card.files || []).length + '개 파일 상세'));
      for (const file of card.files || []) renderFile(file, files);
      box.append(files); cards.append(box);
    }
    coverageRoot.append(cards);
    const pending = (data.files || []).filter(file => file.coverage_status === 'no_transaction_dates');
    if (pending.length) {
      const review = node('section', 'card-coverage-review');
      review.append(node('h3', '', '거래일자가 없는 파일 ' + pending.length + '개'));
      review.append(node('p', 'card-workspace-muted',
        '거래일자가 없는 파일은 공백 계산에서 제외합니다. 파일에 거래가 추가되면 현황을 다시 계산합니다.'));
      const groups = new Map();
      for (const file of pending) {
        const issuer = String(file.issuer_hint || '').trim();
        const tail = String(file.card_tail_hint || '').trim();
        const label = issuer && /^\d{4}$/.test(tail) ?
          issuer + ' · 끝' + tail + ' (표시용)' : '카드 식별 정보 없음';
        if (!groups.has(label)) groups.set(label, []);
        groups.get(label).push(file);
      }
      for (const [label, files] of groups) {
        const group = node('details', 'card-coverage-files card-coverage-pending');
        group.append(node('summary', '', label + ' · ' + files.length + '개 파일 보기'));
        for (const file of files) renderFile(file, group);
        review.append(group);
      }
      coverageRoot.append(review);
    }
    if (!(data.cards || []).length && !pending.length) {
      coverageRoot.append(node('p', 'card-coverage-empty', '거래일자가 있는 카드 자료가 없습니다. 카드 내역 파일을 업로드하면 공백을 계산할 수 있습니다.'));
    }
  }
  async function refreshCoverage() {
    if (!coverageRoot) return;
    const status = byId('card-coverage-status');
    if (status) status.textContent = '수집 현황을 불러오고 있습니다.';
    coverageRoot.setAttribute('aria-busy', 'true');
    try {
      renderCoverage(await request('/api/cards/coverage/summary'));
      if (status) status.textContent = '수집 현황을 불러왔습니다.';
    }
    catch (error) {
      coverageRoot.replaceChildren();
      const message = node('p', 'card-workspace-error', error.message + ' 다시 확인해 주세요.');
      const retry = node('button', 'card-workspace-secondary', '수집 현황 다시 불러오기'); retry.type = 'button';
      retry.addEventListener('click', refreshCoverage); message.append(retry); coverageRoot.append(message);
      if (status) status.textContent = '수집 현황을 불러오지 못했습니다. 오류를 확인하고 다시 시도해 주세요.';
    } finally { coverageRoot.removeAttribute('aria-busy'); }
  }
  const reloadCoverage = document.getElementById('card-coverage-refresh');
  if (reloadCoverage) reloadCoverage.addEventListener('click', refreshCoverage);

  async function showBatchDetail() {
    if (!batchRoot) return;
    const batchId = query().get('batch') || '';
    if (!/^batch-[a-f0-9]{24}$/.test(batchId)) { batchRoot.hidden = true; return; }
    batchRoot.hidden = false;
    batchRoot.replaceChildren(node('p', 'card-workspace-status',
      '저장된 파일과 거래일자 처리 결과를 불러오고 있습니다.'));
    try {
      const data = await request('/api/imports/' + encodeURIComponent(batchId));
      batchRoot.replaceChildren(node('h3', '', '파일 처리 결과'));
      batchRoot.append(node('p', 'card-workspace-muted',
        '원본 저장·거래 분류·거래일자 공백 계산 상태를 함께 표시합니다.'));
      if (data.upload_summary) {
        const summary = data.upload_summary;
        batchRoot.append(node('p', 'card-coverage-state', '원천 행 ' +
          (summary.source_rows ?? summary.row_count ?? '확인 불가') +
          ' · 처리 오류 ' + (summary.error_count ?? '확인 불가') +
          ' · ' + fileStatus(summary.status)));
      } else if (data.status) batchRoot.append(node('p', 'card-coverage-state',
        fileStatus(data.status)));
      else batchRoot.append(node('p', 'card-workspace-muted', '상세 처리 상태를 확인했습니다.'));

      batchRoot.append(node('p', 'card-workspace-muted',
        '거래일자는 카드 거래 원행에서 읽어 카드별 거래일자 공백 현황에 반영합니다.'));
    } catch (error) {
      batchRoot.replaceChildren(node('p', 'card-workspace-error',
        error.message + ' 해당 원본을 다시 확인해 주세요.'));
    }
  }
  async function showLinkedTransaction() {
    if (!linkedTransaction) return;
    const transactionId = query().get('transaction') || '';
    if (!transactionId) return;
    linkedTransaction.hidden = false;
    linkedTransaction.setAttribute('aria-busy', 'true');
    linkedTransaction.replaceChildren(node('p', 'card-workspace-status', '연결된 거래 상세를 불러오고 있습니다.'));
    try {
      const response = await fetch('/api/cards/transactions/detail?' + new URLSearchParams({id: transactionId}),
        {credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ?
        '거래를 볼 권한을 확인해 주세요.' : '거래 상세를 찾지 못했습니다. 카드 내역을 새로 조회해 주세요.');
      const data = await response.json();
      if (typeof data.html !== 'string') throw new Error('거래 상세를 읽지 못했습니다.');
      linkedTransaction.replaceChildren(node('h2', '', '연결된 카드 거래'));
      const detail = node('div', 'card-linked-transaction-content'); detail.innerHTML = data.html;
      linkedTransaction.append(detail);
    } catch (error) { linkedTransaction.replaceChildren(node('p', 'card-workspace-error', error.message)); }
    finally { linkedTransaction.removeAttribute('aria-busy'); }
  }

  applyPanel(panelName());
  resumeUploads();
  showBatchDetail();
  showLinkedTransaction();
  if (location.hash === '#newupload' || location.hash === '#summary' || location.hash === '#preview') {
    if (panelName() !== 'upload') setPanel('upload', {replace: true, focus: false});
    uploadPanel.scrollIntoView({block: 'start'});
  }
  if (location.hash === '#expense-cleanup') location.replace('/cards/all');
})();
