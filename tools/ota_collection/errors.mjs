import { STOP } from './constants.mjs';

export class OtaError extends Error {
  constructor(code, { cls = 'unknown', status = null, diagnostic = null, resume = null, provider = null, cause = null } = {}) {
    super(code);
    this.name = 'OtaError';
    this.code = code;
    this.cls = cls;
    this.status = status;
    this.diagnostic = diagnostic;
    this.resume = resume;
    this.provider = provider;
    if (cause !== null) this.cause = cause;
  }
}

export function isOtaError(value) {
  return value instanceof OtaError;
}

export function toOtaError(value, fallbackCode = 'UNKNOWN_ERROR') {
  if (isOtaError(value)) return value;
  const detail = value && typeof value === 'object' && 'message' in value ? String(value.message) : String(value);
  return new OtaError(fallbackCode, { cls: 'unknown', diagnostic: detail, cause: value });
}

export function statusForError(error) {
  if (!isOtaError(error)) return STOP.NETWORK;
  if (error.code === 'LOGIN_REQUIRED') return STOP.LOGIN;
  switch (error.cls) {
    case 'auth':
      return STOP.LOGIN;
    case 'shape':
      return STOP.SHAPE;
    case 'identity':
      return STOP.IDENTITY;
    case 'abort':
      return STOP.ABORT;
    case 'rate':
    case 'network':
    case 'http':
      return STOP.FAILED;
    default:
      return STOP.NETWORK;
  }
}

export function statusForUnexpected(error) {
  if (error && error.name === 'AbortError') return STOP.ABORT;
  return STOP.FAILED;
}
