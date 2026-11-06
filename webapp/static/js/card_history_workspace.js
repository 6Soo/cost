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
    context.textContent = `${selectedGap.issuer} · 끝${selectedGap.card_tail} · ${selectedGap.date_basis} 기준 · ${selectedGap.start} ~ ${selectedGap.end} 자료를 추가합니다. 업로드 뒤 조회기간이 검증돼야 누락 구간이 해소됩니다.`;
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
    entry.append(node('strong', 'card-upload-result-name', name || '카드 파일'));
    entry.append(node('span', 'card-upload-result-state', message));
    uploadResults.hidden = false;
    uploadResults.append(entry);
    return entry;
  }
  function updateEntry(entry, message, state = 'pending') {
    entry.dataset.state = state;
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
    const evidence = result.coverage_evidence || {};
    if (result.coverage_confirmed) {
      const details = [evidence.issuer, evidence.card_tail ? '끝' + evidence.card_tail : '',
        evidence.date_basis, evidence.start_date && evidence.end_date ?
          evidence.start_date + ' ~ ' + evidence.end_date : ''].filter(Boolean).join(' · ');
      entry.append(node('span', 'card-upload-result-note', '원본의 전체 조회 조건을 확인했습니다.' + (details ? ' ' + details : '')));
    } else if (batchId && result.coverage_available !== false) {
      entry.append(node('p', 'card-upload-result-note', '조회기간 확인이 필요합니다. 거래 발생일로 조회기간을 추정하지 않습니다.'));
      appendCoverageForm(entry, batchId, evidence);
    } else {
      entry.append(node('span', 'card-upload-result-note', '조회기간을 확인할 수 없습니다. 업로드 결과는 저장되어 있습니다.'));
    }
    if (selectedGap) {
      const matched = result.coverage_confirmed === true && evidence.card_id === selectedGap.card_id &&
        evidence.date_basis === selectedGap.date_basis && evidence.start_date <= selectedGap.start &&
        evidence.end_date >= selectedGap.end;
      entry.append(node('span', 'card-upload-result-note', matched ?
        '선택한 누락 기간의 전체 조회를 확인했습니다.' :
        '선택한 누락 기간 전체의 조회 증빙은 아직 확보되지 않았습니다. 현황에서 기간을 다시 확인해 주세요.'));
    }
  }
  function appendCoverageForm(entry, batchId, evidence) {
    if (!evidence || !batchId) return;
    const details = node('details', 'card-upload-coverage-confirm');
    details.append(node('summary', '', '실제 조회기간 확인'));
    const form = node('form', 'card-upload-coverage-form');
    form.append(node('p', 'card-workspace-muted', '카드사에서 조회한 카드·기간·기준을 확인해 주세요. 전체 결과가 아닌 파일은 전체 조회로 표시하지 마세요.'));
    const inputs = {};
    const fields = [
      ['issuer', '카드사', 'text'], ['card_tail', '카드 끝4자리', 'text'],
      ['date_basis', '조회 기준', 'select'], ['start_date', '조회 시작일', 'date'],
      ['end_date', '조회 종료일', 'date']
    ];
    for (const [name, labelText, type] of fields) {
      const label = node('label', '', labelText);
      const input = type === 'select' ? node('select') : node('input');
      input.name = name;
      if (type === 'select') {
        for (const value of ['', '승인일', '이용일', '매입일']) {
          const option = node('option', '', value || '실제 조회 기준 선택');
          option.value = value; input.append(option);
        }
      } else input.type = type;
      input.value = evidence[name] || '';
      input.required = true;
      if ((name === 'issuer' || name === 'card_tail') && evidence[name]) input.readOnly = true;
      label.append(input); form.append(label); inputs[name] = input;
    }
    const acknowledge = node('label', 'card-upload-coverage-check');
    const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.required = true;
    acknowledge.append(checkbox, document.createTextNode('이 파일이 위 카드·기간·조회 기준의 전체 조회 결과임을 확인했습니다.'));
    form.append(acknowledge);
    const save = node('button', 'card-workspace-secondary', '조회기간 확인 저장'); save.type = 'submit'; form.append(save);
    const message = node('p', 'card-workspace-status'); message.setAttribute('role', 'status'); form.append(message);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      save.disabled = true; message.textContent = '조회기간을 저장하고 있습니다.';
      const confirmation = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value]));
      confirmation.complete = checkbox.checked; confirmation.card_id = evidence.card_id || '';
      try {
        const result = await request('/api/imports/' + encodeURIComponent(batchId) + '/coverage/confirm',
          JSON.stringify({evidence: confirmation}), {'Content-Type': 'application/json'});
        if (!result.confirmed) throw new Error(result.reason || '조회조건을 다시 확인해 주세요.');
        message.textContent = '조회기간 확인을 저장했습니다.';
        save.textContent = '조회기간 확인 저장';
        if (selectedGap) {
          const matched = evidence.card_id === selectedGap.card_id &&
            evidence.date_basis === selectedGap.date_basis && evidence.start_date <= selectedGap.start &&
            evidence.end_date >= selectedGap.end;
          entry.append(node('span', 'card-upload-result-note', matched ?
            '선택한 누락 기간의 조회 확인을 저장했습니다.' :
            '선택한 누락 기간과 다른 범위입니다. 남은 누락 기간은 현황에 계속 표시됩니다.'));
        }
        await refreshCoverage();
      } catch (error) { message.textContent = error.message; }
      finally { save.disabled = false; }
    });
    details.append(form); entry.append(details);
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
            throw new Error(state.message || '파일 처리에 실패했습니다. 저장된 파일의 결과를 확인해 주세요.');
          }
          failures = 0;
          updateEntry(entry, (state.message || '파일 처리 중') + ' · ' + Math.floor((Date.now() - started) / 1000) + '초');
        }
      } catch (error) {
        if (error.message && /로그인|권한|파일 처리에 실패했습니다/.test(error.message)) throw error;
        failures += 1;
        updateEntry(entry, error.message || '처리 상태를 다시 확인하고 있습니다.');
        if (failures >= 5) throw new Error('파일은 접수됐습니다. 연결을 확인한 뒤 처리 결과 링크에서 다시 확인해 주세요.');
      }
      await new Promise(resolve => setTimeout(resolve, Math.min(10000, failures ? 1000 * 2 ** failures : 1500)));
    }
  }
  async function showResult(entry, job, result) {
    updateEntry(entry, uploadOutcome(result), 'saved');
    batchLink(entry, result.batch_id || job.batch_id);
    showCoverageEvidence(entry, result, result.batch_id || job.batch_id);
  }
  async function resumeUploads() {
    const jobs = readJobs();
    if (!jobs.length || uploadResults.dataset.resuming === 'true') return;
    uploadResults.dataset.resuming = 'true';
    if (panelName() !== 'upload') {
      const url = new URL(location.href); url.searchParams.set('panel', 'upload');
      history.replaceState({}, '', url);
      uploadPanel.hidden = false; coveragePanel.hidden = true;
      uploadButton.setAttribute('aria-expanded', 'true');
      coverageButton.setAttribute('aria-expanded', 'false');
    }
    uploadResults.replaceChildren();
    const note = node('p', 'card-workspace-status', jobs.length + '개 파일의 저장된 처리 상태를 확인하고 있습니다.');
    note.setAttribute('role', 'status'); uploadResults.append(note);
    const entries = jobs.map(job => resultEntry(job.filename, '저장된 처리 상태를 확인하고 있습니다.'));
    let cursor = 0;
    const worker = async () => {
      while (cursor < jobs.length) {
        const index = cursor++; const job = jobs[index];
        try { await showResult(entries[index], job, await awaitUpload(job, entries[index])); }
        catch (error) { updateEntry(entries[index], error.message, 'error'); batchLink(entries[index], job.batch_id); }
      }
    };
    await Promise.all(Array.from({length: Math.min(4, jobs.length)}, worker));
    note.textContent = jobs.length + '개 파일의 저장 상태를 확인했습니다. 업로드된 파일은 다시 올릴 필요가 없습니다.';
    delete uploadResults.dataset.resuming;
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
      uploadStatus.textContent = '파일별 처리 결과를 확인해 주세요. 조회기간은 거래 발생기간과 별도로 확인됩니다.';
      await refreshCoverage();
    } catch (error) { uploadStatus.textContent = error.message; }
    finally { uploadSubmit.disabled = false; uploadInput.disabled = false; }
  });

  function cardText(card) {
    return [card.issuer, card.card_tail ? '끝' + card.card_tail : '', card.date_basis].filter(Boolean).join(' · ');
  }
  function renderFile(file, parent) {
    const item = node('div', 'card-coverage-file');
    item.append(node('strong', '', file.filename || '이름 없는 원본'));
    const periods = (file.query_periods || []).map(period =>
      period.date_basis + ' ' + period.start + ' ~ ' + period.end).join(' · ');
    item.append(node('p', 'card-workspace-muted',
      (periods ? '조회기간: ' + periods : '조회기간 확인 필요') +
      ' · 원천 ' + (file.source_rows ?? 0) + '행 · 고유 거래 ' + (file.unique_transactions ?? 0) + '건' +
      (file.zero_rows ? ' · 거래 0건' : '') + ' · 처리 상태 ' + (file.status || '확인 필요')));
    if (file.transaction_start) item.append(node('p', 'card-workspace-muted',
      '거래 발생기간: ' + file.transaction_start + ' ~ ' + file.transaction_end + ' (조회기간과 별개)'));
    if (/^batch-[a-f0-9]{24}$/.test(file.batch_id || '')) {
      const link = node('a', 'card-upload-result-link', '업로드 처리 결과 보기');
      const params = new URLSearchParams(location.search); params.set('panel', 'upload'); params.set('batch', file.batch_id);
      link.href = '/cards/all?' + params.toString(); item.append(link);
    }
    parent.append(item);
  }
  function renderBaseline(card, box) {
    const disclosure = node('details', 'card-coverage-baseline');
    disclosure.append(node('summary', '', '관리 시작일 ' + (card.management_start ? '변경' : '설정')));
    const form = node('form', 'card-coverage-baseline-form');
    const label = node('label', '', cardText(card) + ' 기준으로 관리할 시작일');
    const input = node('input'); input.type = 'date'; input.required = true;
    input.value = card.management_start || card.periods?.[0]?.start || '';
    label.append(input); form.append(label);
    const save = node('button', 'card-workspace-secondary', '관리 시작일 저장'); save.type = 'submit'; form.append(save);
    const status = node('p', 'card-workspace-status'); status.setAttribute('role', 'status'); form.append(status);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!form.reportValidity()) return;
      save.disabled = true; status.textContent = '관리 시작일을 저장하고 있습니다.';
      try {
        await request('/api/cards/coverage/baseline', JSON.stringify({card_id: card.card_id,
          date_basis: card.date_basis, management_start: input.value,
          expected_revision: card.management_revision || 0}), {'Content-Type': 'application/json'});
        status.textContent = '관리 시작일을 저장했습니다.';
        await refreshCoverage();
      } catch (error) { status.textContent = error.message; }
      finally { save.disabled = false; }
    });
    disclosure.append(form); box.append(disclosure);
  }
  function renderCoverage(data) {
    coverageRoot.replaceChildren();
    if (!data.available) {
      coverageRoot.append(node('p', 'card-workspace-error', '조회기간 관리 기능을 사용할 수 없습니다. 카드 파일 업로드는 계속할 수 있습니다.'));
      return;
    }
    const overview = data.overview || {};
    const metrics = node('div', 'card-coverage-metrics');
    for (const [key, label] of [['card_count', '관리 카드'], ['covered_bases', '조회 기준'],
      ['gap_count', '미수집 구간'], ['files_need_review', '조회 확인 필요 파일']]) {
      const metric = node('div', 'card-coverage-metric');
      metric.append(node('strong', '', overview[key] ?? 0), node('span', '', label)); metrics.append(metric);
    }
    coverageRoot.append(metrics);
    const cards = node('div', 'card-coverage-cards');
    for (const card of data.cards || []) {
      const box = node('section', 'card-coverage-card');
      box.append(node('h3', '', cardText(card)));
      box.append(node('p', 'card-workspace-muted', card.identity_scope === 'source_file' ?
        '파일 단위 식별 · 끝4자리가 같은 다른 카드와 합치지 않습니다.' : '카드별 조회기간'));
      const gaps = card.gaps || [];
      box.append(node('p', 'card-coverage-state', gaps.length ? '미수집 기간 ' + gaps.length + '곳' :
        !card.management_start ? '확인된 조회기간 · 관리 시작일 미설정' : '관리 범위 조회 확인'));
      box.append(node('p', 'card-workspace-muted', card.management_start ?
        '관리 시작일 ' + card.management_start : '최초 확인기간 이전은 누락으로 판단하지 않습니다.'));
      renderBaseline(card, box);
      const timeline = [...(card.periods || []).map(period => ({...period, missing: false})),
        ...gaps.map(period => ({...period, missing: true}))].sort((a, b) => a.start.localeCompare(b.start));
      for (const period of timeline) {
        const line = node('div', 'card-coverage-period' + (period.missing ? ' is-missing' : ''));
        line.append(node('span', '', (period.missing ? '미수집 ' : '조회 확인 ') + period.start + ' ~ ' + period.end));
        if (period.missing) {
          const add = node('button', 'card-workspace-secondary', '이 기간 자료 추가'); add.type = 'button';
          add.addEventListener('click', () => openGap(card, period)); line.append(add);
        }
        box.append(line);
      }
      const files = node('details', 'card-coverage-files');
      files.append(node('summary', '', (card.files || []).length + '개 파일 상세'));
      for (const file of card.files || []) renderFile(file, files);
      box.append(files); cards.append(box);
    }
    coverageRoot.append(cards);
    const pending = (data.files || []).filter(file => file.coverage_status !== 'confirmed');
    if (pending.length) {
      const section = node('details', 'card-coverage-files card-coverage-pending');
      section.append(node('summary', '', '조회 확인이 필요한 파일 ' + pending.length + '개'));
      section.append(node('p', 'card-workspace-muted', '거래 발생일로 조회기간을 추정하지 않습니다. 원본 조회 조건을 확인해 주세요.'));
      for (const file of pending) renderFile(file, section);
      coverageRoot.append(section);
    }
    if (!(data.cards || []).length && !pending.length) {
      coverageRoot.append(node('p', 'card-coverage-empty', '확인된 조회기간이 없습니다. 카드사에서 받은 전체 결과 파일을 업로드하면 현황을 확인할 수 있습니다.'));
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
    batchRoot.hidden = false; batchRoot.replaceChildren(node('p', 'card-workspace-status', '저장된 파일의 처리 결과를 불러오고 있습니다.'));
    try {
      const data = await request('/api/imports/' + encodeURIComponent(batchId));
      batchRoot.replaceChildren(node('h3', '', '파일 처리 결과'));
      batchRoot.append(node('p', 'card-workspace-muted', '파일 ' + batchId + ' · 분류 및 금융 상태는 조회기간 확인과 별개입니다.'));
      if (data.upload_summary) {
        const summary = data.upload_summary;
        batchRoot.append(node('p', 'card-coverage-state', '원천 행 ' + (summary.source_rows ?? summary.row_count ?? '확인 불가') +
          ' · 처리 오류 ' + (summary.error_count ?? '확인 불가') + ' · 상태 ' + (summary.status || '확인 필요')));
      } else if (data.status) batchRoot.append(node('p', 'card-coverage-state', '저장 상태 ' + data.status));
      else batchRoot.append(node('p', 'card-workspace-muted', '상세 처리 상태를 확인했습니다.'));
    } catch (error) {
      batchRoot.replaceChildren(node('p', 'card-workspace-error', error.message + ' 페이지를 새로고침해 다시 확인해 주세요.'));
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
  if (location.hash === '#expense-cleanup') location.replace('/my-actions');
})();
