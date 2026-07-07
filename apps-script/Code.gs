/**
 * 숲길여행 비용처리 자동화 — Apps Script 엔진 (단일 계정 kkokkohero6 실행)
 *
 * 구조: 진행 장부는 여행별 탭(출발일_지역, 예: 0630_오제)으로 구성.
 *  - 각 카드건의 '실사용일'이 속한 여행 탭을 찾아 그 탭의 비교본 '{탭}_C'(오른쪽)에 기록.
 *  - 어떤 여행 기간에도 안 걸리는 국내건 = 기타비용 → '기타비용_C' 탭.
 * 진입점: onOpen() 메뉴 → runReconciliation() (멱등: RAW 흰색 행만 처리).
 */

const CONFIG = {
  RAW_SOURCES: [
    { id: '1nYxV9UM9rMRjEhnhdc8evE2xb3z6RxgWd5f5ci6PPdE', sheetName: null },
    { id: '11jjbN882fdQDcIexuzX-l0yBw02VgIna1jhnJNMkN_o', sheetName: null },
    { id: '1SiOftobiUJSxSdvBEKL9AmxgQkjzkzDjs2O_8SBoyh4', sheetName: null },
  ],
  LEARN_LEDGER:  { id: '1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8', sheetName: null },
  TARGET_LEDGER_ID: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', // 여행별 탭이 있는 진행 장부
  STAGING: { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: '메일수집' },

  HEADER_ROWS: 1,               // RAW 시트 헤더 행 수(없으면 0)
  TRIP_WINDOW_DAYS: 7,          // 출발일부터 여행 기간(3~5일 + 버퍼)
  ETC_TAB: '기타비용',          // 비여행 국내건 버킷 → '기타비용_C'
  RULES_TAB: '분류규칙',        // 영구 학습 규칙 (가맹점→계정과목)
  REVIEW_TAB: '학습대기',       // HOLD된 distinct 패턴 → 사람이 1회 판단

  // 비교탭 열(_C). 앞 6개는 수기 장부와 나란히 비교되도록 유사 배치.
  LEDGER_HEADER: ['거래일자', '거래처', '적요', '결제수단', '금액', '예약번호',
                  '계정과목', '결제일', '국내/해외', '통화', '현지금액', '상태', '출처'],

  COLOR: { DONE: '#d9ead3', CANCEL: '#f4cccc', NONE: '#ffffff' },

  // 카드 주인별 분류 성향(prior). key = 카드 뒷4자리.
  // 강한 신호(날짜·키워드·메일매칭)가 모두 빠졌을 때만 적용되는 '기본값'이다 — 확정 분류를 덮지 않는다.
  CARD_PROFILES: {
    // 본인(김주형): 기타비용 위주, 큰 금액은 항공료에 국한 → 미상 대액은 여비교통비로.
    '3820': { owner: '김주형', kind: 'etc', bigAccount: '여비교통비', bigThreshold: 300000 },
    // (추후) 가이드별로 카드가 하나씩 생기면 뒷4자리로 등록. 성향은 travel:
    // '1234': { owner: '가이드A', kind: 'travel', travelAccount: '숙박비' },
  },
  // 위 표에 없는 카드의 기본 성향. 현재는 3820 외 전부 대표가이드(여행성)이므로 travel.
  DEFAULT_CARD_PROFILE: { owner: '대표가이드', kind: 'travel', travelAccount: '숙박비' },
};

const KW = {
  TRANSPORT: ['TOYOTA', 'RENT', 'ENEOS', 'HERTZ', 'TAXI', 'PARKING', 'SHELL', 'ESSO',
              'TOLL', 'EXPRESSWAY', 'JR', 'RAIL', 'TATEYAMA', 'KUROBE', 'MINITZ',
              '렌트', '렌터카', '주유'],
  AIR:       ['대한항공', 'KOREAN AIR', '아시아나', 'ASIANA', '제주항공', 'JEJU AIR',
              '진에어', 'JIN AIR', '마이트립', 'MYTRIP', 'NIPPON TRAVEL', '항공'],
  LODGING:   ['HOTEL', 'INN', 'ROUTE-INN', 'TOYOKO', 'RESORT', 'RYOKAN', 'HOSTEL', 'ONSE',
              'ホテル', '호텔', '료칸', '민박', '亀の井', '칸'],
  OTA:       ['AGODA', 'BOOKING', 'TRIP.COM', '트립닷컴', '부킹', '아고다', '마이트립'],
  FOOD_AREA: ['SERVICE AREA', 'MICHINOEKI', 'SEVENELEVEN', 'APITA', 'MARKET', '휴게'],
  ADMISSION: ['NATADERA', 'PARK', '입장', 'MUSEUM', 'ZOO'],
  PG:        ['KCP', '결제대행', '전자상거래', 'PG', 'INICIS', '이니시스', 'NICE', '나이스',
              '네이버페이', '카카오페이', 'NAVERPAY', 'KAKAOPAY'],
};

// 여행 세부 계정 (여행건)
const BIZCAT_TRAVEL = {
  '커피/음료전문점': '식비', '휴게음식점': '식비', '일반음식점': '식비',
  '한식': '식비', '중식': '식비', '일식': '식비', '양식': '식비',
  '슈퍼마켓': '식비', '편의점': '식비', '주유소': '교통비', '용역서비스업': '교통비',
};
// 기타비용(비여행 국내) 표준(IFRS) 계정
const BIZCAT_ETC = {
  '커피/음료전문점': '회의비', '휴게음식점': '복리후생비', '일반음식점': '복리후생비',
  '한식': '복리후생비', '중식': '복리후생비', '일식': '복리후생비', '양식': '복리후생비',
  '슈퍼마켓': '소모품비', '편의점': '소모품비', '용역서비스업': '지급수수료',
};

const OVERSEAS_FOOD_THRESHOLD = 100000;

// ─────────────────────────────────────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi().createMenu('비용처리')
    .addItem('정산 실행 (미분류만)', 'runReconciliation')
    .addSeparator()
    .addItem('메일 미리보기 (변경 없음/로그)', 'dryRunIngest')
    .addItem('메일 수집 (메일수집 탭 기록)', 'ingestPaymentEmails')
    .addSeparator()
    .addItem('학습대기 → 규칙 반영', 'promoteReviewToRules')
    .addItem('학습맵 다시 만들기', 'rebuildKnowledgeBase')
    .addToUi();
}

// ─────────────────────────────────────────────────────────────
// 메인 — 멱등: 흰색(미분류) 행만 처리, 여행 탭별 _C 로 라우팅
// ─────────────────────────────────────────────────────────────
function runReconciliation() {
  const ledgerSS = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const kb = buildKnowledgeBase();
  const rules = loadRules(ledgerSS);
  const trips = buildTrips(ledgerSS);
  const emailIdx = loadEmailIndex();
  const targets = {};          // tabName → {sheet, keys:Set}
  const holds = {};            // distinct 패턴 → 학습대기 후보
  const stats = { done: 0, cancel: 0, hold: 0 };

  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openFirst(src);
    if (!sh) return;
    const rng = sh.getDataRange();
    const values = rng.getValues();
    const bg = rng.getBackgrounds();

    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      if (!isWhite(bg[r][0])) continue;
      const rec = parseRaw(values[r]);
      // (R2-5) 포맷 미인식 행을 조용히 넘기지 않는다 — 카드사 양식이 바뀌면
      // 누락이 소리 없이 발생하던 문제. 내용이 있는 행이면 노트로 표시.
      if (!rec) {
        if (values[r].join('').trim()) noteCell(sh, r + 1, '포맷 미인식(UNKNOWN) — 카드사 다운로드 양식 변경 여부 확인');
        continue;
      }
      if (!rec.merchant && !rec.krw) continue;

      const v = classify(rec, kb, emailIdx, trips, rules);

      if (v.status === 'CANCEL') {
        // (R2-5) 취소 반대분개: 이미 _C 탭에 전기된 원거래가 있으면 음수 한 줄을 같은 탭에 기록.
        // (과거엔 색만 바꿔 장부에 취소가 반영되지 않았다. design.md '반대분개 또는 제외' 구현)
        const revTab = postReversal(ledgerSS, rec);
        if (revTab) noteCell(sh, r + 1, '취소 — ' + revTab + ' 탭에 반대분개 기록');
        setRowColor(sh, r + 1, CONFIG.COLOR.CANCEL); stats.cancel++;
      } else if (v.status === 'CONFIRM') {
        const t = getTarget(targets, ledgerSS, v.tripName);
        const key = makeKey(v.useDateOverride || rec.useDate, rec.merchant, rec.krw);
        if (!t.keys.has(key)) { appendToLedger(t.sheet, rec, v); t.keys.add(key); }
        setRowColor(sh, r + 1, CONFIG.COLOR.DONE); stats.done++;
      } else {
        noteCell(sh, r + 1, v.reason);
        const hk = normMerchant(rec.merchant) + '|' + (rec.bizCat || '');
        if (!holds[hk]) holds[hk] = { merchant: rec.merchant, bizCat: rec.bizCat || '',
                                      date: rec.useDate, reason: v.reason };
        stats.hold++;
      }
    }
  });

  flushReview(ledgerSS, holds);
  toast('정산 완료 — 확정 ' + stats.done + ' / 취소 ' + stats.cancel +
        ' / 보류 ' + stats.hold + ' (학습대기 탭 확인)');
}

// ─────────────────────────────────────────────────────────────
// 여행 탭 모델
// ─────────────────────────────────────────────────────────────
function buildTrips(ss) {
  const trips = [];
  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    if (/_C$/.test(name)) return;                       // 비교본 제외
    const m = name.match(/^(\d{2})(\d{2})_(.+)$/);       // 출발일_지역
    if (!m) return;
    trips.push({ name: name, mm: +m[1], dd: +m[2], region: m[3] });
  });
  return trips;
}
// 실사용일이 속한 여행(가장 늦게 시작한 매칭 여행). 연도는 카드건 연도 기준(연초 wrap 고려).
function findTrip(trips, useDate) {
  const d = ymd(useDate); if (!d) return null;
  let best = null, bestStart = -1;
  trips.forEach(function (t) {
    [d.y, d.y - 1].forEach(function (yr) {
      const start = Date.UTC(yr, t.mm - 1, t.dd);
      const end = start + CONFIG.TRIP_WINDOW_DAYS * 86400000;
      const cur = Date.UTC(d.y, d.m - 1, d.d);
      if (cur >= start && cur <= end && start > bestStart) { best = t; bestStart = start; }
    });
  });
  return best;
}

// ─────────────────────────────────────────────────────────────
// RAW 포맷 자동 감지 + 정규화
// ─────────────────────────────────────────────────────────────
function detectFormat(row) {
  const c = row.map(function (x) { return String(x == null ? '' : x).trim(); });
  if (/^\d{1,2}:\d{2}/.test(c[2])) return 'DOMESTIC';
  if (['JPY', 'USD', 'KRW', 'EUR'].indexOf((c[10] || '').toUpperCase()) >= 0) return 'OVERSEAS_A';
  if (/^\d+$/.test(c[0]) && /\d{4}-\*/.test(c[3] || '')) return 'OVERSEAS_B';
  return 'UNKNOWN';
}
function parseRaw(row) {
  const c = row.map(function (x) { return String(x == null ? '' : x).trim(); });
  const fmt = detectFormat(row);
  let rec;
  if (fmt === 'OVERSEAS_A') {
    rec = { postDate: c[0], useDate: c[1], card: c[4], user: c[5], saleType: c[6],
            merchant: c[7], country: c[8], currency: c[10], foreign: num(c[11]),
            rate: num(c[13]), krw: num(c[16]), bizCat: '', overseas: true };
  } else if (fmt === 'DOMESTIC') {
    rec = { postDate: c[0], useDate: c[1], time: c[2], card: c[5], user: c[6],
            merchant: c[7], bizCat: c[8], saleType: c[9], krw: num(c[11]),
            currency: 'KRW', overseas: false };
  } else if (fmt === 'OVERSEAS_B') {
    rec = { useDate: c[1], card: c[3], merchant: c[7], krw: num(c[5]),
            postDate: c[14], currency: 'KRW', bizCat: '', overseas: true };
  } else { return null; }
  rec.format = fmt;
  rec.last4 = digits(rec.card).slice(-4);
  rec.useDate = normDate(rec.useDate);
  rec.postDate = normDate(rec.postDate);
  return rec;
}

// ─────────────────────────────────────────────────────────────
// 2단계 — 분류 (+ 여행 라우팅)
// ─────────────────────────────────────────────────────────────
function classify(rec, kb, emailIdx, trips, rules) {
  const name = (rec.merchant || '').toUpperCase();

  if (/취소|환불|CANCEL/i.test(rec.saleType || '') || rec.krw < 0) return { status: 'CANCEL' };

  const profile = CONFIG.CARD_PROFILES[rec.last4] || CONFIG.DEFAULT_CARD_PROFILE;  // 카드 주인 성향 — 마지막 fallback에서만 사용

  // 0순위: 사람이 확정한 영구 규칙 (학습 결과). 두 번 묻지 않기 위함.
  const ruled = rules && rules[normMerchant(rec.merchant)];

  // OTA(숙박/항공) → 메일 매칭으로 실사용일·예약번호 확보 (계정은 규칙>메일추정)
  if (hasKw(name, KW.OTA)) {
    const hit = emailIdx && matchEmail(emailIdx, rec);
    if (hit && hit.useDate) {
      const acct = (ruled && ruled.account) || (hit.item === '항공권' ? '여비교통비' : '숙박비');
      return route({ status: 'CONFIRM', account: acct, useDateOverride: hit.useDate,
                     bookingNo: hit.bookingNo, note: 'OTA:' + hit.source }, rec, trips);
    }
    return { status: 'HOLD', reason: 'OTA 실사용시기 확인 필요 — 메일 매칭 대기' };
  }

  // 규칙 적중 → 즉시 확정 (구분: 기타면 ETC 탭, 아니면 날짜로 여행 라우팅)
  if (ruled && ruled.account) {
    if (/기타/.test(ruled.kind)) return { status: 'CONFIRM', account: ruled.account, tripName: CONFIG.ETC_TAB };
    return route({ status: 'CONFIRM', account: ruled.account }, rec, trips);
  }

  const learned = kb[normMerchant(rec.merchant)];
  if (learned) return route({ status: 'CONFIRM', account: learned }, rec, trips);

  if (hasKw(name, KW.AIR)) return route({ status: 'CONFIRM', account: '여비교통비' }, rec, trips);

  const trip = findTrip(trips, rec.useDate);
  const isTravel = rec.overseas || !!trip;

  if (isTravel) {
    let account;
    if (hasKw(name, KW.LODGING)) account = '숙박비';
    else if (hasKw(name, KW.TRANSPORT)) account = '교통비';
    else if (hasKw(name, KW.ADMISSION)) account = '입장료';
    else if (hasKw(name, KW.FOOD_AREA)) account = '식비';
    else if (rec.bizCat && BIZCAT_TRAVEL[rec.bizCat]) account = BIZCAT_TRAVEL[rec.bizCat];
    else if (!rec.overseas) account = '식비';                       // 국내여행 기본
    else if (rec.krw <= OVERSEAS_FOOD_THRESHOLD) account = '식비';  // 해외 소액 기본
    else return { status: 'HOLD', reason: '해외 10만원 초과 미상 가맹점 — 수동 확인' };
    return route({ status: 'CONFIRM', account: account }, rec, trips, trip);
  }

  // 비여행 국내 = 기타비용
  if (hasKw(name, KW.PG) || (rec.bizCat && /전자상거래|PG/.test(rec.bizCat))) {
    const hit = emailIdx && matchEmail(emailIdx, rec);
    // (R2-5) 메일이 계정과목을 못 주면 '여비교통비'로 강제하지 않고 보류한다.
    // KICC 파서는 account를 채우지 않으므로 과거엔 PG 결제가 일괄 여비교통비로 오분류될 수 있었다.
    if (hit && hit.account) {
      return { status: 'CONFIRM', account: hit.account, tripName: CONFIG.ETC_TAB,
               note: '메일:' + hit.source, bookingNo: hit.bookingNo, project: hit.item };
    }
    if (hit) {
      return { status: 'HOLD', reason: '온라인결제 메일 매칭됨(' + hit.source +
               (hit.item ? '/' + hit.item : '') + ') — 계정과목만 확인해 학습대기에 입력' };
    }
    return { status: 'HOLD', reason: '온라인결제(PG/페이) — KICC·페이 메일 매칭 필요' };
  }
  if (rec.bizCat && BIZCAT_ETC[rec.bizCat]) return { status: 'CONFIRM', account: BIZCAT_ETC[rec.bizCat], tripName: CONFIG.ETC_TAB };

  // 카드 주인 성향(prior) — 위의 강한 신호가 모두 빠진 '미상' 건에만 적용되는 기본값.
  if (profile) {
    // 본인 카드: 기타비용 위주이고 큰 금액은 항공료뿐 → 미상 대액은 여비교통비로 확정.
    if (profile.kind === 'etc' && profile.bigAccount && rec.krw >= profile.bigThreshold) {
      return route({ status: 'CONFIRM', account: profile.bigAccount, note: '성향:' + (profile.owner || '') + '/대액' }, rec, trips);
    }
    // 여행성 카드(대표가이드 등): 기타로 오분류하지 않고, 여행 귀속을 사람이 확인하도록 보류.
    if (profile.kind === 'travel') {
      return { status: 'HOLD', reason: '여행 귀속 확인 — ' + (profile.owner || '') + ' 카드(여행성). 해당 여행 탭 생성/날짜 확인' };
    }
  }

  return { status: 'HOLD', reason: '기타비용 미상 업종 — 회의비/복리후생비/소모품비 확인' };
}
// 여행건에 목적지 탭 지정
function route(v, rec, trips, trip) {
  const t = trip || findTrip(trips, v.useDateOverride || rec.useDate);
  v.tripName = t ? t.name : (rec.overseas ? '여행_미매칭' : CONFIG.ETC_TAB);
  if (t) v.project = t.region;
  return v;
}

// ─────────────────────────────────────────────────────────────
// 학습 — 완료 장부 가맹점→계정과목
// ─────────────────────────────────────────────────────────────
function buildKnowledgeBase() {
  const cached = PropertiesService.getScriptProperties().getProperty('KB');
  return cached ? JSON.parse(cached) : rebuildKnowledgeBase();
}
function rebuildKnowledgeBase() {
  const kb = {};
  const ss = SpreadsheetApp.openById(CONFIG.LEARN_LEDGER.id);
  ss.getSheets().forEach(function (sh) {
    if (/_C$/.test(sh.getName())) return;
    const values = sh.getDataRange().getValues();
    values.forEach(function (row) {
      // 완료장부: 거래처 + 적요(용도) 패턴에서 학습
      const merchant = row.filter(function (x) { return /[A-Za-z가-힣]/.test(String(x)); })[1];
      const memo = String(row.join(' '));
      const acct = memoToAccount(memo);
      if (merchant && acct) kb[normMerchant(merchant)] = acct;
    });
  });
  PropertiesService.getScriptProperties().setProperty('KB', JSON.stringify(kb));
  return kb;
}
function memoToAccount(memo) {
  if (/숙박/.test(memo)) return '숙박비';
  if (/항공/.test(memo)) return '여비교통비';
  if (/교통/.test(memo)) return '교통비';
  if (/입장/.test(memo)) return '입장료';
  if (/식비/.test(memo)) return '식비';
  return '';
}

// ─────────────────────────────────────────────────────────────
// 학습 루프 — 분류규칙(영구) + 학습대기(사람이 1회 판단)
// ─────────────────────────────────────────────────────────────
const RULES_HEADER = ['가맹점', '계정과목', '구분(여행/기타)', '비고'];
const REVIEW_HEADER = ['가맹점', '업종', '예시일자', '보류사유', '계정과목(입력)', '구분(여행/기타)'];

function loadRules(ss) {
  const map = {};
  const sh = ss.getSheetByName(CONFIG.RULES_TAB);
  if (!sh) return map;
  const v = sh.getDataRange().getValues();
  for (let r = 1; r < v.length; r++) {
    const key = normMerchant(v[r][0]);
    if (key && v[r][1]) map[key] = { account: String(v[r][1]).trim(), kind: String(v[r][2] || '').trim() };
  }
  return map;
}

// HOLD distinct 패턴을 학습대기 탭에 축적(중복 제외)
function flushReview(ss, holds) {
  const keys = Object.keys(holds);
  if (!keys.length) return;
  const sh = ensureTab(ss, CONFIG.REVIEW_TAB, REVIEW_HEADER);
  const rules = loadRules(ss);
  const existing = new Set();
  const cur = sh.getDataRange().getValues();
  for (let r = 1; r < cur.length; r++) existing.add(normMerchant(cur[r][0]));
  keys.forEach(function (k) {
    const h = holds[k];
    const nm = normMerchant(h.merchant);
    if (existing.has(nm) || rules[nm]) return;           // 이미 대기중이거나 규칙 있음 → skip
    sh.appendRow([h.merchant, h.bizCat, h.date, h.reason, '', '']);
    existing.add(nm);
  });
}

// 학습대기에서 계정 채워진 행 → 분류규칙으로 승격(그 후 자동 분류)
function promoteReviewToRules() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const rv = ss.getSheetByName(CONFIG.REVIEW_TAB);
  if (!rv) { toast('학습대기 탭이 없습니다.'); return; }
  const rules = ensureTab(ss, CONFIG.RULES_TAB, RULES_HEADER);
  const v = rv.getDataRange().getValues();
  let promoted = 0;
  const remain = [REVIEW_HEADER];
  for (let r = 1; r < v.length; r++) {
    const merchant = v[r][0], account = String(v[r][4] || '').trim(), kind = String(v[r][5] || '').trim();
    if (account) { rules.appendRow([merchant, account, kind, '학습:' + new Date().toISOString().slice(0, 10)]); promoted++; }
    else remain.push(v[r]);                               // 아직 미입력 → 대기 유지
  }
  rv.clearContents();
  rv.getRange(1, 1, remain.length, REVIEW_HEADER.length).setValues(remain);
  PropertiesService.getScriptProperties().deleteProperty('KB'); // 규칙 반영 후 캐시 무효화
  toast(promoted + '건 규칙 반영 완료. 다음 정산부터 자동 분류됩니다.');
}

function ensureTab(ss, name, header) {
  let sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(header); sh.getRange(1, 1, 1, header.length).setFontWeight('bold'); }
  return sh;
}

// ─────────────────────────────────────────────────────────────
// 3단계 — _C 탭 전기
// ─────────────────────────────────────────────────────────────
function getTarget(cache, ss, tripName) {
  if (cache[tripName]) return cache[tripName];
  const sheet = getOrCreateCompareTab(ss, tripName);
  cache[tripName] = { sheet: sheet, keys: loadKeys(sheet) };
  return cache[tripName];
}
function getOrCreateCompareTab(ss, tripName) {
  const cName = tripName + '_C';
  let c = ss.getSheetByName(cName);
  if (!c) {
    const orig = ss.getSheetByName(tripName);
    c = orig ? ss.insertSheet(cName, orig.getIndex()) : ss.insertSheet(cName); // orig 바로 오른쪽
    c.appendRow(CONFIG.LEDGER_HEADER);
    c.getRange(1, 1, 1, CONFIG.LEDGER_HEADER.length).setFontWeight('bold');
  }
  return c;
}
function appendToLedger(sheet, rec, v) {
  const useDate = v.useDateOverride || rec.useDate;
  sheet.appendRow([
    useDate,                                       // 거래일자(실사용)
    rec.merchant,                                  // 거래처
    makeMemo(v.account, useDate, v.note),          // 적요 (용도_MMDD)
    rec.last4 + (rec.user ? '/' + rec.user : ''),  // 결제수단
    rec.krw,                                       // 금액
    v.bookingNo || '',                             // 예약번호
    v.account,                                     // 계정과목
    rec.postDate || rec.useDate,                   // 결제일
    rec.overseas ? '해외' : '국내',                // 국내/해외
    rec.currency || 'KRW',                         // 통화
    rec.foreign || '',                             // 현지금액
    '기록완료',                                    // 상태
    rec.format || '',                              // 출처
  ]);
}
const ACCOUNT_MEMO = { '숙박비': '숙박', '여비교통비': '항공', '교통비': '교통', '식비': '식비', '입장료': '입장료' };
function makeMemo(account, useDate, note) {
  const base = ACCOUNT_MEMO[account] || account;
  const s = String(useDate);
  const mmdd = /\d{4}-\d{2}-\d{2}/.test(s) ? '_' + s.slice(5).replace('-', '') : '';
  return base + mmdd + (note ? ' [' + note + ']' : '');
}
// (R2-5) 취소 건 반대분개 — 전 _C 탭에서 같은 가맹점·같은 금액(양수)으로 전기된
// 원거래를 찾아, 그 탭에 음수 금액 한 줄을 덧붙인다. 못 찾으면 null(색 표시만).
// 멱등성: 취소 행 자체가 CANCEL 색으로 칠해져 재처리되지 않는다.
function postReversal(ledgerSS, rec) {
  const posAmt = Math.abs(rec.krw);
  if (!posAmt) return null;
  const merchant = normMerchant(rec.merchant);
  const sheets = ledgerSS.getSheets().filter(function (sh) { return /_C$/.test(sh.getName()); });
  for (let i = 0; i < sheets.length; i++) {
    const sh = sheets[i];
    if (sh.getLastRow() < 2) continue;
    const values = sh.getDataRange().getValues();
    for (let r = 1; r < values.length; r++) {
      if (normMerchant(values[r][1]) !== merchant) continue;
      if (num(values[r][4]) !== posAmt) continue;   // 양수 원거래만
      sh.appendRow([
        rec.useDate, rec.merchant, '취소 반대분개',
        rec.last4 + (rec.user ? '/' + rec.user : ''),
        -posAmt, '', values[r][6] /* 원거래와 같은 계정과목 */,
        rec.postDate || rec.useDate, rec.overseas ? '해외' : '국내',
        rec.currency || 'KRW', '', '취소반영', rec.format || '',
      ]);
      return sh.getName();
    }
  }
  return null;
}

function loadKeys(sheet) {
  const set = new Set();
  const values = sheet.getDataRange().getValues();
  for (let r = 1; r < values.length; r++) set.add(makeKey(values[r][0], values[r][1], values[r][4]));
  return set;
}

// ─────────────────────────────────────────────────────────────
// 메일 스테이징 매칭
// ─────────────────────────────────────────────────────────────
function loadEmailIndex() {
  const ss = SpreadsheetApp.openById(CONFIG.STAGING.id);
  const sh = ss.getSheetByName(CONFIG.STAGING.sheetName);
  if (!sh || sh.getLastRow() < 2) return null;
  const values = sh.getDataRange().getValues();
  const col = {}; values[0].forEach(function (h, i) { col[h] = i; });
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    rows.push({ source: row[col.source], type: row[col.type], useDate: normDate(row[col.useDate]),
                paidDate: normDate(row[col.paidDate]),   // (R2-5) 결제일 근접 매칭용
                merchant: row[col.merchant], item: row[col.item], amount: num(row[col.amount]),
                account: row[col.account], bookingNo: String(row[col.bookingNo] || '') });
  }
  return rows;
}
// (R2-5) 금액 단독 매칭의 오매칭 방지 보강:
//  1) 결제일 근접(±3일) 조건 — 메일 수신일(paidDate) ≈ 예약 결제 시점이므로
//     카드 이용일(useDate)과 3일 넘게 벌어지면 동일 금액대 다른 결제로 간주.
//     (실사용일 useDate가 아니라 '결제 시점'끼리 비교 — OTA 선결제 특성 보존)
//  2) 같은 메일의 중복 매칭 금지(_used) — 한 메일은 카드 건 하나에만.
//  3) 후보가 여럿이면 결제일이 가장 가까운 메일 채택.
function matchEmail(index, rec) {
  const amt = Math.round(rec.krw);
  const recPay = dateMs(rec.useDate);   // 카드 '이용일' = 결제 발생일
  let best = null, bestDiff = Infinity;
  index.forEach(function (e) {
    if (e.type === 'refund' || e._used) return;
    const ea = Math.round(Math.abs(e.amount));
    if (!(ea > 0 && Math.abs(ea - amt) <= Math.max(2, amt * 0.01))) return;
    const ePay = dateMs(e.paidDate);
    let diff = 0;
    if (recPay != null && ePay != null) {
      diff = Math.abs(ePay - recPay) / 86400000;
      if (diff > 3) return;   // 결제일 3일 초과 이격 → 다른 결제
    }
    if (diff < bestDiff) { best = e; bestDiff = diff; }
  });
  if (best) best._used = true;
  return best;
}
function dateMs(v) {
  const s = normDate(v);
  if (!/^\d{4}-\d{2}-\d{2}/.test(String(s || ''))) return null;
  const t = new Date(String(s).slice(0, 10) + 'T00:00:00Z').getTime();
  return isNaN(t) ? null : t;
}

// ─────────────────────────────────────────────────────────────
// 헬퍼
// ─────────────────────────────────────────────────────────────
function openFirst(ref) {
  const ss = SpreadsheetApp.openById(ref.id);
  return ref.sheetName ? ss.getSheetByName(ref.sheetName) : ss.getSheets()[0];
}
function makeKey(date, merchant, amount) { return [normDate(date), normMerchant(merchant), num(amount)].join('|'); }
function normMerchant(s) { return String(s || '').toUpperCase().replace(/\s+/g, ' ').trim(); }
function hasKw(name, list) { return list.some(function (k) { return name.indexOf(k.toUpperCase()) >= 0; }); }
function num(v) { if (typeof v === 'number') return v; return Number(String(v || '').replace(/[^0-9.-]/g, '')) || 0; }
function digits(s) { return String(s || '').replace(/\D/g, ''); }
function normDate(d) {
  if (d instanceof Date) return Utilities.formatDate(d, 'Asia/Seoul', 'yyyy-MM-dd');
  const s = String(d || '').trim();
  let m = s.match(/(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})/);
  if (m) return m[1] + '-' + pad(m[2]) + '-' + pad(m[3]);
  m = s.match(/^(\d{2})[.\-\/](\d{1,2})[.\-\/](\d{1,2})$/);         // 26.04.27 → 2026-04-27
  if (m) return '20' + m[1] + '-' + pad(m[2]) + '-' + pad(m[3]);
  return s;
}
function ymd(s) {
  const m = String(s || '').match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
}
function pad(n) { return ('0' + n).slice(-2); }
function isWhite(hex) { const h = String(hex || '').toLowerCase(); return h === '' || h === '#ffffff' || h === '#fff' || h === 'white'; }
function setRowColor(sh, rowNum, color) { sh.getRange(rowNum, 1, 1, sh.getLastColumn()).setBackground(color); }
function noteCell(sh, rowNum, text) { sh.getRange(rowNum, 1).setNote(text); }
function toast(msg) {
  // 독립형(standalone) 프로젝트에선 getActiveSpreadsheet()가 null → 대상 장부를 열어서 알림.
  const ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  if (ss) ss.toast(msg, '비용처리', 8); else Logger.log(msg);
}
