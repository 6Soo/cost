/**
 * Gmail 결제/예약 메일 인제스천 — kkokkohero6@gmail.com 계정에서 실행.
 *
 * label:결제데이터 -label:처리완료 메일을 발신자별 파서로 구조화 →
 * '메일수집' 스테이징 시트에 append → 처리완료 라벨 부여(멱등/증분).
 *
 * 실제 샘플(Trip 호텔/항공, Agoda, KICC 이지페이) 기준으로 파서를 맞춤.
 */

const GMAIL_CFG = {
  QUERY: 'label:결제데이터 -label:처리완료',
  DONE_LABEL: '처리완료',
  STAGING: { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: '메일수집' }, // TODO 확정
  MAX_THREADS: 100,
};

// 스테이징 시트 헤더 순서
const STAGING_COLS = ['source', 'type', 'paidDate', 'useDate', 'merchant', 'item',
                      'currency', 'amount', 'bookingNo', 'card', 'account', 'messageId'];

// ─────────────────────────────────────────────────────────────
// 발신자별 파서. match(m) → 대상 여부, parse(m) → 레코드(부분) 또는 null(스킵)
// ─────────────────────────────────────────────────────────────
const PARSERS = [
  // ── Trip.com 호텔 (확정 / 취소·환불) ──
  {
    id: 'trip_hotel',
    match: function (m) { return /KR_HTL_NoReply@trip\.com/i.test(m.from); },
    parse: function (m) {
      // 체크인 임박 알림 등 결제 아님 → 스킵 (확정/취소만 처리)
      const isCancel = /취소되었습니다|환불/.test(m.subject + m.body);
      const isConfirm = /예약이 확정되었습니다/.test(m.subject + m.body);
      if (!isCancel && !isConfirm) return null;

      const rec = {
        source: 'trip_hotel',
        bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
        merchant: firstGroup(m.subject, /\](.+?)\s*예약이/) ||
                  firstGroup(m.subject, /(.+?)\s*예약이/),
        card: firstGroup(m.body, /([가-힣A-Za-z]+카드)\(신용카드\)/),
        currency: 'KRW',
        item: '숙박',
      };
      const ci = kdate(m.body, /체크인[:\s]*([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/);
      rec.useDate = ci;
      if (isCancel) {
        rec.type = 'refund';
        rec.paidDate = m.date;
        rec.amount = -won(m.body, /환불\s*금액\s*([0-9,]+)\s*원/);
      } else {
        rec.type = 'charge';
        rec.paidDate = m.date; // 실제 결제일은 카드내역과 매칭. 메일 수신일로 근사
        rec.amount = won(m.body, /(?:온라인 사전 결제[\s\S]{0,60}?|[가-힣A-Za-z]+카드\(신용카드\)\s*)([0-9,]+)\s*원/);
      }
      return rec;
    },
  },

  // ── Trip.com 항공 (본문에 금액 없음 → useDate 확보, 금액 보류) ──
  {
    id: 'trip_flight',
    match: function (m) { return /kr_flt_noreply@trip\.com/i.test(m.from); },
    parse: function (m) {
      if (!/발권되었습니다|예약 확정/.test(m.body + m.subject)) return null;
      return {
        source: 'trip_flight',
        type: 'charge',
        bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
        merchant: firstGroup(m.subject, /안내:\s*(.+)$/) || '항공권',
        item: '항공권 ' + (firstGroup(m.body, /PNR\)?:\s*([A-Z0-9]+)/) || ''),
        useDate: kdate(m.body, /가는편[^\n]*?([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/),
        currency: 'KRW',
        amount: 0,          // 본문 미포함(첨부 PDF) → 카드내역 매칭 필요
        card: '',
        paidDate: m.date,
        account: '여비교통비',
      };
    },
  },

  // ── Agoda (영문, 확정 / 환불) ──
  {
    id: 'agoda',
    match: function (m) { return /agoda\.com/i.test(m.from); },
    parse: function (m) {
      const isRefund = /refund/i.test(m.body);
      const cur = firstGroup(m.body, /(?:refund in the amount of|Total(?:\s*Price)?)\s*([A-Z]{3})/i) || 'JPY';
      const amt = num(firstGroup(m.body, /(?:amount of|Total(?:\s*Price)?)\s*[A-Z]{3}\s*([0-9,\.]+)/i));
      return {
        source: 'agoda',
        type: isRefund ? 'refund' : 'charge',
        bookingNo: firstGroup(m.body, /booking ID\s*([0-9]+)/i) || firstGroup(m.subject, /Booking ID\s*([0-9]+)/i),
        merchant: firstGroup(m.body, /Hotel:\s*(.+)/i),
        item: '숙박',
        useDate: endate(m.body, /Arrival:\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})/i) ||
                 endate(m.subject, /Check in\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})/i),
        currency: cur,
        amount: isRefund ? -amt : amt,
        paidDate: m.date,
      };
    },
  },

  // ── KICC 이지페이 (국내 신용카드 결제, 구조화 잘 됨) ──
  {
    id: 'kicc_easypay',
    match: function (m) { return /easypay_noreturn@easypay\.co\.kr/i.test(m.from); },
    parse: function (m) {
      return {
        source: 'kicc_easypay',
        type: 'charge',
        merchant: line(m.body, /상\s*호\s*(.+)/) || line(m.body, /상호\s*(.+)/),
        item: line(m.body, /상품명\s*(.+)/),
        paidDate: kdatetime(m.body, /결제일시\s*([0-9]{4}년\s*[0-9]{2}월\s*[0-9]{2}일)/),
        currency: 'KRW',
        amount: won(m.body, /상품금액\s*([0-9,]+)\s*원/),
        bookingNo: line(m.body, /승인번호\s*([0-9]+)/),
        card: line(m.body, /결제기관\s*(.+)/),
      };
    },
  },

  // ── Booking.com (샘플 확보 후 확정) ──
  {
    id: 'booking',
    match: function (m) { return /booking\.com/i.test(m.from); },
    parse: function (m) {
      return {
        source: 'booking',
        type: /cancel|refund|취소|환불/i.test(m.body) ? 'refund' : 'charge',
        merchant: firstGroup(m.body, /(?:호텔|Property|Hotel)[:\s]+(.+)/i),
        useDate: kdate(m.body, /체크인[:\s]*([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/) ||
                 endate(m.body, /Check-?in\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})/i),
        item: '숙박',
        paidDate: m.date,
        amount: 0,
      };
    },
  },
];

// ─────────────────────────────────────────────────────────────
// 메인
// ─────────────────────────────────────────────────────────────
function ingestPaymentEmails() {
  const sheet = openStaging_();
  const seen = loadSeenMessageIds_(sheet);
  const doneLabel = getOrCreateLabel_(GMAIL_CFG.DONE_LABEL);
  const threads = GmailApp.search(GMAIL_CFG.QUERY, 0, GMAIL_CFG.MAX_THREADS);
  let added = 0, skipped = 0;

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
      if (!parser) { skipped++; return; }
      const partial = parser.parse(m);
      if (!partial) { skipped++; return; }     // 알림/비결제 스킵
      appendStaging_(sheet, Object.assign({ amount: 0, currency: 'KRW' }, partial, { messageId: m.id }));
      seen.add(m.id);
      added++;
    });
    thread.addLabel(doneLabel);
  });

  SpreadsheetApp.getActiveSpreadsheet().toast('메일 수집 ' + added + '건 (스킵 ' + skipped + ')', '비용처리', 6);
}

// ── 스테이징 ──
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
// 참고: num()·digits()·pad() 는 Code.gs 에 단일 정의. Apps Script 는 프로젝트 내
// 모든 .gs 가 전역 스코프를 공유하므로 여기서 재선언하지 않는다(중복 선언 방지).
function firstGroup(t, re) { const m = String(t || '').match(re); return m ? m[1].trim() : ''; }
function after(t, re) { const m = String(t || '').match(re); return m ? m[1] : ''; }
function line(t, re) { const m = String(t || '').match(re); return m ? m[1].replace(/\t/g, ' ').trim() : ''; }
function won(t, re) { const m = String(t || '').match(re); return m ? num(m[1]) : 0; }
function kdate(t, re) {
  const g = firstGroup(t, re); const m = g.match(/([0-9]{4})년\s*([0-9]{1,2})월\s*([0-9]{1,2})일/);
  return m ? m[1] + '-' + pad(m[2]) + '-' + pad(m[3]) : '';
}
function kdatetime(t, re) { return kdate(t, re); }
function endate(t, re) {
  const g = firstGroup(t, re);
  const M = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
  const m = g.match(/([A-Za-z]+)\s+([0-9]{1,2}),\s*([0-9]{4})/);
  return m && M[m[1]] ? m[3] + '-' + pad(M[m[1]]) + '-' + pad(m[2]) : '';
}
