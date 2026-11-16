import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Bootstrap } from '../../api/types';
import { getJSON, postJSON } from '../../api/client';
import type {
  LegacyCandidate,
  LegacyReceiptList,
  PaseoCatalog,
  PaseoModel,
  ReceiptReviewDraft,
  Revision,
  WorkflowBatch,
  WorkflowCandidate,
  WorkflowList,
} from './types';
import './receipts.css';

type PageProps = { bootstrap: Bootstrap; path: string; search: URLSearchParams };
type Source = { sha: string; kind: 'image' | 'pdf-page'; label: string; pdfSha?: string; page?: number };
type UploadFailure = { key: string; file: File; body?: Blob; kind: 'image' | 'pdf'; message: string };
type PendingApply = { request_id: string; selections: Array<{ candidate_id: string; expected_revision: Revision }> };
type PendingRun = { request_id: string; images: string[]; provider: string; model: string; label: string };
type PendingReceiptRequests = {
  apply: PendingApply | null;
  run: PendingRun | null;
  retries: Record<string, string>;
};

const emptyLegacy: LegacyReceiptList = { candidates: [], images: [], pdfs: [], uploads: [] };
const pendingRequestsStorageKey = 'cost.receipts.pending-workflow.v1';
const statusLabel: Record<string, string> = {
  queued: '대기 중', pending: '대기 중', running: '처리 중', started: '처리 중',
  done: '완료', completed: '완료', succeeded: '완료', failed: '실패', error: '실패',
  applied: '장부 반영됨', cancelled: '취소됨',
};
const paymentOptions = [
  { value: '', label: '결제수단 선택' },
  { value: 'cash', label: '현금' },
  { value: 'private_card', label: '개인카드' },
  { value: 'corporate_card', label: '법인카드' },
];
const currencyOptions = [
  { value: '', label: '통화 선택' },
  { value: 'JPY', label: '엔화 JPY' },
  { value: 'KRW', label: '원화 KRW' },
];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '요청을 완료하지 못했습니다. 연결 상태를 확인해 주세요.';
}

function randomRequestId(): string {
  const browserCrypto = typeof globalThis.crypto !== 'undefined' ? globalThis.crypto : undefined;
  if (browserCrypto?.randomUUID) return browserCrypto.randomUUID().replaceAll('-', '');
  if (!browserCrypto?.getRandomValues) {
    return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padStart(32, '0').slice(-32);
  }
  const bytes = new Uint8Array(16);
  browserCrypto.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
}

function readPendingRequests(): PendingReceiptRequests {
  const empty: PendingReceiptRequests = { apply: null, run: null, retries: {} };
  if (typeof window === 'undefined') return empty;
  try {
    const raw = window.sessionStorage.getItem(pendingRequestsStorageKey);
    if (!raw) return empty;
    const saved = JSON.parse(raw) as Record<string, unknown>;
    if (saved.version !== 1) return empty;
    const applyValue = saved.apply as Record<string, unknown> | null;
    const applySelections = Array.isArray(applyValue?.selections) ? applyValue.selections : [];
    const apply = typeof applyValue?.request_id === 'string'
      && /^[a-f0-9]{32}$/.test(applyValue.request_id)
      && applySelections.length > 0
      && applySelections.every((selection) => {
        const item = selection as Record<string, unknown>;
        return typeof item.candidate_id === 'string' && Number.isInteger(item.expected_revision);
      })
      ? applyValue as unknown as PendingApply
      : null;
    const runValue = saved.run as Record<string, unknown> | null;
    const runImages = Array.isArray(runValue?.images) ? runValue.images : [];
    const run = typeof runValue?.request_id === 'string'
      && /^[a-f0-9]{32}$/.test(runValue.request_id)
      && runImages.length > 0
      && runImages.every((image) => typeof image === 'string' && /^[a-f0-9]{64}$/.test(image))
      && typeof runValue.provider === 'string'
      && typeof runValue.model === 'string'
      && typeof runValue.label === 'string'
      ? runValue as unknown as PendingRun
      : null;
    const retriesValue = saved.retries && typeof saved.retries === 'object'
      ? saved.retries as Record<string, unknown>
      : {};
    const retries: Record<string, string> = {};
    for (const [jobId, requestId] of Object.entries(retriesValue)) {
      if (/^[a-f0-9]{32}$/.test(jobId) && typeof requestId === 'string' && /^[a-f0-9]{32}$/.test(requestId)) {
        retries[jobId] = requestId;
      }
    }
    return { apply, run, retries };
  } catch {
    return empty;
  }
}

function writePendingRequests(pending: PendingReceiptRequests): void {
  if (typeof window === 'undefined') return;
  try {
    if (!pending.apply && !pending.run && !Object.keys(pending.retries).length) {
      window.sessionStorage.removeItem(pendingRequestsStorageKey);
      return;
    }
    window.sessionStorage.setItem(pendingRequestsStorageKey, JSON.stringify({ version: 1, ...pending }));
  } catch {
    // Session storage can be disabled; the in-memory retry path remains available.
  }
}

function imageUrl(sha: string): string {
  return `/api/receipts/image/${encodeURIComponent(sha)}`;
}

function normalizeImage(file: File): Promise<Blob> {
  const limit = 5 * 1024 * 1024;
  if ((file.type === 'image/jpeg' || file.type === 'image/png') && file.size <= limit) return Promise.resolve(file);
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/') && !/\.(jpe?g|png|heic|heif|webp)$/i.test(file.name)) {
      reject(new Error('사진 형식만 등록할 수 있습니다.'));
      return;
    }
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = async () => {
      try {
        if (!image.naturalWidth || !image.naturalHeight) throw new Error('사진 크기를 확인할 수 없습니다.');
        for (const maxSide of [3000, 2600, 2200]) {
          const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
          const canvas = document.createElement('canvas');
          canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
          canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
          const context = canvas.getContext('2d');
          if (!context) throw new Error('사진 변환을 사용할 수 없습니다.');
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          for (const quality of [0.92, 0.82, 0.72]) {
            const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, 'image/jpeg', quality));
            if (blob && blob.size > 0 && blob.size <= limit) {
              resolve(blob);
              return;
            }
          }
        }
        throw new Error('사진이 5MB 제한을 넘었습니다. 더 작은 사진으로 다시 등록해 주세요.');
      } catch (error) {
        reject(error);
      } finally {
        URL.revokeObjectURL(objectUrl);
      }
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error('사진을 열 수 없습니다. HEIC 파일은 JPEG로 내보내 다시 등록해 주세요.'));
    };
    image.src = objectUrl;
  });
}

async function uploadOriginal(file: File, body: Blob, kind: 'image' | 'pdf', csrf: string): Promise<unknown> {
  const response = await fetch(kind === 'pdf' ? '/api/receipts/pdf' : '/api/receipts/image', {
    method: 'POST',
    headers: {
      'Content-Type': kind === 'pdf' ? 'application/pdf' : 'application/octet-stream',
      'X-CSRF-Token': csrf,
      'X-Receipt-Filename': encodeURIComponent(file.name),
    },
    body,
  });
  let result: unknown;
  try {
    result = await response.json();
  } catch {
    throw new Error(response.ok ? '원본 저장 상태를 확인하지 못했습니다. 목록을 새로고침해 주세요.' : `원본 저장 오류 (${response.status})`);
  }
  if (!response.ok) {
    const payload = result as { message?: string; code?: string };
    throw new Error(payload.message || payload.code || `원본 저장 오류 (${response.status})`);
  }
  return result;
}

function statusText(status: string): string {
  return statusLabel[status.toLowerCase()] || status || '상태 확인 중';
}

function pythonJson(value: unknown, parentKey = ''): string {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 'null';
    return parentKey === 'box' && Number.isInteger(value) ? `${value}.0` : String(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => pythonJson(item, parentKey)).join(', ')}]`;
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}: ${pythonJson(record[key], key)}`).join(', ')}}`;
  }
  return 'null';
}

async function legacyVersion(candidate: LegacyCandidate): Promise<string | undefined> {
  try {
    const bytes = new TextEncoder().encode(pythonJson(candidate));
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
  } catch {
    return undefined;
  }
}

function paymentLabel(payment: string | null | undefined): string {
  return paymentOptions.find((option) => option.value === payment)?.label || '결제수단 미확인';
}

function dateLabel(value: string | null | undefined): string {
  return value || '날짜 미확인';
}

function candidateDraft(candidate: WorkflowCandidate): ReceiptReviewDraft {
  return {
    expectedRevision: candidate.revision,
    merchant: candidate.merchant || '',
    date: candidate.date || '',
    amount: candidate.amount == null ? '' : String(candidate.amount),
    currency: candidate.currency || '',
    payment: candidate.payment || '',
    trip_id: candidate.trip_id || '',
    category: candidate.category || '',
    company_expense: candidate.company_expense ?? null,
    selected: Boolean(candidate.selected),
    editing: false,
    dirty: false,
    saving: false,
  };
}

function comparableAmount(value: unknown): string {
  const text = String(value ?? '').trim();
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const whole = match[2].replace(/^0+(?=\d)/, '');
  const fraction = (match[3] || '').replace(/0+$/, '');
  return `${match[1]}${whole}${fraction ? `.${fraction}` : ''}`;
}

function reviewMatchesCandidate(
  candidate: WorkflowCandidate,
  pending: NonNullable<ReceiptReviewDraft['pending']>,
): boolean {
  if (candidate.selected !== pending.selected) return false;
  const record = candidate as unknown as Record<string, unknown>;
  return Object.entries(pending.changes).every(([key, expected]) => {
    const actual = record[key];
    if (key === 'amount') return comparableAmount(actual) === comparableAmount(expected);
    if (key === 'merchant' && typeof actual === 'string' && typeof expected === 'string') {
      return actual.trim() === expected.trim();
    }
    return (actual ?? null) === (expected ?? null);
  });
}

function candidateForImage(candidate: WorkflowCandidate): string {
  return candidate.image || '';
}

function hasActiveJob(batch: WorkflowBatch): boolean {
  return batch.jobs.some((job) => ['queued', 'pending', 'running', 'started'].includes(job.status.toLowerCase()));
}

export function ReceiptsPage({ bootstrap, search }: PageProps) {
  const [legacy, setLegacy] = useState<LegacyReceiptList>(emptyLegacy);
  const [workflow, setWorkflow] = useState<WorkflowList>({ batches: [] });
  const [catalog, setCatalog] = useState<PaseoCatalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [provider, setProvider] = useState('');
  const [sources, setSources] = useState<Source[]>([]);
  const [activeSha, setActiveSha] = useState('');
  const [selectedShas, setSelectedShas] = useState<Set<string>>(() => new Set());
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadFailures, setUploadFailures] = useState<UploadFailure[]>([]);
  const [uploading, setUploading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pageError, setPageError] = useState('');
  const [notice, setNotice] = useState('');
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, ReceiptReviewDraft>>({});
  const [pendingRequests, setPendingRequests] = useState<PendingReceiptRequests>(readPendingRequests);
  const pendingRequestsRef = useRef(pendingRequests);
  const pendingApply = pendingRequests.apply;
  const pendingRun = pendingRequests.run;
  const [applying, setApplying] = useState(false);
  const [retryingJob, setRetryingJob] = useState('');
  const [mobilePane, setMobilePane] = useState<'source' | 'results'>('source');
  const [zoomOpen, setZoomOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [sourceAspect, setSourceAspect] = useState<number | null>(null);
  const [legacyManualOpen, setLegacyManualOpen] = useState(false);
  const [manualSha, setManualSha] = useState('');
  const [manualMerchant, setManualMerchant] = useState('');
  const [manualDate, setManualDate] = useState('');
  const [manualCurrency, setManualCurrency] = useState('JPY');
  const [manualAmount, setManualAmount] = useState('');
  const [manualPayment, setManualPayment] = useState('cash');
  const [manualTrip, setManualTrip] = useState(search.get('trip') || '');
  const [savingManual, setSavingManual] = useState(false);
  const [legacyDrafts, setLegacyDrafts] = useState<Record<string, Partial<LegacyCandidate>>>({});
  const [savingLegacy, setSavingLegacy] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const zoomDialog = useRef<HTMLDialogElement>(null);
  const zoomTrigger = useRef<HTMLElement | null>(null);
  const csrf = bootstrap.csrf;

  const updatePendingRequests = useCallback((patch: Partial<PendingReceiptRequests>) => {
    const next = { ...pendingRequestsRef.current, ...patch };
    pendingRequestsRef.current = next;
    setPendingRequests(next);
    writePendingRequests(next);
  }, []);

  const openZoom = useCallback((trigger: HTMLElement) => {
    zoomTrigger.current = trigger;
    setZoom(1);
    setZoomOpen(true);
  }, []);

  const closeZoom = useCallback(() => {
    if (zoomDialog.current?.open) zoomDialog.current.close();
    else setZoomOpen(false);
  }, []);

  const onZoomClose = useCallback(() => {
    setZoomOpen(false);
    const trigger = zoomTrigger.current;
    zoomTrigger.current = null;
    if (trigger?.isConnected) trigger.focus();
  }, []);

  const loadLegacy = useCallback(async () => {
    const data = await getJSON<LegacyReceiptList>('/api/receipts');
    const candidates = await Promise.all(data.candidates.map(async (candidate) => ({
      ...candidate,
      version: candidate.version || await legacyVersion(candidate),
    })));
    const versioned = { ...data, candidates };
    setLegacy(versioned);
    return versioned;
  }, []);

  const loadWorkflow = useCallback(async () => {
    const data = await getJSON<WorkflowList>('/api/receipts/workflow');
    setWorkflow(data);
    const pending = pendingRequestsRef.current.apply;
    if (pending) {
      const candidates = new Map(data.batches.flatMap((batch) => batch.candidates)
        .map((candidate) => [candidate.candidate_id, candidate]));
      if (pending.selections.every((selection) => candidates.get(selection.candidate_id)?.applied)) {
        updatePendingRequests({ apply: null });
      }
    }
    return data;
  }, [updatePendingRequests]);

  const loadCatalog = useCallback(async (forProvider?: string) => {
    setCatalogError('');
    const suffix = forProvider ? `?provider=${encodeURIComponent(forProvider)}` : '';
    try {
      const data = await getJSON<PaseoCatalog>(`/api/receipts/paseo/models${suffix}`);
      setCatalog(data);
      if (!forProvider && !provider && data.providers.length) setProvider(data.providers[0].id);
      return data;
    } catch (error) {
      setCatalogError(errorText(error));
      throw error;
    }
  }, [provider]);

  const refreshAll = useCallback(async (includeCatalog = true) => {
    setRefreshing(true);
    setPageError('');
    try {
      const tasks: Array<Promise<unknown>> = [loadLegacy(), loadWorkflow()];
      if (includeCatalog) tasks.push(loadCatalog(provider || undefined).catch(() => undefined));
      const [legacyData] = await Promise.all(tasks);
      const sourceData = legacyData as LegacyReceiptList | undefined;
      if (sourceData) {
        const nextSources: Source[] = sourceData.images.map((sha) => ({ sha, kind: 'image', label: '사진 원본' }));
        for (const pdf of sourceData.pdfs || []) {
          pdf.pages.forEach((sha, index) => nextSources.push({
            sha, kind: 'pdf-page', label: `PDF ${pdf.sha256.slice(0, 8)} · ${index + 1}페이지`, pdfSha: pdf.sha256, page: index + 1,
          }));
        }
        setSources(nextSources);
        if (!activeSha && nextSources.length) setActiveSha(nextSources.at(-1)!.sha);
        setSelectedShas((current) => new Set([...current].filter((sha) => nextSources.some((source) => source.sha === sha))));
      }
      setNotice('영수증 저장 상태를 새로 읽었습니다.');
    } catch (error) {
      setPageError(errorText(error));
    } finally {
      setRefreshing(false);
    }
  }, [activeSha, loadCatalog, loadLegacy, loadWorkflow, provider]);

  useEffect(() => { void refreshAll(); }, []); // Initial data is server-authoritative.

  useEffect(() => {
    if (!catalog || !provider) return;
    if (catalog.models.every((model) => model.provider === provider)) return;
    void loadCatalog(provider).catch(() => undefined);
  }, [catalog, loadCatalog, provider]);

  const allCandidates = useMemo(() => workflow.batches.flatMap((batch) => batch.candidates), [workflow]);
  const visibleCandidates = useMemo(
    () => allCandidates.filter((candidate) => !activeSha || candidateForImage(candidate) === activeSha),
    [activeSha, allCandidates],
  );
  const activeSource = sources.find((source) => source.sha === activeSha);
  const currentModels = (catalog?.models || []).filter((model) => !provider || model.provider === provider);
  const selectedCandidates = allCandidates.filter((candidate) => {
    const draft = reviewDrafts[candidate.candidate_id];
    return (draft ? draft.selected : candidate.selected) && !candidate.applied;
  });
  const canApply = selectedCandidates.length > 0
    && selectedCandidates.every((candidate) => !reviewDrafts[candidate.candidate_id]?.dirty
      && !reviewDrafts[candidate.candidate_id]?.saving
      && !reviewDrafts[candidate.candidate_id]?.error);
  const selectedJobsCount = selectedShas.size;
  const anyActive = workflow.batches.some(hasActiveJob);
  const applyLocked = Boolean(pendingApply);

  useEffect(() => {
    if (!anyActive) return;
    const timer = window.setInterval(() => {
      void loadWorkflow().catch(() => undefined);
    }, 4500);
    return () => window.clearInterval(timer);
  }, [anyActive, loadWorkflow]);

  useEffect(() => {
    const dialog = zoomDialog.current;
    if (!dialog) return;
    if (zoomOpen && !dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLButtonElement>('[data-zoom-close]')?.focus();
    } else if (!zoomOpen && dialog.open) {
      dialog.close();
    }
  }, [zoomOpen]);

  useEffect(() => { setSourceAspect(null); }, [activeSha]);

  const updateSources = useCallback(async () => {
    const data = await loadLegacy();
    const nextSources: Source[] = data.images.map((sha) => ({ sha, kind: 'image', label: '사진 원본' }));
    for (const pdf of data.pdfs || []) {
      pdf.pages.forEach((sha, index) => nextSources.push({
        sha, kind: 'pdf-page', label: `PDF ${pdf.sha256.slice(0, 8)} · ${index + 1}페이지`, pdfSha: pdf.sha256, page: index + 1,
      }));
    }
    setSources(nextSources);
    return data;
  }, [loadLegacy]);

  const uploadOne = useCallback(async (file: File, existing?: UploadFailure) => {
    const kind: 'image' | 'pdf' = file.type === 'application/pdf' || /\.pdf$/i.test(file.name) ? 'pdf' : 'image';
    let body: Blob | undefined = existing?.body;
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    try {
      body ||= kind === 'pdf' ? file : await normalizeImage(file);
      const uploadResult = await uploadOriginal(file, body, kind, csrf) as { sha256?: string; pages?: string[] };
      setUploadFailures((current) => current.filter((item) => item.key !== key));
      const data = await updateSources();
      if (kind === 'image') {
        const newest = uploadResult.sha256 && data.images.includes(uploadResult.sha256) ? uploadResult.sha256 : data.images.at(-1);
        if (newest) setActiveSha(newest);
      } else {
        const page = uploadResult.pages?.[0];
        const pdf = (data.pdfs || []).find((item) => item.pages.includes(page || '')) || data.pdfs?.at(-1);
        if (page && data.images.includes(page)) setActiveSha(page);
        else if (pdf?.pages[0]) setActiveSha(pdf.pages[0]);
      }
      setNotice(`${file.name} 원본을 저장했습니다. 모델 실행은 사진을 고르고 직접 선택해 시작합니다.`);
    } catch (error) {
      const failure: UploadFailure = { key, file, body, kind, message: errorText(error) };
      setUploadFailures((current) => [...current.filter((item) => item.key !== key), failure]);
    }
  }, [csrf, updateSources]);

  const onUpload = useCallback(async () => {
    if (!uploadFiles.length || uploading) return;
    setUploading(true);
    setPageError('');
    try {
      for (const file of uploadFiles) await uploadOne(file);
      setUploadFiles([]);
      if (fileInput.current) fileInput.current.value = '';
    } finally {
      setUploading(false);
    }
  }, [uploadFiles, uploadOne, uploading]);

  const retryUpload = useCallback(async (failure: UploadFailure) => {
    setUploading(true);
    try {
      await uploadOne(failure.file, failure);
    } finally {
      setUploading(false);
    }
  }, [uploadOne]);

  const submitModelRun = useCallback(async (pending: PendingRun) => {
    updatePendingRequests({ run: pending });
    setPageError('');
    setNotice(`${pending.label}에 ${pending.images.length}장 작업을 요청합니다.`);
    try {
      await postJSON<{ batch: WorkflowBatch }>('/api/receipts/workflow/batches', {
        images: pending.images, provider: pending.provider, model: pending.model, request_id: pending.request_id,
      }, csrf);
      setSelectedShas(new Set());
      await loadWorkflow();
      updatePendingRequests({ run: null });
      setNotice(`${pending.label} 작업이 접수됐습니다. 사진별 상태는 이 화면에 계속 저장됩니다.`);
    } catch (error) {
      updatePendingRequests({ run: pending });
      setPageError(`${errorText(error)} 접수 여부를 확인한 뒤 같은 요청을 재시도할 수 있습니다. 재시도는 동일한 request_id와 사진 목록을 사용합니다.`);
      await loadWorkflow().catch(() => undefined);
    }
  }, [csrf, loadWorkflow, updatePendingRequests]);

  const runModel = useCallback(async (model: PaseoModel) => {
    if (!selectedShas.size) {
      setPageError('분석할 사진을 먼저 선택하세요.');
      return;
    }
    await submitModelRun({ request_id: randomRequestId(), images: [...selectedShas], provider: model.provider, model: model.id, label: model.label });
  }, [selectedShas, submitModelRun]);

  const beginCandidateEdit = useCallback((candidate: WorkflowCandidate) => {
    setReviewDrafts((current) => ({
      ...current,
      [candidate.candidate_id]: { ...candidateDraft(candidate), editing: true, dirty: false },
    }));
  }, []);

  const discardCandidateEdit = useCallback((candidateId: string) => {
    setReviewDrafts((state) => {
      const next = { ...state };
      delete next[candidateId];
      return next;
    });
  }, []);

  const restartCandidateEdit = useCallback(async (candidateId: string) => {
    try {
      const latest = await loadWorkflow();
      const candidate = latest.batches.flatMap((batch) => batch.candidates)
        .find((item) => item.candidate_id === candidateId);
      if (!candidate) {
        setPageError('최신 후보를 찾지 못했습니다. 목록을 새로고침한 뒤 다시 확인해 주세요.');
        return;
      }
      if (candidate.applied) {
        setPageError('이미 장부에 반영된 후보는 수정할 수 없습니다. 최신 목록을 확인해 주세요.');
        return;
      }
      beginCandidateEdit(candidate);
      setNotice('최신 서버 revision으로 교정을 다시 시작했습니다.');
    } catch (error) {
      setPageError(`최신 후보를 불러오지 못했습니다. ${errorText(error)}`);
    }
  }, [beginCandidateEdit, loadWorkflow]);

  const changeDraft = useCallback((candidate: WorkflowCandidate, key: keyof ReceiptReviewDraft, value: unknown) => {
    setReviewDrafts((current) => {
      const existing = current[candidate.candidate_id] || candidateDraft(candidate);
      return { ...current, [candidate.candidate_id]: { ...existing, [key]: value, dirty: true, error: undefined } };
    });
  }, []);

  const saveCandidate = useCallback(async (candidate: WorkflowCandidate, retry = false, selectedOverride?: boolean) => {
    const current = reviewDrafts[candidate.candidate_id] || candidateDraft(candidate);
    const effectiveCurrent = selectedOverride === undefined ? current : { ...current, selected: selectedOverride };
    const pending = retry && current.pending ? current.pending : {
      expected_revision: effectiveCurrent.expectedRevision,
      changes: effectiveCurrent.editing ? {
        merchant: effectiveCurrent.merchant,
        date: effectiveCurrent.date,
        amount: effectiveCurrent.amount === '' ? null : effectiveCurrent.amount,
        currency: effectiveCurrent.currency || null,
        payment: effectiveCurrent.payment || null,
        trip_id: effectiveCurrent.trip_id || null,
        category: effectiveCurrent.category || null,
        company_expense: effectiveCurrent.company_expense,
      } : {},
      selected: effectiveCurrent.selected,
    };
    setReviewDrafts((state) => ({ ...state, [candidate.candidate_id]: { ...effectiveCurrent, pending, saving: true, error: undefined, revisionConflict: false } }));
    try {
      const result = await postJSON<{ candidate: WorkflowCandidate }>('/api/receipts/workflow/review', {
        candidate_id: candidate.candidate_id,
        expected_revision: pending.expected_revision,
        changes: pending.changes,
        selected: pending.selected,
      }, csrf);
      setWorkflow((state) => ({
        batches: state.batches.map((batch) => ({
          ...batch,
          candidates: batch.candidates.map((item) => item.candidate_id === candidate.candidate_id ? result.candidate : item),
        })),
      }));
      setReviewDrafts((state) => {
        const next = { ...state };
        delete next[candidate.candidate_id];
        return next;
      });
      setNotice(`${result.candidate.merchant || '영수증'} 교정과 선택 상태를 저장했습니다.`);
    } catch (error) {
      const latest = await loadWorkflow().catch(() => null);
      const persisted = latest?.batches.flatMap((batch) => batch.candidates)
        .find((item) => item.candidate_id === candidate.candidate_id);
      if (persisted && reviewMatchesCandidate(persisted, pending)) {
        setReviewDrafts((state) => {
          const next = { ...state };
          delete next[candidate.candidate_id];
          return next;
        });
        setNotice(`${persisted.merchant || '영수증'} 교정이 서버에 저장된 것을 확인했습니다.`);
        return;
      }
      if (persisted && persisted.revision !== pending.expected_revision) {
        setReviewDrafts((state) => ({
          ...state,
          [candidate.candidate_id]: {
            ...effectiveCurrent,
            pending: undefined,
            saving: false,
            revisionConflict: true,
            error: '편집을 시작한 뒤 서버 값이 바뀌었습니다. 최신 revision을 불러와 다시 시작해 주세요.',
          },
        }));
        return;
      }
      if (persisted) {
        setReviewDrafts((state) => ({
          ...state,
          [candidate.candidate_id]: { ...effectiveCurrent, pending: undefined, saving: false, error: errorText(error) },
        }));
        return;
      }
      setReviewDrafts((state) => ({
        ...state,
        [candidate.candidate_id]: { ...effectiveCurrent, pending, saving: false, error: errorText(error) },
      }));
    }
  }, [csrf, loadWorkflow, reviewDrafts]);

  const toggleCandidateSelection = useCallback((candidate: WorkflowCandidate, checked: boolean) => {
    const existing = reviewDrafts[candidate.candidate_id];
    if (existing) {
      setReviewDrafts((state) => ({
        ...state,
        [candidate.candidate_id]: { ...existing, selected: checked, dirty: true, error: undefined },
      }));
      return;
    }
    const draft = candidateDraft(candidate);
    setReviewDrafts((state) => ({ ...state, [candidate.candidate_id]: { ...draft, selected: checked, dirty: true } }));
    void saveCandidate(candidate, false, checked);
  }, [reviewDrafts, saveCandidate]);

  const retryJob = useCallback(async (jobId: string) => {
    const requestId = pendingRequestsRef.current.retries[jobId] || randomRequestId();
    updatePendingRequests({ retries: { ...pendingRequestsRef.current.retries, [jobId]: requestId } });
    setRetryingJob(jobId);
    setPageError('');
    try {
      await postJSON<{ batch: WorkflowBatch }>('/api/receipts/workflow/retry', { job_id: jobId, request_id: requestId }, csrf);
      await loadWorkflow();
      const retries = { ...pendingRequestsRef.current.retries };
      delete retries[jobId];
      updatePendingRequests({ retries });
      setNotice('실패한 사진의 재분석 작업을 접수했습니다.');
    } catch (error) {
      setPageError(`${errorText(error)} 다시 시도하면 같은 request_id를 사용합니다.`);
    } finally {
      setRetryingJob('');
    }
  }, [csrf, loadWorkflow, updatePendingRequests]);

  const applySelected = useCallback(async (retry = false) => {
    const pending = retry && pendingApply ? pendingApply : {
      request_id: randomRequestId(),
      selections: selectedCandidates.map((candidate) => ({
        candidate_id: candidate.candidate_id,
        expected_revision: reviewDrafts[candidate.candidate_id]?.expectedRevision ?? candidate.revision,
      })),
    };
    if (!pending.selections.length || applying) return;
    updatePendingRequests({ apply: pending });
    setApplying(true);
    setPageError('');
    try {
      await postJSON<unknown>('/api/receipts/workflow/apply', pending, csrf);
      await Promise.all([loadWorkflow(), loadLegacy()]);
      updatePendingRequests({ apply: null });
      setNotice(`${pending.selections.length}건의 선택 반영 요청을 처리했습니다. 서버에 저장된 반영 상태를 다시 읽었습니다.`);
    } catch (error) {
      setPageError(`${errorText(error)} 재시도는 같은 request_id와 같은 선택·revision 묶음을 사용합니다.`);
    } finally {
      setApplying(false);
    }
  }, [applying, csrf, loadLegacy, loadWorkflow, pendingApply, reviewDrafts, selectedCandidates, updatePendingRequests]);

  const saveManual = useCallback(async () => {
    if (savingManual) return;
    const total = Number(manualAmount);
    if (!manualMerchant.trim() || !manualDate || !manualCurrency || !manualPayment || !Number.isFinite(total) || total <= 0) {
      setPageError('상호·날짜·통화·금액·결제수단을 입력해야 합니다.');
      return;
    }
    setSavingManual(true);
    setPageError('');
    try {
      await postJSON('/api/receipts/scan', {
        ...(manualSha ? { image: manualSha } : {}),
        ...(manualTrip ? { trip_id: manualTrip } : {}),
        header_source: 'ocr',
        regions: [{ box: null, merchant: manualMerchant.trim(), date: manualDate,
          currency: manualCurrency, total, payment: manualPayment, confidence: 1 }],
      }, csrf);
      setManualMerchant(''); setManualDate(''); setManualAmount('');
      setLegacyManualOpen(false);
      setNotice('직접 입력한 영수증을 기존 영수증 목록에 등록했습니다.');
      await loadLegacy().catch((error) => {
        setPageError(`등록 요청은 처리됐지만 목록을 다시 읽지 못했습니다. 같은 내용을 다시 보내지 말고 목록 새로고침으로 확인해 주세요. ${errorText(error)}`);
      });
    } catch (error) {
      setPageError(`${errorText(error)} 등록 여부가 불확실하면 같은 내용을 다시 보내기 전에 목록을 새로고침해 확인해 주세요.`);
    } finally {
      setSavingManual(false);
    }
  }, [csrf, loadLegacy, manualAmount, manualCurrency, manualDate, manualMerchant, manualPayment, manualSha, manualTrip, savingManual]);

  const saveLegacyCandidate = useCallback(async (candidate: LegacyCandidate) => {
    const draft = legacyDrafts[candidate.identity] || {};
    setSavingLegacy(candidate.identity);
    setPageError('');
    if (!candidate.version) {
      setPageError('이전 후보의 저장 revision을 확인할 수 없어 안전하게 수정하지 않았습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.');
      setSavingLegacy('');
      return;
    }
    try {
      await postJSON('/api/receipts/edit', {
        identity: candidate.identity,
        expected_version: candidate.version,
        merchant: draft.merchant ?? candidate.merchant,
        date: draft.date ?? candidate.date,
        [candidate.currency === 'KRW' ? 'total_original' : 'total_jpy']:
          Number(draft.total_original ?? draft.total_jpy ?? (candidate.currency === 'KRW' ? candidate.total_original : candidate.total_jpy)),
        payment: draft.payment ?? candidate.payment,
        trip_id: draft.trip_id ?? candidate.trip_id ?? '',
        payee: draft.payee ?? candidate.payee ?? '',
        category: draft.category ?? candidate.category ?? '',
      }, csrf);
      setLegacyDrafts((state) => { const next = { ...state }; delete next[candidate.identity]; return next; });
      await loadLegacy();
      setNotice('기존 영수증 후보를 저장했습니다.');
    } catch (error) {
      setPageError(errorText(error));
    } finally {
      setSavingLegacy('');
    }
  }, [csrf, legacyDrafts, loadLegacy]);

  const legacyEdit = useCallback((candidate: LegacyCandidate, field: keyof LegacyCandidate, value: unknown) => {
    setLegacyDrafts((state) => ({ ...state, [candidate.identity]: { ...state[candidate.identity], [field]: value } }));
  }, []);

  const startManualFor = useCallback((sha = '') => {
    setManualSha(sha);
    setLegacyManualOpen(true);
    if (sha) setActiveSha(sha);
    window.setTimeout(() => document.getElementById('receipt-manual-merchant')?.focus(), 0);
  }, []);

  const setCandidateDraftValue = (candidate: WorkflowCandidate, field: keyof ReceiptReviewDraft, value: unknown) => {
    changeDraft(candidate, field, value);
  };

  const currentImageCandidates = visibleCandidates;

  return (
    <main className="receipt-page" aria-labelledby="receipt-title">
      <header className="receipt-page__header">
        <div>
          <p className="receipt-eyebrow">비용 · 영수증</p>
          <h1 id="receipt-title">영수증 작업공간</h1>
          <p className="receipt-lede">원본 사진을 고르고 모델을 직접 선택해 처리한 뒤, 사진별 결과를 수정하고 선택한 건만 한 번에 반영합니다.</p>
        </div>
        <button className="receipt-button receipt-button--quiet" type="button" onClick={() => void refreshAll()} disabled={refreshing}>
          {refreshing ? '새로고침 중…' : '목록 새로고침'}
        </button>
      </header>

      <div className="receipt-live" role="status" aria-live="polite">{notice}</div>
      {pageError && <div className="receipt-alert" role="alert"><span>{pageError}</span><button type="button" className="receipt-button receipt-button--quiet" onClick={() => setPageError('')}>닫기</button></div>}

      <section className="receipt-card receipt-upload" aria-labelledby="receipt-upload-title">
        <div className="receipt-section-heading">
          <div><p className="receipt-step">01 · 원본</p><h2 id="receipt-upload-title">사진 또는 PDF 등록</h2></div>
          <span className="receipt-count">저장된 원본 {sources.length}장</span>
        </div>
        <div className="receipt-upload__controls">
          <label className="receipt-file-picker">
            <span>사진·PDF 선택</span>
            <input ref={fileInput} type="file" accept="image/*,application/pdf,.pdf" multiple
              onChange={(event) => setUploadFiles((files) => [...files, ...Array.from(event.target.files || [])])} />
          </label>
          <button className="receipt-button receipt-button--primary" type="button" onClick={() => void onUpload()} disabled={!uploadFiles.length || uploading}>
            {uploading ? '원본 저장 중…' : `선택한 파일 저장${uploadFiles.length ? ` ${uploadFiles.length}개` : ''}`}
          </button>
          <button className="receipt-button receipt-button--quiet" type="button" onClick={() => startManualFor(activeSha)}>내용 직접 입력</button>
        </div>
        {uploadFiles.length > 0 && <ul className="receipt-file-list" aria-label="저장할 파일">
          {uploadFiles.map((file, index) => <li key={`${file.name}-${file.lastModified}-${index}`}>
            <span>{file.name} · {Math.max(1, Math.ceil(file.size / 1024))}KB</span>
            <button type="button" className="receipt-link-button" aria-label={`${file.name} 선택 제거`} onClick={() => setUploadFiles((files) => files.filter((_, itemIndex) => itemIndex !== index))}>제거</button>
          </li>)}
        </ul>}
        {uploadFailures.length > 0 && <div className="receipt-upload-failures" aria-label="저장 실패 파일">
          {uploadFailures.map((failure) => <div className="receipt-upload-failure" key={failure.key}>
            <div><strong>{failure.file.name}</strong><p>{failure.message}</p></div>
            <button type="button" className="receipt-button receipt-button--quiet" disabled={uploading} onClick={() => void retryUpload(failure)}>같은 원본 재시도</button>
          </div>)}
        </div>}
        <p className="receipt-help">사진은 기존 원본 저장 경로에 보관되고, PDF는 페이지 이미지를 처리용으로 연결합니다. 파일 등록만으로 모델이 실행되지는 않습니다.</p>
      </section>

      {legacyManualOpen && <section className="receipt-card receipt-manual" aria-labelledby="receipt-manual-title">
        <div className="receipt-section-heading"><div><p className="receipt-step">기존 기능</p><h2 id="receipt-manual-title">영수증 내용 직접 입력</h2></div>
          <button type="button" className="receipt-button receipt-button--quiet" onClick={() => setLegacyManualOpen(false)}>닫기</button></div>
        {manualSha && <div className="receipt-manual__source"><img src={imageUrl(manualSha)} alt="직접 입력할 영수증 원본" /><span>{activeSource?.kind === 'pdf-page' ? '선택한 PDF 페이지 이미지' : '선택한 원본 사진'} · 확대해도 저장 원본은 바뀌지 않습니다.</span></div>}
        <form className="receipt-form-grid" onSubmit={(event) => { event.preventDefault(); void saveManual(); }}>
          <label>상호<input id="receipt-manual-merchant" name="merchant" autoComplete="organization" required value={manualMerchant} onChange={(event) => setManualMerchant(event.target.value)} /></label>
          <label>날짜<input name="date" type="date" required value={manualDate} onChange={(event) => setManualDate(event.target.value)} /></label>
          <label>통화<select name="currency" required value={manualCurrency} onChange={(event) => setManualCurrency(event.target.value)}>{currencyOptions.filter((option) => option.value).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <label>금액<input name="total" inputMode="decimal" type="number" min="1" step="any" required value={manualAmount} onChange={(event) => setManualAmount(event.target.value)} /></label>
          <label>결제수단<select name="payment" required value={manualPayment} onChange={(event) => setManualPayment(event.target.value)}>{paymentOptions.filter((option) => option.value).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <label>여행<select name="trip_id" value={manualTrip} onChange={(event) => setManualTrip(event.target.value)}><option value="">여행 미지정</option>{bootstrap.trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}</select></label>
          <div className="receipt-row-actions"><button type="submit" className="receipt-button receipt-button--primary" disabled={savingManual}>{savingManual ? '저장 중…' : '영수증 등록'}</button></div>
        </form>
      </section>}

      <section className="receipt-card receipt-models" aria-labelledby="receipt-model-title">
        <div className="receipt-section-heading"><div><p className="receipt-step">02 · 모델</p><h2 id="receipt-model-title">처리할 모델 선택</h2></div>
          <span className={`receipt-connection ${catalog?.connected ? 'is-connected' : 'is-disconnected'}`}><i aria-hidden="true" />{catalog?.connected ? `${catalog.host_label || '로컬 Paseo'} 연결` : 'Paseo 연결 확인 필요'}</span></div>
        <div className="receipt-model-toolbar">
          <label>Provider<select value={provider} onChange={(event) => { setProvider(event.target.value); void loadCatalog(event.target.value || undefined).catch(() => undefined); }}>
            <option value="">Provider 선택</option>{(catalog?.providers || []).map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.label}{item.available ? '' : ' · 사용 불가'}</option>)}
          </select></label>
          <p>{selectedJobsCount ? `${selectedJobsCount}장 선택됨` : '처리할 사진을 먼저 선택하세요.'}</p>
        </div>
        {catalogError && <div className="receipt-inline-error" role="alert">모델 목록을 가져오지 못했습니다. {catalogError} <button type="button" className="receipt-link-button" onClick={() => void loadCatalog(provider || undefined).catch(() => undefined)}>다시 조회</button></div>}
        {pendingRun && <div className="receipt-pending-run" role="status">
          <div><strong>이전 요청의 접수 결과를 확인할 수 없습니다.</strong><span>{pendingRun.label} · 사진 {pendingRun.images.length}장 · 같은 request_id 보존</span></div>
          <button type="button" className="receipt-button receipt-button--quiet" onClick={() => void loadWorkflow().then(() => setNotice('저장된 작업 목록을 확인했습니다.')).catch((error) => setPageError(errorText(error)))}>작업 목록 확인</button>
          <button type="button" className="receipt-button receipt-button--primary" disabled={Boolean(retryingJob) || uploading} onClick={() => void submitModelRun(pendingRun)}>같은 모델 요청 재시도</button>
        </div>}
        <div className="receipt-model-grid">
          {currentModels.map((model) => <article className={`receipt-model ${model.selectable ? '' : 'is-disabled'}`} key={`${model.provider}/${model.id}`}>
            <div><span className="receipt-model__provider">{model.provider}</span><h3>{model.label}</h3><code>{model.id}</code></div>
            {model.default_thinking && <p className="receipt-model__meta">기본 추론 · {model.default_thinking}</p>}
            {!model.selectable && <p className="receipt-model__reason">{model.reason || '현재 실행할 수 없습니다.'}</p>}
            <button type="button" className="receipt-button receipt-button--primary" disabled={!model.selectable || !catalog?.connected || !selectedShas.size || Boolean(pendingRun)}
              onClick={() => void runModel(model)}>{model.selectable ? '이 모델로 처리' : '선택할 수 없음'}</button>
          </article>)}
          {!currentModels.length && <p className="receipt-empty">선택한 provider에서 가져온 모델이 없습니다. 목록을 새로고침해 주세요.</p>}
        </div>
        <p className="receipt-help">모델 목록은 서버가 반환한 실제 provider·model만 표시합니다. 모델 탐색이나 화면 복귀는 실행하지 않으며, 처리 버튼을 눌렀을 때 선택한 사진이 전송됩니다.</p>
      </section>

      <div className="receipt-mobile-tabs" role="group" aria-label="영수증 작업공간 보기">
        <button type="button" aria-pressed={mobilePane === 'source'} onClick={() => setMobilePane('source')}>원본</button>
        <button type="button" aria-pressed={mobilePane === 'results'} onClick={() => setMobilePane('results')}>결과 {allCandidates.length ? `(${allCandidates.length})` : ''}</button>
      </div>

      <section className="receipt-workspace" aria-label="원본과 처리 결과">
        <section className={`receipt-card receipt-source-pane ${mobilePane === 'source' ? 'is-mobile-active' : ''}`} aria-labelledby="receipt-source-title">
          <div className="receipt-section-heading"><div><p className="receipt-step">03 · 사진별 작업</p><h2 id="receipt-source-title">원본 선택</h2></div>
            <span className="receipt-count">{sources.length}개</span></div>
          {sources.length ? <div className="receipt-source-strip" aria-label="저장된 사진">
            {sources.map((source) => <article key={source.sha} className={`receipt-source-tile ${activeSha === source.sha ? 'is-active' : ''}`}>
              <button type="button" className="receipt-source-tile__open" aria-pressed={activeSha === source.sha} onClick={() => setActiveSha(source.sha)}>
                <img src={imageUrl(source.sha)} alt="" loading="lazy" />
                <span>{source.label}</span>
              </button>
              <label className="receipt-source-select"><input type="checkbox" aria-label={`${source.label} 분석 대상으로 선택`} checked={selectedShas.has(source.sha)}
                onChange={(event) => setSelectedShas((current) => { const next = new Set(current); event.target.checked ? next.add(source.sha) : next.delete(source.sha); return next; })} /><span>분석</span></label>
            </article>)}
          </div> : <div className="receipt-empty receipt-empty--panel"><strong>저장된 사진이 없습니다.</strong><span>영수증 사진이나 PDF를 등록하면 이곳에서 원본을 선택할 수 있습니다.</span></div>}
          <div className="receipt-original">
            {activeSha ? <>
              <div className="receipt-original__topline"><span>{activeSource?.label || '영수증 사진'} · 원본 SHA 뒤 8자리 {activeSha.slice(-8)}</span>
              <button type="button" className="receipt-link-button" onClick={(event) => openZoom(event.currentTarget)}>{activeSource?.kind === 'pdf-page' ? '페이지 확대' : '원본 확대'}</button></div>
              <button type="button" className="receipt-original__image-button" style={{
                aspectRatio: sourceAspect || '4 / 3',
                width: sourceAspect ? `min(100%, calc(var(--receipt-source-max-height) * ${sourceAspect}))` : undefined,
              }} onClick={(event) => openZoom(event.currentTarget)} aria-label="선택한 영수증 원본 확대">
                <img src={imageUrl(activeSha)} alt={activeSource?.kind === 'pdf-page' ? '선택한 PDF 페이지 이미지' : '선택한 영수증 원본 사진'} onLoad={(event) => {
                  const image = event.currentTarget;
                  if (image.naturalWidth && image.naturalHeight) setSourceAspect(image.naturalWidth / image.naturalHeight);
                }} />
                {currentImageCandidates.map((candidate) => candidate.box && candidateForImage(candidate) === activeSha && candidate.box.length === 4 ? <span key={candidate.candidate_id} className="receipt-region-outline"
                  style={{ left: `${candidate.box[0] * 100}%`, top: `${candidate.box[1] * 100}%`, width: `${(candidate.box[2] - candidate.box[0]) * 100}%`, height: `${(candidate.box[3] - candidate.box[1]) * 100}%` }} aria-hidden="true" /> : null)}
              </button>
              {activeSource?.kind === 'pdf-page' && <p className="receipt-help">PDF {activeSource.pdfSha?.slice(0, 8)}의 {activeSource.page}페이지 미리보기입니다. PDF 원본 파일은 서버에서 보존됩니다.</p>}
              <div className="receipt-original__actions"><button type="button" className="receipt-button receipt-button--quiet" onClick={() => startManualFor(activeSha)}>이 사진에 직접 입력</button>
                <a className="receipt-button receipt-button--quiet" href={imageUrl(activeSha)} target="_blank" rel="noreferrer">{activeSource?.kind === 'pdf-page' ? '페이지 이미지 열기' : '원본 사진 열기'}</a>
                {activeSource?.pdfSha && <a className="receipt-button receipt-button--quiet" href={`/api/receipts/pdf/${encodeURIComponent(activeSource.pdfSha)}`} target="_blank" rel="noreferrer">PDF 원본 열기</a>}</div>
            </> : <div className="receipt-empty"><strong>사진을 선택하세요.</strong><span>저장된 원본은 확대해 확인할 수 있습니다.</span></div>}
          </div>
          <div className="receipt-job-list">
            <div className="receipt-section-heading receipt-section-heading--small"><h3>사진별 처리 상태</h3><span>{workflow.batches.length}개 작업</span></div>
            {workflow.batches.map((batch) => <div className="receipt-batch" key={batch.batch_id}>
              <div className="receipt-batch__heading"><strong>{batch.provider} · {batch.model}</strong><span>{statusText(batch.status)}</span></div>
              <ul>{batch.jobs.map((job) => <li key={job.job_id}>
                <button type="button" className="receipt-link-button" onClick={() => { setActiveSha(job.image); setMobilePane('source'); }}>{job.image.slice(0, 12)}…</button>
                <span className={`receipt-status receipt-status--${job.status.toLowerCase()}`}>{statusText(job.status)}{job.code ? ` · ${job.code}` : ''}</span>
                {['failed', 'error'].includes(job.status.toLowerCase()) && <button type="button" className="receipt-link-button" disabled={retryingJob === job.job_id} onClick={() => void retryJob(job.job_id)}>{retryingJob === job.job_id ? '재접수 중…' : '이 사진 재시도'}</button>}
              </li>)}</ul>
            </div>)}
            {!workflow.batches.length && <p className="receipt-help">아직 모델 처리 작업이 없습니다.</p>}
          </div>
        </section>

        <section className={`receipt-card receipt-results-pane ${mobilePane === 'results' ? 'is-mobile-active' : ''}`} aria-labelledby="receipt-results-title">
          <div className="receipt-section-heading"><div><p className="receipt-step">04 · 교정·반영</p><h2 id="receipt-results-title">사진 결과</h2></div>
            <span className="receipt-count">{currentImageCandidates.length}건</span></div>
          {activeSha && <p className="receipt-active-photo">선택한 사진 · {activeSha.slice(-8)}</p>}
          <div className="receipt-result-list">
            {currentImageCandidates.map((candidate) => {
              const draft = reviewDrafts[candidate.candidate_id];
              const current = draft || candidateDraft(candidate);
              return <article className={`receipt-result ${candidate.applied ? 'is-applied' : ''}`} key={candidate.candidate_id}>
                <div className="receipt-result__top">
                  <label className="receipt-select"><input type="checkbox" checked={current.selected} disabled={candidate.applied || current.saving || Boolean(current.pending) || Boolean(current.revisionConflict) || applyLocked}
                    onChange={(event) => toggleCandidateSelection(candidate, event.target.checked)} /><span>반영 선택</span></label>
                  <span className={`receipt-status ${candidate.applied ? 'receipt-status--applied' : ''}`}>{candidate.applied ? '장부 반영됨' : '미반영'}</span>
                </div>
                {draft?.editing ? draft.revisionConflict ? <div className="receipt-inline-error" role="alert">
                  <span>{draft.error || '편집을 시작한 뒤 서버 값이 바뀌었습니다.'} 현재 서버 값은 {candidate.merchant || '상호 미확인'} · {dateLabel(candidate.date)} · {candidate.amount ?? '금액 미확인'} {candidate.currency || ''}입니다.</span>
                  <button type="button" className="receipt-button receipt-button--quiet" disabled={draft.saving} onClick={() => void restartCandidateEdit(candidate.candidate_id)}>최신 값으로 다시 편집</button>
                  <button type="button" className="receipt-button receipt-button--quiet" onClick={() => discardCandidateEdit(candidate.candidate_id)}>닫기</button>
                </div> : <div className="receipt-form-grid receipt-form-grid--candidate">
                  <label>상호<input value={draft.merchant} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'merchant', event.target.value)} /></label>
                  <label>날짜<input type="date" value={draft.date} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'date', event.target.value)} /></label>
                  <label>금액<input type="number" inputMode="decimal" value={draft.amount} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'amount', event.target.value)} /></label>
                  <label>통화<select value={draft.currency} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'currency', event.target.value)}>{currencyOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                  <label>결제수단<select value={draft.payment} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'payment', event.target.value)}>{paymentOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                  <label>여행<select value={draft.trip_id} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'trip_id', event.target.value)}><option value="">여행 미지정</option>{bootstrap.trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}</select></label>
                  <label>항목<input value={draft.category} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'category', event.target.value)} /></label>
                  {draft.payment === 'private_card' && <label className="receipt-checkbox-field"><input type="checkbox" checked={draft.company_expense ?? false} disabled={draft.saving || Boolean(draft.pending)} onChange={(event) => setCandidateDraftValue(candidate, 'company_expense', event.target.checked)} /> 회사 비용으로 인정</label>}
                  {draft.error && <div className="receipt-inline-error" role="alert">저장하지 못했습니다: {draft.error}</div>}
                  <div className="receipt-row-actions">
                    <button type="button" className="receipt-button receipt-button--primary" disabled={draft.saving || (!draft.dirty && !draft.error)}
                      onClick={() => void saveCandidate(candidate, Boolean(draft.error && draft.pending))}>{draft.saving ? '저장 중…' : draft.error ? '같은 교정 재시도' : '교정 저장'}</button>
                    <button type="button" className="receipt-button receipt-button--quiet" disabled={draft.saving} onClick={() => discardCandidateEdit(candidate.candidate_id)}>취소</button>
                  </div>
                </div> : <>
                  {draft?.error && <div className="receipt-inline-error" role="alert"><span>선택 상태를 저장하지 못했습니다: {draft.error}</span>
                    {draft.revisionConflict
                      ? <><button type="button" className="receipt-button receipt-button--quiet" disabled={draft.saving} onClick={() => void restartCandidateEdit(candidate.candidate_id)}>최신 값으로 다시 편집</button>
                        <button type="button" className="receipt-button receipt-button--quiet" onClick={() => discardCandidateEdit(candidate.candidate_id)}>닫기</button></>
                      : <button type="button" className="receipt-button receipt-button--quiet" disabled={draft.saving} onClick={() => void saveCandidate(candidate, Boolean(draft.pending))}>{draft.saving ? '저장 중…' : '같은 선택 저장 재시도'}</button>}
                  </div>}
                  <div className="receipt-result__identity"><strong>{candidate.merchant || '상호 확인 필요'}</strong><span>{dateLabel(candidate.date)}</span></div>
                  <p className="receipt-result__amount">{candidate.amount ?? '금액 미확인'} {candidate.currency || '통화 확인'} <span>· {paymentLabel(candidate.payment)}</span></p>
                  <dl className="receipt-result__details"><div><dt>여행</dt><dd>{bootstrap.trips.find((trip) => trip.id === candidate.trip_id)?.title || (candidate.trip_id ? '여행 확인 필요' : '미지정')}</dd></div><div><dt>항목</dt><dd>{candidate.category || '미지정'}</dd></div>
                    {candidate.company_expense != null && <div><dt>회사 비용</dt><dd>{candidate.company_expense ? '인정' : '미인정'}</dd></div>}
                    {candidate.ledger_id && <div><dt>장부 연결</dt><dd>{candidate.ledger_id}</dd></div>}</dl>
                  <div className="receipt-row-actions"><button type="button" className="receipt-button receipt-button--quiet" disabled={candidate.applied || applyLocked || Boolean(draft?.pending)} onClick={() => beginCandidateEdit(candidate)}>수정</button>
                    <button type="button" className="receipt-link-button" onClick={() => { setActiveSha(candidate.image); setMobilePane('source'); }}>원본 보기</button></div>
                </>}
              </article>;
            })}
            {!currentImageCandidates.length && <div className="receipt-empty receipt-empty--panel"><strong>{activeSha ? '이 사진의 결과가 아직 없습니다.' : '표시할 결과가 없습니다.'}</strong><span>작업 중이면 이 화면에서 사진별 처리 상태를 확인할 수 있습니다.</span></div>}
          </div>
          <div className="receipt-apply-bar">
            {pendingApply ? <><div><strong>요청 결과를 확인해야 합니다.</strong><span>{pendingApply.selections.length}건 · 같은 request_id 유지</span></div>
              <button type="button" className="receipt-button receipt-button--primary" onClick={() => void applySelected(true)} disabled={applying}>{applying ? '반영 상태 확인 중…' : '같은 반영 요청 재시도'}</button></>
              : <><div><strong>{selectedCandidates.length}건 선택됨</strong><span>선택한 후보를 원자적으로 반영합니다.</span></div>
                <button type="button" className="receipt-button receipt-button--primary" onClick={() => void applySelected()} disabled={!canApply || applying}>{applying ? '반영 중…' : `선택한 ${selectedCandidates.length}건 반영`}</button></>}
          </div>
          {selectedCandidates.some((candidate) => candidate.payment === 'corporate_card') && <p className="receipt-help">법인카드 연결은 기존 지출에 증빙을 연결하며 새 지출을 만들지 않습니다. 최종 판단과 보호 검사는 서버가 수행합니다.</p>}
        </section>
      </section>

      <section className="receipt-card receipt-legacy" aria-labelledby="receipt-legacy-title">
        <div className="receipt-section-heading"><div><p className="receipt-step">기존 영수증 데이터</p><h2 id="receipt-legacy-title">직접 입력·기존 후보</h2></div>
          <span className="receipt-count">{legacy.candidates.length}건</span></div>
        <p className="receipt-help">기존 수기 입력 후보를 새 작업으로 바꾸거나 삭제하지 않고 이어서 수정할 수 있습니다.</p>
        {legacy.candidates.length > 0 ? <div className="receipt-legacy-list">
          {legacy.candidates.map((candidate) => {
            const draft = legacyDrafts[candidate.identity] || {};
            return <article className="receipt-legacy-row" key={candidate.identity}>
              <div className="receipt-legacy-row__source">{candidate.image_sha ? <img src={imageUrl(candidate.image_sha)} alt="영수증 원본 사진" loading="lazy" /> : <span className="receipt-manual-tag">수기 입력</span>}</div>
              <div className="receipt-legacy-row__fields">
                <label>상호<input value={String(draft.merchant ?? candidate.merchant ?? '')} onChange={(event) => legacyEdit(candidate, 'merchant', event.target.value)} /></label>
                <label>날짜<input type="date" value={String(draft.date ?? candidate.date ?? '')} onChange={(event) => legacyEdit(candidate, 'date', event.target.value)} /></label>
                <label>금액 ({candidate.currency || 'JPY'})<input type="number" value={String(draft.total_original ?? draft.total_jpy ?? (candidate.currency === 'KRW' ? candidate.total_original : candidate.total_jpy) ?? '')}
                  onChange={(event) => legacyEdit(candidate, candidate.currency === 'KRW' ? 'total_original' : 'total_jpy', Number(event.target.value))} /></label>
                <label>결제수단<select value={String(draft.payment ?? candidate.payment ?? '')} onChange={(event) => legacyEdit(candidate, 'payment', event.target.value)}>{paymentOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                <label>여행<select value={String(draft.trip_id ?? candidate.trip_id ?? '')} onChange={(event) => legacyEdit(candidate, 'trip_id', event.target.value)}><option value="">여행 미지정</option>{bootstrap.trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}</select></label>
                <label>비용 분류<input value={String(draft.category ?? candidate.category ?? '')} onChange={(event) => legacyEdit(candidate, 'category', event.target.value)} /></label>
              </div>
              <div className="receipt-legacy-row__actions"><span>{candidate.hold || (candidate.amount_krw == null ? '추가 확인 필요' : `${candidate.amount_krw.toLocaleString()}원`)}</span>
                <button type="button" className="receipt-button receipt-button--quiet" disabled={savingLegacy === candidate.identity || !Object.keys(draft).length} onClick={() => void saveLegacyCandidate(candidate)}>{savingLegacy === candidate.identity ? '저장 중…' : '기존 후보 저장'}</button>
                {candidate.image_sha && <a className="receipt-link-button" href={imageUrl(candidate.image_sha)} target="_blank" rel="noreferrer">원본 보기</a>}</div>
            </article>;
          })}
        </div> : <div className="receipt-empty"><span>기존 수기 후보가 없습니다. 직접 입력을 시작할 수 있습니다.</span><button type="button" className="receipt-link-button" onClick={() => startManualFor(activeSha)}>직접 입력</button></div>}
      </section>

      {zoomOpen && activeSha && <dialog ref={zoomDialog} className="receipt-zoom" aria-labelledby="receipt-zoom-title" aria-describedby="receipt-zoom-description"
        onClose={onZoomClose} onClick={(event) => { if (event.target === event.currentTarget) closeZoom(); }}
        onKeyDown={(event) => {
          if (event.key === '+' || event.key === '=') { event.preventDefault(); setZoom((value) => Math.min(3, value + 0.25)); }
          else if (event.key === '-') { event.preventDefault(); setZoom((value) => Math.max(1, value - 0.25)); }
        }}>
        <div className="receipt-zoom__toolbar"><h2 id="receipt-zoom-title">{activeSource?.kind === 'pdf-page' ? 'PDF 페이지 확대' : '원본 사진 확대'} · {activeSource?.label || '사진'} · {activeSha.slice(-8)}</h2>
          <div><button type="button" className="receipt-button receipt-button--quiet" onClick={() => setZoom((value) => Math.max(1, value - 0.25))} aria-label="축소">−</button>
            <span>{Math.round(zoom * 100)}%</span><button type="button" className="receipt-button receipt-button--quiet" onClick={() => setZoom((value) => Math.min(3, value + 0.25))} aria-label="확대">+</button>
            <button type="button" data-zoom-close className="receipt-button receipt-button--primary" onClick={closeZoom}>닫기</button></div></div>
        <div className="receipt-zoom__viewport"><img src={imageUrl(activeSha)} alt={activeSource?.kind === 'pdf-page' ? '확대된 PDF 페이지 이미지' : '확대된 영수증 원본 사진'} style={{ transform: `scale(${zoom})` }} /></div>
        <p id="receipt-zoom-description">키보드 + / − 또는 확대·축소 버튼으로 크기를 조절하고 Escape로 닫습니다. PDF는 보존된 페이지 이미지만 표시하며 PDF 파일 자체를 읽어 표시하지 않습니다.</p>
      </dialog>}
    </main>
  );
}
