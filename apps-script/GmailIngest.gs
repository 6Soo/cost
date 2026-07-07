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
      const t = m.subject + '\n' + m.body;
      // 환불(취소) — '기존 결제 수단으로 400106원 환불' / '환불 금액은 400106원'
      if (/환불 완료|환불 요청|취소 요청 접수/.test(t)) {
        const amt = won(t, /([0-9,]+)\s*원\s*환불/) || won(t, /환불[^0-9]{0,20}([0-9,]+)\s*원/);
        return {
          source: 'trip_flight', type: 'refund',
          bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
          merchant: '항공권', item: '항공권 환불',
          currency: 'KRW', amount: -amt, paidDate: m.date, account: '여비교통비',
        };
      }
      if (!/발권되었습니다|예약 확정/.test(t)) return null;
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

  // ── Agoda (한/영/일 자동번역 혼재) — 예약번호·숙소·체크인일 추출(금액은 대개 없음→카드매칭) ──
  {
    id: 'agoda',
    match: function (m) { return /agoda\.com/i.test(m.from); },
    parse: function (m) {
      const t = m.subject + '\n' + m.body;
      const isRefund = /환불|refunded|refund of|refund in the amount/i.test(t);   // '취소 정책' 문구는 환불로 안 봄
      const mo = money(t, /(?:Total\s*Price|Total|amount of|결제.{0,4}금액|합계|금액|料金)/i);
      const curCode = firstGroup(t, /\b(JPY|KRW|USD|EUR)\b/);
      return {
        source: 'agoda',
        type: isRefund ? 'refund' : 'charge',
        bookingNo: firstGroup(t, /(?:booking\s*id|예약\s*번호|予約番号)\s*[:：]?\s*([0-9]{6,})/i) ||
                   digits(firstGroup(t, /ID[:：]\s*([0-9]{6,})/i)),
        merchant: firstGroup(t, /(?:숙소명|호텔명|Hotel|宿泊施設名)\s*[:：]\s*(.+)/i),
        item: '숙박',
        // 체크인: 한국어 '2026년 6월 25일' 또는 영문/일문 'June 25, 2026'
        useDate: ymd2(firstGroup(t, /(?:체크인|arrival|check[\s-]?in|チェックイン)[^0-9]{0,6}([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/i)) ||
                 endate(t, /(?:체크인|arrival|check[\s-]?in|チェックイン)[^A-Za-z0-9]{0,6}([A-Za-z]+ [0-9]{1,2}, [0-9]{4})/i),
        currency: mo.currency || curCode || 'JPY',
        amount: isRefund ? -mo.amount : mo.amount,
        paidDate: m.date,
      };
    },
  },

  // ── 트립닷컴 렌터카 교통위반 벌금 (금액은 첨부 PDF → 카드 결제분과 매칭 대기) ──
  {
    id: 'trip_fine',
    match: function (m) { return /tcarservice\.trip\.com/i.test(m.from) || /traffic fine/i.test(m.subject); },
    parse: function (m) {
      const t = m.subject + '\n' + m.body;
      const od = t.match(/Date of Offence[:：]?\s*([0-9]{1,2})\/([0-9]{1,2})\/([0-9]{4})/i);   // DD/MM/YYYY
      return {
        source: 'trip_fine',
        type: 'charge',
        merchant: firstGroup(t, /租车公司名称[:：]\s*(.+)/) || firstGroup(t, /(Avis Budget Group|Budget|Avis)/i) || '렌터카(벌금)',
        item: '렌터카 교통위반 벌금',
        bookingNo: firstGroup(t, /Rental Agreement Number[:：]?\s*([A-Za-z0-9]+)/i),
        useDate: od ? od[3] + '-' + pad(od[2]) + '-' + pad(od[1]) : '',
        currency: 'KRW',
        amount: 0,               // 벌금액은 첨부 PDF에만 → 카드 결제분 도착 시 수동 매칭(보류)
        account: '여비교통비',
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
        // 결제일시가 '2026/06/28' 슬래시 또는 '2026년 06월 28일' 둘 다 지원
        paidDate: ymd2(firstGroup(m.body, /결제일시\s*([0-9]{4}[.\-\/][0-9]{1,2}[.\-\/][0-9]{1,2}|[0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/)),
        currency: 'KRW',
        amount: won(m.body, /상품금액\s*([0-9,]+)\s*원/),
        bookingNo: line(m.body, /승인번호\s*([0-9]+)/),
        card: line(m.body, /결제기관\s*(.+)/),
      };
    },
  },

  // ── Booking.com (실제 샘플 반영) ──
  //  · noreply-payments@booking.com = 영수증(금액 O)   · noreply@booking.com = 예약확정(금액 X)
  //  · property.booking.com·평가하기·"새로운 메시지" = 노이즈 → 스킵
  {
    id: 'booking',
    match: function (m) { return /booking\.com/i.test(m.from); },
    parse: function (m) {
      const t = m.subject + '\n' + m.body;
      if (/평가하기|후기|Rate\s|review/i.test(m.subject)) return null;         // 후기요청 스킵
      if (/property\.booking\.com/i.test(m.from) || /새로운 메시지|메시지가 있습니다|메시지를 보냈/.test(m.subject)) return null; // 숙소 메시지 스킵

      const isReceipt = /noreply-payments@booking\.com/i.test(m.from) || /영수증|receipt/i.test(m.subject);
      const mo = money(t, /결제된?\s*금액/);
      return {
        source: 'booking',
        type: /환불|취소|refund|cancel/i.test(t) ? 'refund' : 'charge',
        bookingNo: firstGroup(t, /예약\s*번호[:\s]*([0-9]{6,})/) || firstGroup(t, /booking\s*(?:number|id)[:\s]*([0-9]{6,})/i),
        merchant: firstGroup(t, /숙소\s*이름\s*[\r\n]+\s*(.+)/) ||
                  firstGroup(m.subject, /[!\s]\s*([A-Za-z].*?)\s*예약이 확정/) ||
                  firstGroup(t, /(?:숙소명|Hotel|Property)[:\s]+(.+)/i),
        item: '숙박',
        useDate: ymd2(firstGroup(t, /체크인[:\s]*([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/)) ||
                 endate(t, /Check-?in\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})/i),
        currency: mo.currency || 'KRW',
        amount: isReceipt ? mo.amount : 0,   // 영수증만 금액, 확정메일은 카드매칭
        paidDate: m.date,
      };
    },
  },
];

// ─────────────────────────────────────────────────────────────
// 미리보기(안전) — 라벨/시트 변경 없이 파서 결과만 로그로 출력.
// Apps Script 편집기에서 dryRunIngest 실행 → '실행 로그(Ctrl+Enter)' 확인.
// 파서 검증·튜닝용이라 몇 번을 돌려도 부작용 없음.
// ─────────────────────────────────────────────────────────────
function dryRunIngest() {
  const threads = GmailApp.search(GMAIL_CFG.QUERY, 0, 30);
  let seen = 0, parsed = 0, skipped = 0;
  Logger.log('쿼리: %s  (스레드 %s개)', GMAIL_CFG.QUERY, threads.length);
  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (gm) {
      const m = {
        id: gm.getId(), from: gm.getFrom(), subject: gm.getSubject(),
        date: Utilities.formatDate(gm.getDate(), 'Asia/Seoul', 'yyyy-MM-dd'),
        body: gm.getPlainBody(),
      };
      seen++;
      const parser = PARSERS.find(function (p) { return p.match(m); });
      const rec = parser ? parser.parse(m) : null;
      if (rec) { parsed++; } else { skipped++; }
      Logger.log('· [%s] %s (%s)\n    → %s',
        parser ? parser.id : '매칭파서없음', m.subject, m.from,
        rec ? JSON.stringify(rec) : '스킵(비결제/미매칭)');
    });
  });
  Logger.log('요약: 메시지 %s개 / 파싱 %s / 스킵 %s (변경사항 없음)', seen, parsed, skipped);
}

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
// 년월일·슬래시·점·하이픈 날짜를 yyyy-MM-dd로. (HTML메일은 값이 다음 줄에 오므로 라벨 뒤 \s* 로 넘어감)
function ymd2(g) {
  const s = String(g || '');
  let m = s.match(/([0-9]{4})년\s*([0-9]{1,2})월\s*([0-9]{1,2})일/);
  if (m) return m[1] + '-' + pad(m[2]) + '-' + pad(m[3]);
  m = s.match(/([0-9]{4})[.\-\/]\s*([0-9]{1,2})[.\-\/]\s*([0-9]{1,2})/);
  return m ? m[1] + '-' + pad(m[2]) + '-' + pad(m[3]) : '';
}
// 라벨 뒤 60자 안에서 통화기호(¥/₩/$)·숫자 추출. Booking '결제된 금액 ¥73,800' 등.
function money(t, labelRe) {
  const s = String(t || ''); const m = s.match(labelRe);
  if (!m) return { amount: 0, currency: '' };
  const seg = s.slice(m.index, m.index + 60);
  const cur = /¥|JPY/i.test(seg) ? 'JPY' : /₩|KRW|원/.test(seg) ? 'KRW' : /\$|USD/i.test(seg) ? 'USD' : '';
  const n = seg.match(/([0-9][0-9,]{2,})/);
  return { amount: n ? num(n[1]) : 0, currency: cur };
}
function endate(t, re) {
  const g = firstGroup(t, re);
  const M = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
  const m = g.match(/([A-Za-z]+)\s+([0-9]{1,2}),\s*([0-9]{4})/);
  return m && M[m[1]] ? m[3] + '-' + pad(M[m[1]]) + '-' + pad(m[2]) : '';
}
