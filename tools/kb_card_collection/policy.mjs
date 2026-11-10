// 국민 기업카드 수집 스크립트의 순수 정책 경계: 소스·조회축·조회기간 계산.
// 브라우저/파일/스토어 같은 부작용 없음. 날짜는 전부 호출자 입력 + 주입된 화면 허용일에서만 나온다.
export const SOURCES = Object.freeze({
  DOMESTIC: "국민 기업카드 국내 매입",
  OVERSEAS: "국민 기업카드 해외 매입",
});

export const SOURCE_URLS = Object.freeze({
  [SOURCES.DOMESTIC]: "https://biz.kbcard.com/CXERCMLSD0002.cms",
  [SOURCES.OVERSEAS]: "https://biz.kbcard.com/CXERCMLS0008.cms",
});

export const SOURCE_FILES_PREFIX = Object.freeze({
  [SOURCES.DOMESTIC]: "kb-domestic-acquired",
  [SOURCES.OVERSEAS]: "kb-overseas-acquired",
});

export const POSTING_AXIS = "매입일";

export const MAX_LOOKBACK_DAYS = 1095;

export class PolicyError extends Error {
  constructor(message) {
    super(message);
    this.name = "PolicyError";
  }
}

function dayNumber(y, m, d) {
  return Math.floor(Date.UTC(y, m - 1, d) / 86400000);
}

function parseIsoDate(value, label) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new PolicyError(`${label} must be YYYY-MM-DD`);
  }
  const [y, m, d] = value.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) {
    throw new PolicyError(`${label} is not a calendar date: ${value}`);
  }
  return { y, m, d, epochDay: dayNumber(y, m, d) };
}

function toIsoDate(p) {
  return `${String(p.y).padStart(4, "0")}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
}

function addDays(p, n) {
  const dt = new Date(Date.UTC(p.y, p.m - 1, p.d + n));
  const y = dt.getUTCFullYear();
  const m = dt.getUTCMonth() + 1;
  const d = dt.getUTCDate();
  return { y, m, d, epochDay: dayNumber(y, m, d) };
}

function cmp(a, b) {
  return a.epochDay - b.epochDay;
}

// 시작일 = 호출자가 넘긴 마지막 국민 이용일 당일. 하루 차감/추가 없음(메뉴얼 계약).
function resolveStartDate({ lastUseDate }) {
  if (typeof lastUseDate !== "string" || lastUseDate.trim() === "") {
    throw new PolicyError("lastUseDate is required (start day = caller-provided last use day)");
  }
  return parseIsoDate(lastUseDate.trim(), "lastUseDate");
}

function resolveCeiling({ allowedCeiling }) {
  if (allowedCeiling === null || allowedCeiling === undefined) {
    return { status: "ENV_PROBE_UNVERIFIED" };
  }
  if (typeof allowedCeiling !== "object") {
    throw new PolicyError("allowedCeiling must be { floor, ceiling } or null");
  }
  const floor = allowedCeiling.floor === undefined || allowedCeiling.floor === null
    ? null : parseIsoDate(allowedCeiling.floor, "screen.floor");
  const ceiling = allowedCeiling.ceiling === undefined || allowedCeiling.ceiling === null
    ? null : parseIsoDate(allowedCeiling.ceiling, "screen.ceiling");
  if (!floor || !ceiling) {
    throw new PolicyError("screen allowed-dates incomplete: need both floor and ceiling");
  }
  if (cmp(floor, ceiling) > 0) {
    throw new PolicyError("screen floor is after screen ceiling");
  }
  return { status: "OK", floor, ceiling };
}

// 종료일 = 화면 실제 허용일(상한)과 실행일 중 이른 날짜. 화면 허용일을 못 읽으면 실행일로
// 대신하지 않고 ENV_PROBE_UNVERIFIED로 멈춘다.
export function buildPeriod({ lastUseDate, executionDate, allowedCeiling, maxLookbackDays = MAX_LOOKBACK_DAYS } = {}) {
  const start = resolveStartDate({ lastUseDate });
  const exec = parseIsoDate(executionDate, "executionDate");
  const resolved = resolveCeiling({ allowedCeiling });
  if (resolved.status !== "OK") {
    return {
      status: "ENV_PROBE_UNVERIFIED",
      startDate: null,
      endDate: null,
      executionDate: toIsoDate(exec),
      reason: "screen allowed-dates not read; refusing to substitute executionDate",
    };
  }
  const { ceiling } = resolved;
  const end = cmp(ceiling, exec) <= 0 ? ceiling : exec;
  if (cmp(start, end) > 0) {
    return {
      status: "NO_WINDOW",
      startDate: toIsoDate(start),
      endDate: toIsoDate(end),
      executionDate: toIsoDate(exec),
      reason: "resolved window is empty (start after end)",
    };
  }
  const clampedEnd = addDays(start, maxLookbackDays);
  const clampedByLookback = cmp(end, clampedEnd) > 0;
  return {
    status: "OK",
    startDate: toIsoDate(start),
    endDate: toIsoDate(clampedByLookback ? clampedEnd : end),
    executionDate: toIsoDate(exec),
    screenCeiling: toIsoDate(ceiling),
    maxLookbackDays,
    clampedByLookback,
    postingAxis: POSTING_AXIS,
  };
}

export function sourcesFromFlag(flag) {
  if (flag === undefined || flag === null || flag === "both") return [SOURCES.DOMESTIC, SOURCES.OVERSEAS];
  if (flag === "domestic") return [SOURCES.DOMESTIC];
  if (flag === "overseas") return [SOURCES.OVERSEAS];
  return null;
}
