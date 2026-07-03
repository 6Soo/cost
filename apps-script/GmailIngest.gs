/**
 * Gmail 결제/예약 메일 인제스천 — kkokkohero6@gmail.com 계정에서 실행.
 *
 * label:결제데이터 -label:처리완료 메일을 발신자별 파서로 구조화 →
 * '메일수집' 스테이징 시트에 append → 처리완료 라벨 부여(멱등/증분).
 *
 * ⚠ PARSERS 의 실제 정규식은 예시 메일(발신자/제목/본문)을 받으면 확정한다.
 */

const GMAIL_CFG = {
  QUERY: 'label:결제데이터 -label:처리완료',
  DONE_LABEL: '처리완료',
  STAGING: { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: '메일수집' }, // TODO 확정
  MAX_THREADS: 50, // 실행당 처리량(트리거로 반복)
};

// 스테이징 시트 헤더 순서
const STAGING_COLS = ['source', 'paidDate', 'useDate', 'merchant', 'item', 'amount', 'messageId'];

/**
 * 발신자별 파서 레지스트리.
 * match: 메시지가 이 파서 대상인지. parse: 구조화 레코드(부분) 반환.
 * TODO: 실제 예시 메일 받으면 from/정규식 확정.
 */
const PARSERS = [
  {
    source: 'naverpay',
    match: function (m) { return /naverpay|네이버페이|npay/i.test(m.from + m.subject); },
    parse: function (m) {
      return {
        paidDate: m.date,
        amount: firstNumber(m.body, /결제\s*금액[^0-9]*([0-9,]+)/),
        merchant: firstGroup(m.body, /(?:가맹점|상호)[^\n:]*[:：]?\s*([^\n]+)/),
        item: firstGroup(m.body, /(?:상품명|주문)[^\n:]*[:：]?\s*([^\n]+)/),
      };
    },
  },
  {
    source: 'kakaopay',
    match: function (m) { return /kakaopay|카카오페이/i.test(m.from + m.subject); },
    parse: function (m) {
      return {
        paidDate: m.date,
        amount: firstNumber(m.body, /([0-9,]+)\s*원/),
        merchant: firstGroup(m.body, /(?:가맹점|사용처)[^\n:]*[:：]?\s*([^\n]+)/),
      };
    },
  },
  {
    source: 'agoda',
    match: function (m) { return /agoda/i.test(m.from); },
    parse: function (m) {
      return {
        useDate: firstGroup(m.body, /(?:체크인|Check-?in)[^\n:]*[:：]?\s*([0-9]{4}[-.\/][0-9]{1,2}[-.\/][0-9]{1,2})/i),
        merchant: firstGroup(m.body, /(?:호텔|Hotel)[^\n:]*[:：]?\s*([^\n]+)/i),
        amount: firstNumber(m.body, /(?:총액|Total)[^0-9]*([0-9,]+)/i),
        item: '숙박',
      };
    },
  },
  {
    source: 'booking',
    match: function (m) { return /booking\.com/i.test(m.from); },
    parse: function (m) {
      return {
        useDate: firstGroup(m.body, /(?:체크인|Check-?in)[^\n:]*[:：]?\s*([0-9]{4}[-.\/][0-9]{1,2}[-.\/][0-9]{1,2})/i),
        merchant: firstGroup(m.body, /(?:호텔|Property|Hotel)[^\n:]*[:：]?\s*([^\n]+)/i),
        item: '숙박',
      };
    },
  },
  {
    source: 'tripcom',
    match: function (m) { return /trip\.com|ctrip/i.test(m.from); },
    parse: function (m) {
      return {
        useDate: firstGroup(m.body, /(?:탑승|체크인|Departure|Check-?in)[^\n:]*[:：]?\s*([0-9]{4}[-.\/][0-9]{1,2}[-.\/][0-9]{1,2})/i),
        merchant: firstGroup(m.body, /(?:항공|호텔|Airline|Hotel)[^\n:]*[:：]?\s*([^\n]+)/i),
      };
    },
  },
];

function ingestPaymentEmails() {
  const sheet = openStaging_();
  const seen = loadSeenMessageIds_(sheet);
  const doneLabel = getOrCreateLabel_(GMAIL_CFG.DONE_LABEL);
  const threads = GmailApp.search(GMAIL_CFG.QUERY, 0, GMAIL_CFG.MAX_THREADS);
  let added = 0;

  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (gm) {
      const m = {
        id: gm.getId(),
        from: gm.getFrom(),
        subject: gm.getSubject(),
        date: Utilities.formatDate(gm.getDate(), 'Asia/Seoul', 'yyyy-MM-dd'),
        body: gm.getPlainBody(),
      };
      if (seen.has(m.id)) return;
      const parser = PARSERS.find(function (p) { return p.match(m); });
      if (!parser) return; // 대상 아님
      const rec = Object.assign({ source: parser.source, amount: 0 }, parser.parse(m), { messageId: m.id });
      appendStaging_(sheet, rec);
      seen.add(m.id);
      added++;
    });
    thread.addLabel(doneLabel);
  });

  SpreadsheetApp.getActiveSpreadsheet().toast('메일 수집 ' + added + '건', '비용처리', 6);
}

// ── 스테이징 헬퍼 ──
function openStaging_() {
  const ss = SpreadsheetApp.openById(GMAIL_CFG.STAGING.id);
  let sh = ss.getSheetByName(GMAIL_CFG.STAGING.sheetName);
  if (!sh) { sh = ss.insertSheet(GMAIL_CFG.STAGING.sheetName); sh.appendRow(STAGING_COLS); }
  return sh;
}
function appendStaging_(sh, rec) {
  sh.appendRow(STAGING_COLS.map(function (c) { return rec[c] != null ? rec[c] : ''; }));
}
function loadSeenMessageIds_(sh) {
  const set = new Set();
  const idCol = STAGING_COLS.indexOf('messageId');
  const values = sh.getDataRange().getValues();
  for (let r = 1; r < values.length; r++) if (values[r][idCol]) set.add(String(values[r][idCol]));
  return set;
}
function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

// ── 파싱 유틸 ──
function firstGroup(text, re) { const m = String(text || '').match(re); return m ? m[1].trim() : ''; }
function firstNumber(text, re) { const m = String(text || '').match(re); return m ? Number(m[1].replace(/[^0-9.-]/g, '')) : 0; }
