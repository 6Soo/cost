/**
 * Gmail 결제/예약 메일 인제스천 — kkokkohero6@gmail.com 계정에서 실행.
 *
 * label:결제데이터 -label:처리완료 메일을 발신자별 파서로 구조화 →
 * '메일수집' 스테이징 시트에 append → 처리완료 라벨 부여(멱등/증분).
 *
 * 실제 샘플(Trip 호텔/항공, Agoda, KICC 이지페이) 기준으로 파서를 맞춤.
 */

const GMAIL_CFG = {
  DONE_LABEL: '처리완료',
  // ★자동 수집 마스터 스위치(2026-07-22 사용자 지시로 기본 OFF): false면 10분 트리거가 firing해도
  //  아무것도 안 긁고 즉시 종료 → '메일수집' 탭이 자동으로 안 불어남(비용 파이프라인은 이 탭 미사용).
  //  다시 켜려면 여기를 true로 바꿔 재배포 후 시트메뉴 '자동 수집 켜기' 실행. 수동 '메일 수집'은 항상 동작.
  AUTO_DRAIN: false,
  STAGING: { id: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU', sheetName: '메일수집' },
  MAX_THREADS: 100,            // 한 배치 스레드 수
  TIME_BUDGET_MS: 300000,      // 실행 예산 5분(6분 제한 안전마진) — 초과 전까지 배치 반복
  // 수집 대상 기간 하한(yyyy/MM/dd). 현재 분기 작업엔 2026년만 필요(과거는 대부분 노이즈).
  //  과거 backlog까지 필요하면 날짜를 낮추거나 '' 로 비운다. (메일점검은 이 값과 무관하게 전체를 센다)
  SINCE: '2026/01/01',
};

// 결제/예약 메일 발신자(도메인·주소). '결제데이터' 라벨 필터가 최근 유입분을 놓쳐도(관측됨)
//  이 발신자 검색은 라벨과 무관하게 직접 잡는다. 대표가이드(kew2000)·본인(kkokko-hero) 계정 모두 커버.
const PAY_SENDERS = [
  { group: '트립닷컴',   q: 'from:trip.com' },
  { group: '부킹닷컴',   q: 'from:booking.com' },
  { group: '아고다',     q: 'from:(agoda.com OR agoda-messaging.com OR agoda-emails.com)' },
  { group: '클룩',       q: 'from:klook.com' },
  { group: '라쿠텐/자란',q: 'from:(rakuten.com OR jalan.net)' },
  { group: '스카이티켓', q: 'from:skyticket.com' },
  { group: 'Mytrip',     q: 'from:(support.kr.mytrip.com OR mytrip.com)' },
  { group: '11번가',     q: 'from:11st.co.kr' },
  { group: '휴양림/리조트', q: 'from:(foresttrip.go.kr OR ganghwa-resort.com OR smartropay.co.kr OR smartro.co.kr)' },
  { group: '항공사',     q: 'from:(koreanair.com OR vietnamairlines.com OR volotea.com OR skyscanner.com OR flyasiana.com OR jejuair.net OR jinair.com OR eastarjet.com)' },
  { group: 'KICC이지페이',q: 'from:easypay.co.kr' },
  { group: 'PG(KCP/NICE)',q: 'from:(kcp.co.kr OR nicepg.co.kr OR inicis.com OR nspay.co.kr)' },
  { group: '네이버/카카오/토스/페이코', q: 'from:(navercorp.com OR kakaocorp.com OR tosspayments.com OR payco.com)' },
  { group: '카드사',     q: 'from:(hanacard.co.kr OR kbcard.com OR shinhancard.com)' },
];
// 수집 대상 계정(라벨 아님, 실제 수신주소). 새 대표가이드 계정이 늘면 여기 추가.
const MAIL_ACCOUNTS = ['kew2000@daum.net', 'kkokko-hero@hanmail.net'];

// 계정 수신분 전체 검색식.
//  kew2000@daum.net 등 전달계정은 다음(Daum) 메일함 규칙에서 이미 1차 선별된 메일만
//  Gmail로 넘어오므로, 여기서 발신자 화이트리스트를 또 걸면 이중필터로 누락이 생긴다.
//  → 발신자 조건 없이 계정 수신 전체를 파싱한다(사용자 지시, 2026-07-15).
function senderQuery_(extra) {
  const accts = MAIL_ACCOUNTS.map(function (a) { return 'to:' + a; }).join(' OR ');
  const since = GMAIL_CFG.SINCE ? ' after:' + GMAIL_CFG.SINCE : '';
  return '{' + accts + '}' + since + (extra ? ' ' + extra : '');
}

// 무인 드레인 — 10분마다 '메일 수집'을 자동 실행해 backlog를 사람 없이 소진.
//  메일점검에서 미처리 0 되면 removeDrainTrigger()로 해제. (중복 등록 방지 후 재생성)
function setupDrainTrigger() {
  if (!GMAIL_CFG.AUTO_DRAIN) {   // 마스터 스위치 OFF면 트리거 생성 거부(오작동 방지)
    toast('AUTO_DRAIN=false 상태 — 자동 수집이 꺼져 있습니다. 켜려면 GMAIL_CFG.AUTO_DRAIN=true로 바꿔 재배포하세요.');
    return;
  }
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'ingestPaymentEmails') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('ingestPaymentEmails').timeBased().everyMinutes(10).create();
  toast('자동 수집 트리거 등록(10분마다). 미처리 0 되면 "자동 수집 해제" 실행하세요.');
}
function removeDrainTrigger() {
  let n = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'ingestPaymentEmails') { ScriptApp.deleteTrigger(t); n++; }
  });
  toast('자동 수집 트리거 ' + n + '개 해제.');
}

// 스테이징 시트 헤더 순서
const STAGING_COLS = ['source', 'type', 'paidDate', 'useDate', 'merchant', 'item',
                       'currency', 'amount', 'bookingNo', 'card', 'account', 'messageId',
                       'serviceStartOn', 'bookingStatus', 'settlementCondition'];

// ─────────────────────────────────────────────────────────────
// 발신자별 파서. match(m) → 대상 여부, parse(m) → 레코드(부분) 또는 null(스킵)
// ─────────────────────────────────────────────────────────────
const PARSERS = [
  // ── Mytrip / Gotogate 추가서비스 영수증 ──
  // 주문번호 뒤 회차 "(1)"와 "숫자 KRW" 순서의 소수점 금액을 범용 파서가
  // 놓쳤다. 변경수수료는 새 항공권이 아니라 원예약에 붙는 추가 서비스로 보존한다.
  {
    id: 'mytrip',
    match: function (m) {
      return /(?:support\.kr\.)?mytrip\.com/i.test(m.from) ||
             /Mytrip/i.test(m.subject + '\n' + m.body);
    },
    parse: function (m) {
      const t = m.subject + '\n' + m.body;
      const orderMatch = t.match(/\b([0-9]{4}-[0-9]{3}-[0-9]{3})(?:\s*\(([0-9]+)\))?/);
      const orderNo = orderMatch ? orderMatch[1] : '';
      const sequence = orderMatch && orderMatch[2] ? orderMatch[2] : '';
      const isCancelPending = /예약을\s*취소|환불될\s*예정|항공권\s*가격에서[\s\S]{0,80}차감/i.test(t);
      const isPending = /처리\s*중|최대\s*72시간|확정되면\s*확인\s*이메일/i.test(t);
      const pnr = isCancelPending ? firstGroup(t, /\b([A-Z0-9]{6})\b/) : '';
      const serviceFee = decimalKrw_(t, /서비스\s*수수료[^\d]{0,30}([0-9][0-9,]*(?:\.[0-9]+)?)\s*KRW/i);
      if (isCancelPending) {
        return {
          source: 'mytrip',
          type: 'cancel_pending',
          bookingNo: orderNo,
          merchant: 'Mytrip',
          item: '예약취소 처리중' +
            (pnr ? ' PNR ' + pnr : '') +
            (serviceFee ? ' 환불차감수수료 ' + Math.round(serviceFee) + '원' : ''),
          currency: 'KRW',
          amount: 0, // 차감 수수료는 새 카드 청구가 아니므로 카드매칭 금액으로 쓰지 않는다.
          paidDate: m.date,
          account: '여비교통비',
          card: '',
        };
      }
      if (isPending) {
        return {
          source: 'mytrip',
          type: 'pending',
          bookingNo: orderNo,
          merchant: 'Mytrip',
          item: '항공사 처리중 주문',
          currency: 'KRW',
          amount: 0,
          paidDate: m.date,
          account: '여비교통비',
          card: '',
        };
      }
      const isPaid = /결제가\s*확인|결제액|구입해\s*주셔서|영수증|구매하신\s*추가\s*서비스/i.test(t);
      if (!isPaid) {
        return {
          source: 'mytrip',
          type: 'evidence_only',
          bookingNo: orderNo,
          merchant: 'Mytrip',
          item: '일정·안내 예약 관계 증빙',
          currency: 'KRW',
          amount: 0,
          paidDate: m.date,
          account: '여비교통비',
          card: '',
        };
      }
      const isAdditional = /추가\s*서비스\s*영수증/i.test(t);
      const totals = decimalKrwValues_(firstGroup(t, /(?:합계|결제액)[\s\S]{0,160}?((?:[0-9][0-9,.]*\s*KRW[\s\S]{0,30}?){1,3})/i));
      const charged = totals.length ? Math.round(totals[totals.length - 1]) : 0;
      const fareDelta = decimalKrw_(t, /항공료[^\d]{0,30}([0-9][0-9,]*(?:\.[0-9]+)?)\s*KRW/i);
      return {
        source: 'mytrip',
        type: 'charge',
        bookingNo: orderNo,
        merchant: 'Mytrip',
        item: isAdditional
          ? '항공권 변경 추가서비스' + (sequence ? ' (' + sequence + ')' : '') +
            (serviceFee ? ' 수수료 ' + Math.round(serviceFee) + '원' : '') +
            (fareDelta ? ' 운임차액 ' + Math.round(fareDelta) + '원' : '')
          : '항공권',
        useDate: mytripDate_(t, m.date),
        currency: 'KRW',
        amount: charged,
        paidDate: m.date,
        account: '여비교통비',
        card: '',
      };
    },
  },

  // ── Trip.com 호텔 (확정 / 취소·환불) ──
  {
    id: 'trip_hotel',
    match: function (m) { return /KR_HTL_NoReply@trip\.com/i.test(m.from); },
    parse: function (m) {
      // 확정/환불은 '제목' 기준으로 판정 — 확정메일 본문의 취소정책 문구('환불되지 않습니다')에
      // 오검출되던 버그 수정. 체크인임박·확정번호·변경불가 등은 스킵.
      const subj = m.subject || '';
      const isRefund = /환불|취소되었습니다|무료로 취소|취소되었어요/.test(subj);
      const isConfirm = /예약이 확정/.test(subj);
      const refundText = subj + '\n' + m.body;
      // Trip 취소 메일은 "환불을 요청했습니다/1~7영업일 소요"와
      // "환불 완료"를 한 본문에 함께 싣기도 한다. 완료 표지가 있으면 진행중
      // 문구보다 우선해야 이미 완료된 환불을 pending으로 되돌리지 않는다.
      const refundCompleted = /환불(?:이|\s*)\s*완료|환불\s*처리\s*완료|취소\s*완료/.test(refundText);
      const refundPending = isRefund && !refundCompleted &&
        /환불이\s*시작|환불을\s*요청|환불\s*처리\s*중|환불금이[\s\S]{0,40}입금|입금되는\s*데[\s\S]{0,30}영업일/.test(refundText);
      const evidenceType =
        /예약 정보가 업데이트/.test(subj) ? 'update' :
        /인보이스 정보/.test(subj) ? 'invoice' : '';
      if (!isRefund && !isConfirm && !evidenceType) return null;

      const name = subj.replace(/^\[[^\]]*\]\s*/, '');   // 앞머리 [예약 확정 안내] 제거
      const rec = {
        source: 'trip_hotel',
        bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
        merchant: firstGroup(name, /(.+?)\s*예약(?:이|에 대한|을)/),   // 확정·환불 제목 모두 커버
        card: firstGroup(m.body, /([가-힣A-Za-z]+카드)\(신용카드\)/),
        currency: 'KRW',
        item: '숙박',
        useDate: kdate(m.body, /체크인[:\s]*([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/),
        paidDate: m.date, // 실제 결제일은 카드내역과 매칭. 메일 수신일로 근사
      };
      if (evidenceType) {
        rec.type = evidenceType;
        rec.amount = 0;
        rec.item = '예약 관계 증빙';
        return rec;
      }
      if (isRefund) {
        const refundAmount = won(m.body, /환불\s*금액\s*([0-9,]+)/) ||
                             won(m.body, /([0-9,]+)\s*원이\s*\(?가/);
        rec.type = refundPending ? 'refund_pending' : 'refund';
        rec.amount = refundPending ? 0 : -refundAmount;
        if (refundPending && refundAmount) rec.item = '숙박 환불예정금액 ' + refundAmount;
      } else {
        rec.type = 'charge';
        rec.amount = won(m.body, /(?:온라인 사전 결제[\s\S]{0,60}?|[가-힣A-Za-z]+카드\(신용카드\)\s*)([0-9,]+)\s*원/);
        // Only the provider's confirmed reservation with one parsed booking
        // reference may populate the downstream structured service date.
        // A date in an update/invoice/evidence mail is intentionally ignored.
        if (isConfirm && rec.bookingNo && /^\d{6,19}$/.test(rec.bookingNo) &&
            /^20\d{2}-\d{2}-\d{2}$/.test(rec.useDate || '')) {
          rec.bookingStatus = 'confirmed';
          rec.serviceStartOn = rec.useDate;
        }
      }
      return rec;
    },
  },

  // ── Trip.com 항공 (본문에 금액 없음 → useDate 확보, 금액 보류) ──
  {
    id: 'trip_flight',
    match: function (m) { return /kr_flt_noreply@trip\.com/i.test(m.from); },
    parse: function (m) {
      const subj = m.subject || '';
      if (/결제\s*실패|결제를\s*완료하지\s*못/.test(subj + '\n' + m.body)) {
        const attempted = won(m.body, /(?:결제|청구|총)\s*금액[^0-9]{0,20}([0-9,]+)/);
        return {
          source: 'trip_flight', type: 'payment_failed',
          bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
          merchant: '항공권',
          item: attempted ? '항공권 결제실패 요청금액 ' + attempted : '항공권 결제실패',
          currency: 'KRW', amount: 0, paidDate: m.date, account: '여비교통비',
        };
      }
      // 환불/취소는 '제목' 기준(확정메일 정책문구의 '환불'에 오검출 방지).
      // 제목 예: '항공권 환불: 후쿠오카…' / '환불 완료: 서울-니가타'
      if (/환불|취소/.test(subj)) {
        const amt = won(m.body, /([0-9,]+)\s*원\s*환불/) || won(m.body, /환불[^0-9]{0,20}([0-9,]+)\s*원/) ||
                    won(m.body, /환불\s*금액[^0-9]{0,10}([0-9,]+)/);
        return {
          source: 'trip_flight', type: 'refund',
          bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
          merchant: '항공권', item: '항공권 환불',
          currency: 'KRW', amount: -amt, paidDate: m.date, account: '여비교통비',
        };
      }
      if (/결제 완료 안내/.test(subj)) {
        const paymentAmount =
          won(m.body, /총\s*금액[^0-9]{0,20}([0-9,]+)\s*원/) ||
          won(m.body, /결제\s*금액[^0-9]{0,20}([0-9,]+)\s*원/);
        return {
          source: 'trip_flight', type: 'payment_confirmation',
          bookingNo: digits(after(m.body, /예약번호\s*([0-9​‌‍\s]+)/)),
          merchant: '항공권', item: '결제 완료·발권대기 관계 증빙',
          useDate: kdate(
            m.body,
            /출발[:：]\s*([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/
          ),
          currency: 'KRW', amount: paymentAmount,
          paidDate: m.date, account: '여비교통비',
        };
      }
      if (!/발권되었습니다|예약 확정/.test(subj + m.body)) return null;
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
                 endate(t, /(?:체크인|arrival|check[\s-]?in|チェックイン)[^A-Za-z0-9]{0,6}((?:[A-Za-z]+ [0-9]{1,2},? [0-9]{4})|(?:[0-9]{1,2} [A-Za-z]+ [0-9]{4}))/i),
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
        merchant: firstGroup(t, /租车公司名称[:：]\s*([^\n\\电]+)/) || firstGroup(t, /(Avis Budget Group|Budget|Avis)/i) || '렌터카(벌금)',
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
      // 결제/취소 구분: 제목 '[신용카드]취소하신 내역' → refund(음수). 취소는 '취소일시'.
      const isCancel = /취소/.test(m.subject);
      const amt = isCancel
        ? won(m.body, /취소금액\s*([0-9,]+)\s*원/) ||
          won(m.body, /(?:상품금액|결제금액)\s*([0-9,]+)\s*원/)
        : won(m.body, /(?:상품금액|결제금액)\s*([0-9,]+)\s*원/);
      const controlNo = /easypay\.co\.kr/i.test(m.body)
        ? firstGroup(m.body, /[?&]controlNo=([0-9]+)/i)
        : '';
      return {
        source: 'kicc_easypay',
        type: isCancel ? 'refund' : 'charge',
        merchant: line(m.body, /상\s*호\s*(.+)/) || line(m.body, /상호\s*(.+)/),
        item: line(m.body, /상품명\s*(.+)/) +
              (controlNo ? ' | payment_receipt_id=' + controlNo : ''),
        // 결제일시/취소일시가 '2026/06/28' 슬래시 또는 '2026년 06월 28일' 둘 다 지원
        paidDate: ymd2(firstGroup(m.body, /(?:결제일시|취소일시)\s*([0-9]{4}[.\-\/][0-9]{1,2}[.\-\/][0-9]{1,2}|[0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/)),
        currency: 'KRW',
        amount: isCancel ? -amt : amt,
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
    match: function (m) {
      return /booking\.com/i.test(m.from + '\n' + m.body);
    },
    parse: function (m) {
      const t = m.subject + '\n' + m.body;
      if (/평가하기|후기|Rate\s|review/i.test(m.subject)) return null;         // 후기요청 스킵
      if (/property\.booking\.com/i.test(m.from) || /새로운 메시지|메시지가 있습니다|메시지를 보냈/.test(m.subject)) return null; // 숙소 메시지 스킵

      const isReceipt = /noreply-payments@booking\.com/i.test(m.from) ||
                        /영수증|receipt|결제.{0,3}완료|지불\s*금액/i.test(t);
      const isSupportUpdate =
        /support\.booking\.com/i.test(t) &&
        /중요\s*업데이트|문의|Customer\s*Service/i.test(t);
      const isCancel = /환불|취소|refund|cancel/i.test(m.subject);
      // CTA인 "지금 결제"만으로 실패로 보지 않는다. 실제 실패/미청구 문구가
      // 있어야 payment_failed이며, 예약 약관의 환불 문구는 hold 신호가 아니다.
      const paymentFailed = /결제\s*(?:금액\s*)?청구에\s*실패|결제\s*실패|결제를\s*(?:완료하지|처리하지)\s*못/.test(t);
      const holdPossible =
        /보증금을\s*청구할\s*수/.test(t) ||
        /(?:보증금|카드\s*사전\s*승인|승인\s*보류)[\s\S]{0,100}(?:잠시\s*묶|승인\s*취소|전액\s*환불)/.test(t);
      const payAtProperty =
        /선결제가\s*필요\s*없/.test(t) ||
        /(?:요금은|결제는)[^\n]{0,100}(?:숙소|호텔)[^\n]{0,60}(?:체크인할\s*때\s*)?결제/.test(t) ||
        /(?:숙소|호텔)에서\s*결제하시면/.test(t);
      const paymentScheduled =
        /결제\s*일정이\s*확정/.test(t) ||
        /정해진\s*날짜[\s\S]{0,80}자동\s*청구/.test(t) ||
        /결제\s*예정(?:\s*금액)?/.test(t);
      const cancelNoCharge = isCancel &&
        /청구되지\s*않|추후\s*예정\s*결제\s*취소|금액\s*[¥₩]?\s*0\b/i.test(t);
      // 금액 라벨: '결제된 금액' / '총 지불 금액' / '총 결제 금액' 등
      const mo = money(t, /(?:총\s*지불\s*금액|총\s*결제\s*금액|결제(?:한|된|\s*완료된)?\s*금액|결제\s*완료|환불된\s*금액|amount\s*paid|total\s*price|total)/i);
      // 미완료 상태의 금액은 장부 amount가 아니라 설명용 후보로만 보존한다.
      // 각 상태 라벨 바로 뒤의 금액만 읽어 취소 위약금·세금·보증금과 섞지 않는다.
      const failedMo = paymentFailed
        ? money(t, /결제\s*실패|결제\s*(?:금액\s*)?청구에\s*실패/i)
        : { amount: 0, currency: '' };
      const scheduledMo = paymentScheduled
        ? money(t, /결제\s*예정(?:\s*금액)?|자동\s*청구\s*예정/i)
        : { amount: 0, currency: '' };
      const propertyMo = payAtProperty
        ? money(t, /합계|총\s*(?:예약\s*)?요금|total\s*price/i)
        : { amount: 0, currency: '' };
      const statusMo = paymentFailed ? failedMo :
                       paymentScheduled ? scheduledMo :
                       payAtProperty ? propertyMo : { amount: 0, currency: '' };
      const bookingNo = firstGroup(t, /예약\s*번호[:\s]*([0-9]{6,})/) ||
        firstGroup(t, /고객\s*확인번호[:\s]*([0-9-]{6,})/) ||
        firstGroup(t, /(?:booking\s*(?:number|id)|confirmation)[:\s]*([0-9]{6,})/i);
      const useDate = bookingDate_(t, m.date) ||
        endate(t, /Check-?in\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})/i);
      const confirmedBooking = !isSupportUpdate && !isCancel && !paymentFailed &&
        !payAtProperty && !holdPossible && !paymentScheduled &&
        /예약이\s*확정|booking\s*(?:is\s*)?confirmed|confirmed\s*booking/i.test(t) &&
        /^[0-9]{6,19}$/.test(bookingNo) && /^20\d{2}-\d{2}-\d{2}$/.test(useDate);
      // A possible authorization and a generic free-cancellation policy are
      // not a captured refundable deposit.  Record the latter only when the
      // message explicitly says the deposit was charged and will be returned.
      const refundableDepositPending = !isSupportUpdate && !isCancel &&
        /보증금[\s\S]{0,80}(?:결제|청구)(?:가)?\s*완료|보증금[\s\S]{0,80}청구되었습니다/.test(t) &&
        /(?:체크아웃|숙박\s*종료)[\s\S]{0,100}(?:반환|환불)/.test(t);
      const result = {
        source: 'booking',
        // 환불/취소는 '제목' 기준(확정메일 본문·PIN·정책의 '취소' 오검출 방지)
        type: isSupportUpdate ? 'evidence_only' :
              paymentFailed ? 'payment_failed' :
              cancelNoCharge ? 'cancel_no_charge' :
              isCancel ? 'refund' :
              paymentScheduled ? 'payment_scheduled' :
              payAtProperty ? 'pay_at_property' :
              holdPossible ? 'authorization_hold_possible' :
              'charge',
        bookingNo: bookingNo,
        merchant: firstGroup(t, /숙소\s*이름\s*[\r\n]+\s*(.+)/) ||
                  firstGroup(m.subject, /[!\s]\s*([A-Za-z].*?)\s*예약이 확정/) ||
                  firstGroup(t, /(?:숙소명|Hotel|Property)[:\s]+(.+)/i),
        item: isSupportUpdate ? '예약 고객센터 진행상태 증빙' :
              paymentFailed ? '숙박 결제실패' +
                (statusMo.amount ? ' 요청금액 ' + statusMo.amount : '') :
              paymentScheduled ? '숙박 자동결제 예정' +
                (statusMo.amount ? '금액 ' + statusMo.amount : '') :
              payAtProperty ? '숙박 현장결제 예정' +
                (statusMo.amount ? '금액 ' + statusMo.amount : '') +
                (holdPossible ? ' | 카드사전승인 가능' : '') :
              holdPossible ? '숙박 카드사전승인 가능' :
              '숙박',
        useDate: useDate,
        currency: statusMo.currency || mo.currency || 'KRW',
        amount: isSupportUpdate || paymentFailed || holdPossible || payAtProperty || paymentScheduled || cancelNoCharge
          ? 0 : isCancel ? -mo.amount : isReceipt ? mo.amount : 0,
        paidDate: m.date,
      };
      if (confirmedBooking) {
        result.bookingStatus = 'confirmed';
        result.serviceStartOn = useDate;
      }
      if (refundableDepositPending && /^[0-9]{6,19}$/.test(bookingNo)) {
        result.settlementCondition = 'refundable_deposit_pending';
      }
      return result;
    },
  },

  // ── 네이버페이 (본인 3820 간편결제 스트림) — 온라인/오프라인 두 레이아웃 ──
  //  · '자동결제 등록/해지'는 결제 아님 → 스킵.  값이 HTML표라 라벨 뒤 \s* 로 다음 줄 값을 잡는다.
  {
    id: 'naverpay',
    match: function (m) { return /naverpayadmin_noreply@navercorp\.com/i.test(m.from) || /\[네이버페이\]/.test(m.subject); },
    parse: function (m) {
      if (/자동결제\s*(등록|해지)|정기결제\s*(등록|해지)/.test(m.subject)) return null;   // 등록/해지 알림 스킵
      if (!/결제하신 내역|결제\s*완료|결제완료/.test(m.subject + m.body)) return null;
      const isCancel = /취소|환불/.test(m.subject);
      const amt = won(m.body, /최종결제금액\s*([0-9,]+)\s*원/) ||
                  won(m.body, /주문금액\s*([0-9,]+)\s*원/) ||
                  won(m.body, /총\s*결제\s*금액\s*([0-9,]+)\s*원/);
      return {
        source: 'naverpay',
        type: isCancel ? 'refund' : 'charge',
        merchant: firstGroup(m.body, /(?:결제처|가맹점명)\s*(.+)/),
        item: firstGroup(m.body, /(?:상품정보|주문상품|상품명)\s*(.+)/),
        paidDate: ymd2(firstGroup(m.body, /결제일자\s*([0-9]{4}[.\-\/][0-9]{1,2}[.\-\/][0-9]{1,2})/)),
        currency: 'KRW',
        amount: isCancel ? -amt : amt,
        bookingNo: firstGroup(m.body, /결제번호\s*([0-9]{6,}[A-Z0-9]*)/),
        card: '',
      };
    },
  },

  // ── 토스페이먼츠 (bill@bill-mail.tosspayments.com) — 결제/부분취소. 대표가이드 skyticket 항공 등 ──
  {
    id: 'toss',
    match: function (m) { return /tosspayments\.com/i.test(m.from) || /토스페이먼츠/.test(m.body); },
    parse: function (m) {
      if (!/결제금액/.test(m.body)) return null;
      const isCancel = /취소/.test(m.subject) || /부분취소되었|취소되었어요/.test(m.body);
      const full = won(m.body, /결제금액\s*([0-9,]+)\s*원/);
      const cancelAmt = won(m.body, /(?:부분취소금액|취소금액)\s*([0-9,]+)\s*원/);
      const approval = firstGroup(m.body, /승인번호\s*([0-9]+)/);
      const orderNo = firstGroup(m.body, /주문번호\s*([A-Z0-9_-]+)/i);
      return {
        source: 'toss',
        type: isCancel ? 'refund' : 'charge',
        merchant: firstGroup(m.body, /판매자\s*(.+)/),
        item: firstGroup(m.body, /구매상품\s*(.+)/) +
              (approval ? ' | approval_id=' + approval : ''),
        paidDate: ymd2(firstGroup(m.body, /결제일시\s*([0-9]{4}[.\-\/][0-9]{1,2}[.\-\/][0-9]{1,2})/)),
        currency: 'KRW',
        amount: isCancel ? -(cancelAmt || full) : full,
        bookingNo: orderNo || approval,
        card: firstGroup(m.body, /결제카드\s*(.+)/),
      };
    },
  },

  // ── 카카오페이 (kakaocorp 구독결제 등) ──
  {
    id: 'kakaopay',
    match: function (m) { return /@kakaocorp\.com/i.test(m.from) && /카카오페이|결제금액/.test(m.body); },
    parse: function (m) {
      if (!/결제금액|구독이 완료/.test(m.body)) return null;
      const isCancel = /취소|해지|환불/.test(m.subject);
      const name = firstGroup(m.body, /상품명\s*(.+)/);
      return {
        source: 'kakaopay',
        type: isCancel ? 'refund' : 'charge',
        merchant: name || '카카오',
        item: name,
        paidDate: m.date,
        currency: 'KRW',
        amount: (isCancel ? -1 : 1) * won(m.body, /결제금액\s*([0-9,]+)\s*원/),
        bookingNo: '',
        card: firstGroup(m.body, /결제수단\s*(.+)/),
      };
    },
  },

  // ── SKYTICKET 구입완료 / 최종안내 / 결제 전 자동취소 ──
  // 구간별 "항공료 합계"가 반복된 뒤 마지막 "결제 금액"이 나오므로
  // 범용 KRW 추출기는 첫 구간 금액을 거래 총액으로 오인한다.
  {
    id: 'skyticket',
    match: function (m) { return /@skyticket\.com/i.test(m.from); },
    parse: function (m) {
      const t = m.subject + '\n' + m.body;
      const applicationNo = firstGroup(t, /신청번호\s*[:：]?\s*([0-9]{6,})/);
      const isAutoCancel = /자동\s*취소|자동취소/.test(m.subject) &&
        /결제\s*기한[\s\S]{0,50}취소|결제\s*전\s*취소/.test(t);
      const isPurchased = /구입\s*완료|본\s*메일로\s*구입이\s*완료|결제완료\s*메일/.test(t);
      const isFinalInfo = /최종\s*안내/.test(m.subject);
      if (!isAutoCancel && !isPurchased && !isFinalInfo) return null;
      const amount = isPurchased
        ? won(t, /결제\s*금액\s*[:：]?\s*(?:KRW\s*)?([0-9,]+)/i)
        : 0;
      const firstTravelDate = firstGroup(
        t,
        /([0-9]{4}-[0-9]{2}-[0-9]{2})[^\n]{0,80}출발/
      );
      const route = firstGroup(
        t,
        /[0-9]{4}-[0-9]{2}-[0-9]{2}\s+([^\n]{1,80}?출발\s*-\s*[^\n]{1,80}?도착)/
      );
      return {
        source: 'skyticket',
        type: isAutoCancel ? 'cancel_no_charge' :
              isPurchased ? 'charge' : 'evidence_only',
        bookingNo: applicationNo,
        merchant: 'SKYTICKET',
        item: '항공권' + (route ? ' ' + route : ''),
        useDate: ymd2(firstTravelDate),
        paidDate: m.date,
        currency: 'KRW',
        amount: isPurchased ? amount : 0,
        card: '',
        account: '여비교통비',
      };
    },
  },

  // ── 범용 폴백 (반드시 마지막) ──
  //  전달계정 메일은 다음(Daum)에서 이미 선별됐으므로 매칭 파서가 없어도 버리지 않는다.
  //  금액·예약번호·취소여부를 휴리스틱으로 뽑고, 실패해도 제목·발신자를 기록해 누락 0을 보장.
  {
    id: 'generic',
    match: function () { return true; },
    parse: function (m) {
      const trustedKcp = /admin8\.kcp\.co\.kr/i.test(m.body);
      const kcpOrder = trustedKcp ? firstGroup(m.body, /[?&]order_no=([A-Z0-9_-]+)/i) : '';
      const kcpPayment = trustedKcp ? firstGroup(m.body, /[?&]tno=([0-9]+)/i) : '';
      const kcpAmount = trustedKcp ? won(m.body, /[?&]trade_mony=([0-9]+)/i) : 0;
      if (kcpOrder || kcpPayment) {
        return {
          source: 'generic',
          type: 'evidence_only',
          merchant: 'KCP 거래명세서',
          item: 'order_id=' + kcpOrder + ';payment_id=' + kcpPayment,
          paidDate: m.date,
          currency: 'KRW',
          amount: kcpAmount,
          bookingNo: kcpOrder,
          card: '',
        };
      }
      const isCancel = /취소|환불|refund|cancel/i.test(m.subject);
      const krw = won(m.body, /(?:결제|승인|합계|총)\s*(?:금액|요금)?[^\d\-]{0,12}([0-9][0-9,]{2,})\s*원/) ||
                  won(m.body, /(?:KRW|₩)\s*([0-9][0-9,]{2,})/) ||
                  Math.round(decimalKrw_(m.body, /(?:결제액|결제금액|합계|총액)[\s\S]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*KRW/i));
      const jpy = won(m.body, /(?:JPY|¥|￥)\s*([0-9][0-9,]{2,})/);
      const book = firstGroup(m.subject + '\n' + m.body,
        /(?:예약\s*번호|주문\s*번호|승인\s*번호|booking\s*(?:id|number)|reservation)\s*[:#]?\s*([A-Z0-9\-]{6,20})/i);
      const senderName = (m.from.match(/^"?([^"<]+?)"?\s*</) || [,''])[1].trim();
      return {
        source: 'generic',
        type: isCancel ? 'refund' : 'charge',
        merchant: senderName || m.from,
        item: (m.subject || '').slice(0, 80),
        paidDate: m.date,
        currency: jpy && !krw ? 'JPY' : 'KRW',
        amount: (isCancel ? -1 : 1) * (krw || jpy || 0),
        bookingNo: book || '',
        card: '',
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
  const q = senderQuery_('-label:' + GMAIL_CFG.DONE_LABEL);
  const threads = GmailApp.search(q, 0, 30);
  let seen = 0, parsed = 0, skipped = 0;
  Logger.log('쿼리: %s  (스레드 %s개)', q, threads.length);
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
function ingestPaymentEmails(e) {
  // 자동(시간)트리거 발화이고 AUTO_DRAIN=false면 아무것도 안 하고 종료. 수동 메뉴실행(e 없음)은 정상 동작.
  if (e && e.triggerUid && !GMAIL_CFG.AUTO_DRAIN) {
    console.log('AUTO_DRAIN=false — 자동 수집 트리거 무시(수동 실행만 허용).');
    return;
  }
  const sheet = openStaging_();
  const seen = loadSeenMessageIds_(sheet);
  const doneLabel = getOrCreateLabel_(GMAIL_CFG.DONE_LABEL);
  const q = senderQuery_('-label:' + GMAIL_CFG.DONE_LABEL);   // 라벨 무관 발신자 검색 + 미처리분만
  const start = new Date().getTime();
  let added = 0, skipped = 0, batches = 0, threadsDone = 0;

  // backlog가 수년치라 한 번에 못 끝냄 → 시간 예산 안에서 배치(100스레드)를 반복.
  //  각 배치는 처리 후 '처리완료' 라벨을 붙여 다음 검색에서 제외(멱등/증분).
  while (new Date().getTime() - start < GMAIL_CFG.TIME_BUDGET_MS) {
    const threads = GmailApp.search(q, 0, GMAIL_CFG.MAX_THREADS);
    if (!threads.length) break;                              // 미처리분 소진
    threads.forEach(function (thread) {
      thread.getMessages().forEach(function (gm) {
        const m = {
          id: gm.getId(), from: gm.getFrom(), subject: gm.getSubject(),
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
      threadsDone++;
    });
    batches++;
  }

  const drained = GmailApp.search(q, 0, 1).length === 0;
  toast('메일 수집 ' + added + '건 (스킵 ' + skipped + ') · 스레드 ' + threadsDone +
        ' / ' + batches + '배치' + (drained ? ' · 전량 완료' : ' · 남음(다시 실행)'));
}

// ─────────────────────────────────────────────────────────────
// 메일 점검(커버리지 감사) — 결제 메일이 Gmail에 충분히 유입됐고 파이프라인에 도달했는지 대조.
//  '메일점검' 탭에: 발신자 그룹별 [총 스레드 · 처리완료(파싱시도) · 미처리], 계정별 유입 범위·건수,
//  월별 유입건수(빈 달 = backlog 누락 신호), '메일수집' 실제 기록수를 리포트.
//  → 미처리>0이면 '메일 수집'을 (전량 완료 뜰 때까지) 재실행하면 됨.
// ─────────────────────────────────────────────────────────────
function auditMailCoverage() {
  const ss = SpreadsheetApp.openById(GMAIL_CFG.STAGING.id);
  const sh = ensureTab_(ss, '메일점검');
  sh.clearContents();
  const acctsQ = '{' + MAIL_ACCOUNTS.map(function (a) { return 'to:' + a; }).join(' OR ') + '}';
  let r = 1;
  const write = function (vals, bold) {
    if (!vals || !vals.length) { r++; return; }          // 빈 스페이서 행 — 범위 0열 방지
    sh.getRange(r, 1, 1, vals.length).setValues([vals]);
    if (bold) sh.getRange(r, 1, 1, vals.length).setFontWeight('bold');
    r++;
  };

  write(['메일 점검 — 생성 ' + today_()], true);
  write([]);
  // 1) 계정별 유입 범위(가장 오래된/최신) + 총 건수
  write(['① 계정별 유입', '총 스레드', '가장 오래된', '가장 최신', '처리완료', '미처리'], true);
  MAIL_ACCOUNTS.forEach(function (a) {
    const base = 'to:' + a + ' {' + PAY_SENDERS.map(function (s) { return '(' + s.q + ')'; }).join(' OR ') + '}';
    const tot = gcount_(base);
    const done = gcount_(base + ' label:' + GMAIL_CFG.DONE_LABEL);
    const oldest = edge_(base, true), newest = edge_(base, false);
    write([a, tot.label, oldest, newest, done.label, (tot.n - done.n) + (tot.capped ? '+' : '')]);
  });
  write([]);
  // 2) 발신자 그룹별 커버리지(두 계정 합산)
  write(['② 발신자 그룹', '총 스레드', '처리완료(파싱시도)', '미처리', '판정'], true);
  PAY_SENDERS.forEach(function (s) {
    const base = '(' + s.q + ') ' + acctsQ;
    const tot = gcount_(base);
    const done = gcount_(base + ' label:' + GMAIL_CFG.DONE_LABEL);
    const pend = tot.n - done.n;
    const verdict = tot.n === 0 ? '유입 없음(발신주소 확인)' : pend > 0 ? '미처리 ' + pend + '건 — 수집 재실행' : '완료';
    write([s.group, tot.label, done.label, pend + (tot.capped ? '+' : ''), verdict]);
  });
  write([]);
  // 3) 월별 유입(최근 24개월) — 빈 달은 backlog 누락 신호
  write(['③ 월별 유입(결제발신자, 두 계정 합산)', '스레드'], true);
  const now = new Date();
  const baseAll = '{' + PAY_SENDERS.map(function (s) { return '(' + s.q + ')'; }).join(' OR ') + '} ' + acctsQ;
  for (let i = 0; i < 24; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const d2 = new Date(now.getFullYear(), now.getMonth() - i + 1, 1);
    const q = baseAll + ' after:' + ymdSlash_(d) + ' before:' + ymdSlash_(d2);
    const c = gcount_(q);
    write([ym_(d), c.label]);
  }
  write([]);
  // 4) '메일수집' 실제 기록수
  const stg = ss.getSheetByName(GMAIL_CFG.STAGING.sheetName);
  const stgN = stg ? Math.max(0, stg.getLastRow() - 1) : 0;
  write(['④ 메일수집 탭 기록수', stgN + '건 (파서가 결제로 인식·구조화한 건. 알림·중복 제외라 총 유입보다 훨씬 적은 게 정상)'], true);
  sh.setColumnWidth(1, 260); for (let c = 2; c <= 6; c++) sh.setColumnWidth(c, 130);
  toast('메일 점검 완료 — "메일점검" 탭 확인. 미처리>0인 그룹은 "메일 수집" 재실행.');
}

// 검색 결과 개수(페이지네이션, cap 상한). {n, capped, label} 반환.
function gcount_(q, cap) {
  cap = cap || 5000;
  let n = 0, start = 0, page;
  do { page = GmailApp.search(q, start, 500); n += page.length; start += page.length; }
  while (page.length === 500 && start < cap);
  const capped = page.length === 500 && start >= cap;
  return { n: n, capped: capped, label: n + (capped ? '+' : '') };
}
// 가장 오래된/최신 스레드 날짜. GmailApp은 최신순 → oldest는 마지막 페이지에서.
function edge_(q, oldest) {
  if (oldest) {
    const c = gcount_(q, 5000);
    if (!c.n) return '';
    const idx = Math.max(0, c.n - 1);
    const pg = GmailApp.search(q, Math.floor(idx / 500) * 500, 500);
    const t = pg[pg.length - 1];
    return t ? Utilities.formatDate(t.getLastMessageDate(), 'Asia/Seoul', 'yyyy-MM-dd') : '';
  }
  const pg = GmailApp.search(q, 0, 1);
  return pg.length ? Utilities.formatDate(pg[0].getLastMessageDate(), 'Asia/Seoul', 'yyyy-MM-dd') : '';
}
function ensureTab_(ss, name) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  return sh;
}
function ymdSlash_(d) { return d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate(); }
function ym_(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1); }
function today_() { return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd'); }

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
// HTML 메일은 예약번호 숫자 사이에 zero-width 문자를 삽입하는 경우가 있다.
// 모든 공통 추출 함수가 같은 정규화된 텍스트를 보게 해 특정 OTA별 누락을 막는다.
function normalizeMailText_(t) {
  return String(t || '').replace(/[\u200B-\u200D\u2060\uFEFF]/g, '');
}
function firstGroup(t, re) { const m = normalizeMailText_(t).match(re); return m ? m[1].trim() : ''; }
function after(t, re) { const m = normalizeMailText_(t).match(re); return m ? m[1] : ''; }
function line(t, re) { const m = normalizeMailText_(t).match(re); return m ? m[1].replace(/\t/g, ' ').trim() : ''; }
function won(t, re) { const m = normalizeMailText_(t).match(re); return m ? num(m[1]) : 0; }
function decimalKrw_(t, re) {
  const m = normalizeMailText_(t).match(re);
  return m ? Number(String(m[1]).replace(/,/g, '')) : 0;
}
function decimalKrwValues_(t) {
  const values = []; const re = /([0-9][0-9,]*(?:\.[0-9]+)?)\s*KRW/ig;
  let m;
  while ((m = re.exec(normalizeMailText_(t))) !== null) values.push(Number(m[1].replace(/,/g, '')));
  return values;
}
function mytripDate_(t, paidDate) {
  const m = normalizeMailText_(t).match(
    /\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*([0-9]{1,2})\s+([A-Za-z]+)(?:\s+([0-9]{4}))?/i
  );
  if (!m) return '';
  const months = {
    jan:1,january:1,feb:2,february:2,mar:3,march:3,apr:4,april:4,
    may:5,jun:6,june:6,jul:7,july:7,aug:8,august:8,sep:9,september:9,
    oct:10,october:10,nov:11,november:11,dec:12,december:12,
  };
  const month = months[m[2].toLowerCase()];
  const year = m[3] || firstGroup(paidDate, /^([0-9]{4})/);
  return month && year ? year + '-' + pad(month) + '-' + pad(m[1]) : '';
}
function bookingDate_(t, paidDate) {
  const full = firstGroup(
    t,
    /체크인[:\s]*([0-9]{4}년\s*[0-9]{1,2}월\s*[0-9]{1,2}일)/
  );
  if (full) return ymd2(full);
  const flight = normalizeMailText_(t).match(
    /(?:발|행|\n)\s*([0-9]{1,2})월\s*([0-9]{1,2})일\s*\([^)]+\)\s*[·•]?\s*[0-9]{1,2}:[0-9]{2}/
  ) || normalizeMailText_(t).match(
    /([0-9]{1,2})월\s*([0-9]{1,2})일\s*\([^)]+\)\s*[·•]?\s*[0-9]{1,2}:[0-9]{2}/
  );
  const year = firstGroup(paidDate, /^([0-9]{4})/);
  return flight && year
    ? year + '-' + pad(flight[1]) + '-' + pad(flight[2])
    : '';
}
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
  const cur = /¥|JPY/i.test(seg) ? 'JPY' : /€|EUR/i.test(seg) ? 'EUR' :
              /₩|KRW|원/.test(seg) ? 'KRW' : /฿|THB/i.test(seg) ? 'THB' :
              /\$|USD/i.test(seg) ? 'USD' : '';
  const n = seg.match(/([0-9][0-9,]*(?:\.[0-9]+)?)/);   // 천단위콤마 + 소수점(EUR 등)
  return { amount: n ? num(n[1]) : 0, currency: cur };
}
function endate(t, re) {
  const g = firstGroup(t, re);
  const M = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
  let m = g.match(/([A-Za-z]+)\s+([0-9]{1,2}),?\s*([0-9]{4})/);   // July 8, 2026
  if (m && M[m[1]]) return m[3] + '-' + pad(M[m[1]]) + '-' + pad(m[2]);
  m = g.match(/([0-9]{1,2})\s+([A-Za-z]+)\s+([0-9]{4})/);         // 8 July 2026 (영국식)
  return m && M[m[2]] ? m[3] + '-' + pad(M[m[2]]) + '-' + pad(m[1]) : '';
}
