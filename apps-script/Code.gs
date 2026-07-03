/**
 * 숲길여행 비용처리 자동화 — Apps Script 엔진 (단일 계정 kkokkohero6 실행)
 *
 * 진입점: onOpen() 메뉴 → runReconciliation() 이 2·3·4단계 수행(멱등).
 * RAW 3개 시트는 서로 다른 3개 포맷이며 detectFormat() 으로 자동 감지한다.
 *
 * 열 인덱스는 실제 샘플(2026 데이터) 기준. 헤더 행 수만 시트별로 확인해 맞추면 됨.
 */

const CONFIG = {
  RAW_SOURCES: [
    { id: '1nYxV9UM9rMRjEhnhdc8evE2xb3z6RxgWd5f5ci6PPdE', sheetName: null },
    { id: '11jjbN882fdQDcIexuzX-l0yBw02VgIna1jhnJNMkN_o', sheetName: null },
    { id: '1SiOftobiUJSxSdvBEKL9AmxgQkjzkzDjs2O_8SBoyh4', sheetName: null },
  ],
  LEARN_LEDGER:  { id: '1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8', sheetName: null },
  TARGET_LEDGER: { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: null },
  STAGING:       { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: '메일수집' },

  HEADER_ROWS: 1, // 시트에 헤더가 없으면 0 (샘플엔 헤더 없이 데이터부터인 것으로 보임 → 확인)

  // 장부(원장) 출력 열 — 완료장부 계승(적요=용도_날짜, 예약번호 조인) + 명시적 계정/실사용일 추가.
  // 필수(본질): 거래일자·계정과목·적요·금액·가맹점. 나머지는 부가.
  LEDGER_HEADER: ['거래일자', '결제일', '계정과목', '적요', '금액', '가맹점', '예약번호',
                  '여행/프로젝트', '결제수단', '국내/해외', '통화', '현지금액', '상태', '출처'],

  COLOR: { DONE: '#d9ead3', CANCEL: '#f4cccc', NONE: '#ffffff' },

  // 국내 카드 소유자(마지막 4자리). ※ 사용자가 말한 '3320'은 실제 데이터상 '3820'으로 보임 → 확인.
  DOMESTIC_OWNER_CARD: '3820', // 김주형(김*형)
};

// 분류 키워드
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

// 국내 '기타비용'(3820 김주형·비여행): 업종 → 표준(IFRS) 계정과목
const BIZCAT_ETC = {
  '커피/음료전문점': '회의비',
  '휴게음식점': '복리후생비',
  '일반음식점': '복리후생비',
  '한식': '복리후생비', '중식': '복리후생비', '일식': '복리후생비', '양식': '복리후생비',
  '슈퍼마켓': '소모품비',
  '편의점': '소모품비',
  '용역서비스업': '지급수수료',
};
// 국내 '여행'(그 외 카드·아슬란): 업종 → 여행 세부 계정
const BIZCAT_TRAVEL = {
  '커피/음료전문점': '식비',
  '휴게음식점': '식비', '일반음식점': '식비',
  '한식': '식비', '중식': '식비', '일식': '식비', '양식': '식비',
  '슈퍼마켓': '식비', '편의점': '식비',
  '주유소': '교통비', '용역서비스업': '교통비',
};

const OVERSEAS_FOOD_THRESHOLD = 100000;

// ─────────────────────────────────────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi().createMenu('비용처리')
    .addItem('정산 실행 (미분류만)', 'runReconciliation')
    .addItem('학습맵 다시 만들기', 'rebuildKnowledgeBase')
    .addToUi();
}

// ─────────────────────────────────────────────────────────────
// 메인 — 멱등: 흰색(미분류) 행만 처리
// ─────────────────────────────────────────────────────────────
function runReconciliation() {
  const kb = buildKnowledgeBase();
  const ledger = openSheet(CONFIG.TARGET_LEDGER);
  ensureLedgerHeader(ledger);
  const existing = loadLedgerKeys(ledger);
  const emailIdx = loadEmailIndex();          // 메일수집 스테이징(있으면) 인덱스
  const stats = { done: 0, cancel: 0, hold: 0 };

  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openSheet(src);
    if (!sh) return;
    const rng = sh.getDataRange();
    const values = rng.getValues();
    const bg = rng.getBackgrounds();

    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      if (!isWhite(bg[r][0])) continue;
      const rec = parseRaw(values[r]);
      if (!rec || (!rec.merchant && !rec.krw)) continue;

      const v = classify(rec, kb, emailIdx);

      if (v.status === 'CANCEL') {
        setRowColor(sh, r + 1, CONFIG.COLOR.CANCEL);
        stats.cancel++;
      } else if (v.status === 'CONFIRM') {
        const key = makeKey(rec.useDate, rec.merchant, rec.krw);
        if (!existing.has(key)) { appendToLedger(ledger, rec, v); existing.add(key); }
        setRowColor(sh, r + 1, CONFIG.COLOR.DONE);
        stats.done++;
      } else {
        noteCell(sh, r + 1, v.reason);
        stats.hold++;
      }
    }
  });

  toast('정산 완료 — 확정 ' + stats.done + ' / 취소 ' + stats.cancel + ' / 보류 ' + stats.hold);
}

// ─────────────────────────────────────────────────────────────
// RAW 포맷 자동 감지 + 정규화
//   반환: {postDate, useDate, time, card, last4, user, merchant, bizCat,
//          country, currency, foreign, rate, krw, saleType, overseas, format}
// ─────────────────────────────────────────────────────────────
function detectFormat(row) {
  const c = row.map(function (x) { return String(x == null ? '' : x).trim(); });
  if (/^\d{1,2}:\d{2}/.test(c[2])) return 'DOMESTIC';                 // 3열=시각
  if (['JPY','USD','KRW','EUR'].indexOf((c[10] || '').toUpperCase()) >= 0) return 'OVERSEAS_A'; // 11열=통화
  if (/^\d+$/.test(c[0]) && /\d{4}-\*/.test(c[3] || '')) return 'OVERSEAS_B'; // 1열=순번,4열=카드
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
  } else {
    return null;
  }
  rec.format = fmt;
  rec.last4 = digits(rec.card).slice(-4);
  rec.useDate = normDate(rec.useDate);
  rec.postDate = normDate(rec.postDate);
  return rec;
}

// ─────────────────────────────────────────────────────────────
// 2단계 — 분류
// ─────────────────────────────────────────────────────────────
function classify(rec, kb, emailIdx) {
  const name = (rec.merchant || '').toUpperCase();

  // 매출취소/환불
  if (/취소|환불|CANCEL/i.test(rec.saleType || '') || rec.krw < 0) return { status: 'CANCEL' };

  // OTA(숙박) → 예약번호/금액으로 메일 매칭(실사용일), 실패 시 보류
  if (hasKw(name, KW.OTA)) {
    const hit = emailIdx && matchEmail(emailIdx, rec);
    if (hit && hit.useDate) return { status: 'CONFIRM', account: hit.item === '항공권' ? '여비교통비' : '숙박비',
                                     useDateOverride: hit.useDate, bookingNo: hit.bookingNo, note: 'OTA:' + hit.source };
    return { status: 'HOLD', reason: 'OTA 실사용시기 확인 필요(트립/아고다/부킹) — 메일 매칭 대기' };
  }

  // 학습맵(과거 확정) 우선
  const learned = kb[normMerchant(rec.merchant)];
  if (learned) return { status: 'CONFIRM', account: learned };

  // 항공권(직접 항공사/여행사)
  if (hasKw(name, KW.AIR)) return { status: 'CONFIRM', account: '여비교통비' };

  if (rec.overseas) {
    // 해외는 항상 여행경비
    if (hasKw(name, KW.LODGING))   return { status: 'CONFIRM', account: '숙박비' };
    if (hasKw(name, KW.TRANSPORT)) return { status: 'CONFIRM', account: '교통비' };
    if (hasKw(name, KW.ADMISSION)) return { status: 'CONFIRM', account: '입장료' };
    if (hasKw(name, KW.FOOD_AREA)) return { status: 'CONFIRM', account: '식비' };
    if (rec.krw <= OVERSEAS_FOOD_THRESHOLD) return { status: 'CONFIRM', account: '식비' };
    return { status: 'HOLD', reason: '해외 10만원 초과 미상 가맹점 — 수동 확인' };
  }

  // ── 국내: 온라인결제(PG/페이) → 메일 매칭 ──
  if (hasKw(name, KW.PG) || (rec.bizCat && /전자상거래|PG/.test(rec.bizCat))) {
    const hit = emailIdx && matchEmail(emailIdx, rec);
    if (hit) return { status: 'CONFIRM', account: hit.account || '여비교통비', note: '메일:' + hit.source,
                      bookingNo: hit.bookingNo, project: hit.item };
    return { status: 'HOLD', reason: '온라인결제(PG/페이) — KICC·페이 메일 매칭 필요' };
  }

  // ── 국내: 기타비용(3820 김주형) vs 국내여행(그 외 카드) ──
  const isTravel = rec.last4 !== CONFIG.DOMESTIC_OWNER_CARD;
  if (hasKw(name, KW.TRANSPORT)) return { status: 'CONFIRM', account: '교통비' };
  const map = isTravel ? BIZCAT_TRAVEL : BIZCAT_ETC;
  if (rec.bizCat && map[rec.bizCat]) return { status: 'CONFIRM', account: map[rec.bizCat] };
  if (isTravel) return { status: 'CONFIRM', account: '식비' };           // 국내여행 기본 식비
  return { status: 'HOLD', reason: '3820 미상 업종 — 회의비/복리후생비/소모품비 확인' }; // 기타비용은 확인
}

// ─────────────────────────────────────────────────────────────
// 학습 — 완료 장부에서 가맹점→계정과목
// ─────────────────────────────────────────────────────────────
function buildKnowledgeBase() {
  const cached = PropertiesService.getScriptProperties().getProperty('KB');
  return cached ? JSON.parse(cached) : rebuildKnowledgeBase();
}
function rebuildKnowledgeBase() {
  const sh = openSheet(CONFIG.LEARN_LEDGER);
  const kb = {};
  if (sh) {
    const values = sh.getDataRange().getValues();
    const head = values[0].map(String);
    const mi = idxOf(head, ['가맹점', '적요', '가맹점명']);
    const ai = idxOf(head, ['계정과목', '계정']);
    for (let r = 1; r < values.length; r++) {
      const m = values[r][mi], a = values[r][ai];
      if (m && a) kb[normMerchant(m)] = String(a).trim();
    }
  }
  PropertiesService.getScriptProperties().setProperty('KB', JSON.stringify(kb));
  return kb;
}

// ─────────────────────────────────────────────────────────────
// 3단계 — 장부 전기
// ─────────────────────────────────────────────────────────────
function ensureLedgerHeader(ledger) {
  if (ledger.getLastRow() === 0) ledger.appendRow(CONFIG.LEDGER_HEADER);
}
function appendToLedger(ledger, rec, v) {
  const useDate = v.useDateOverride || rec.useDate;
  ledger.appendRow([
    useDate,                                      // 거래일자(실사용)
    rec.postDate || rec.useDate,                  // 결제일
    v.account,                                    // 계정과목
    makeMemo(v.account, useDate, v.note),         // 적요 (용도_MMDD 형식)
    rec.krw,                                      // 금액(원)
    rec.merchant,                                 // 가맹점
    v.bookingNo || '',                            // 예약번호(OTA 조인키)
    v.project || '',                              // 여행/프로젝트
    rec.last4 + (rec.user ? '/' + rec.user : ''), // 결제수단
    rec.overseas ? '해외' : '국내',               // 국내/해외
    rec.currency || 'KRW',                        // 통화
    rec.foreign || '',                            // 현지금액
    '기록완료',                                   // 상태
    rec.format || '',                             // 출처(포맷)
  ]);
}
// 완료장부 계승: 용도 접두 + 실사용일(MMDD). 예: 숙박_0705, 식비, 교통비
const ACCOUNT_MEMO = { '숙박비': '숙박', '여비교통비': '항공', '교통비': '교통', '식비': '식비', '입장료': '입장료' };
function makeMemo(account, useDate, note) {
  const base = ACCOUNT_MEMO[account] || account;
  const mmdd = (String(useDate).match(/\d{4}-(\d{2})-(\d{2})/) || [])[0] ?
               String(useDate).slice(5).replace('-', '') : '';
  return base + (mmdd ? '_' + mmdd : '') + (note ? ' [' + note + ']' : '');
}
function loadLedgerKeys(ledger) {
  const set = new Set();
  const values = ledger.getDataRange().getValues();
  const head = values[0] ? values[0].map(String) : [];
  const di = idxOf(head, ['거래일자']), mi = idxOf(head, ['가맹점']), ki = idxOf(head, ['금액']);
  for (let r = 1; r < values.length; r++) {
    set.add(makeKey(values[r][di], values[r][mi], values[r][ki]));
  }
  return set;
}

// ─────────────────────────────────────────────────────────────
// 메일 스테이징 매칭 (있을 때만)
// ─────────────────────────────────────────────────────────────
function loadEmailIndex() {
  const ss = SpreadsheetApp.openById(CONFIG.STAGING.id);
  const sh = ss.getSheetByName(CONFIG.STAGING.sheetName);
  if (!sh || sh.getLastRow() < 2) return null;
  const values = sh.getDataRange().getValues();
  const head = values[0].map(String);
  const col = {};
  head.forEach(function (h, i) { col[h] = i; });
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    rows.push({
      source: row[col.source], type: row[col.type],
      useDate: normDate(row[col.useDate]), merchant: row[col.merchant],
      item: row[col.item], amount: num(row[col.amount]), account: row[col.account],
      bookingNo: String(row[col.bookingNo] || ''),
    });
  }
  return rows;
}
// 매칭: 금액 근접(±1%). 트립 호텔은 원화라 금액 일치가 강함(아고다 JPY는 약함 → 추후 예약번호 보강).
function matchEmail(index, rec) {
  const amt = Math.round(rec.krw);
  let best = null;
  index.forEach(function (e) {
    if (e.type === 'refund') return;
    const ea = Math.round(Math.abs(e.amount));
    if (ea > 0 && Math.abs(ea - amt) <= Math.max(2, amt * 0.01)) best = best || e;
  });
  return best;
}

// ─────────────────────────────────────────────────────────────
// 헬퍼
// ─────────────────────────────────────────────────────────────
function openSheet(ref) {
  const ss = SpreadsheetApp.openById(ref.id);
  return ref.sheetName ? ss.getSheetByName(ref.sheetName) : ss.getSheets()[0];
}
function makeKey(date, merchant, amount) { return [normDate(date), normMerchant(merchant), num(amount)].join('|'); }
function normMerchant(s) { return String(s || '').toUpperCase().replace(/\s+/g, ' ').trim(); }
function hasKw(name, list) { return list.some(function (k) { return name.indexOf(k.toUpperCase()) >= 0; }); }
function num(v) { if (typeof v === 'number') return v; return Number(String(v || '').replace(/[^0-9.-]/g, '')) || 0; }
function digits(s) { return String(s || '').replace(/\D/g, ''); }
function idxOf(head, names) {
  for (let i = 0; i < head.length; i++) for (let n = 0; n < names.length; n++)
    if (String(head[i]).indexOf(names[n]) >= 0) return i;
  return -1;
}
function normDate(d) {
  if (d instanceof Date) return Utilities.formatDate(d, 'Asia/Seoul', 'yyyy-MM-dd');
  const s = String(d || '').trim();
  const m = s.match(/(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})/);
  return m ? m[1] + '-' + pad(m[2]) + '-' + pad(m[3]) : s;
}
function pad(n) { return ('0' + n).slice(-2); }
function isWhite(hex) { const h = String(hex || '').toLowerCase(); return h === '' || h === '#ffffff' || h === '#fff' || h === 'white'; }
function setRowColor(sh, rowNum, color) { sh.getRange(rowNum, 1, 1, sh.getLastColumn()).setBackground(color); }
function noteCell(sh, rowNum, text) { sh.getRange(rowNum, 1).setNote(text); }
function toast(msg) { SpreadsheetApp.getActiveSpreadsheet().toast(msg, '비용처리', 8); }
