#!/usr/bin/env node
/**
 * Pure helpers plus an explicit ego-browser entry (see entry-runner.mjs).
 *
 * Importing this module has no side effects: it never creates a TaskSpace and never
 * starts a run. `runEgoJob` is exported so callers (tests, another operator script)
 * can inject a TaskSpace page and a fetch implementation bounded to a provider origin.
 * The CLI path serves `--plan`/`--help` under plain `node` only.
 */
import { realpathSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PROVIDER_LIST, STATUS, TOOL_NAME, TOOL_VERSION } from './ota_collection/constants.mjs';
import { adaptPageFetch } from './ota_collection/http.mjs';
import { runCollection } from './ota_collection/collector.mjs';
import { resolveArchiveRoot, safeChildPath, utcStamp } from './ota_collection/storage.mjs';

export const EGO_RUN_COMMAND = "ego-browser nodejs -e \"const { mainEgo } = await import('file:///C:/absolute/path/tools/ota_collection/entry-runner.mjs'); await mainEgo({ taskSpace: globalThis.taskSpace })\"";

export function parseProviders(value = null) {
  if (value === null || value === undefined || value === '') return [...PROVIDER_LIST];
  const parts = String(value)
    .split(',')
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);
  const unknown = parts.filter((part) => !PROVIDER_LIST.includes(part));
  if (parts.length === 0 || unknown.length > 0) {
    throw new Error(`unknown provider(s): ${unknown.join(', ') || '(empty)'}; expected ${PROVIDER_LIST.join(', ')}`);
  }
  return parts;
}

export function buildPlanText(providers = PROVIDER_LIST) {
  const lines = [
    `${TOOL_NAME} v${TOOL_VERSION} - read-only OTA portal collection (Agoda / Trip.com / Booking.com)`,
    `실행(명시적 진입): ${EGO_RUN_COMMAND}`,
    'collect_ota_portals.mjs는 순수 함수/계획 CLI다. import만으로는 브라우저나 TaskSpace가 기동하지 않는다.',
    '이 진입점은 스킬 규칙대로 목표 단위 TaskSpace 하나만 만들고 이후 회차에 재사용한다(사용자 소유 이름 충돌 시 실패를 보고하고 새로 만들지 않는다).',
    '',
    '준비',
    '- 포털 로그인/재인증은 사용자 작업이다. 스크립트는 자격증명, 쿠키, OTP, 이메일 인증번호, 화면 관측 토큰을 다루거나 자동화하지 않는다.',
    '- 로그인 만료/인증 신호는 LOGIN_REQUIRED로 멈추고 상태만 남긴다. 인증을 우회하지 않는다.',
    '- 각 공급자의 관측 entry/URL 템플릿으로 페이지를 이동한 뒤 조회한다. 여기에 기록되지 않은 URL은 추측하지 않는다.',
    '',
    '공급자 절차(모두 읽기 전용 조회)',
    '- agoda: 목록 POST /api/ko-kr/mmbc/v2/GetBookingsList (bookingPhase 기본 Completed, Upcoming/Completed/Cancelled 선택, pageIndex 1부터, pageSize 40, includeArchive true, pagination.totalPages까지; 목록 요청 최대 5). 상세 POST /api/ko-kr/mmbc/eb/details 는 화면에서 관측한 token이 필요하다. 미지정이면 CAPTURE_REQUIRED, 추측하지 않는다. 상세 시도 최대 3(지수 백오프).',
    '- trip: 목록 POST https://online.trip.com/restapi/soa2/26974/getAllOrders.json (OrderStatusClassify All, Count 20, 날짜 조건 비움; 응답 Offset으로 페이지네이션, 토큰 누락 시 PARTIAL). 상세 POST https://kr.trip.com/restapi/soa2/27453/GetOrderDetailOnline (orderId + FrontHead.sign; sign은 목록 OrderActions[].ActionURLH5에서 읽음, 없으면 CAPTURE_REQUIRED).',
    '- booking: 목록 POST https://secure.booking.com/dml/graphql?lang=ko operationName UserTrips. query 텍스트는 화면 관측이 필요하다. 미지정이면 CAPTURE_REQUIRED. 관측 절차상 두 번째 커서 페이지 요청은 오류가 나므로 1페이지(50건)까지만 수집하며 이후를 성공으로 표시하지 않는다. 여행 상세(tab=bookings 화면 텍스트, 일부 confirm 링크)는 안정 템플릿이 없어 미지원으로 상태화한다.',
    '',
    '공통 규칙',
    '- 동시 요청 최대 6, 목록 요청 공급자당 최대 5, 상세 시도 최대 3(지수 백오프), 실패 30건 초과 시 중단.',
    '- 원자료(응답)는 새 보호 출력 디렉터리에만 저장한다: 기본 .local-archive/ota-portal/<시각>, --archive 또는 OTA_ARCHIVE_DIR를 쓰면 그 아래 run-<무작위> 신설 디렉터리. 기존 파일 덮어쓰기는 거부한다(새 파일 생성 전용).',
    '- stdout/요약/manifest에는 건수·상태·원인 코드만. 자격증명·계정 식별자·요청 헤더/본문·관측 토큰/쿼리는 기록하지 않는다.',
    '- 미지원/미관측 경로는 CAPTURE_REQUIRED/AUTH_UNKNOWN/PARTIAL로 상태화하고 성공으로 표시하지 않는다. 브라우저 페이지를 직접 붙이기보다 주입된 페이지에서 공급자 origin 정합성을 코드로 검사한다.',
    '',
    '경계',
    '- 조회만 한다: 예약 변경/취소, 결제, 메시지 전송, 쿠폰 사용 금지.',
    '- 운영 DB apply, 예약 작업 등록, 배포를 하지 않는다. 수집과 수입은 분리되어 있으며 저장 형식은 기존 importer와 호환된다: Agoda tools/import_agoda_api_details.py, Trip tools/import_trip_api_details.py.',
    `- ${STATUS.LOGIN_REQUIRED} / ${STATUS.CAPTURE_REQUIRED} / ${STATUS.AUTH_UNKNOWN} / ${STATUS.INTERRUPTED} 는 사용자 개입 또는 재개점이 필요하다.`,
    '',
    '계획 조회: node tools/collect_ota_portals.mjs --plan [--provider agoda,trip,booking]',
    '합성 fixture 테스트: node --test "tests/ota_collection/*.test.mjs"',
  ];
  return lines.join('\n');
}

function printUsage() {
  console.log('usage: node tools/collect_ota_portals.mjs --plan [--provider agoda,trip,booking]');
  console.log('       (브라우저 실행은 ego-browser nodejs에서 명시적 진입점으로: ' + EGO_RUN_COMMAND + ')');
}

function isDirectInvocation() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return realpathSync(path.resolve(entry)) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

async function mainDirect(argv) {
  if (argv.includes('--help') || argv.includes('-h')) {
    printUsage();
    return 0;
  }
  if (!argv.includes('--plan')) {
    printUsage();
    return 2;
  }
  const index = argv.indexOf('--provider');
  if (index === -1) {
    console.log(buildPlanText());
    return 0;
  }
  const raw = argv[index + 1];
  if (raw === undefined || raw.startsWith('-')) {
    console.error('--provider expects a comma-separated list, for example --provider agoda,trip');
    return 2;
  }
  try {
    console.log(buildPlanText(parseProviders(raw)));
    return 0;
  } catch (error) {
    console.error(`error: ${error.message}`);
    printUsage();
    return 2;
  }
}

async function firstPageOf(handle) {
  if (!handle) return null;
  if (typeof handle.pages === 'function') {
    try {
      const pages = await handle.pages();
      if (Array.isArray(pages) && pages.length > 0) {
        const preferred = pages.find((candidate) => candidate?.label === 'p1') ?? pages[0];
        return preferred;
      }
    } catch (error) {
      throw new Error(`cannot list browser pages on the injected TaskSpace: ${error?.message ?? error}`, { cause: error });
    }
  }
  if (typeof handle.newPage === 'function') {
    try {
      return await handle.newPage();
    } catch (error) {
      throw new Error(`cannot open a browser page on the injected TaskSpace: ${error?.message ?? error}`, { cause: error });
    }
  }
  if (typeof handle.page === 'function') {
    try {
      const candidate = handle.page('p1');
      if (candidate) return candidate;
    } catch {
      // fall through to the explicit error below
    }
  }
  return null;
}

export async function runEgoJob({
  providers = PROVIDER_LIST,
  archiveDir = null,
  opts = {},
  clock,
  fetchImpl = null,
  task = null,
  taskSpace = null,
  taskSpaceId = null,
  page = null,
  runId = null,
} = {}) {
  const selected = parseProviders(Array.isArray(providers) ? providers.join(',') : providers);
  if (!runId) runId = `run-${utcStamp()}-${Math.random().toString(16).slice(2, 8)}`;
  const base = resolveArchiveRoot({ archiveDir });
  const root = safeChildPath(base.root, runId);
  const goalName = `ota portal collection${selected.length === PROVIDER_LIST.length && selected.every((name, index) => name === PROVIDER_LIST[index]) ? '' : ` ${selected.join(',')}`}`;

  let handle = task;
  if (task && taskSpaceId !== null && taskSpaceId !== undefined) {
    throw new Error('pass either an injected task or taskSpaceId, not both');
  }
  if (!handle && taskSpaceId !== null && taskSpaceId !== undefined && typeof taskSpace !== 'function') {
    throw new Error('taskSpace factory is required to resume taskSpaceId');
  }
  let access = fetchImpl;
  if (!handle && typeof taskSpace === 'function') {
    const requested = taskSpaceId ?? goalName;
    try {
      handle = await taskSpace(requested);
    } catch (error) {
      throw new Error(`${error?.code ?? 'TASK_SPACE_ERROR'}: cannot resume or create the collection TaskSpace '${requested}'; if it is user-owned ask the user instead of creating another space`, { cause: error });
    }
  }

  let targetPage = page;
  if (!targetPage && handle) {
    targetPage = await firstPageOf(handle);
  }
  if (!access && targetPage && typeof targetPage.fetch === 'function') {
    access = adaptPageFetch(targetPage.fetch.bind(targetPage));
  }
  if (typeof access !== 'function') {
    throw new Error('no browser page available; run entry-runner.mjs under ego-browser nodejs or pass fetchImpl');
  }
  const outcome = await runCollection({
    providers: selected,
    archiveRoot: root,
    runId,
    opts,
    clock,
    fetchImpl: access,
    goto: targetPage && typeof targetPage.goto === 'function' ? (url) => targetPage.goto(url) : null,
  });
  for (const row of outcome.rows) {
    const c = row.counts;
    console.log(`${row.provider}: ${row.status} listed=${c.listed} details_saved=${c.details_saved} details_invalid=${c.details_invalid} details_capture=${c.details_capture} details_skipped=${c.details_skipped} items_invalid=${c.items_invalid}`);
  }
  console.log(`${TOOL_NAME} v${TOOL_VERSION} run=${runId} status=${outcome.manifest.status} archive=${root}`);
  const needsUser = [STATUS.LOGIN_REQUIRED, STATUS.AUTH_UNKNOWN, STATUS.CAPTURE_REQUIRED, STATUS.INTERRUPTED].includes(outcome.manifest.status);
  if (needsUser) {
    console.log(`needs user action or resume point - see ${path.join(root, 'manifest.json')}`);
    if (handle && typeof handle.handOff === 'function') await handle.handOff();
  } else if (handle && typeof handle.finish === 'function') {
    await handle.finish({ keep: [] });
  }
  return outcome;
}

// CLI convenience only: importing this module (including inside ego-browser)
// never starts a TaskSpace or a run.
if (typeof process !== 'undefined' && process.argv && isDirectInvocation()) {
  process.exitCode = await mainDirect(process.argv.slice(2));
}
