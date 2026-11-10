export const TOOL_NAME = 'collect_ota_portals';
export const TOOL_VERSION = '1.0.0';
export const DEFAULT_ARCHIVE_DIRNAME = 'ota-portal';

export const LIST_PAGE_LIMIT = 5;
export const MAX_ATTEMPTS = 3;
export const RETRY_BASE_MS = 250;
export const RETRY_CAP_MS = 8000;
export const DETAIL_CONCURRENCY = 6;
export const MAX_FAILURES = 30;

export const PROVIDER_LIST = Object.freeze(['agoda', 'trip', 'booking']);
export const AGODA_PHASE_DEFAULT = 'Completed';
export const TRIP_COUNT = 20;
export const AGODA_PAGE_SIZE = 40;

export const STATUS = Object.freeze({
  OK: 'ok',
  INVALID: 'invalid',
  PARTIAL: 'partial',
  CAPTURE_REQUIRED: 'CAPTURE_REQUIRED',
  AUTH_UNKNOWN: 'AUTH_UNKNOWN',
  LOGIN_REQUIRED: 'LOGIN_REQUIRED',
  INTERRUPTED: 'INTERRUPTED',
  FAILED: 'FAILED',
  SKIPPED: 'skipped',
});

export const SEVERITY = Object.freeze({
  [STATUS.LOGIN_REQUIRED]: 5,
  [STATUS.INTERRUPTED]: 4,
  [STATUS.CAPTURE_REQUIRED]: 3,
  [STATUS.AUTH_UNKNOWN]: 3,
  [STATUS.PARTIAL]: 2,
  [STATUS.FAILED]: 1,
  [STATUS.INVALID]: 1,
  [STATUS.SKIPPED]: 0,
  [STATUS.OK]: 0,
});

export const STOP = Object.freeze({
  LOGIN: 'LOGIN_REQUIRED',
  CAPTURE: 'CAPTURE_REQUIRED',
  AUTH_UNKNOWN: 'AUTH_UNKNOWN',
  SHAPE: 'CAPTURE_REQUIRED',
  IDENTITY: 'invalid',
  RATE: 'FAILED',
  NETWORK: 'FAILED',
  HTTP: 'FAILED',
  FAILED: 'FAILED',
  ABORT: 'INTERRUPTED',
});

export const SENSITIVE_KEY = /(token|authorization|cookie|password|secret|api[-_]?key|sessionid|credential|sign)/i;

export function severityOf(status) {
  return SEVERITY[status] ?? 0;
}

export function maxStatus(statuses) {
  let worst = STATUS.OK;
  for (const status of statuses) {
    if (severityOf(status) > severityOf(worst)) worst = status;
  }
  return worst;
}
