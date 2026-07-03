/**
 * 숲길여행 비용처리 자동화 — Apps Script 엔진
 *
 * 실행: 사용자(김주형 이사)의 구글 계정에서 실행됨 → openById 로 5개 시트에 공유 없이 접근.
 * 진입점: onOpen() 이 "비용처리" 메뉴를 만들고, runReconciliation() 이 2·3·4단계를 수행.
 *
 * ⚠ CONFIG 의 컬럼 인덱스/시트명/색상값은 실제 시트 헤더를 확인한 뒤 확정한다.
 *   (헤더행 + 샘플 몇 줄을 받으면 즉시 채운다.)
 */

// ─────────────────────────────────────────────────────────────
// CONFIG — 실제 시트에 맞춰 확정할 값
// ─────────────────────────────────────────────────────────────
const CONFIG = {
  RAW_SOURCES: [
    { id: '1nYxV9UM9rMRjEhnhdc8evE2xb3z6RxgWd5f5ci6PPdE', sheetName: null }, // null = 첫 시트
    { id: '11jjbN882fdQDcIexuzX-l0yBw02VgIna1jhnJNMkN_o', sheetName: null },
    { id: '1SiOftobiUJSxSdvBEKL9AmxgQkjzkzDjs2O_8SBoyh4', sheetName: null },
  ],
  LEARN_LEDGER:  { id: '1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8', sheetName: null }, // 1분기 완료(정답)
  TARGET_LEDGER: { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: null }, // 기록 대상

  HEADER_ROWS: 1, // 헤더 행 수 (샘플 확인 후 조정)

  // RAW 시트 컬럼 (0-base). TODO: 실제 헤더에 맞춰 확정.
  RAW_COL: { date: 0, merchant: 1, amount: 2, cardNo: 3, currency: 4 },

  // 장부 시트 컬럼 (0-base). TODO: 기존 완료 장부 헤더에 맞춰 확정.
  LEDGER_COL: { date: 0, account: 1, memo: 2, amount: 3, merchant: 4 },

  // 4단계 배경색 (TODO: 완료 시트에서 실제 색 추출해 확정).
  COLOR: {
    DONE:   '#d9ead3', // 기록 완료 (가장 많은 색)
    CANCEL: '#f4cccc', // 매출취소
    NONE:   '#ffffff', // 미분류(흰색) = 처리 대상
  },

  // 카드번호별 사용자/맥락
  CARD_OWNER: { '3320': '김주형' }, // 그 외 카드번호 = 아슬란 대장 등
};

// 분류 키워드
const KW = {
  TRANSPORT: ['TOYOTA','RENT','ENEOS','HERTZ','TAXI','PARKING','SHELL','ESSO','TOLL','EXPRESSWAY','렌트','렌터카','주유'],
  LODGING:   ['HOTEL','HOSTEL','INN','RESORT','RYOKAN','호텔','민박','료칸'],
  OTA:       ['TRIP.COM','TRIP','AGODA','BOOKING','부킹','아고다','트립'],
  PAY:       ['네이버페이','카카오페이','NAVERPAY','KAKAOPAY','NAVER PAY','KAKAO PAY'],
};

const OVERSEAS_FOOD_THRESHOLD = 100000; // 해외 10만원 이하 → 기본 식비

// ─────────────────────────────────────────────────────────────
// 메뉴
// ─────────────────────────────────────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('비용처리')
    .addItem('정산 실행 (미분류만)', 'runReconciliation')
    .addItem('학습맵 다시 만들기', 'rebuildKnowledgeBase')
    .addToUi();
}

// ─────────────────────────────────────────────────────────────
// 메인: 2·3·4단계 통합, 멱등
// ─────────────────────────────────────────────────────────────
function runReconciliation() {
  const kb = buildKnowledgeBase();                 // 완료 장부에서 가맹점→계정과목 학습
  const ledger = openSheet(CONFIG.TARGET_LEDGER);
  const existing = loadLedgerKeys(ledger);         // 중복 전기 방지용 기존 키 집합
  const stats = { done: 0, cancel: 0, hold: 0 };

  CONFIG.RAW_SOURCES.forEach(function (src) {
    const sh = openSheet(src);
    const rng = sh.getDataRange();
    const values = rng.getValues();
    const bg = rng.getBackgrounds();

    for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
      if (!isWhite(bg[r][0])) continue;            // 흰색(미분류) 행만 처리 → 멱등
      const row = values[r];
      const rec = parseRaw(row);
      if (!rec.date && !rec.merchant) continue;    // 빈 행 skip

      const verdict = classify(rec, kb);           // {status, account, reason}

      if (verdict.status === 'CANCEL') {
        setRowColor(sh, r + 1, CONFIG.COLOR.CANCEL);
        stats.cancel++;
      } else if (verdict.status === 'CONFIRM') {
        const key = makeKey(rec.date, rec.merchant, rec.amount);
        if (!existing.has(key)) {
          appendToLedger(ledger, rec, verdict.account);
          existing.add(key);
        }
        setRowColor(sh, r + 1, CONFIG.COLOR.DONE);
        stats.done++;
      } else { // HOLD
        noteCell(sh, r + 1, verdict.reason);       // 흰색 유지 + 보류 사유 노트
        stats.hold++;
      }
    }
  });

  toast('정산 완료 — 확정 ' + stats.done + ' / 취소 ' + stats.cancel + ' / 보류 ' + stats.hold);
}

// ─────────────────────────────────────────────────────────────
// 2단계: 분류
// ─────────────────────────────────────────────────────────────
function classify(rec, kb) {
  const name = (rec.merchant || '').toUpperCase();

  // 매출취소/환불: 음수 금액
  if (rec.amount < 0) return { status: 'CANCEL' };

  // 학습맵 우선 (과거 사람이 확정한 판단 재사용)
  const learned = kb[normMerchant(rec.merchant)];
  if (learned) return { status: 'CONFIRM', account: learned };

  // OTA → 보류 (결제≠사용, 자동추론 불가)
  if (hasKw(name, KW.OTA)) return { status: 'HOLD', reason: 'OTA 실사용시기 확인 필요(트립/아고다/부킹)' };

  if (rec.overseas) {
    if (hasKw(name, KW.LODGING))   return { status: 'CONFIRM', account: '숙박비' };
    if (hasKw(name, KW.TRANSPORT)) return { status: 'CONFIRM', account: '여비교통비' };
    if (rec.amount <= OVERSEAS_FOOD_THRESHOLD) return { status: 'CONFIRM', account: '식비' };
    return { status: 'HOLD', reason: '해외 10만원 초과 미상 가맹점 — 수동 확인' };
  }

  // 국내
  if (rec.cardNo === '3320') {
    if (hasKw(name, KW.PAY) || rec.amount >= 100000)
      return { status: 'HOLD', reason: '3320 페이/고액 — 페이 내역 매칭 필요' };
    return { status: 'HOLD', reason: '3320 소액 — 소모품/복리후생/회의비 중 확인' };
  }
  return { status: 'CONFIRM', account: '식비' }; // 그 외 카드 국내여행 기본 식비
}

// ─────────────────────────────────────────────────────────────
// 학습: 완료 장부 → 가맹점 → 계정과목
// ─────────────────────────────────────────────────────────────
function buildKnowledgeBase() {
  const cached = PropertiesService.getScriptProperties().getProperty('KB');
  if (cached) return JSON.parse(cached);
  return rebuildKnowledgeBase();
}

function rebuildKnowledgeBase() {
  const sh = openSheet(CONFIG.LEARN_LEDGER);
  const values = sh.getDataRange().getValues();
  const kb = {};
  for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
    const merchant = values[r][CONFIG.LEDGER_COL.merchant];
    const account  = values[r][CONFIG.LEDGER_COL.account];
    if (merchant && account) kb[normMerchant(merchant)] = String(account).trim();
  }
  PropertiesService.getScriptProperties().setProperty('KB', JSON.stringify(kb));
  return kb;
}

// ─────────────────────────────────────────────────────────────
// 3단계: 장부 전기
// ─────────────────────────────────────────────────────────────
function appendToLedger(ledger, rec, account) {
  const row = [];
  row[CONFIG.LEDGER_COL.date]     = rec.date;
  row[CONFIG.LEDGER_COL.account]  = account;
  row[CONFIG.LEDGER_COL.memo]     = rec.merchant;
  row[CONFIG.LEDGER_COL.amount]   = rec.amount;
  row[CONFIG.LEDGER_COL.merchant] = rec.merchant;
  ledger.appendRow(row);
}

function loadLedgerKeys(ledger) {
  const set = new Set();
  const values = ledger.getDataRange().getValues();
  for (let r = CONFIG.HEADER_ROWS; r < values.length; r++) {
    const v = values[r];
    set.add(makeKey(v[CONFIG.LEDGER_COL.date], v[CONFIG.LEDGER_COL.merchant], v[CONFIG.LEDGER_COL.amount]));
  }
  return set;
}

// ─────────────────────────────────────────────────────────────
// 헬퍼
// ─────────────────────────────────────────────────────────────
function parseRaw(row) {
  const c = CONFIG.RAW_COL;
  const amount = toNumber(row[c.amount]);
  const currency = String(row[c.currency] || '').trim().toUpperCase();
  return {
    date: row[c.date],
    merchant: String(row[c.merchant] || '').trim(),
    amount: amount,
    cardNo: String(row[c.cardNo] || '').trim(),
    overseas: currency && currency !== 'KRW' && currency !== '원' && currency !== '₩',
  };
}

function openSheet(ref) {
  const ss = SpreadsheetApp.openById(ref.id);
  return ref.sheetName ? ss.getSheetByName(ref.sheetName) : ss.getSheets()[0];
}

function makeKey(date, merchant, amount) {
  return [fmtDate(date), normMerchant(merchant), toNumber(amount)].join('|');
}
function normMerchant(s) { return String(s || '').toUpperCase().replace(/\s+/g, ' ').trim(); }
function hasKw(name, list) { return list.some(function (k) { return name.indexOf(k.toUpperCase()) >= 0; }); }
function toNumber(v) {
  if (typeof v === 'number') return v;
  return Number(String(v || '').replace(/[^0-9.-]/g, '')) || 0;
}
function fmtDate(d) {
  if (d instanceof Date) return Utilities.formatDate(d, 'Asia/Seoul', 'yyyy-MM-dd');
  return String(d || '').trim();
}
function isWhite(hex) {
  const h = String(hex || '').toLowerCase();
  return h === '' || h === '#ffffff' || h === 'white' || h === '#fff';
}
function setRowColor(sh, rowNum, color) {
  sh.getRange(rowNum, 1, 1, sh.getLastColumn()).setBackground(color);
}
function noteCell(sh, rowNum, text) {
  sh.getRange(rowNum, 1).setNote(text);
}
function toast(msg) {
  SpreadsheetApp.getActiveSpreadsheet().toast(msg, '비용처리', 8);
}
