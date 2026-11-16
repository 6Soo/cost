(() => {
  'use strict';

  const csrf = window.RECEIPT_WORKFLOW_CSRF || '';
  const trips = window.RECEIPT_WORKFLOW_TRIPS || [];
  const byId = (id) => document.getElementById(id);
  const labels = { cash: '현금', private_card: '개인카드', corporate_card: '법인카드' };
  const candidateById = new Map();
  const drafts = new Map();
  const retryingJobs = new Set();
  let catalog = null;
  let models = [];
  let images = [];
  let batches = [];
  let lastBatchFingerprint = '';
  let polling = false;
  let workflowDisabled = false;

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const newId = () => {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID().replaceAll('-', '').toLowerCase();
    const bytes = new Uint8Array(16);
    if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  };
  const isWorkflowDisabled = (error) => error.httpStatus === 404 || error.httpStatus === 501 ||
    /(?:RECEIPT_)?WORKFLOW_(?:DISABLED|NOT_ENABLED)|FEATURE_(?:DISABLED|NOT_ENABLED)|PASEO_NOT_ENABLED/i.test(error.code || '');
  function messageForCode(code, httpStatus = 0) {
    const value = String(code || '').toUpperCase();
    if (/PASEO_PROMPT_CHANGED|PROMPT_CHANGED/.test(value)) return '분석 지시가 바뀌었습니다. 새 분석을 시작해 주세요.';
    if (/AUTH_REQUIRED|LOGIN_REQUIRED|UNAUTHORIZED|AUTH_EXPIRED|SESSION_EXPIRED/.test(value) || httpStatus === 401) {
      return 'Paseo 로그인이 필요합니다. 로그인한 뒤 모델 목록을 새로고침해 주세요.';
    }
    if (/RATE_LIMIT|DAILY_CAP|DAILY_LIMIT|QUOTA|USAGE_LIMIT|LIMIT_EXCEEDED/.test(value)) {
      return '모델 사용 한도에 도달했습니다. 한도가 풀린 뒤 다시 시도해 주세요.';
    }
    if (/UNSUPPORTED_(?:IMAGE|PHOTO|MEDIA)|(?:IMAGE|PHOTO)_(?:UNSUPPORTED|NOT_SUPPORTED)|IMAGE_TYPE/.test(value)) {
      return '이 사진 형식은 선택한 모델에서 처리할 수 없습니다. 지원되는 사진으로 다시 분석해 주세요. 원본은 보관되어 있습니다.';
    }
    if (/REVISION|STALE|EDIT_CONFLICT|REVIEW_CONFLICT/.test(value)) {
      return '다른 화면에서 이 교정 내용을 바꿨습니다. 최신 결과를 확인한 뒤 다시 저장해 주세요. 입력한 값은 보존했습니다.';
    }
    if (/DUPLICATE|REFUND|CLOSED_PERIOD|CARD_PROTECT|SOURCE_PROTECT|LEDGER_PROTECT|PROTECTED/.test(value)) {
      return '장부 보호 조건 때문에 반영을 중단했습니다. 선택과 수정값은 보존했습니다. 원본·중복·환불·마감 조건을 확인해 주세요.';
    }
    if (/STATUS_UNKNOWN|RUN_UNKNOWN|OUTCOME_UNKNOWN|TRANSMISSION|NETWORK|TIMEOUT|CONNECTION_RESET/.test(value)) {
      return '이전 실행 상태를 확인하고 있어요. 중복 실행을 막기 위해 잠시 기다려 주세요.';
    }
    if (/PASEO_UNAVAILABLE|PASEO_NOT_CONNECTED|PROVIDER_UNAVAILABLE|MODEL_UNAVAILABLE|CONNECTION_FAILED|HOST_UNAVAILABLE|HOST_UNREACHABLE|CONNECT_FAILED|NOT_CONNECTED/.test(value)) {
      return '모델 연결을 확인할 수 없습니다. Paseo 연결 상태를 확인한 뒤 모델 목록을 새로고침해 주세요.';
    }
    if (httpStatus === 409) return '서버가 요청을 접수하지 않았습니다. 현재 작업 상태를 새로고침해 확인해 주세요.';
    if (httpStatus === 403) return '접근 권한을 확인하고 화면을 다시 열어 주세요.';
    return '';
  }
  function errorFeedback(error, fallback = '요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.') {
    const code = String(error?.code || '').trim();
    const rawMessage = String(error?.message || '').trim();
    const messageLooksLikeCode = /^[A-Z][A-Z0-9_:-]{2,}$/.test(rawMessage);
    const normalizedCode = code || (messageLooksLikeCode ? rawMessage : '');
    let message = messageForCode(normalizedCode);
    if (!message && /failed to fetch|networkerror|load failed|connection refused/i.test(rawMessage)) {
      message = messageForCode('NETWORK_ERROR');
    }
    if (!message && rawMessage && !messageLooksLikeCode) message = rawMessage;
    if (!message) message = messageForCode('', error?.httpStatus);
    if (!message) message = fallback;
    return normalizedCode ? `${message} (진단 코드: ${normalizedCode})` : message;
  }
  function showWorkflowDisabled(error) {
    if (!isWorkflowDisabled(error)) return false;
    workflowDisabled = true;
    const message = 'Paseo 사진 처리는 현재 사용할 수 없습니다. 기존 영수증 업로드·검수·직접 입력은 계속 이용할 수 있습니다.';
    byId('rw-host-status').textContent = message;
    byId('rw-model-reason').textContent = message;
    byId('rw-batches').innerHTML = `<p class="rw-empty" role="alert">${escapeHtml(message)} <a href="/receipts?mode=classic">기존 검수·직접 입력 열기</a></p>`;
    updateControls();
    return true;
  }
  const apiRead = async (response) => {
    let body;
    try { body = await response.json(); } catch {
      const error = new Error(response.status === 403 ? '접근 권한을 확인하고 화면을 다시 열어 주세요.' : '서버 응답을 확인하지 못했습니다.');
      error.httpStatus = response.status;
      throw error;
    }
    if (!response.ok) {
      const code = body?.code || '';
      const serverMessage = body?.message || body?.detail || '';
      const message = messageForCode(code) || (serverMessage !== code ? serverMessage : '') ||
        messageForCode('', response.status) || '요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      const error = new Error(message);
      error.code = code;
      error.httpStatus = response.status;
      throw error;
    }
    return body;
  };
  const get = (path) => fetch(path, { cache: 'no-store', headers: { 'X-CSRF-Token': csrf } }).then(apiRead);
  const post = (path, body) => fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  }).then(apiRead);
  const pageStatus = (message) => { byId('rw-page-status').textContent = message || ''; };
  const isoTime = (value) => {
    if (!value) return '시각 정보 없음';
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString('ko-KR');
  };
  const imageUrl = (sha) => `/api/receipts/image/${encodeURIComponent(sha || '')}`;

  function renderImages() {
    const pdfPages = new Map();
    const uploadNames = new Map((images.uploads || []).map((item) => [item.sha256, item.name]));
    for (const pdf of images.pdfs || []) {
      (pdf.pages || []).forEach((sha, index) => {
        if (!pdfPages.has(sha)) pdfPages.set(sha, `PDF ${index + 1}페이지`);
      });
    }
    const list = byId('rw-photo-list');
    const rows = (images.images || []).filter((sha) => /^[0-9a-f]{64}$/.test(sha));
    if (!rows.length) {
      list.innerHTML = `<p class="rw-empty" data-rw-no-photos>저장된 사진이 없습니다. 위에서 사진을 올려 주세요.</p>`;
      return;
    }
    list.innerHTML = rows.map((sha) => {
      const name = uploadNames.get(sha) || pdfPages.get(sha) || '저장된 사진';
      const source = pdfPages.has(sha) ? 'PDF 페이지' : '사진';
      return `<label class="rw-photo-choice">
        <input type="checkbox" data-rw-image value="${escapeHtml(sha)}" aria-label="${escapeHtml(name)} 분석 대상으로 선택">
        <span class="rw-photo-thumb"><img src="${imageUrl(sha)}" loading="lazy" width="96" height="112" alt="저장된 영수증 원본"></span>
        <span class="rw-photo-copy"><strong>${escapeHtml(name)}</strong><small>${source}</small></span>
      </label>`;
    }).join('');
    updateControls();
  }

  async function loadImages() {
    try {
      images = await get('/api/receipts');
      renderImages();
    } catch (error) {
      byId('rw-photo-list').innerHTML = `<p class="rw-empty" role="alert">저장된 원본을 불러오지 못했습니다. ${escapeHtml(errorFeedback(error))}</p>`;
    }
  }

  function renderProviders() {
    const select = byId('rw-provider');
    const current = select.value;
    const providers = catalog?.providers || [];
    select.innerHTML = `<option value="">Provider 선택</option>` + providers.map((provider) => {
      const suffix = provider.available ? '' : ' · 연결할 수 없음';
      return `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.label || provider.id)}${suffix}</option>`;
    }).join('');
    if (providers.some((provider) => provider.id === current)) select.value = current;
    else if (providers.length) select.value = providers[0].id;
  }

  function renderModels() {
    const select = byId('rw-model');
    const selectedId = select.value;
    const provider = (catalog?.providers || []).find((item) => item.id === byId('rw-provider').value);
    const available = Boolean(catalog?.connected && provider?.available);
    if (!provider) {
      select.innerHTML = `<option value="">Provider를 먼저 선택하세요</option>`;
      select.disabled = true;
      models = [];
      byId('rw-model-reason').textContent = '목록 탐색은 모델을 실행하지 않습니다.';
      updateControls();
      return;
    }
    models = (catalog?.models || []).filter((model) => !model.provider || model.provider === provider.id);
    select.disabled = false;
    select.innerHTML = `<option value="">Model 선택</option>` + models.map((model) => {
      const unavailableReason = model.reason || (!available ? 'Provider 연결을 확인할 수 없음' : '사진 처리 경로를 확인할 수 없음');
      const reason = model.selectable && available ? '' : ` · 처리 불가: ${unavailableReason}`;
      return `<option value="${escapeHtml(model.id)}" ${model.selectable && available ? '' : 'disabled'}>${escapeHtml(model.label || model.id)}${reason}</option>`;
    }).join('');
    if (models.some((model) => model.id === selectedId && model.selectable && available)) select.value = selectedId;
    const selected = models.find((model) => model.id === select.value);
    byId('rw-model-reason').textContent = selected
      ? (selected.selectable && available ? '이 모델로 처리 버튼을 누르면 선택한 사진의 분석이 시작됩니다.' : selected.reason || '현재 처리할 수 없습니다.')
      : '모델을 선택해 주세요. 목록을 둘러봐도 분석은 시작되지 않습니다.';
    updateControls();
  }

  async function loadCatalog(providerId = '') {
    const status = byId('rw-host-status');
    status.textContent = '연결된 로컬 Paseo 모델 목록을 확인하고 있습니다.';
    const suffix = providerId ? `?provider=${encodeURIComponent(providerId)}` : '';
    try {
      catalog = await get(`/api/receipts/paseo/models${suffix}`);
      const checked = isoTime(catalog.checked_at);
      const host = catalog.host_label || '연결된 PC';
      status.textContent = catalog.connected
        ? `${host} · 목록 확인 ${checked}`
        : `${host}에 연결할 수 없습니다 · 마지막 확인 ${checked}`;
      if (!providerId) renderProviders();
      renderModels();
    } catch (error) {
      catalog = null;
      models = [];
      byId('rw-provider').innerHTML = `<option value="">Provider 목록을 불러오지 못함</option>`;
      byId('rw-model').innerHTML = `<option value="">목록을 사용할 수 없습니다</option>`;
      byId('rw-model').disabled = true;
      const unavailable = showWorkflowDisabled(error);
      byId('rw-model-reason').textContent = unavailable
        ? 'Paseo 처리를 사용할 수 없습니다. 기존 업로드·검수 기능은 유지됩니다.'
        : '연결과 목록을 새로고침해 주세요. 임의 모델은 실행할 수 없습니다.';
      if (!unavailable) status.textContent = `모델 목록을 불러오지 못했습니다 · ${errorFeedback(error)}`;
      updateControls();
    }
  }

  function statusInfo(job, count) {
    if (job.status === 'running' || job.status === 'queued' || job.status === 'starting') return { label: '분석 중', state: 'running' };
    if (job.status === 'failed' || job.status === 'error') return { label: '분석 실패', state: 'failed' };
    if (job.status === 'done' || job.status === 'complete' || job.status === 'completed') {
      return count ? { label: `분석 완료 · ${count}건`, state: 'done' } : { label: '영수증 0건', state: 'empty' };
    }
    return { label: job.status || '상태 확인 중', state: 'unknown' };
  }

  function boxStyle(box) {
    if (!Array.isArray(box) || box.length !== 4 || box.some((value) => !Number.isFinite(Number(value)))) return '';
    const [left, top, right, bottom] = box.map(Number);
    if (left < 0 || top < 0 || right > 1 || bottom > 1 || right <= left || bottom <= top) return '';
    return `left:${left * 100}%;top:${top * 100}%;width:${(right - left) * 100}%;height:${(bottom - top) * 100}%`;
  }

  function fieldMarkup(candidate, field, label, type = 'text', extra = '') {
    const draft = drafts.get(candidate.candidate_id);
    const value = draft && Object.prototype.hasOwnProperty.call(draft.changes, field)
      ? draft.changes[field]
      : candidate[field];
    const controlId = `rw-${escapeHtml(candidate.candidate_id)}-${field}`;
    return `<div class="rw-field ${extra}"><label for="${controlId}">${label}</label>
      <input id="${controlId}" data-field="${field}" data-focus-key="${escapeHtml(candidate.candidate_id)}|${field}" type="${type}" value="${escapeHtml(value ?? '')}" ${field === 'amount' ? 'inputmode="decimal" step="any"' : ''}></div>`;
  }

  function tripMarkup(candidate) {
    const draft = drafts.get(candidate.candidate_id);
    const value = draft && Object.prototype.hasOwnProperty.call(draft.changes, 'trip_id')
      ? draft.changes.trip_id : candidate.trip_id;
    let options = `<option value="" ${value ? '' : 'selected'}>여행 선택</option>` + trips.map((trip) =>
      `<option value="${escapeHtml(trip.id)}" ${trip.id === value ? 'selected' : ''}>${escapeHtml(trip.name || trip.id)}</option>`).join('');
    if (value && !trips.some((trip) => trip.id === value)) options += `<option value="${escapeHtml(value)}" selected>현재 값 · ${escapeHtml(value)}</option>`;
    return `<div class="rw-field"><label for="rw-${escapeHtml(candidate.candidate_id)}-trip_id">여행</label>
      <select id="rw-${escapeHtml(candidate.candidate_id)}-trip_id" data-field="trip_id" data-focus-key="${escapeHtml(candidate.candidate_id)}|trip_id">${options}</select></div>`;
  }

  function paymentMarkup(candidate) {
    const draft = drafts.get(candidate.candidate_id);
    const value = draft && Object.prototype.hasOwnProperty.call(draft.changes, 'payment')
      ? draft.changes.payment : candidate.payment;
    const options = [`<option value="" ${value ? '' : 'selected'}>결제수단 확인</option>`, ...Object.entries(labels).map(([key, label]) =>
      `<option value="${key}" ${key === value ? 'selected' : ''}>${label}</option>`)].join('');
    return `<div class="rw-field"><label for="rw-${escapeHtml(candidate.candidate_id)}-payment">결제수단</label>
      <select id="rw-${escapeHtml(candidate.candidate_id)}-payment" data-field="payment" data-focus-key="${escapeHtml(candidate.candidate_id)}|payment">${options}</select></div>`;
  }

  function candidateMarkup(candidate, index) {
    const id = candidate.candidate_id;
    const draft = drafts.get(id);
    const selected = draft?.selected !== undefined ? draft.selected : candidate.selected === true;
    const applied = candidate.applied === true;
    const sha = /^[0-9a-f]{64}$/.test(candidate.image || '') ? candidate.image : '';
    const zoomKey = `rw-zoom-${index}`;
    const picture = sha
      ? `<div class="rw-photo-stage"><a class="rw-photo-link" href="${imageUrl(sha)}" target="_blank" rel="noopener" aria-label="원본 사진을 새 창에서 열기"><div class="rw-photo-inner" data-zoom-key="${zoomKey}"><img src="${imageUrl(sha)}" loading="lazy" width="640" height="480" alt="${escapeHtml(candidate.merchant || '영수증')} 원본 사진">${boxStyle(candidate.box) ? `<span class="rw-region-box" style="${boxStyle(candidate.box)}" aria-hidden="true"></span>` : ''}</div></a></div>
        <label class="rw-zoom-control" for="${zoomKey}">사진 확대 <input id="${zoomKey}" type="range" min="1" max="3" step="0.25" value="1" data-zoom="${zoomKey}"><output>1×</output></label>`
      : `<p class="rw-empty">원본 사진을 불러올 수 없습니다.</p>`;
    const appliedLink = applied && candidate.ledger_id
      ? `<a class="rw-ledger-link" href="/row?id=${encodeURIComponent(candidate.ledger_id)}">장부 행 보기 · ${escapeHtml(candidate.ledger_id)}</a>`
      : '';
    const saveText = draft?.conflict
      ? '다른 화면에서 이 내역이 수정되었습니다. 최신 revision을 확인하고 다시 저장해 주세요.'
      : draft?.error || (draft?.saving ? '수정 저장 중' : '수정은 자동 저장됩니다.');
    const retryText = draft?.conflict ? '최신 revision으로 다시 저장' : '다시 저장';
    return `<article class="rw-candidate" data-candidate="${escapeHtml(id)}">
      <div class="rw-candidate-head"><h5>${escapeHtml(candidate.merchant || `영수증 ${index + 1}`)}</h5>
        <span class="rw-status" data-state="${applied ? 'posted' : 'review'}">${applied ? '장부 반영됨' : '검수 대기'}</span></div>
      ${applied ? '' : `<label class="rw-candidate-select"><input type="checkbox" data-select-candidate="${escapeHtml(id)}" data-focus-key="${escapeHtml(id)}|selected" ${selected ? 'checked' : ''}> 장부에 반영할 내역으로 선택</label>`}
      <div class="rw-candidate-layout"><div class="rw-candidate-photo">${picture}</div>
        <div class="rw-fields">
          ${fieldMarkup(candidate, 'merchant', '상호')}
          ${fieldMarkup(candidate, 'date', '날짜', 'date')}
          ${fieldMarkup(candidate, 'amount', '금액', 'number')}
          ${fieldMarkup(candidate, 'currency', '통화')}
          ${paymentMarkup(candidate)}
          ${tripMarkup(candidate)}
          ${fieldMarkup(candidate, 'category', '항목')}
          <label class="rw-company-expense"><input type="checkbox" data-field="company_expense" data-focus-key="${escapeHtml(id)}|company_expense" ${(draft?.changes.company_expense ?? candidate.company_expense) === true ? 'checked' : ''}> 개인카드 회사 비용 인정</label>
          <div class="rw-save-state" role="status" aria-live="polite" data-save-state="${escapeHtml(id)}" data-error="${draft?.error || draft?.conflict ? 'true' : 'false'}">${escapeHtml(saveText)}
            <button type="button" class="rw-button rw-quiet rw-conflict-retry" data-conflict-retry="${escapeHtml(id)}" data-visible="${draft?.conflict || draft?.error ? 'true' : 'false'}">${retryText}</button>
          </div>
        </div></div>${appliedLink}</article>`;
  }

  function renderJob(job, batch, index) {
    const candidates = (batch.candidates || []).filter((candidate) => candidate.image === job.image);
    const info = statusInfo(job, candidates.length);
    const reason = job.code ? `<p class="rw-job-reason" title="진단 코드: ${escapeHtml(job.code)}">처리 안내: ${escapeHtml(messageForCode(job.code) || '분석 과정에서 문제가 생겨 결과를 만들지 못했습니다. 원본은 보관되어 있습니다. 다시 분석을 시도해 주세요.')}</p>` : '';
    const canRetry = Boolean(job.job_id && (job.status === 'done' || job.status === 'failed'));
    const retrying = retryingJobs.has(job.job_id);
    const retryButton = canRetry
      ? `<button type="button" class="rw-button rw-quiet" data-retry-job="${escapeHtml(job.job_id)}" ${retrying ? 'disabled' : ''}>${retrying ? '재분석 접수 중' : '이 사진 다시 분석'}</button>`
      : '';
    const content = candidates.length
      ? candidates.map((candidate, candidateIndex) => candidateMarkup(candidate, index * 100 + candidateIndex)).join('')
      : `<div class="rw-job-empty"><p class="rw-empty">${info.state === 'empty' ? '사진에서 영수증을 찾지 못했습니다. 원본은 보관되어 있습니다.' : info.state === 'running' ? '결과가 도착하면 이 목록에 저장됩니다.' : info.state === 'failed' ? '원본을 보관했습니다. 실패한 사진만 다시 처리할 수 있습니다.' : '아직 검수할 결과가 없습니다.'}</p>
        ${/^[0-9a-f]{64}$/.test(job.image || '') ? `<div class="rw-photo-stage rw-job-photo"><a class="rw-photo-link" href="${imageUrl(job.image)}" target="_blank" rel="noopener" aria-label="원본 사진을 새 창에서 열기"><img src="${imageUrl(job.image)}" loading="lazy" width="640" height="480" alt="영수증 원본 사진"></a></div>` : ''}</div>`;
    return `<section class="rw-job" data-job="${escapeHtml(job.job_id || '')}">
      <div class="rw-job-heading"><h4>사진 ${index + 1}</h4><span class="rw-status" data-state="${info.state}">${escapeHtml(info.label)}</span></div>${reason}${content}${retryButton ? `<div class="rw-inline-actions">${retryButton}</div>` : ''}</section>`;
  }

  function renderBatches() {
    const root = byId('rw-batches');
    if (!batches.length) {
      root.innerHTML = `<p class="rw-empty">진행 중이거나 검수할 분석이 없습니다. 사진을 선택하고 모델을 실행하세요.</p>`;
      updateControls();
      return;
    }
    candidateById.clear();
    let jobIndex = 0;
    root.innerHTML = batches.map((batch) => {
      (batch.candidates || []).forEach((candidate) => candidateById.set(candidate.candidate_id, candidate));
      const jobHtml = (batch.jobs || []).map((job) => renderJob(job, batch, jobIndex++)).join('');
      const count = (batch.candidates || []).length;
      const batchLabel = batch.status === 'posted' ? '장부 반영됨' :
        (batch.jobs || []).some((job) => job.status === 'running' || job.status === 'queued' || job.status === 'starting') ? '분석 중' :
          (batch.jobs || []).length && (batch.jobs || []).every((job) => job.status === 'done' || job.status === 'completed' || job.status === 'failed') ? '처리 완료' : (batch.status || '상태 확인 중');
      return `<article class="rw-batch"><div class="rw-batch-heading"><div><h3>${escapeHtml(batch.provider || 'Paseo')} · ${escapeHtml(batch.model || '선택 모델')}</h3>
        <p class="rw-batch-meta">시작 ${escapeHtml(isoTime(batch.created_at))} · 사진 ${(batch.jobs || []).length}장 · 후보 ${count}건</p></div>
        <span class="rw-status" data-state="${batchLabel === '장부 반영됨' ? 'posted' : batchLabel === '분석 중' ? 'running' : 'done'}">${escapeHtml(batchLabel)}</span></div>${jobHtml}</article>`;
    }).join('');
    updateControls();
  }

  function preserveFocus(action) {
    const active = document.activeElement;
    const focusKey = active?.dataset?.focusKey;
    const zoomKey = active?.dataset?.zoom;
    const value = active?.value;
    const checked = active?.type === 'checkbox' ? active.checked : undefined;
    const start = typeof active?.selectionStart === 'number' ? active.selectionStart : null;
    const end = typeof active?.selectionEnd === 'number' ? active.selectionEnd : null;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    action();
    if (focusKey || zoomKey) {
      const replacement = [...document.querySelectorAll('[data-focus-key],[data-zoom]')]
        .find((node) => (node.dataset.focusKey === focusKey && focusKey) || (node.dataset.zoom === zoomKey && zoomKey));
      if (replacement) {
        if (replacement.type === 'checkbox') replacement.checked = checked;
        else if (value !== undefined) replacement.value = value;
        if (replacement.dataset.zoom) {
          const inner = document.querySelector(`[data-zoom-key="${CSS.escape(replacement.dataset.zoom)}"]`);
          if (inner) inner.style.setProperty('--rw-zoom', replacement.value);
        }
        replacement.focus({ preventScroll: true });
        if (start !== null && typeof replacement.setSelectionRange === 'function') {
          try { replacement.setSelectionRange(start, end); } catch { /* date/select controls have no text selection */ }
        }
      }
    }
    window.scrollTo(scrollX, scrollY);
  }

  function renderCurrentBatches() {
    preserveFocus(renderBatches);
    for (const [id, draft] of drafts) {
      const state = document.querySelector(`[data-save-state="${CSS.escape(id)}"]`);
      if (state) {
        state.dataset.error = draft.error || draft.conflict ? 'true' : 'false';
        state.firstChild.textContent = draft.conflict
          ? '다른 화면에서 이 내역이 수정되었습니다. 최신 revision을 확인하고 다시 저장해 주세요.'
          : draft.error || (draft.saving ? '수정 저장 중' : '수정은 자동 저장됩니다.');
        const retry = state.querySelector('[data-conflict-retry]');
        if (retry) {
          retry.dataset.visible = draft.conflict || draft.error ? 'true' : 'false';
          retry.textContent = draft.conflict ? '최신 revision으로 다시 저장' : '다시 저장';
        }
      }
    }
  }

  function selectedCount() {
    let count = 0;
    for (const [id, candidate] of candidateById) {
      const draft = drafts.get(id);
      const selected = draft?.selected !== undefined ? draft.selected : candidate.selected === true;
      if (selected && !candidate.applied) count += 1;
    }
    return count;
  }

  function updateControls() {
    const checkedImages = document.querySelectorAll('[data-rw-image]:checked').length;
    const provider = (catalog?.providers || []).find((item) => item.id === byId('rw-provider')?.value);
    const model = models.find((item) => item.id === byId('rw-model')?.value);
    const canRun = Boolean(!workflowDisabled && checkedImages && catalog?.connected && provider?.available && model?.selectable);
    if (byId('rw-run-model')) byId('rw-run-model').disabled = !canRun;
    const count = selectedCount();
    if (byId('rw-selection-summary')) byId('rw-selection-summary').textContent = `선택된 내역 ${count}건`;
    if (byId('rw-apply')) byId('rw-apply').disabled = workflowDisabled || count === 0;
  }

  async function refreshState({ quiet = false } = {}) {
    if (polling) return;
    polling = true;
    try {
      const result = await get('/api/receipts/workflow');
      const next = Array.isArray(result.batches) ? result.batches : [];
      const fingerprint = JSON.stringify(next);
      batches = next;
      if (fingerprint !== lastBatchFingerprint) {
        lastBatchFingerprint = fingerprint;
        renderCurrentBatches();
      }
      updateControls();
      if (!quiet) pageStatus('서버에 저장된 작업 상태를 불러왔습니다.');
    } catch (error) {
      const unavailable = showWorkflowDisabled(error);
      if (!quiet && !unavailable) pageStatus(`결과를 새로 불러오지 못했습니다 · ${errorFeedback(error)}`);
    } finally {
      polling = false;
    }
  }

  function candidatesInData() {
    candidateById.clear();
    for (const batch of batches) for (const candidate of batch.candidates || []) candidateById.set(candidate.candidate_id, candidate);
  }

  function inputValue(field, control) {
    if (field === 'company_expense') return Boolean(control.checked);
    if (field === 'amount') return control.value === '' ? null : Number(control.value);
    return control.value;
  }

  function scheduleReview(candidateId, field, value) {
    let draft = drafts.get(candidateId);
    const candidate = candidateById.get(candidateId);
    if (!draft && !candidate) return;
    const nextValue = field === 'selected' ? Boolean(value) : value;
    const currentValue = field === 'selected'
      ? (draft?.selected !== undefined ? draft.selected : candidate.selected === true)
      : (draft && Object.prototype.hasOwnProperty.call(draft.changes, field) ? draft.changes[field] : candidate?.[field]);
    if (Object.is(currentValue, nextValue)) return;
    if (!draft) {
      draft = { baseRevision: candidate.revision, changes: {}, selected: undefined, timer: null, saving: false, conflict: false, error: '' };
      drafts.set(candidateId, draft);
    }
    if (field === 'selected') draft.selected = nextValue;
    else draft.changes[field] = nextValue;
    draft.error = '';
    if (draft.timer) clearTimeout(draft.timer);
    draft.timer = setTimeout(() => flushReview(candidateId), 550);
    const state = document.querySelector(`[data-save-state="${CSS.escape(candidateId)}"]`);
    if (state) {
      state.dataset.error = 'false';
      state.firstChild.textContent = '수정 저장 대기 중';
    }
    updateControls();
  }

  async function flushReview(candidateId, allowConflict = false) {
    const draft = drafts.get(candidateId);
    const candidate = candidateById.get(candidateId);
    if (!draft || !candidate) return true;
    if (draft.timer) clearTimeout(draft.timer);
    draft.timer = null;
    if (draft.saving) return draft.promise;
    if (allowConflict && draft.conflict) {
      draft.baseRevision = candidate.revision;
      draft.conflict = false;
    }
    if (draft.conflict && !allowConflict) return false;
    if (!Object.keys(draft.changes).length && draft.selected === undefined) return true;
    const sentChanges = { ...draft.changes };
    const sentSelected = draft.selected;
    draft.saving = true;
    draft.error = '';
    let saved = false;
    draft.promise = (async () => {
      try {
        const result = await post('/api/receipts/workflow/review', {
          candidate_id: candidateId,
          expected_revision: draft.baseRevision,
          changes: sentChanges,
          ...(sentSelected === undefined ? {} : { selected: sentSelected }),
        });
        const updated = result.candidate;
        if (!updated || updated.revision == null) throw new Error('서버가 저장 revision을 반환하지 않았습니다.');
        for (const batch of batches) {
          const index = (batch.candidates || []).findIndex((item) => item.candidate_id === candidateId);
          if (index >= 0) batch.candidates[index] = updated;
        }
        candidateById.set(candidateId, updated);
        draft.baseRevision = updated.revision;
        for (const [key, value] of Object.entries(sentChanges)) {
          if (Object.is(draft.changes[key], value)) delete draft.changes[key];
        }
        if (sentSelected !== undefined && draft.selected === sentSelected) draft.selected = undefined;
        draft.conflict = false;
        if (!Object.keys(draft.changes).length && draft.selected === undefined) drafts.delete(candidateId);
        saved = true;
        pageStatus('교정 내용을 저장했습니다.');
        return true;
      } catch (error) {
        if (error.httpStatus === 409 || /REVISION|STALE|CONFLICT/i.test(error.code || '')) {
          draft.conflict = true;
          draft.error = '';
          pageStatus('다른 화면에서 이 내역을 수정했습니다. 최신 결과를 불러와 확인한 뒤 다시 저장할 수 있습니다.');
          void refreshState({ quiet: true });
        } else {
          draft.error = `${errorFeedback(error)} 다시 저장해 주세요.`;
          pageStatus(draft.error);
        }
        return false;
      } finally {
        draft.saving = false;
        draft.promise = null;
        renderCurrentBatches();
        if (saved && drafts.get(candidateId) === draft && !draft.conflict &&
            (Object.keys(draft.changes).length || draft.selected !== undefined)) {
          draft.timer = setTimeout(() => flushReview(candidateId), 0);
        }
      }
    })();
    return draft.promise;
  }

  async function flushAllReviews() {
    const ids = [...drafts.keys()];
    const results = await Promise.all(ids.map((id) => flushReview(id)));
    return results.every(Boolean) && drafts.size === 0;
  }

  function imageRequestId(signature) {
    const key = 'receipt-workflow-start-request';
    try {
      const previous = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (previous?.signature === signature && /^[0-9a-f]{32}$/.test(previous.request_id || '')) return previous.request_id;
      const request_id = newId();
      sessionStorage.setItem(key, JSON.stringify({ signature, request_id }));
      return request_id;
    } catch { return newId(); }
  }

  function retryRequestId(jobId) {
    const key = `receipt-workflow-retry:${jobId}`;
    try {
      const previous = JSON.parse(localStorage.getItem(key) || 'null');
      if (previous?.job_id === jobId && /^[0-9a-f]{32}$/.test(previous.request_id || '')) {
        return { request_id: previous.request_id, key };
      }
      const request_id = newId();
      localStorage.setItem(key, JSON.stringify({ job_id: jobId, request_id }));
      return { request_id, key };
    } catch { return { request_id: newId(), key: '' }; }
  }

  async function retryJob(jobId) {
    if (!jobId || retryingJobs.has(jobId)) return;
    retryingJobs.add(jobId);
    renderCurrentBatches();
    pageStatus('사진 재분석 요청을 보내고 있습니다.');
    const request = retryRequestId(jobId);
    try {
      const result = await post('/api/receipts/workflow/retry', {
        job_id: jobId,
        request_id: request.request_id,
      });
      if (!result.batch) throw new Error('서버가 재분석 상태를 반환하지 않았습니다.');
      if (request.key) try { localStorage.removeItem(request.key); } catch { /* the server remains authoritative */ }
      const index = batches.findIndex((batch) => batch.batch_id === result.batch.batch_id);
      if (index < 0) batches = [result.batch, ...batches];
      else batches[index] = result.batch;
      lastBatchFingerprint = JSON.stringify(batches);
      candidatesInData();
      renderCurrentBatches();
      pageStatus('사진 재분석을 접수했습니다. 작업 상태는 서버에 저장됩니다.');
    } catch (error) {
      if (error.httpStatus === 409) {
        if (request.key) try { localStorage.removeItem(request.key); } catch { /* keep the server response visible */ }
        pageStatus(`서버가 재분석을 접수하지 않았습니다 · ${errorFeedback(error)}`);
        await refreshState({ quiet: true });
      } else {
        pageStatus(`재분석 요청 결과를 확인하지 못했습니다 · ${errorFeedback(error, '이전 실행 상태를 확인하고 있어요. 중복 실행을 막기 위해 잠시 기다려 주세요.')} 같은 요청 ID를 유지합니다.`);
      }
    } finally {
      retryingJobs.delete(jobId);
      renderCurrentBatches();
    }
  }

  async function startBatch() {
    const selectedImages = [...document.querySelectorAll('[data-rw-image]:checked')].map((input) => input.value);
    const provider = byId('rw-provider').value;
    const model = byId('rw-model').value;
    const signature = JSON.stringify({ images: selectedImages.slice().sort(), provider, model });
    if (!selectedImages.length || !provider || !model) return;
    byId('rw-run-model').disabled = true;
    pageStatus('선택한 모델에 사진을 전달하고 있습니다. 다른 페이지로 이동해도 작업은 서버에 저장됩니다.');
    try {
      const result = await post('/api/receipts/workflow/batches', {
        images: selectedImages,
        provider,
        model,
        request_id: imageRequestId(signature),
      });
      try { sessionStorage.removeItem('receipt-workflow-start-request'); } catch { /* the server remains authoritative */ }
      pageStatus(`분석을 시작했습니다. 사진 ${selectedImages.length}장 · 작업 상태는 서버에 저장됩니다.`);
      if (result.batch) {
        batches = [result.batch, ...batches.filter((item) => item.batch_id !== result.batch.batch_id)];
        lastBatchFingerprint = JSON.stringify(batches);
        candidatesInData();
        renderCurrentBatches();
      } else await refreshState({ quiet: true });
    } catch (error) {
      pageStatus(`분석을 시작하지 못했습니다 · ${errorFeedback(error, '이전 실행 상태를 확인하고 있어요. 중복 실행을 막기 위해 잠시 기다려 주세요.')} 같은 사진으로 재시도하면 저장 여부를 확인합니다.`);
    } finally { updateControls(); }
  }

  function applyRequestId(selections) {
    const signature = JSON.stringify(selections.map(({ candidate_id, expected_revision }) => [candidate_id, expected_revision]).sort());
    const key = 'receipt-workflow-apply-request';
    try {
      const previous = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (previous?.signature === signature && /^[0-9a-f]{32}$/.test(previous.request_id || '')) return { request_id: previous.request_id, key };
      const request_id = newId();
      sessionStorage.setItem(key, JSON.stringify({ signature, request_id }));
      return { request_id, key };
    } catch { return { request_id: newId(), key: '' }; }
  }

  async function applySelected() {
    byId('rw-apply').disabled = true;
    pageStatus('수정 내용을 저장하고 선택 항목을 검증하고 있습니다.');
    if (!await flushAllReviews()) {
      pageStatus('수정 저장이 끝나지 않았습니다. 오류나 revision 충돌을 확인한 뒤 다시 시도해 주세요.');
      updateControls();
      return;
    }
    await refreshState({ quiet: true });
    candidatesInData();
    const selections = [...candidateById.values()]
      .filter((candidate) => candidate.selected === true && candidate.applied !== true)
      .map((candidate) => ({ candidate_id: candidate.candidate_id, expected_revision: candidate.revision }));
    if (!selections.length) {
      pageStatus('장부에 반영할 선택 항목이 없습니다.');
      updateControls();
      return;
    }
    const request = applyRequestId(selections);
    try {
      await post('/api/receipts/workflow/apply', { request_id: request.request_id, selections });
      if (request.key) try { sessionStorage.removeItem(request.key); } catch { /* read state from the server */ }
      await refreshState({ quiet: true });
      pageStatus('장부 반영 결과를 서버에서 다시 확인했습니다. 반영된 내역의 장부 행 링크가 표시됩니다.');
    } catch (error) {
      pageStatus(`장부에 반영하지 못했습니다 · ${errorFeedback(error)} 선택과 수정값은 보존했습니다. 다시 시도해 주세요.`);
    }
    updateControls();
  }

  async function digest(file) {
    const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }

  async function recoverUpload(file, kind) {
    const sha = await digest(file);
    const current = await get('/api/receipts');
    if (kind === 'image') return (current.images || []).includes(sha);
    return (current.pdfs || []).some((pdf) => pdf.sha256 === sha);
  }

  async function uploadFiles() {
    const input = byId('rw-files');
    const files = [...input.files];
    if (!files.length) {
      byId('rw-upload-status').textContent = '먼저 저장할 사진이나 PDF를 선택하세요.';
      input.focus();
      return;
    }
    const button = byId('rw-upload-button');
    const status = byId('rw-upload-status');
    button.disabled = true;
    const completed = [];
    const failed = [];
    try {
      for (const [index, file] of files.entries()) {
        status.textContent = `${file.name} 저장 중 · ${index + 1}/${files.length}`;
        const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
        const kind = isPdf ? 'pdf' : 'image';
        const endpoint = isPdf ? '/api/receipts/pdf' : '/api/receipts/image';
        const accepted = isPdf || file.type === 'image/png' || file.type === 'image/jpeg' || /\.(png|jpe?g)$/i.test(file.name);
        if (!accepted) { failed.push(`${file.name}: 이 화면은 JPEG·PNG·PDF를 지원합니다. HEIC는 기존 업로드 화면에서 등록해 주세요.`); continue; }
        if (!file.size || file.size > 5 * 1024 * 1024) { failed.push(`${file.name}: 파일은 5MB 이하여야 합니다.`); continue; }
        try {
          const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': isPdf ? 'application/pdf' : 'application/octet-stream',
              'X-CSRF-Token': csrf,
              'X-Receipt-Filename': encodeURIComponent(file.name),
              'X-Receipt-Language': 'ja',
            },
            body: file,
          });
          await apiRead(response);
          completed.push(file.name);
        } catch (error) {
          if (error instanceof TypeError || error.name === 'AbortError') {
            try {
              if (await recoverUpload(file, kind)) { completed.push(`${file.name} · 저장 결과 확인됨`); continue; }
            } catch { /* uncertain upload stays visible for an explicit retry */ }
          }
          failed.push(`${file.name}: ${errorFeedback(error)}`);
        }
      }
      await loadImages();
      status.textContent = [completed.length ? `원본 ${completed.length}개 저장됨` : '', failed.join(' / ')].filter(Boolean).join(' · ') || '저장 결과가 없습니다.';
      pageStatus(completed.length ? '원본을 보관했습니다. 분석할 사진을 선택하고 모델을 고르세요.' : '원본을 저장하지 못했습니다. 파일별 사유를 확인해 주세요.');
      document.dispatchEvent(new CustomEvent('receipt-workflow-change', { detail: { uploaded: completed.length } }));
    } finally {
      button.disabled = false;
      input.value = '';
    }
  }

  byId('rw-provider').addEventListener('change', () => loadCatalog(byId('rw-provider').value));
  byId('rw-model').addEventListener('change', () => {
    const model = models.find((item) => item.id === byId('rw-model').value);
    byId('rw-model-reason').textContent = model
      ? (model.selectable ? '이 모델로 처리 버튼을 누르면 분석이 시작됩니다.' : model.reason || '이 모델은 현재 선택할 수 없습니다.')
      : '모델 목록을 둘러봐도 분석은 시작되지 않습니다.';
    updateControls();
  });
  byId('rw-catalog-refresh').addEventListener('click', () => loadCatalog(byId('rw-provider').value));
  byId('rw-run-model').addEventListener('click', startBatch);
  byId('rw-refresh').addEventListener('click', () => refreshState());
  byId('rw-upload-button').addEventListener('click', uploadFiles);
  byId('rw-photo-list').addEventListener('change', updateControls);
  byId('rw-select-all').addEventListener('click', () => {
    document.querySelectorAll('[data-rw-image]').forEach((input) => { input.checked = true; });
    updateControls();
  });
  byId('rw-clear-selection').addEventListener('click', () => {
    document.querySelectorAll('[data-rw-image]').forEach((input) => { input.checked = false; });
    updateControls();
  });
  byId('rw-batches').addEventListener('input', (event) => {
    const control = event.target.closest('[data-field]');
    if (!control) {
      const zoom = event.target.closest('[data-zoom]');
      if (zoom) {
        const inner = document.querySelector(`[data-zoom-key="${CSS.escape(zoom.dataset.zoom)}"]`);
        if (inner) inner.style.setProperty('--rw-zoom', zoom.value);
        const output = zoom.parentElement.querySelector('output');
        if (output) output.value = `${zoom.value}×`;
      }
      return;
    }
    const candidate = control.closest('[data-candidate]');
    if (candidate) scheduleReview(candidate.dataset.candidate, control.dataset.field, inputValue(control.dataset.field, control));
  });
  byId('rw-batches').addEventListener('change', (event) => {
    const selection = event.target.closest('[data-select-candidate]');
    if (selection) scheduleReview(selection.dataset.selectCandidate, 'selected', selection.checked);
    const control = event.target.closest('[data-field]');
    if (control) {
      const candidate = control.closest('[data-candidate]');
      if (candidate) scheduleReview(candidate.dataset.candidate, control.dataset.field, inputValue(control.dataset.field, control));
    }
  });
  byId('rw-batches').addEventListener('click', (event) => {
    const retryJobButton = event.target.closest('[data-retry-job]');
    if (retryJobButton) {
      void retryJob(retryJobButton.dataset.retryJob);
      return;
    }
    const retry = event.target.closest('[data-conflict-retry]');
    if (retry) {
      const id = retry.dataset.conflictRetry;
      const draft = drafts.get(id);
      if (draft?.conflict) {
        void refreshState({ quiet: true }).then(() => flushReview(id, true));
      } else if (draft?.error) {
        draft.error = '';
        renderCurrentBatches();
        void flushReview(id);
      }
    }
  });
  byId('rw-apply').addEventListener('click', applySelected);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void refreshState({ quiet: true });
  });
  document.addEventListener('receipt-workflow-change', (event) => {
    if (event.detail?.uploaded) void loadImages();
  });
  window.addEventListener('beforeunload', (event) => {
    if (![...drafts.values()].some((draft) => draft.timer || draft.saving || draft.conflict || Object.keys(draft.changes).length || draft.selected !== undefined)) return;
    event.preventDefault();
    event.returnValue = '';
  });

  candidatesInData();
  void loadImages();
  void loadCatalog();
  void refreshState({ quiet: true });
  window.setInterval(() => {
    if (document.visibilityState === 'visible') void refreshState({ quiet: true });
  }, 4000);
})();
