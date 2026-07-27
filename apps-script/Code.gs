/**
 * 숲길여행 비용처리 자동화 — Apps Script 엔진 (단일 계정 kkokkohero6 실행)
 *
 * 작업 흐름(사람 방식 그대로):
 *  ① 카드 이용내역(RAW) 파싱 → 분류 → 실사용일이 속한 **실제 여행탭의 '지출 내용' 섹션에 직접 기록**.
 *  ② RAW 행 초록 색칠 = 실탭 기록 완료 확인. (애매한 건은 색 없이 HOLD → 학습대기)
 *  - 어떤 여행 기간에도 안 걸리는 국내건 = 기타비용 탭, 매칭 실패 해외건 = '여행_미매칭' 탭.
 * 진입점: onOpen() 메뉴 → runReconciliation() (멱등: RAW 흰색 행만 처리 + 실탭 중복 대조).
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
  TRIP_YEAR: 2026,              // 여행 탭(MMDD_지역·M월_지역)의 기본 연도. 탭명에 'YYYY_' 접두가 있으면 그 연도 우선.
                                //  이 연도와 '다른 연도' 카드건은 해당 탭에 안 들어감(2025 비용이 2026 여행탭에 섞이는 것 방지).
  DATE_TOL_DAYS: 4,             // 승인일/이용일/매입일 차이 허용(장부 대조·점검의 날짜 매칭 여유)
  OTA_PAYMENT_DATE_TOL_DAYS: 3, // OTA 확정 결합: 메일 결제일과 카드 이용일의 최대 차이
  AI_MODEL: 'gemini-2.0-flash', // 미상 가맹점 추론용 Gemini 모델. 스크립트 속성 GEMINI_API_KEY 필요(없으면 자동 생략).
  OTA_DATE_TOL_DAYS: 60,        // OTA 선결제 특례 — 카드 결제일과 장부(체크인일)가 수주~수개월 벌어질 수 있음
  ETC_TAB: '2분기_기타비용',    // 비여행 국내건 버킷(실제 장부 탭명) → '2분기_기타비용_C'. 분기 바뀌면 갱신.
  RULES_TAB: '분류규칙',        // 영구 학습 규칙 (가맹점→계정과목)
  REVIEW_TAB: '학습대기',       // HOLD된 distinct 패턴 → 사람이 1회 판단
  OTA_AUDIT_TAB: 'OTA_매칭감사', // 카드↔메일 결합의 재현 가능한 증거 보관
  CARD_EVENT_TAB: '카드거래원장', // 모든 RAW 행을 상태와 무관하게 1건씩 보존하는 불변 원장

  // 전기 행 형식 — 실제 장부 '지출 내용' 섹션과 1:1(앞 5개). 실탭엔 앞 5열만 쓰고
  //  예약번호·비고는 셀 노트로 보존. 실탭이 없는 버킷(여행_미매칭 등)은 7열 그대로 기록.
  LEDGER_HEADER: ['거래일자', '항목', '내용', '증빙유형', '금액', '예약번호', '비고'],

  COLOR: { DONE: '#d9ead3', CANCEL: '#f4cccc', SKIP: '#efefef', NONE: '#ffffff' },
  // SKIP(회색) = 과년도(TRIP_YEAR 이전) 일반 지출 — 이번 정리 대상 아님 표시.

  // 카드 주인별 분류 성향(prior). key = 카드 뒷4자리.
  // 강한 신호(날짜·키워드·메일매칭)가 모두 빠졌을 때만 적용되는 '기본값'이다 — 확정 분류를 덮지 않는다.
  CARD_PROFILES: {
    // 본인(김주형): 기타비용 위주, 큰 금액은 항공료에 국한 → 미상 대액은 여비교통비로.
    '3820': { owner: '김주형', kind: 'etc', bigAccount: '여비교통비', bigThreshold: 300000 },
    // 대장(가이드) 지급카드 — 사용내역은 여행탭이 아니라 '대장_이름' 전용 탭으로 분리(2026-07-21 규칙).
    '5836': { owner: '현수',    kind: 'travel', travelAccount: '숙박비', leaderTab: '대장_현수' },
    '4813': { owner: '바로바로', kind: 'travel', travelAccount: '숙박비', leaderTab: '대장_바로바로' },
    // 8831은 2026-07에 엘레나에게 전달 — 7/1 이전 사용분은 일반 여행탭(대장 구분 없음), 이후만 대장 탭(2026-07-22 규칙).
    '8831': { owner: '엘레나',  kind: 'travel', travelAccount: '숙박비', leaderTab: '대장_엘레나', leaderSince: '2026-07-01' },
  },
  // 위 표에 없는 카드의 기본 성향. 현재는 3820 외 전부 대표가이드(여행성)이므로 travel.
  DEFAULT_CARD_PROFILE: { owner: '대표가이드', kind: 'travel', travelAccount: '숙박비' },
};

// 가맹점명 추론 사전 — 카드 명세의 로마자 표기(일본: HOTERU/SHOKUDO 등, 유럽: RISTORANTE/PEAGE 등)까지 포함.
//  분류 순서는 classify() 참고: LODGING → TRANSPORT → ADMISSION → FOOD 순이라 'BUSINESS HOTEL'은 숙박으로 먼저 잡힘.
const KW = {
  TRANSPORT: ['TOYOTA', 'RENT', 'ENEOS', 'HERTZ', 'TAXI', 'PARKING', 'SHELL', 'ESSO',
              'TOLL', 'EXPRESSWAY', 'JR', 'RAIL', 'TATEYAMA', 'KUROBE', 'MINITZ',
              '렌트', '렌터카', '주유',
              // 로프웨이·곤돌라·리프트 등 산악 교통
              'GONDOLA', 'LIFT', 'ROPEWAY', 'CABLE', 'FUNICULAR',
              // 일본 철도·공항철도
              'KEISEI', 'SKYLINE', 'SHINKANSEN', 'KINTETSU', 'ODAKYU', 'METRO',
              // 렌터카 체인
              'AVIS', 'EUROPCAR', 'SIXT', 'BY CAR', 'NIPPON RENT', 'TIMES CAR', 'ORIX',
              // 유럽 주유·고속도로
              'AGIP', 'TOTAL', 'STAZ.SERV', 'AUTOSTRADE', 'AUTOROUTE', 'PEAGE', 'APRR', 'AREA ',
              'FERRY', 'TRAGHETTI'],
  AIR:       ['대한항공', 'KOREAN AIR', '아시아나', 'ASIANA', '제주항공', 'JEJU AIR',
              '진에어', 'JIN AIR', '마이트립', 'MYTRIP', 'NIPPON TRAVEL', '항공',
              'A.N.A', 'ANA AIR', 'AIRLINE', 'AIRWAYS', 'PEACH AVIATION', 'SKYMARK', 'SKYTICKET',
              'LUFTHANSA', 'AIR FRANCE', 'KLM', 'EMIRATES', 'QATAR', 'TURKISH AIR'],
  LODGING:   ['HOTEL', 'INN', 'ROUTE-INN', 'TOYOKO', 'RESORT', 'RYOKAN', 'HOSTEL', 'ONSE',
              'ホテル', '호텔', '료칸', '민박', '亀の井', '칸',
              // 로마자 일본어·기타 숙박 표기
              'HOTERU', 'PENSION', 'LODGE', 'GUEST HOUSE', 'MINSHUKU', 'B&B', 'AUBERGE',
              'RAKUTEN'],   // 라쿠텐트래블(숙박 OTA — 메일 파서 없으므로 숙박비 직행)
  OTA:       ['AGODA', 'BOOKING', 'TRIP.COM', '트립닷컴', '부킹', '아고다', '마이트립', 'EXPEDIA', 'AIRBNB'],
  FOOD_AREA: ['SERVICE AREA', 'MICHINOEKI', 'SEVENELEVEN', 'APITA', 'MARKET', '휴게',
              // 로마자 일본어 식당·마트
              'SHOKUDO', 'IZAKAYA', 'SUSHI', 'RAMEN', 'UDON', 'SOBA', 'YAKINIKU', 'WASHOKU',
              'ICHIBA', 'GASUTO', 'SAIZERIYA', 'MATSUYA', 'YOSHINOYA', 'SUKIYA', 'COCOICHI',
              'LAWSON', 'FAMILYMART', 'KONBINI',
              // 서양권 식당·마트
              'RESTAURANT', 'RISTORANTE', 'TRATTORIA', 'OSTERIA', 'PIZZERIA', 'BRASSERIE',
              'BOULANGERIE', 'CAFE', 'COFFEE', 'SUPER U', 'CARREFOUR', 'LIDL', 'MONOPRIX', 'COOP'],
  ADMISSION: ['NATADERA', 'PARK', '입장', 'MUSEUM', 'ZOO', 'VIEWLAND', 'MUSEE', 'AQUARIUM',
              'ONSEN', 'CASTLE', 'CASTELLO', 'GARDEN', 'SHRINE', 'TEMPLE'],
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
    .addItem('메일 점검 (유입·파싱 커버리지 대조)', 'auditMailCoverage')
    .addItem('OTA 메일-카드 결합 점검', 'auditOtaMatches')
    .addItem('자동 수집 켜기 (10분마다 backlog 소진)', 'setupDrainTrigger')
    .addItem('자동 수집 해제', 'removeDrainTrigger')
    .addSeparator()
    .addItem('학습대기 → 규칙 반영', 'promoteReviewToRules')
    .addItem('학습맵 다시 만들기', 'rebuildKnowledgeBase')
    .addSeparator()
    .addItem('정산 점검 (내 카드내역 전부 장부에 있나 대조)', 'auditCoverage')
    .addSeparator()
    .addItem('정산 롤백 (자동 전기 전부 회수 — 수기 행 보존)', 'rollbackAutoPostings')
    .addItem('비교탭(_C) 정리 — 수기와 대조해 중복 제거 (과거 방식 잔재)', 'pruneCompareTabs')
    .addItem('비교탭(_C) 전체 삭제 (과거 방식 잔재)', 'deleteCompareTabs')
    .addItem('엔진 색 초기화 — 재처리용 (수동 표시는 보존)', 'resetRawColors')
    .addSeparator()
    .addItem('입금 동기화 — 수입 내용 → 대장 명단 입금상태', 'syncPaymentsToLeader')
    .addToUi();
}

// ─────────────────────────────────────────────────────────────
// 장부 지출행 추출 + 포괄 매칭 (수기탭·_C탭·기타비용탭 공통)
//  금액만으로 매칭하면 같은 금액의 다른 결제가 오매칭됨 → 금액을 1차 게이트로 두되
//  '날짜(±허용)·가맹점·카드' 중 최소 1개가 보강돼야 매칭으로 인정한다.
// ─────────────────────────────────────────────────────────────
// OTA 브랜드 정규화 — 카드 명세엔 "AGODA COMPANY PTE"·"TRIP.COM", 장부/메일엔 "아고다"·호텔명 등
//  표기가 들쑥날쑥 → 양쪽을 브랜드 토큰으로 환원해 비교. (호텔명으로 적힌 수기 건은 메일 브릿지로 해결)
const OTA_BRANDS = [
  { key: 'TRIPCOM', pats: ['TRIP.COM', 'TRIP COM', 'TRIPCOM', '트립닷컴', '트립'] },
  { key: 'AGODA',   pats: ['AGODA', '아고다'] },
  { key: 'BOOKING', pats: ['BOOKING', '부킹'] },
  { key: 'MYTRIP',  pats: ['MYTRIP', '마이트립'] },
];
function otaBrand(name) {
  const n = normMerchant(name);
  if (!n) return '';
  for (let i = 0; i < OTA_BRANDS.length; i++) {
    if (OTA_BRANDS[i].pats.some(function (p) { return n.indexOf(p) >= 0; })) return OTA_BRANDS[i].key;
  }
  return '';
}

// 한 장부 탭의 '지출 내용' 섹션에서 지출행을 구조화해 뽑는다(수입 섹션·총금액 행 제외).
//  헤더는 '증빙유형'+'금액'이 함께 있는 행으로 감지 → 컬럼을 이름으로 매핑(수기/자동 배치 차이 흡수).
function extractLedgerRecords(sheet) {
  const dataRange = sheet.getDataRange();
  const v = dataRange.getValues();
  const cellNotes = dataRange.getNotes();
  let hdr = -1;
  for (let r = 0; r < v.length; r++) {
    const has = function (kw) { return v[r].some(function (x) { return String(x).indexOf(kw) >= 0; }); };
    if (has('증빙유형') && has('금액')) { hdr = r; break; }
  }
  if (hdr < 0) return [];                                 // 지출 섹션 없음
  const H = v[hdr].map(function (x) { return String(x); });
  const find = function (kw) { return H.findIndex(function (h) { return h.indexOf(kw) >= 0; }); };
  const ci = { date: find('거래일자'), item: find('항목'), acct: find('내용'), card: find('증빙유형'),
               amt: find('금액'), book: find('예약번호'), note: find('비고') };
  if (ci.amt < 0) return [];
  const out = [];
  for (let r = hdr + 1; r < v.length; r++) {
    if (v[r].some(function (x) { return /총\s*금액|합\s*계/.test(String(x)); })) break;   // 소계/총계 도달 → 종료
    const amt = num(v[r][ci.amt]);
    if (!amt) continue;
    out.push({
      date: normDate(ci.date >= 0 ? v[r][ci.date] : ''),
      merchant: ci.item >= 0 ? String(v[r][ci.item] || '') : '',
      card: ci.card >= 0 ? digits(v[r][ci.card]).slice(-4) : '',
      amount: amt,
      bookingNo: ci.book >= 0 ? digits(v[r][ci.book]) : '',
      eventId: cardEventIdFromText((ci.note >= 0 ? v[r][ci.note] : '') + ' ' +
                                   (ci.item >= 0 ? cellNotes[r][ci.item] : '')),
    });
  }
  return out;
}
// 두 지출 레코드가 '동일 결제'인가. 매칭되면 근거 문자열, 아니면 '' 반환.
//  ① 예약번호 일치 → 즉시 확정(최강 신호).
//  ② 금액 일치(필수 게이트) + (날짜 ±4일 | 가맹점 유사/OTA 동일브랜드 | 카드 일치) 중 1개 이상.
//  ③ OTA 특례: 한쪽이라도 OTA 브랜드면 결제일↔체크인일이 수주 벌어짐 → 날짜 허용폭을 60일로 완화한 '추정' 매칭.
function recordsMatch(a, b) {
  // 양쪽에 이벤트 ID가 있으면 그것만이 동일성 기준이다. 금액·날짜가 같은 별도 결제를 합치지 않는다.
  if (a.eventId && b.eventId) return a.eventId === b.eventId ? '카드거래ID' : '';
  if (a.bookingNo && b.bookingNo && a.bookingNo === b.bookingNo) return '예약번호';
  if (Math.round(Math.abs(a.amount)) !== Math.round(Math.abs(b.amount))) return '';  // 금액 게이트
  const brandA = otaBrand(a.merchant), brandB = otaBrand(b.merchant);
  const sig = [];
  const da = dateMs(a.date), db = dateMs(b.date);
  const dayDiff = (da != null && db != null) ? Math.abs(da - db) / 86400000 : null;
  if (dayDiff != null && dayDiff <= CONFIG.DATE_TOL_DAYS) sig.push('날짜');          // 승인/이용/매입 차이 허용
  if ((brandA && brandA === brandB) || merchantSimilar(a.merchant, b.merchant)) sig.push('가맹점');
  if (a.card && b.card && a.card === b.card) sig.push('카드');
  if (sig.length) return '금액+' + sig.join('+');
  // OTA 특례 — 가맹점(호텔명 vs OTA명)·카드(수기엔 미기재)가 다 어긋나도, 금액 일치 + 60일 내면 추정.
  if ((brandA || brandB) && (dayDiff == null || dayDiff <= CONFIG.OTA_DATE_TOL_DAYS)) return '금액+OTA(추정)';
  return '';
}
function merchantSimilar(a, b) {
  const A = normMerchant(a).replace(/[^0-9A-Z가-힣ぁ-んァ-ヶ一-龯]/g, '');
  const B = normMerchant(b).replace(/[^0-9A-Z가-힣ぁ-んァ-ヶ一-龯]/g, '');
  if (!A || !B) return false;
  if (A === B) return true;
  const s = A.length < B.length ? A : B, l = A.length < B.length ? B : A;
  if (s.length >= 3 && l.indexOf(s) >= 0) return true;        // 짧은 쪽이 긴 쪽에 포함
  return s.length >= 4 && l.slice(0, 4) === s.slice(0, 4);    // 앞 4글자 공유
}

// ─────────────────────────────────────────────────────────────
// 4단계 — 비교탭 정리: {탭}_C 를 수기 {탭}의 '지출 내용'과 포괄 대조.
//  이미 수기 장부에 있는 건(금액+날짜/가맹점/카드 매칭)은 _C에서 제거 → _C엔 '아직 안 적은 것'만 남김.
//  같은 수기행은 한 번만 소진(한 _C행 제거에 재사용 금지). 사람이 최종 확인 전제.
// ─────────────────────────────────────────────────────────────
function pruneCompareTabs() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  let removed = 0, tabs = 0;
  ss.getSheets().forEach(function (cSheet) {
    const cName = cSheet.getName();
    if (!/_C$/.test(cName)) return;
    const base = ss.getSheetByName(cName.slice(0, -2));   // '_C' 떼면 원본 여행탭
    if (!base || cSheet.getLastRow() < 2) return;
    const manual = extractLedgerRecords(base);            // 수기 지출행
    const used = manual.map(function () { return false; });
    const values = cSheet.getDataRange().getValues();
    const keep = [values[0]];                             // 헤더 유지
    for (let r = 1; r < values.length; r++) {
      const rec = { date: normDate(values[r][0]), merchant: String(values[r][1] || ''),
                    card: digits(values[r][3]).slice(-4), amount: num(values[r][4]),
                    bookingNo: digits(values[r][5]) };
      let matched = -1;
      for (let i = 0; i < manual.length; i++) {
        if (!used[i] && recordsMatch(rec, manual[i])) { matched = i; break; }
      }
      if (matched >= 0) { used[matched] = true; removed++; continue; }   // 이미 수기에 있음 → 제거
      keep.push(values[r]);
    }
    cSheet.clearContents();
    cSheet.getRange(1, 1, keep.length, CONFIG.LEDGER_HEADER.length).setValues(keep);
    tabs++;
  });
  toast('비교탭 정리 완료 — 이미 수기에 있는 ' + removed + '건 제거, ' + tabs + '개 _C 갱신.');
}

// ─────────────────────────────────────────────────────────────
// 정산 점검(완전성 감사) — 내 카드내역(RAW) 전부가 장부 어딘가에 기록됐는지 대조.
//  장부(수기탭 + _C탭 + 기타비용)를 금액→레코드 인덱스로 만들고, RAW 전 건을 포괄 매칭.
//  결과를 '정산_점검' 탭에 리포트: 기록됨(발견 위치) / 미기록(누락!) / 취소 / 미인식.
//  → '미기록'이 0이 되면 내 이용내역이 전부 장부로 옮겨진 것.
// ─────────────────────────────────────────────────────────────
const AUDIT_TAB = '정산_점검';
const AUDIT_HEADER = ['카드', '이용일', '가맹점', '금액', '상태', '발견위치', '매칭근거', 'RAW색', '비고'];
const OTA_AUDIT_HEADER = ['카드원본', '판정', '카드일', '카드가맹점', '카드금액', '카드통화',
                          '메일원본', '메일ID', '메일결제일', '예약번호', '실사용일',
                          '일치근거', '후보수', '비고', '갱신일'];
function auditCoverage() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const emailIdx = loadEmailIndex();   // OTA 브릿지용 — 카드 OTA건에 호텔명·체크인일·예약번호 보강
  // 1) 장부에 이미 기록된 지출 인덱스 (수기 + 자동 _C 모두). 금액(절대값)→레코드[].
  const index = {};
  const skip = { }; skip[CONFIG.STAGING.sheetName] = 1; skip[CONFIG.RULES_TAB] = 1; skip[CONFIG.REVIEW_TAB] = 1;
  skip[AUDIT_TAB] = 1; skip[CONFIG.OTA_AUDIT_TAB] = 1; skip[CONFIG.CARD_EVENT_TAB] = 1;
  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    if (skip[name]) return;
    const kind = /_C$/.test(name) ? '_C(구방식)' : '장부';
    extractLedgerRecords(sh).forEach(function (rec) {
      rec.tab = name; rec.kind = kind;
      const k = Math.round(Math.abs(rec.amount));
      (index[k] = index[k] || []).push(rec);
    });
  });
  // 2) RAW 전 건을 인덱스와 대조
  const report = [];
  let total = 0, covered = 0, uncovered = 0, cancel = 0, unknown = 0, scopeOut = 0;
  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openFirst(src); if (!sh) return;
    const rng = sh.getDataRange();
    const values = rng.getValues();
    const bg = rng.getBackgrounds();
    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      if (!values[r].join('').trim()) continue;
      const rec = parseRaw(values[r]);
      if (!rec) { unknown++; report.push(['', '', '(포맷 미인식 행)', '', '미인식', '', '', colorName(rowColor(bg[r])), '카드사 양식 확인']); continue; }
      if (!rec.merchant && !rec.krw) continue;
      // 과년도 건은 이번 정리(TRIP_YEAR) 대상 아님 — '미기록'으로 세지 않고 범위외로 분리.
      const dy = ymd(rec.useDate);
      if (dy && dy.y < CONFIG.TRIP_YEAR && !isBookingLike(rec)) {
        scopeOut++;
        report.push([rec.last4, rec.useDate, rec.merchant, rec.krw, '범위외(' + dy.y + ')', '', '', colorName(rowColor(bg[r])), CONFIG.TRIP_YEAR + '년 정리 대상 아님']);
        continue;
      }
      total++;
      const rawColor = colorName(rowColor(bg[r]));
      if (/취소|환불|CANCEL/i.test(rec.saleType || '') || rec.krw < 0) {
        cancel++; report.push([rec.last4, rec.useDate, rec.merchant, rec.krw, '취소', '', '', rawColor, '반대분개 대상']); continue;
      }
      const cand = index[Math.round(Math.abs(rec.krw))] || [];
      // 카드 원본 그대로의 레코드 + (OTA면) 메일 브릿지로 보강한 레코드 — 둘 다로 시도.
      //  OTA는 카드엔 "AGODA…"·결제일, 장부엔 호텔명·체크인일이라 원본끼리는 안 맞는 게 정상.
      //  메일수집에서 같은 금액·근접 결제일의 메일을 찾으면 호텔명/체크인일/예약번호를 얻어 정확 매칭 가능.
      const tries = [{ date: rec.useDate, merchant: rec.merchant, card: rec.last4, amount: rec.krw, bookingNo: '' }];
      let bridged = '';
      if (otaBrand(rec.merchant) && emailIdx) {
        const otaMatch = matchOtaEmail(emailIdx, rec);
        const eh = otaMatch.status === 'EXACT' ? otaMatch.email : null;
        if (eh) {
          tries.unshift({ date: eh.useDate || rec.useDate, merchant: String(eh.merchant || ''),
                          card: rec.last4, amount: rec.krw, bookingNo: digits(eh.bookingNo) });
          bridged = '메일EXACT(' + (eh.source || '') + ')';
        }
      }
      let hit = null, how = '';
      for (let ti = 0; ti < tries.length && !hit; ti++) {
        for (let i = 0; i < cand.length; i++) {
          const m = recordsMatch(tries[ti], cand[i]);
          if (m) { hit = cand[i]; how = (ti === 0 && bridged ? bridged + '→' : '') + m; break; }
        }
      }
      if (hit) {
        covered++;
        const status = /추정/.test(how) ? '기록됨(추정)' : '기록됨';
        report.push([rec.last4, rec.useDate, rec.merchant, rec.krw, status, hit.tab + '(' + hit.kind + ')', how, rawColor, '']);
      } else {
        uncovered++;
        const why = rowIsWhite(bg[r]) ? '아직 정산 안 됨(흰색) — 정산 실행 필요'
                 : rawColor === '완료' ? '완료색인데 장부에 없음 — 삭제됐거나 위치 확인'
                 : /수동표시/.test(rawColor) ? '수동 표시된 행인데 장부 매칭 실패 — 표기 차이(가맹점명 등)일 수 있음, 눈으로 확인'
                 : '전기 누락 — 수동 확인';
        report.push([rec.last4, rec.useDate, rec.merchant, rec.krw, '미기록', '', bridged || '', rawColor, why]);
      }
    }
  });
  // 3) '정산_점검' 탭에 요약 + 상세 기록(미기록은 빨강 강조)
  report.sort(function (a, b) { return (a[4] === '미기록' ? 0 : 1) - (b[4] === '미기록' ? 0 : 1); }); // 미기록 먼저
  const sheet = ensureTab(ss, AUDIT_TAB, AUDIT_HEADER);
  sheet.clearContents();
  const summary = ['요약', '총 ' + total, '기록됨 ' + covered, '미기록 ' + uncovered, '취소 ' + cancel, '미인식 ' + unknown, '범위외 ' + scopeOut, '갱신 ' + today(), ''];
  const out = [summary, AUDIT_HEADER].concat(report);
  sheet.getRange(1, 1, out.length, AUDIT_HEADER.length).setValues(out);
  sheet.getRange(1, 1, 1, AUDIT_HEADER.length).setFontWeight('bold');
  sheet.getRange(2, 1, 1, AUDIT_HEADER.length).setFontWeight('bold');
  // 미기록 행 빨강
  const bgs = report.map(function (row) {
    const c = row[4] === '미기록' ? '#f4cccc' : (row[4] === '미인식' ? '#fff2cc' : '#ffffff');
    return AUDIT_HEADER.map(function () { return c; });
  });
  if (bgs.length) sheet.getRange(3, 1, bgs.length, AUDIT_HEADER.length).setBackgrounds(bgs);
  toast('정산 점검 완료 — 총 ' + total + ' / 기록됨 ' + covered + ' / 미기록 ' + uncovered +
        ' / 취소 ' + cancel + ' / 미인식 ' + unknown + ' ("' + AUDIT_TAB + '" 탭 확인)');
}
// 행 배경색 배열에서 '그 행의 색'을 얻는다 — 첫 번째 비흰색 셀(수작업 표시가 오른쪽 열에만 있어도 인식).
function rowColor(bgRow) {
  for (let c = 0; c < bgRow.length; c++) { if (!isWhite(bgRow[c])) return bgRow[c]; }
  return '';
}
function rowIsWhite(bgRow) { return rowColor(bgRow) === ''; }
// 배경색 → 사람이 읽는 상태명
function colorName(hex) {
  const h = String(hex || '').toLowerCase();
  if (h === '' || h === '#ffffff' || h === '#fff' || h === 'white') return '흰(미처리)';
  if (h === CONFIG.COLOR.DONE.toLowerCase()) return '완료';
  if (h === CONFIG.COLOR.CANCEL.toLowerCase()) return '취소';
  if (h === CONFIG.COLOR.SKIP.toLowerCase()) return '범위외(과년도)';
  return '수동표시(' + hex + ')';   // 엔진 색이 아닌 것 = 사용자가 직접 칠한 표시
}
function isEngineColor(hex) {
  const h = String(hex || '').toLowerCase();
  return h === CONFIG.COLOR.DONE.toLowerCase() || h === CONFIG.COLOR.CANCEL.toLowerCase() ||
         h === CONFIG.COLOR.SKIP.toLowerCase();
}
// 숙박/항공/OTA 결제 여부 — 과년도(2025) 건이라도 다음 해 여행의 선결제일 수 있어 계속 추적한다.
function isBookingLike(rec) {
  const name = (rec.merchant || '').toUpperCase();
  return hasKw(name, KW.OTA) || hasKw(name, KW.AIR) || hasKw(name, KW.LODGING);
}

// 카드내역 시트에서 '엔진이 칠한 색(초록/빨강/회색)'만 지움 → 다음 정산에서 재처리.
//  사용자가 직접 칠한 수동 표시(주황/청록 등)와 그 행의 노트는 보존한다.
function resetRawColors() {
  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openFirst(src);
    if (!sh) return;
    const rng = sh.getDataRange();
    const bg = rng.getBackgrounds();
    const notes = sh.getRange(1, 1, bg.length, 1).getNotes();
    for (let r = 0; r < bg.length; r++) {
      const c0 = rowColor(bg[r]);
      if (!c0) { notes[r][0] = clearRawEngineStatus(notes[r][0]); continue; }
      if (!isEngineColor(c0)) continue;                    // 수동 표시 행: 색·노트 보존
      for (let c = 0; c < bg[r].length; c++) bg[r][c] = CONFIG.COLOR.NONE;
      notes[r][0] = clearRawEngineStatus(notes[r][0]);     // 카드거래ID·사용자 노트는 보존
    }
    rng.setBackgrounds(bg);
    sh.getRange(1, 1, bg.length, 1).setNotes(notes);
  });
  toast('엔진 색(초록/빨강/회색)만 초기화 완료 — 수동 표시는 보존. 다음 정산에서 재처리됩니다.');
}

// ─────────────────────────────────────────────────────────────
// 메인 — 모든 RAW 행을 카드거래원장에 보존하고 card_event_id 기준으로 멱등 전기
// ─────────────────────────────────────────────────────────────
function runReconciliation() {
  const ledgerSS = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const kb = buildKnowledgeBase();
  const rules = loadRules(ledgerSS);
  aiPrepassRules(ledgerSS, kb, rules);   // 사전에 없는 가맹점 → Gemini 일괄 추론(키 있을 때만) → rules에 반영
  const trips = buildTrips(ledgerSS);
  const emailIdx = loadEmailIndex();
  const eventJournal = loadCardEventJournal(ledgerSS);
  const claimedEventIds = {};
  const targets = {};          // tabName → {sheet, mode, sec, existing, rows:[]}
  const holds = {};            // card_event_id → 개별 학습대기 거래
  const cardEvents = [];       // 비어 있지 않은 RAW 행과 정확히 1:1
  const otaAudits = [];        // 이번 실행에서 판정한 OTA 카드↔메일 결합 증거
  const stats = { raw: 0, done: 0, cancel: 0, hold: 0, skip: 0, parseError: 0 };

  // 성능: 행마다 색칠/노트/전기하면 6분 제한 초과 → 시트당 '한 번에' 읽고 쓴다(배치).
  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openFirst(src);
    if (!sh) return;
    const rng = sh.getDataRange();
    const values = rng.getValues();
    const bg = rng.getBackgrounds();                          // 1 read
    const notes = sh.getRange(1, 1, values.length, 1).getNotes();  // 1 read (A열 노트)
    let touched = false;

    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      if (!values[r].join('').trim()) continue;
      stats.raw++;
      const fingerprint = cardEventFingerprint(src, values[r]);
      const eventId = resolveCardEventId(notes[r][0], fingerprint, eventJournal, claimedEventIds);
      notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, '처리 중');
      touched = true;
      const rec = parseRaw(values[r]);
      if (!rec) {
        const reason = '포맷 미인식(UNKNOWN) — 카드사 다운로드 양식 변경 여부 확인';
        notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, reason);
        cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, null, values[r], 'PARSE_ERROR', '', '', '', reason));
        stats.parseError++;
        continue;
      }
      rec.cardEventId = eventId;
      rec.rawRef = rawRef(src, r + 1);
      if (!rec.merchant && !rec.krw) {
        const reason = '거래처와 금액이 모두 비어 있음';
        notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, reason);
        cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, rec, values[r], 'INVALID', '', '', '', reason));
        stats.parseError++;
        continue;
      }

      // 과년도(TRIP_YEAR 이전) 건: 숙박/항공/OTA(다음 해 여행 선결제 가능)만 계속 추적하고,
      //  나머지는 전기하지 않되 카드거래원장에는 반드시 보존한다.
      const dy = ymd(rec.useDate);
      if (dy && dy.y < CONFIG.TRIP_YEAR && !isBookingLike(rec)) {
        for (let c = 0; c < bg[r].length; c++) bg[r][c] = CONFIG.COLOR.SKIP;
        const reason = dy.y + '년 거래 — ' + CONFIG.TRIP_YEAR + '년 전기 범위 밖';
        notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, reason);
        cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, rec, values[r], 'SCOPE_OUT', '', '', '', reason));
        stats.skip++;
        continue;
      }

      const v = classify(rec, kb, emailIdx, trips, rules);
      if (v.otaMatch) otaAudits.push(otaAuditRow(rec, v.otaMatch));

      if (v.status === 'CANCEL') {
        const cancelRec = Object.assign({}, rec, { krw: -Math.abs(num(rec.krw)) });
        const cancelDecision = { status: 'CONFIRM', account: '취소환불', tripName: '취소환불',
                                 note: '카드 취소·환불 원문 보존' };
        const posted = queueLedgerPosting(cancelRec, cancelDecision, targets, ledgerSS);
        const cancelState = posted.ok ? (posted.duplicate ? 'CANCELLED_RECORDED' : 'CANCELLED_POSTED') : 'POSTING_BLOCKED';
        const reason = posted.ok ? '취소·환불 음수 거래 기록' : posted.reason;
        notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, reason);
        cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, cancelRec, values[r],
                                      cancelState, posted.tab || '', '취소환불', '', reason));
        for (let c = 0; c < bg[r].length; c++) bg[r][c] = posted.ok ? CONFIG.COLOR.CANCEL : CONFIG.COLOR.NONE;
        if (!posted.ok) {
          holds[eventId] = reviewItem(cancelRec, eventId, reason);
          stats.hold++;
        }
        stats.cancel++;
      } else if (v.status === 'CONFIRM') {
        const posted = queueLedgerPosting(rec, v, targets, ledgerSS);
        if (!posted.ok) {
          notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, posted.reason);
          holds[eventId] = reviewItem(rec, eventId, posted.reason);
          cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, rec, values[r],
                                        'POSTING_BLOCKED', v.tripName || '', v.account || '', v.bookingNo || '', posted.reason));
          stats.hold++;
        } else {
          const state = posted.duplicate ? 'ALREADY_RECORDED' : 'POSTED';
          const reason = posted.duplicate ? '동일 카드거래ID 또는 동일 결제가 장부에 이미 존재' : '장부 전기 완료';
          notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, reason);
          cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, rec, values[r],
                                        state, posted.tab || '', v.account || '', v.bookingNo || '', reason));
          for (let c = 0; c < bg[r].length; c++) bg[r][c] = CONFIG.COLOR.DONE;
          stats.done++;
        }
      } else {
        notes[r][0] = rawNoteWithEvent(notes[r][0], eventId, v.reason);
        holds[eventId] = reviewItem(rec, eventId, v.reason);
        cardEvents.push(makeCardEvent(src, sh, r + 1, fingerprint, eventId, rec, values[r],
                                      'HOLD', '', '', v.bookingNo || '', v.reason));
        stats.hold++;
      }
    }
    if (touched) {
      rng.setBackgrounds(bg);                                 // 1 write
      sh.getRange(1, 1, values.length, 1).setNotes(notes);    // 1 write
    }
  });

  // 전기: 탭별로 모아서 실탭에 한 번에 기록 (append 반복 금지)
  Object.keys(targets).forEach(function (tab) { flushTarget(targets[tab]); });

  if (cardEvents.length !== stats.raw) throw new Error('카드거래 보존 실패: RAW ' + stats.raw + '행 / 이벤트 ' + cardEvents.length + '건');
  upsertCardEvents(ledgerSS, cardEvents);
  flushReview(ledgerSS, holds);
  upsertOtaAudit(ledgerSS, otaAudits);
  toast('정산 완료 — RAW원장 ' + stats.raw + ' / 확정 ' + stats.done + ' / 취소 ' + stats.cancel +
        ' / 보류 ' + stats.hold + ' / 범위외 ' + stats.skip + ' / 파싱오류 ' + stats.parseError);
}

// ─────────────────────────────────────────────────────────────
// 여행 탭 모델
// ─────────────────────────────────────────────────────────────
function buildTrips(ss) {
  const trips = [];
  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    if (/_C$/.test(name)) return;                       // 비교본 제외
    // 탭명에 'YYYY_' 접두가 있으면 그 연도를, 없으면 CONFIG.TRIP_YEAR(현재 2026)를 여행 연도로.
    let year = CONFIG.TRIP_YEAR, rest = name;
    // 연도 접두는 '20xx'만 인정 — 0620_묘코 같은 MMDD 탭을 연도로 오인하면 여행탭 전체가 누락된다(실제 버그).
    const ym = name.match(/^(20\d{2})_(.+)$/);           // 2026_0630_오제 · 2025_5월_유럽 (연도 명시)
    if (ym) { year = +ym[1]; rest = ym[2]; }
    let m = rest.match(/^(\d{2})(\d{2})_(.+)$/);         // 0625_아키타 (출발일_지역)
    if (m) { trips.push({ name: name, year: year, mm: +m[1], dd: +m[2], region: m[3], windowDays: CONFIG.TRIP_WINDOW_DAYS }); return; }
    m = rest.match(/^(\d{1,2})월_(.+)$/);                // 5월_유럽 · 10월_도고 (월 단위)
    if (m) { trips.push({ name: name, year: year, mm: +m[1], dd: 1, region: m[2], windowDays: 31 }); return; }
  });
  return trips;
}
// 실사용일이 속한 여행(가장 늦게 시작한 매칭 여행).
//  연도 일치 필수 — 여행 탭은 특정 연도(2026)의 여행이므로 '다른 연도' 카드건은 매칭하지 않는다.
//  (월만 같고 연도가 다른 2025 비용이 2026 여행탭에 섞여 들어가던 문제 차단.)
function findTrip(trips, useDate) {
  const d = ymd(useDate); if (!d) return null;
  let best = null, bestStart = -1;
  trips.forEach(function (t) {
    if (t.year !== d.y) return;                         // 카드건 연도 ≠ 여행 연도 → 스킵
    const start = Date.UTC(t.year, t.mm - 1, t.dd);
    const end = start + (t.windowDays || CONFIG.TRIP_WINDOW_DAYS) * 86400000;
    const cur = Date.UTC(d.y, d.m - 1, d.d);
    if (cur >= start && cur <= end && start > bestStart) { best = t; bestStart = start; }
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
    // 해외 명세는 '승인일'(c[1]) 컬럼이 비어 있고 날짜는 '매입일'(c[0])에만 있음 → 매입일을 이용일로.
    rec = { postDate: c[0], useDate: c[0], card: c[4], user: c[5], saleType: c[6],
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

  // OTA는 카드-메일의 완전 결합이 가장 강한 근거다. 카드 주인 성향·가맹점 규칙보다 먼저
  // 판정하며, 완전 결합이 아닌 경우에는 자동 전기하지 않고 증거를 남긴 채 보류한다.
  if (hasKw(name, KW.OTA)) {
    const otaMatch = matchOtaEmail(emailIdx || [], rec);
    if (otaMatch.status === 'EXACT') {
      const hit = otaMatch.email;
      const acct = hit.item === '항공권' ? '여비교통비' : '숙박비';
      return route({ status: 'CONFIRM', account: acct, useDateOverride: hit.useDate,
                     bookingNo: hit.bookingNo, otaMatch: otaMatch,
                     note: otaLedgerNote(rec, otaMatch) }, rec, trips);
    }
    return { status: 'HOLD', otaMatch: otaMatch,
             reason: 'OTA 자동전기 보류 — ' + otaMatch.reason };
  }

  const profile = CONFIG.CARD_PROFILES[rec.last4] || CONFIG.DEFAULT_CARD_PROFILE;  // 카드 주인 성향 — 마지막 fallback에서만 사용

  // 0순위: 사람이 확정한 영구 규칙 (학습 결과). 두 번 묻지 않기 위함.
  const ruled = rules && rules[normMerchant(rec.merchant)];

  // 대장(가이드) 지급카드: 사용내역은 대장 전용 탭으로 직행(카드기명 규칙, 계정은 영구규칙 우선).
  // leaderSince(카드 전달일) 이전 사용분은 대장 구분 없이 일반 분류(예: 8831은 2026-07 엘레나 전달 — 그 전은 여행탭).
  if (profile.leaderTab && (!profile.leaderSince || (rec.useDate && rec.useDate >= profile.leaderSince))) {
    const acct = (ruled && ruled.account) || profile.travelAccount || '숙박비';
    return { status: 'CONFIRM', account: acct, tripName: profile.leaderTab, note: '대장카드:' + profile.owner };
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
    // 여행 지출은 학습대기로 보내지 않는다 — 해외 가맹점은 수백 개가 일회성이라 학습이 무의미.
    //  사전(키워드/업종)으로 추정하고, 사전에 없으면 식비로 기본 추정하되 '미상' 표시(노란 셀)로 사람이 훑게 한다.
    //  (단체 투어 특성상 미상 건 대부분은 단체식사 = 식비. 고액이면 표시가 더 눈에 띄게.)
    let account, uncertain = false, unote = '';
    if (hasKw(name, KW.LODGING)) account = '숙박비';
    else if (hasKw(name, KW.TRANSPORT)) account = '교통비';
    else if (hasKw(name, KW.ADMISSION)) account = '입장료';
    else if (hasKw(name, KW.FOOD_AREA)) account = '식비';
    else if (rec.bizCat && BIZCAT_TRAVEL[rec.bizCat]) account = BIZCAT_TRAVEL[rec.bizCat];
    else if (!rec.overseas) account = '식비';                       // 국내여행 기본
    else if (rec.krw <= OVERSEAS_FOOD_THRESHOLD) account = '식비';  // 해외 소액 기본
    else { account = '식비'; uncertain = true;                      // 해외 고액 미상 — 그래도 기록하고 표시만
           unote = '고액 미상 — 단체식사/현지숙박/전세버스 중 확인'; }
    return route({ status: 'CONFIRM', account: account, uncertain: uncertain,
                   note: unote || undefined }, rec, trips, trip);
  }

  // 비여행 국내 = 기타비용
  if (hasKw(name, KW.PG) || (rec.bizCat && /전자상거래|PG/.test(rec.bizCat))) {
    const hit = emailIdx && matchGenericPaymentEmail(emailIdx, rec);
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
  if (t) { v.tripName = t.name; v.project = t.region; return v; }
  // 여행탭을 못 찾음 — 과년도(TRIP_YEAR 이전) 결제는 미매칭에 쌓지 않고 보류.
  //  (2025년에 결제한 2026년 여행 숙박/항공 선결제인지 사람이 확인)
  const d = ymd(v.useDateOverride || rec.useDate);
  if (d && d.y < CONFIG.TRIP_YEAR) {
    return { status: 'HOLD', reason: d.y + '년 결제 — ' + CONFIG.TRIP_YEAR + '년 여행 선결제(숙박/항공)면 해당 여행탭 확인' };
  }
  v.tripName = rec.overseas ? '여행_미매칭' : CONFIG.ETC_TAB;
  return v;
}

// ─────────────────────────────────────────────────────────────
// AI 가맹점 추론 — 사전(키워드)에 없는 가맹점을 Gemini에게 일괄로 물어 분류.
//  "가맹점명을 검색해서 추론"의 실전 구현: 모델이 상호명(로마자 일본어·유럽권 포함)의 정체를 안다.
//  결과는 '분류규칙' 탭에 영구 저장(비고 AI:날짜) → 같은 가맹점은 평생 1번만 조회. 키 없으면 조용히 생략.
//  설정: https://aistudio.google.com/apikey 에서 무료 키 발급 →
//        Apps Script 편집기 ⚙프로젝트 설정 → 스크립트 속성 → GEMINI_API_KEY 추가.
// ─────────────────────────────────────────────────────────────
function aiKey() { return PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY'); }

// items: [{merchant, country, hint}] → { 정규화가맹점명: 계정과목 }
function aiClassifyMerchants(items) {
  const key = aiKey(); if (!key || !items.length) return {};
  const list = items.map(function (it, i) {
    return (i + 1) + '. ' + it.merchant + (it.country ? ' [' + it.country + ']' : '') + (it.hint ? ' (' + it.hint + ')' : '');
  }).join('\n');
  const prompt =
    '아래는 단체여행사 법인카드 명세의 가맹점명 목록이다(일본 로마자 표기·유럽 상호 포함). ' +
    '각 가맹점이 실제로 무엇인지(체인·상호·업종) 아는 대로 추론해 반드시 다음 중 하나로 분류하라:\n' +
    '식비(식당·카페·이자카야·마트·편의점·시장), 숙박비(호텔·료칸·펜션·민박), ' +
    '교통비(렌터카·주유·철도·버스·페리·주차·고속도로·곤돌라·리프트), 입장료(관광지·온천시설·박물관·정원·사찰), ' +
    '여비교통비(항공사·항공권 발권), 미상(정말 알 수 없을 때만).\n' +
    '설명 없이 JSON 배열만 출력: [{"n":1,"account":"식비"},{"n":2,"account":"숙박비"}]\n\n' + list;
  const res = UrlFetchApp.fetch(
    'https://generativelanguage.googleapis.com/v1beta/models/' + CONFIG.AI_MODEL + ':generateContent?key=' + key,
    { method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      payload: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }],
                                generationConfig: { temperature: 0 } }) });
  if (res.getResponseCode() !== 200) { Logger.log('AI 호출 실패: ' + res.getContentText().slice(0, 300)); return {}; }
  try {
    const text = JSON.parse(res.getContentText()).candidates[0].content.parts[0].text;
    const arr = JSON.parse(text.replace(/^```(json)?\s*|```\s*$/g, '').trim());
    const VALID = { '식비': 1, '숙박비': 1, '교통비': 1, '입장료': 1, '여비교통비': 1 };
    const out = {};
    arr.forEach(function (o) {
      const it = items[o.n - 1];
      if (it && VALID[o.account]) out[normMerchant(it.merchant)] = o.account;
    });
    return out;
  } catch (e) { Logger.log('AI 응답 파싱 실패: ' + e); return {}; }
}

// 정산 전 프리패스 — 색상과 무관하게 사전·규칙·학습맵 어디에도 없는 가맹점을 모아
//  Gemini로 일괄 분류하고 '분류규칙'에 저장 + 이번 정산의 rules 맵에 즉시 반영.
function aiPrepassRules(ledgerSS, kb, rules) {
  if (!aiKey()) return;                                    // 키 없으면 사전 추론만으로 진행
  const seen = {}, cand = [];
  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openFirst(src); if (!sh) return;
    const rng = sh.getDataRange();
    const values = rng.getValues();
    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      const rec = parseRaw(values[r]);
      if (!rec || !rec.merchant || rec.krw < 0) continue;
      const dy = ymd(rec.useDate);
      if (dy && dy.y < CONFIG.TRIP_YEAR && !isBookingLike(rec)) continue;   // 과년도 일반건은 어차피 범위외
      const nm = normMerchant(rec.merchant);
      if (seen[nm] || rules[nm] || kb[nm]) continue;
      const up = rec.merchant.toUpperCase();
      if (hasKw(up, KW.OTA) || hasKw(up, KW.AIR) || hasKw(up, KW.LODGING) || hasKw(up, KW.TRANSPORT) ||
          hasKw(up, KW.ADMISSION) || hasKw(up, KW.FOOD_AREA) || hasKw(up, KW.PG)) continue;  // 사전이 이미 앎
      if (!rec.overseas && rec.bizCat && (BIZCAT_TRAVEL[rec.bizCat] || BIZCAT_ETC[rec.bizCat])) continue; // 업종으로 해결됨
      seen[nm] = 1;
      cand.push({ merchant: rec.merchant, country: rec.country || (rec.overseas ? '해외' : '국내'), hint: rec.bizCat || '' });
    }
  });
  if (!cand.length) return;
  const sheet = ensureTab(ledgerSS, CONFIG.RULES_TAB, RULES_HEADER);
  let learned = 0;
  const rows = [];
  for (let i = 0; i < cand.length && i < 300; i += 60) {   // 60개씩 배치, 회당 최대 300 가맹점(시간 보호)
    const map = aiClassifyMerchants(cand.slice(i, i + 60));
    cand.slice(i, i + 60).forEach(function (c) {
      const nm = normMerchant(c.merchant), acct = map[nm];
      if (!acct) return;
      rules[nm] = { account: acct, kind: '여행' };
      rows.push([c.merchant, acct, '여행', 'AI:' + today()]);
      learned++;
    });
  }
  if (rows.length) sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, RULES_HEADER.length).setValues(rows);
  Logger.log('AI 가맹점 분류: 후보 ' + cand.length + '개 중 ' + learned + '건 규칙 추가(분류규칙 탭, 비고 AI)');
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
const REVIEW_HEADER = ['가맹점', '업종', '예시일자', '금액', '보류사유', '계정과목(입력)',
                       '구분(여행/기타)', '카드거래ID'];

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

function ensureReviewSchema(sh) {
  sh.getRange(1, 1, 1, REVIEW_HEADER.length).setValues([REVIEW_HEADER]).setFontWeight('bold');
}
// HOLD를 가맹점이 아니라 card_event_id별로 1건씩 보존한다.
function flushReview(ss, holds) {
  const keys = Object.keys(holds);
  if (!keys.length) return;
  const sh = ensureTab(ss, CONFIG.REVIEW_TAB, REVIEW_HEADER);
  ensureReviewSchema(sh);
  const existingIds = new Set();
  const cur = sh.getDataRange().getValues();
  for (let r = 1; r < cur.length; r++) if (cur[r][7]) existingIds.add(String(cur[r][7]));
  keys.forEach(function (k) {
    const h = holds[k];
    if (existingIds.has(h.eventId)) return;
    sh.appendRow([h.merchant, h.bizCat, h.date, h.krw || '', h.reason, '', '', h.eventId]);
    existingIds.add(h.eventId);
  });
}

// 학습대기에서 계정 채워진 행 → 분류규칙으로 승격(그 후 자동 분류)
function promoteReviewToRules() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const rv = ss.getSheetByName(CONFIG.REVIEW_TAB);
  if (!rv) { toast('학습대기 탭이 없습니다.'); return; }
  ensureReviewSchema(rv);
  const rules = ensureTab(ss, CONFIG.RULES_TAB, RULES_HEADER);
  const v = rv.getDataRange().getValues();
  let promoted = 0;
  const remain = [REVIEW_HEADER];
  for (let r = 1; r < v.length; r++) {
    const merchant = v[r][0], account = String(v[r][5] || '').trim(), kind = String(v[r][6] || '').trim();
    if (account) { rules.appendRow([merchant, account, kind, '학습:' + new Date().toISOString().slice(0, 10)]); promoted++; }
    else {
      const row = v[r].slice(0, REVIEW_HEADER.length);
      while (row.length < REVIEW_HEADER.length) row.push('');
      remain.push(row);                                   // 아직 미입력 → 대기 유지
    }
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
// 3단계 — 실탭 직접 전기 (사람이 하던 '여행탭에 분류 복사' 그대로)
// ─────────────────────────────────────────────────────────────
// 실탭에서 '지출 내용' 헤더행·컬럼 위치·총 금액 행을 찾는다. (0-기준 인덱스)
function findExpenseSection(sheet) {
  const v = sheet.getDataRange().getValues();
  let hdr = -1;
  for (let r = 0; r < v.length; r++) {
    const has = function (kw) { return v[r].some(function (x) { return String(x).indexOf(kw) >= 0; }); };
    if (has('증빙유형') && has('금액')) { hdr = r; break; }
  }
  if (hdr < 0) return null;
  const H = v[hdr].map(function (x) { return String(x); });
  const find = function (kw) { return H.findIndex(function (h) { return h.indexOf(kw) >= 0; }); };
  const ci = { date: find('거래일자'), item: find('항목'), acct: find('내용'), card: find('증빙유형'), amt: find('금액') };
  if (ci.amt < 0) return null;
  let sumRow = -1, lastData = hdr;
  for (let r = hdr + 1; r < v.length; r++) {
    if (v[r].some(function (x) { return /총\s*금액|합\s*계/.test(String(x)); })) { sumRow = r; break; }
    if (String(v[r].join('')).trim()) lastData = r;
  }
  return { hdr: hdr, ci: ci, sumRow: sumRow, lastData: lastData };
}
// 전기 대상 탭 정보를 로드(캐시). 실탭이 있으면 지출 섹션에 직접, 없으면(여행_미매칭 등) 7열 시트 생성.
function getTarget(cache, ss, tabName) {
  if (cache[tabName]) return cache[tabName];
  let sheet = ss.getSheetByName(tabName);
  let t;
  if (!sheet) {
    sheet = ss.insertSheet(tabName);
    sheet.appendRow(CONFIG.LEDGER_HEADER);
    sheet.getRange(1, 1, 1, CONFIG.LEDGER_HEADER.length).setFontWeight('bold');
    t = { sheet: sheet, mode: 'plain', existing: [], rows: [] };
  } else {
    const sec = findExpenseSection(sheet);
    if (!sec) t = { sheet: sheet, mode: 'none', existing: [], rows: [] };          // 지출 섹션 못 찾음 → 전기 보류
    else t = { sheet: sheet, mode: 'section', sec: sec, existing: extractLedgerRecords(sheet), rows: [] };
  }
  cache[tabName] = t;
  return t;
}
// card_event_id를 장부 레코드의 멱등키로 사용해 전기 후보를 큐에 넣는다.
// 색상은 결과 표시일 뿐, 처리 여부 판정에 사용하지 않는다.
function queueLedgerPosting(rec, decision, targets, ledgerSS) {
  const tabName = decision.tripName || '여행_미매칭';
  const t = getTarget(targets, ledgerSS, tabName);
  if (t.mode === 'none') {
    return { ok: false, duplicate: false, tab: tabName,
             reason: '전기 보류 — "' + tabName + '" 탭에서 지출 섹션 헤더를 찾지 못함' };
  }
  const row7 = buildLedgerRow(rec, decision);
  const cand = { date: row7[0], merchant: String(row7[1] || ''), card: rec.last4,
                 amount: row7[4], bookingNo: digits(row7[5]), eventId: rec.cardEventId || '' };
  const duplicate = t.existing.some(function (e) { return recordsMatch(cand, e); }) ||
                    t.rows.some(function (q) { return recordsMatch(cand, q.cand); });
  if (!duplicate) t.rows.push({ row7: row7, cand: cand, uncertain: !!decision.uncertain });
  return { ok: true, duplicate: duplicate, tab: tabName };
}
// 모아둔 행을 실탭에 한 번에 기록.
//  - section: '총 금액' 합계 범위가 자동 확장되도록 마지막 데이터행 '앞'에 삽입(데이터 없으면 합계행 앞).
//  - 예약번호·비고는 실탭에 열이 없으므로 '항목' 셀 노트로 보존('자동 전기' 표식 겸용).
function flushTarget(t) {
  const n = t.rows.length;
  if (!n || t.mode === 'none') return;
  if (t.mode === 'plain') {
    const start = t.sheet.getLastRow() + 1;
    t.sheet.getRange(start, 1, n, CONFIG.LEDGER_HEADER.length)
      .setValues(t.rows.map(function (q) { return q.row7; }));
    t.sheet.getRange(start, 2, n, 1).setNotes(t.rows.map(function (q) {
      return [['자동 전기', q.row7[5] ? '예약번호 ' + q.row7[5] : '', q.row7[6] || ''].filter(Boolean).join(' · ')];
    }));
    t.rows.forEach(function (q, i) {                       // 미상 추정은 내용(3열)만 노랗게
      if (q.uncertain) t.sheet.getRange(start + i, 3).setBackground('#fff2cc');
    });
    return;
  }
  const sec = t.sec;
  let at;                                                   // 1-기준 삽입 위치
  if (sec.sumRow >= 0 && sec.lastData > sec.hdr) at = sec.lastData + 1;   // 마지막 데이터행 앞(합계 범위 내부)
  else if (sec.sumRow >= 0) at = sec.sumRow + 1;                          // 섹션 비어 있음 → 합계행 앞
  else at = Math.max(t.sheet.getLastRow(), sec.lastData + 1) + 1;         // 합계행 없음 → 섹션 끝에 덧붙임
  if (sec.sumRow >= 0) t.sheet.insertRowsBefore(at, n);
  const ci = sec.ci;
  const put = function (col, idx) {
    if (col < 0) return;
    t.sheet.getRange(at, col + 1, n, 1).setValues(t.rows.map(function (q) { return [q.row7[idx]]; }));
  };
  put(ci.date, 0); put(ci.item, 1); put(ci.acct, 2); put(ci.card, 3); put(ci.amt, 4);
  if (ci.item >= 0) {
    t.sheet.getRange(at, ci.item + 1, n, 1).setNotes(t.rows.map(function (q) {
      return [['자동 전기', q.row7[5] ? '예약번호 ' + q.row7[5] : '', q.row7[6] || ''].filter(Boolean).join(' · ')];
    }));
  }
  // 자신 없는 추정(미상→식비 등)은 '내용' 셀만 노랗게 — 사람이 여행탭에서 노란 셀만 훑으면 됨.
  if (ci.acct >= 0) {
    t.rows.forEach(function (q, i) {
      if (q.uncertain) t.sheet.getRange(at + i, ci.acct + 1).setBackground('#fff2cc');
    });
  }
}
// 전기 한 줄(배열) 생성 — 실제 장부 '지출 내용' 형식.
function buildLedgerRow(rec, v) {
  const useDate = v.useDateOverride || rec.useDate;
  const note = [v.note, rec.overseas ? ((rec.currency || '') + ' ' + (rec.foreign || '')).trim() : '',
                rec.format, rec.cardEventId ? '카드거래ID:' + rec.cardEventId : ''].filter(Boolean).join(' · ');
  return [
    useDate,                                       // 거래일자(실사용일)
    rec.merchant,                                  // 항목(거래처)
    v.account,                                     // 내용(계정과목)
    rec.last4 + (rec.user ? '/' + rec.user : ''),  // 증빙유형
    rec.krw,                                       // 금액
    v.bookingNo || '',                             // 예약번호
    note,                                          // 비고
  ];
}
// 정산 롤백 — 엔진이 실탭에 넣은 행('자동 전기' 노트 표식)을 전부 삭제하고 처음 상태로.
//  수기 행(노트 없음)은 절대 건드리지 않는다. 여행_미매칭 탭 삭제, 학습대기 리셋, 엔진 색 초기화까지.
//  오분류 발견 시 이걸로 되돌리고 → 코드/규칙 고친 뒤 → 정산 실행을 다시 돌리면 된다.
function rollbackAutoPostings() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  let removed = 0;
  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    if (name === '여행_미매칭') { ss.deleteSheet(sh); return; }          // 엔진 생성 탭 → 통째 삭제
    if (name === CONFIG.REVIEW_TAB) {                                    // 학습대기 → 새 형식으로 리셋
      sh.clear(); sh.appendRow(REVIEW_HEADER);
      sh.getRange(1, 1, 1, REVIEW_HEADER.length).setFontWeight('bold');
      return;
    }
    if (sh.getLastRow() < 1) return;
    const notes = sh.getDataRange().getNotes();
    for (let r = notes.length - 1; r >= 0; r--) {                        // 아래부터 지워야 행번호 안 밀림
      if (notes[r].some(function (n) { return String(n).indexOf('자동 전기') === 0; })) {
        sh.deleteRow(r + 1); removed++;
      }
    }
  });
  resetRawColors();
  toast('롤백 완료 — 자동 전기 행 ' + removed + '개 삭제, 여행_미매칭 탭 제거, 학습대기 리셋, 엔진 색 초기화.');
}

// 과거 방식의 잔재인 _C 비교탭을 한 번에 삭제(실탭 직접 전기로 전환 후 정리용).
//  삭제 전 '비교탭 정리'로 수기와 대조해 남은 신규분이 없는지 확인 권장.
function deleteCompareTabs() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  let n = 0;
  ss.getSheets().forEach(function (sh) {
    if (/_C$/.test(sh.getName())) { ss.deleteSheet(sh); n++; }
  });
  toast('_C 비교탭 ' + n + '개 삭제 완료.');
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
                currency: String(row[col.currency] || '').toUpperCase(), card: row[col.card],
                account: row[col.account], bookingNo: String(row[col.bookingNo] || ''),
                messageId: String(row[col.messageId] || ''), rowNumber: r + 1 });
  }
  return rows;
}
// 일반 PG/페이 결제용 보조 매칭. OTA 메일은 아래의 엄격한 matchOtaEmail만 사용한다.
function matchGenericPaymentEmail(index, rec) {
  const amt = Math.round(rec.krw);
  const recPay = dateMs(rec.useDate);   // 카드 '이용일' = 결제 발생일
  let best = null, bestDiff = Infinity;
  index.forEach(function (e) {
    if (e.type === 'refund' || e._used || emailOtaBrand(e)) return;
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

// ─────────────────────────────────────────────────────────────
// OTA 카드 ↔ 결제메일 결합
//
// 자동 전기는 EXACT만 허용한다. EXACT는 다음을 모두 충족해야 한다.
//   1) 카드와 메일의 OTA 브랜드가 동일
//   2) 같은 통화의 결제금액이 정확히 동일
//   3) 메일 결제일과 카드 이용일이 ±3일 이내
//   4) 메일의 카드 끝 4자리가 있으면 카드 원본과 동일
//   5) 예약번호·실사용일이 모두 있고, EXACT 후보가 정확히 한 건
// 나머지는 PROBABLE/HOLD로 감사표에만 남기며 이메일을 소비하지 않는다.
// ─────────────────────────────────────────────────────────────
function emailOtaBrand(e) {
  const fromMerchant = otaBrand(e && e.merchant);
  if (fromMerchant) return fromMerchant;
  const source = String((e && e.source) || '').toUpperCase();
  if (source.indexOf('TRIP') >= 0) return 'TRIPCOM';
  if (source.indexOf('AGODA') >= 0) return 'AGODA';
  if (source.indexOf('BOOKING') >= 0) return 'BOOKING';
  if (source.indexOf('MYTRIP') >= 0) return 'MYTRIP';
  return '';
}
function exactOtaAmount(e, rec) {
  const ec = String(e.currency || '').toUpperCase();
  const rc = String(rec.currency || '').toUpperCase();
  const emailAmount = Math.abs(num(e.amount));
  if (!(emailAmount > 0)) return '';
  if (ec === 'KRW') {
    return Math.round(emailAmount) === Math.round(Math.abs(num(rec.krw))) ? '원화금액 정확' : '';
  }
  // 해외승인 원본에 같은 통화의 외화금액이 있는 경우에만 외화로 정확 대조한다.
  if (ec && ec === rc && num(rec.foreign) > 0 && Math.abs(emailAmount - Math.abs(num(rec.foreign))) < 0.005) {
    return ec + ' 외화금액 정확';
  }
  return '';
}
function similarOtaAmount(e, rec) {
  const ec = String(e.currency || '').toUpperCase();
  const rc = String(rec.currency || '').toUpperCase();
  let cardAmount = 0;
  if (ec === 'KRW') cardAmount = Math.abs(num(rec.krw));
  else if (ec && ec === rc && num(rec.foreign) > 0) cardAmount = Math.abs(num(rec.foreign));
  if (!(cardAmount > 0)) return false;
  const emailAmount = Math.abs(num(e.amount));
  return emailAmount > 0 && Math.abs(emailAmount - cardAmount) <= Math.max(2, cardAmount * 0.01);
}
function paymentDateDiffDays(e, rec) {
  const emailDate = dateMs(e.paidDate), cardDate = dateMs(rec.useDate);
  if (emailDate == null || cardDate == null) return null;
  return Math.abs(emailDate - cardDate) / 86400000;
}
function emailCardEvidence(e, rec) {
  const groups = String(e.card || '').match(/\d{4}/g) || [];
  if (!groups.length) return { ok: true, evidence: '메일 카드끝4자리 미기재' };
  const last4 = groups[groups.length - 1];
  return last4 === rec.last4
    ? { ok: true, evidence: '카드끝4자리 정확' }
    : { ok: false, evidence: '메일 카드끝4자리 불일치' };
}
function otaCandidateEvidence(e, rec) {
  const brand = otaBrand(rec.merchant);
  const dateDiff = paymentDateDiffDays(e, rec);
  const card = emailCardEvidence(e, rec);
  return {
    brand: brand && brand === emailOtaBrand(e),
    amount: exactOtaAmount(e, rec),
    similarAmount: similarOtaAmount(e, rec),
    dateDiff: dateDiff,
    date: dateDiff != null && dateDiff <= CONFIG.OTA_PAYMENT_DATE_TOL_DAYS,
    card: card,
    hasBooking: !!digits(e.bookingNo),
    hasUseDate: !!e.useDate,
    completeBooking: !!(digits(e.bookingNo) && e.useDate),
  };
}
function otaSignals(e, evidence) {
  const out = ['브랜드=' + emailOtaBrand(e)];
  if (evidence.amount) out.push(evidence.amount);
  else if (evidence.similarAmount) out.push('금액 근접');
  if (evidence.dateDiff != null) out.push('결제일 ' + evidence.dateDiff + '일');
  out.push(evidence.card.evidence);
  if (digits(e.bookingNo)) out.push('예약번호');
  if (e.useDate) out.push('실사용일');
  return out.join('+');
}
function otaMatchResult(status, e, evidence, candidateCount, reason) {
  return {
    status: status, email: e || null, evidence: evidence || null,
    candidateCount: candidateCount || 0, reason: reason || '',
  };
}
function matchOtaEmail(index, rec) {
  const brand = otaBrand(rec.merchant);
  if (!brand) return otaMatchResult('HOLD', null, null, 0, '카드 OTA 브랜드를 인식하지 못함');

  const exact = [], probable = [], reserved = [];
  (index || []).forEach(function (e) {
    if (!e || e.type !== 'charge' || emailOtaBrand(e) !== brand) return;
    const evidence = otaCandidateEvidence(e, rec);
    if (!evidence.card.ok || !evidence.date || (!evidence.amount && !evidence.similarAmount)) return;
    const candidate = { email: e, evidence: evidence };
    if (e._used && evidence.amount && evidence.completeBooking) { reserved.push(candidate); return; }
    if (e._used) return;
    if (evidence.amount && evidence.completeBooking) exact.push(candidate);
    else probable.push(candidate);
  });

  if (exact.length === 1) {
    exact[0].email._used = true;  // 한 OTA 메일은 한 카드 원본에만 결합
    return otaMatchResult('EXACT', exact[0].email, exact[0].evidence, 1, '완전 결합');
  }
  if (exact.length > 1) {
    return otaMatchResult('HOLD', null, null, exact.length, '완전 결합 후보가 ' + exact.length + '건이라 유일하지 않음');
  }
  if (reserved.length) {
    return otaMatchResult('HOLD', null, null, reserved.length, '완전 결합 메일이 다른 카드 원본에 이미 연결됨');
  }
  if (probable.length === 1) {
    return otaMatchResult('PROBABLE', probable[0].email, probable[0].evidence, 1,
                          '후보는 있으나 ' + missingOtaEvidence(probable[0].evidence));
  }
  if (probable.length > 1) {
    return otaMatchResult('HOLD', null, null, probable.length, '추정 후보가 ' + probable.length + '건이라 유일하지 않음');
  }
  return otaMatchResult('HOLD', null, null, 0, '동일 브랜드·금액·결제일 조건의 메일 없음');
}
function missingOtaEvidence(evidence) {
  const missing = [];
  if (!evidence.amount) missing.push('정확한 금액');
  if (!evidence.completeBooking) {
    if (!evidence.hasBooking) missing.push('예약번호');
    if (!evidence.hasUseDate) missing.push('실사용일');
  }
  return missing.length ? missing.join('·') : '완전 결합 요건';
}
function otaLedgerNote(rec, match) {
  const e = match.email;
  return ['OTA EXACT', otaSignals(e, match.evidence),
          'RAW:' + rec.rawRef, '메일:' + (e.messageId || ('row-' + e.rowNumber))].join(' · ');
}

// ─────────────────────────────────────────────────────────────
// 불변 카드거래원장
// ─────────────────────────────────────────────────────────────
const CARD_EVENT_HEADER = ['카드거래ID', '원본파일ID', '원본시트ID', '원본행', '원본지문', '상태',
                           '카드끝4', '이용일', '매입일', '가맹점', '원화금액', '통화', '외화금액',
                           '거래구분', '전기탭', '계정과목', '예약번호', '사유', '원본JSON', '갱신시각'];
function cardEventIdFromText(text) {
  const m = String(text || '').match(/(?:CARD_EVENT_ID|카드거래ID|카드거래)\s*[:=]?\s*(CE-[A-Za-z0-9-]+)/i);
  return m ? m[1] : '';
}
function rawNoteWithEvent(existing, eventId, status) {
  const keep = String(existing || '').split(/\r?\n/).filter(function (line) {
    return line && !/^(?:CARD_EVENT_ID|ENGINE_STATUS)\s*:/i.test(line.trim());
  });
  const out = ['CARD_EVENT_ID:' + eventId];
  if (status) out.push('ENGINE_STATUS:' + status);
  return out.concat(keep).join('\n');
}
function clearRawEngineStatus(existing) {
  return String(existing || '').split(/\r?\n/).filter(function (line) {
    return line && !/^ENGINE_STATUS\s*:/i.test(line.trim());
  }).join('\n');
}
function stableRawValue(v) {
  if (v instanceof Date) return Utilities.formatDate(v, 'Asia/Seoul', "yyyy-MM-dd'T'HH:mm:ss");
  return String(v == null ? '' : v).trim();
}
function cardEventFingerprint(src, rawRow) {
  const canonical = [String(src.id || '')].concat(rawRow.map(stableRawValue)).join('\u001f');
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, canonical, Utilities.Charset.UTF_8);
  return digest.map(function (b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
}
function loadCardEventJournal(ss) {
  const out = { byId: {}, byFingerprint: {} };
  const sh = ss.getSheetByName(CONFIG.CARD_EVENT_TAB);
  if (!sh || sh.getLastRow() < 2) return out;
  const values = sh.getDataRange().getValues();
  const col = {}; values[0].forEach(function (h, i) { col[String(h)] = i; });
  for (let r = 1; r < values.length; r++) {
    const id = String(values[r][col['카드거래ID']] || '');
    const fp = String(values[r][col['원본지문']] || '');
    if (!id) continue;
    out.byId[id] = true;
    if (fp) (out.byFingerprint[fp] = out.byFingerprint[fp] || []).push(id);
  }
  return out;
}
function resolveCardEventId(rawNote, fingerprint, journal, claimed) {
  let id = cardEventIdFromText(rawNote);
  if (id && claimed[id]) id = '';                         // 복사된 노트의 ID 충돌 방지
  if (!id) {
    const reusable = (journal.byFingerprint[fingerprint] || []).filter(function (candidate) { return !claimed[candidate]; });
    if (reusable.length === 1) id = reusable[0];          // RAW 재다운로드로 노트가 사라진 경우 복구
  }
  if (!id) id = 'CE-' + Utilities.getUuid();
  claimed[id] = true;
  return id;
}
function rawRowJson(rawRow) {
  return JSON.stringify(rawRow.map(stableRawValue));
}
function makeCardEvent(src, sheet, rowNumber, fingerprint, eventId, rec, rawRow,
                       state, postingTab, account, bookingNo, reason) {
  rec = rec || {};
  return {
    eventId: eventId, sourceId: String(src.id || ''), sheetId: String(sheet.getSheetId()), rowNumber: rowNumber,
    fingerprint: fingerprint, state: state, card4: rec.last4 || '', useDate: rec.useDate || '',
    postDate: rec.postDate || '', merchant: rec.merchant || '', krw: num(rec.krw), currency: rec.currency || '',
    foreign: num(rec.foreign), saleType: rec.saleType || '', postingTab: postingTab || '', account: account || '',
    bookingNo: bookingNo || '', reason: reason || '', rawJson: rawRowJson(rawRow), updatedAt: new Date().toISOString(),
  };
}
function cardEventToRow(e) {
  return [e.eventId, e.sourceId, e.sheetId, e.rowNumber, e.fingerprint, e.state, e.card4, e.useDate,
          e.postDate, e.merchant, e.krw, e.currency, e.foreign, e.saleType, e.postingTab, e.account,
          e.bookingNo, e.reason, e.rawJson, e.updatedAt];
}
function upsertCardEvents(ss, events) {
  if (!events.length) return 0;
  const sh = ensureTab(ss, CONFIG.CARD_EVENT_TAB, CARD_EVENT_HEADER);
  const values = sh.getDataRange().getValues();
  values[0] = CARD_EVENT_HEADER.slice();
  for (let r = 1; r < values.length; r++) {
    values[r] = values[r].slice(0, CARD_EVENT_HEADER.length);
    while (values[r].length < CARD_EVENT_HEADER.length) values[r].push('');
  }
  const byId = {};
  for (let r = 1; r < values.length; r++) if (values[r][0]) byId[String(values[r][0])] = r;
  events.forEach(function (event) {
    const row = cardEventToRow(event);
    const at = byId[event.eventId];
    if (at != null) values[at] = row;
    else { byId[event.eventId] = values.length; values.push(row); }
  });
  sh.getRange(1, 1, values.length, CARD_EVENT_HEADER.length).setValues(values);
  sh.getRange(1, 1, 1, CARD_EVENT_HEADER.length).setFontWeight('bold');
  return events.length;
}
function reviewItem(rec, eventId, reason) {
  return { eventId: eventId, merchant: rec.merchant || '', bizCat: rec.bizCat || '',
           date: rec.useDate || '', krw: rec.krw || '', reason: reason || '' };
}
function rawRef(src, rowNumber) {
  // 원본 파일 ID + 행번호는 카드 원본의 안정적인 식별자다. 승인번호·금액은 중복될 수 있으므로 쓰지 않는다.
  return String(src.id || 'RAW') + ':' + rowNumber;
}
function otaAuditRow(rec, match) {
  const e = match.email || {};
  return [rec.rawRef, match.status, rec.useDate, rec.merchant, rec.krw, rec.currency || 'KRW',
          e.source || '', e.messageId || (e.rowNumber ? 'row-' + e.rowNumber : ''), e.paidDate || '',
          e.bookingNo || '', e.useDate || '',
          match.evidence ? otaSignals(e, match.evidence) : '', match.candidateCount || 0,
          match.reason || '', today()];
}
function upsertOtaAudit(ss, rows) {
  if (!rows.length) return;
  const sh = ensureTab(ss, CONFIG.OTA_AUDIT_TAB, OTA_AUDIT_HEADER);
  const values = sh.getDataRange().getValues();
  const byRawRef = {};
  for (let r = 1; r < values.length; r++) if (values[r][0]) byRawRef[String(values[r][0])] = r;
  rows.forEach(function (row) {
    const at = byRawRef[row[0]];
    if (at != null) values[at] = row;
    else { byRawRef[row[0]] = values.length; values.push(row); }
  });
  sh.getRange(1, 1, values.length, OTA_AUDIT_HEADER.length).setValues(values);
  sh.getRange(1, 1, 1, OTA_AUDIT_HEADER.length).setFontWeight('bold');
}
// 이미 색칠된 RAW까지 포함해 OTA 결합 상태를 다시 계산한다. 장부에는 전기하지 않고 감사표만 갱신한다.
function auditOtaMatches() {
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const emailIdx = loadEmailIndex() || [];
  const rows = [];
  const counts = { EXACT: 0, PROBABLE: 0, HOLD: 0 };
  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openFirst(src); if (!sh) return;
    const values = sh.getDataRange().getValues();
    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      const rec = parseRaw(values[r]);
      if (!rec || !hasKw(String(rec.merchant || '').toUpperCase(), KW.OTA) || rec.krw < 0) continue;
      rec.rawRef = rawRef(src, r + 1);
      const match = matchOtaEmail(emailIdx, rec);
      counts[match.status]++;
      rows.push(otaAuditRow(rec, match));
    }
  });
  upsertOtaAudit(ss, rows);
  toast('OTA 결합 점검 — EXACT ' + counts.EXACT + ' / PROBABLE ' + counts.PROBABLE + ' / HOLD ' + counts.HOLD);
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
function today() { return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd'); }
function isWhite(hex) { const h = String(hex || '').toLowerCase(); return h === '' || h === '#ffffff' || h === '#fff' || h === 'white'; }
function setRowColor(sh, rowNum, color) { sh.getRange(rowNum, 1, 1, sh.getLastColumn()).setBackground(color); }
function noteCell(sh, rowNum, text) { sh.getRange(rowNum, 1).setNote(text); }
function toast(msg) {
  // 편집기에서 실행하면(독립형) 토스트 팝업을 못 띄움 → 실행 로그에 출력.
  //  시트 메뉴에서 실행될 때만 우측 하단 팝업 시도.
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (ss) { ss.toast(msg, '비용처리', 8); return; }
  } catch (e) {}
  Logger.log(msg);
}
