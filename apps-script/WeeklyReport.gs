// ─────────────────────────────────────────────────────────────
// 주간 경영 리포트 (foresttour R3-2)
// 매주 월요일 아침, 투어별 [모객·입금(예약 시스템) × 지출(이 장부)] 스냅샷을
// 이메일 한 통으로 보낸다. 신규 인프라 0 — 예약 시스템의 /api/stats와
// 진행 장부의 _C 탭 합계를 조립만 한다.
//
// Script Properties (파일 > 프로젝트 설정 > 스크립트 속성):
//   STATS_URL     예: https://reserve.foresttour.kr/api/stats
//   STATS_SECRET  예약 시스템의 CRON_SECRET과 동일 값
//   REPORT_TO     수신 이메일 (쉼표로 여러 명)
//
// 설치: setupWeeklyReportTrigger() 1회 실행 → 매주 월 08시.
// 수동 실행: weeklyReport()
// ─────────────────────────────────────────────────────────────

function weeklyReport() {
  const props = PropertiesService.getScriptProperties();
  const to = props.getProperty('REPORT_TO');
  if (!to) throw new Error('REPORT_TO 미설정');

  const stats = fetchStats_(props);                 // 예약 시스템 지표 (없으면 null)
  const expenses = sumLedgerExpenses_();            // 이 장부의 투어별 지출 합계

  const rows = buildReportRows_(stats, expenses);
  const html = renderReportHtml_(rows, stats);

  MailApp.sendEmail({
    to: to,
    subject: '[숲길여행] 주간 경영 리포트 — ' + Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd'),
    htmlBody: html,
  });
}

function setupWeeklyReportTrigger() {
  ScriptApp.newTrigger('weeklyReport').timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(8).create();
}

// ── 데이터 수집 ──────────────────────────────────────────────

function fetchStats_(props) {
  const url = props.getProperty('STATS_URL');
  const secret = props.getProperty('STATS_SECRET');
  if (!url || !secret) return null;
  try {
    const res = UrlFetchApp.fetch(url, {
      headers: { Authorization: 'Bearer ' + secret },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) return null;
    return JSON.parse(res.getContentText());
  } catch (e) {
    return null;   // 예약 시스템이 죽어 있어도 지출 리포트는 나간다
  }
}

// 여행탭(실탭) '지출 내용' 섹션 합계 — 2026-07-13 실탭 직접 전기 전환 이후의 현행 방식.
//  (예전엔 {탭}_C 비교탭에 자동전기했으나 지금은 실탭에 바로 기록되고 _C는 정리 대상이라,
//   _C만 찾던 예전 코드로는 deleteCompareTabs() 실행 후 전 투어 지출이 0/공백으로 나왔다.)
function sumLedgerExpenses_() {
  const out = {};   // 탭명 → 지출 섹션 합계
  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const skip = {};
  [CONFIG.STAGING.sheetName, CONFIG.RULES_TAB, CONFIG.REVIEW_TAB, AUDIT_TAB, '메일점검', 'BookingPIN']
    .forEach(function (n) { skip[n] = true; });
  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    if (skip[name] || /_C$/.test(name) || sh.getLastRow() < 2) return;
    const recs = extractLedgerRecords(sh);   // Code.gs 전역 함수 — 지출 섹션만 파싱
    if (!recs.length) return;
    let sum = 0;
    recs.forEach(function (r) { sum += r.amount; });
    out[name] = sum;
  });
  return out;
}

// ── 조립 ─────────────────────────────────────────────────────
// 매칭 키: 장부 탭명 'MMDD_지역' vs stats.tours[].code 'YYYYMMDD_지역' /
// depart_date의 MMDD. 못 맞추면 각자 단독 행으로 남긴다(누락 없이 전부 표시).

function buildReportRows_(stats, expenses) {
  const rows = [];
  const usedTabs = {};
  const tours = (stats && stats.tours) || [];

  tours.forEach(function (t) {
    let tab = null;
    const mmdd = String(t.depart_date || '').replace(/^\d{4}-(\d{2})-(\d{2}).*/, '$1$2');
    const codeTail = String(t.code || '').replace(/^\d{8}_/, '');
    Object.keys(expenses).forEach(function (tabName) {
      if (usedTabs[tabName] || tab) return;
      const m = tabName.match(/^(\d{4})_(.+)$/);
      if (!m) return;
      if (m[1] === mmdd || (codeTail && m[2] === codeTail)) tab = tabName;
    });
    if (tab) usedTabs[tab] = true;
    rows.push({
      title: t.title, depart: t.depart_date || '미정', status: t.status,
      people: t.people, unpaid: t.unpaid_bookings,
      deposit: t.deposit_people, paid: t.fully_paid_people,
      revenue: t.estimated_revenue_krw, expense: tab ? expenses[tab] : null, tab: tab,
    });
  });

  // 예약 시스템에 없는(과거/수기) 장부 탭도 지출만이라도 표시
  Object.keys(expenses).forEach(function (tabName) {
    if (usedTabs[tabName]) return;
    rows.push({ title: '(장부 탭) ' + tabName, depart: '', status: '', people: null,
                unpaid: null, deposit: null, paid: null, revenue: null,
                expense: expenses[tabName], tab: tabName });
  });
  return rows;
}

function renderReportHtml_(rows, stats) {
  const fmt = function (n) { return n == null ? '—' : Number(n).toLocaleString('ko-KR'); };
  let html = '<div style="font-family:sans-serif">';
  html += '<h2 style="margin:0 0 4px">숲길여행 주간 리포트</h2>';
  html += '<p style="color:#666;margin:0 0 12px;font-size:13px">추정 매출은 가격표×입금상태 기반(실입금 아님) · 지출은 여행탭 지출 섹션 합계';
  if (stats && stats.repeat_customer_rate_pct != null) {
    html += ' · 재방문 고객 비율 <b>' + stats.repeat_customer_rate_pct + '%</b>';
  }
  html += '</p>';
  html += '<table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;font-size:13px">';
  html += '<tr style="background:#f0f4f8"><th>투어</th><th>출발</th><th>인원</th><th>미납</th><th>잔금대기</th><th>완납</th><th>추정매출(원)</th><th>지출(원)</th><th>추정손익(원)</th></tr>';
  rows.forEach(function (r) {
    const profit = (r.revenue != null && r.expense != null) ? r.revenue - r.expense : null;
    html += '<tr><td>' + r.title + '</td><td>' + r.depart + '</td><td align="right">' + fmt(r.people) +
      '</td><td align="right">' + fmt(r.unpaid) + '</td><td align="right">' + fmt(r.deposit) +
      '</td><td align="right">' + fmt(r.paid) + '</td><td align="right">' + fmt(r.revenue) +
      '</td><td align="right">' + fmt(r.expense) + '</td><td align="right"' +
      (profit != null && profit < 0 ? ' style="color:#c00"' : '') + '><b>' + fmt(profit) + '</b></td></tr>';
  });
  html += '</table>';
  html += '<p style="color:#999;font-size:12px;margin-top:10px">자동 발송 — cost/apps-script/WeeklyReport.gs (foresttour R3-2)</p></div>';
  return html;
}
