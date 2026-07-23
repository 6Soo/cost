// ─────────────────────────────────────────────────────────────
// 입금 동기화 (②-B) — 수기장부 '수입 내용' → 예약앱 대장 명단 payment_status
//
// 사람이 여행탭 '수입 내용' 섹션(거래일자·이름·닉네임·예약금·잔금·추가금·금액)에
// 손으로 적은 입금을, 예약앱(reservation)의 대장 명단 입금 상태로 밀어 넣는다.
// 신규 인프라 0 — 예약앱의 내부 API(/api/internal/tours, /api/internal/payments)만 호출.
//
// 입금 상태 판정(예약앱 쪽): 잔금 입금→완납, 예약금만→예약금, 금액만→완납(일시납).
// 상태는 앞으로만 승급한다(관리자 완납 처리를 되돌리지 않음).
//
// Script Properties (파일 > 프로젝트 설정 > 스크립트 속성):
//   RESERVE_API_URL     예: https://reserve.foresttour.kr   (STATS_URL과 같은 호스트)
//   INTERNAL_API_TOKEN  예약앱의 INTERNAL_API_TOKEN과 동일 값 (STATS_SECRET과는 다른 값!)
//
// 수동 실행: syncPaymentsToLeader()  ·  자동(하루 1회): setupPaymentSyncTrigger()
// ─────────────────────────────────────────────────────────────

function syncPaymentsToLeader() {
  const props = PropertiesService.getScriptProperties();
  const base = (props.getProperty('RESERVE_API_URL') || '').replace(/\/+$/, '');
  const token = props.getProperty('INTERNAL_API_TOKEN') || '';
  if (!base || token.length < 16) throw new Error('RESERVE_API_URL / INTERNAL_API_TOKEN 미설정');

  const tours = fetchLeaderTours_(base, token);
  if (!tours) throw new Error('여행 목록을 가져오지 못했습니다 (URL/토큰 확인)');

  const ss = SpreadsheetApp.openById(CONFIG.TARGET_LEDGER_ID);
  const summary = [];
  ss.getSheets().forEach(function (sh) {
    const tabName = sh.getName();
    const m = tabName.match(/^(\d{4})_(.+)$/);   // 'MMDD_지역' 탭만 (템플릿·_C·기타 탭 제외)
    if (!m) return;
    const fldid = matchLeaderTour_(tours, m[1], m[2]);
    if (!fldid) { summary.push('· ' + tabName + ' — 예약앱 여행 매칭 실패(건너뜀)'); return; }
    const payments = parseIncomeSection_(sh);
    if (!payments.length) return;                // 수입 섹션·입금행 없으면 조용히 건너뜀
    const res = postLeaderPayments_(base, token, fldid, payments);
    if (!res) { summary.push('· ' + tabName + ' — 전송 실패'); return; }
    var line = '· ' + tabName + ' — 반영 ' + res.updated + '건';
    if (res.unmatched && res.unmatched.length) line += ' / 미매칭 ' + res.unmatched.length + '명(' + res.unmatched.join(',') + ')';
    if (res.ambiguous && res.ambiguous.length) line += ' / 동명이인 ' + res.ambiguous.length + '명';
    summary.push(line);
  });

  const msg = summary.length ? summary.join('\n') : '처리할 입금이 없습니다.';
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert('입금 동기화 결과\n\n' + msg); } catch (e) { /* 트리거 등 UI 없음 → 로그만 */ }
  return msg;
}

// 하루 1회(오전 9시) 자동 동기화 트리거 설치 (1회 실행)
function setupPaymentSyncTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncPaymentsToLeader') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncPaymentsToLeader').timeBased().everyDays(1).atHour(9).create();
}

// ── 헬퍼 ─────────────────────────────────────────────────────

function fetchLeaderTours_(base, token) {
  try {
    const res = UrlFetchApp.fetch(base + '/api/internal/tours', {
      headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) return null;
    return (JSON.parse(res.getContentText()).tours) || [];
  } catch (e) { return null; }
}

// 장부 탭 'MMDD_지역' → 예약앱 여행 fldid. 출발일 MMDD 우선, 지역(코드 꼬리) 보조.
function matchLeaderTour_(tours, mmdd, region) {
  var hit = null;
  tours.forEach(function (t) {
    if (hit) return;
    var dmmdd = String(t.depart_date || '').replace(/^\d{4}-(\d{2})-(\d{2}).*/, '$1$2');
    var codeTail = String(t.code || '').replace(/^\d{8}_/, '');
    if (dmmdd === mmdd || (codeTail && codeTail === region)) hit = t.fldid;
  });
  return hit;
}

// 여행탭 '수입 내용' 섹션 파싱. 헤더행은 '예약금'과 '잔금'을 함께 가진 행으로 찾는다
// (지출 섹션의 '증빙유형·금액' 헤더와 구분). 열 순서가 바뀌어도 헤더 키워드로 매핑한다.
function parseIncomeSection_(sheet) {
  const v = sheet.getDataRange().getValues();
  var hdr = -1;
  for (var r = 0; r < v.length; r++) {
    var row = v[r].map(function (x) { return String(x); });
    var hasDeposit = row.some(function (h) { return h.indexOf('예약금') >= 0; });
    var hasBalance = row.some(function (h) { return h.indexOf('잔금') >= 0; });
    if (hasDeposit && hasBalance) { hdr = r; break; }
  }
  if (hdr < 0) return [];
  const H = v[hdr].map(function (x) { return String(x); });
  const find = function (kw) { return H.findIndex(function (h) { return h.indexOf(kw) >= 0; }); };
  const ci = {
    date: find('거래일자'), name: find('이름'), nick: find('닉네임'),
    deposit: find('예약금'), balance: find('잔금'), additional: find('추가금'), total: find('금액'),
  };
  if (ci.name < 0) return [];

  const out = [];
  for (var rr = hdr + 1; rr < v.length; rr++) {
    var vals = v[rr];
    if (!String(vals.join('')).trim()) continue;   // 공백 행 허용(섹션 중간 빈 줄)
    // 지출 섹션 시작·합계행을 만나면 수입 섹션 끝
    if (vals.some(function (x) { return /지출\s*내용|증빙유형|총\s*금액|합\s*계/.test(String(x)); })) break;
    var name = ci.name >= 0 ? String(vals[ci.name]).trim() : '';
    var nick = ci.nick >= 0 ? String(vals[ci.nick]).trim() : '';
    if (!name && !nick) continue;                   // 이름·닉네임 둘 다 없으면 데이터행 아님
    out.push({
      name: name, nickname: nick,
      date: ci.date >= 0 ? fmtDate_(vals[ci.date]) : '',
      deposit: ci.deposit >= 0 ? amt_(vals[ci.deposit]) : 0,
      balance: ci.balance >= 0 ? amt_(vals[ci.balance]) : 0,
      additional: ci.additional >= 0 ? amt_(vals[ci.additional]) : 0,
      total: ci.total >= 0 ? amt_(vals[ci.total]) : 0,
    });
  }
  return out;
}

function postLeaderPayments_(base, token, fldid, payments) {
  try {
    const res = UrlFetchApp.fetch(base + '/api/internal/payments', {
      method: 'post', contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token },
      payload: JSON.stringify({ tourFldid: fldid, payments: payments }),
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) return null;
    return JSON.parse(res.getContentText());
  } catch (e) { return null; }
}

function amt_(v) {
  if (typeof v === 'number') return isNaN(v) ? 0 : Math.round(v);
  var n = parseInt(String(v == null ? '' : v).replace(/[^\d-]/g, ''), 10);
  return isNaN(n) ? 0 : n;
}

function fmtDate_(v) {
  if (Object.prototype.toString.call(v) === '[object Date]') {
    return Utilities.formatDate(v, 'Asia/Seoul', 'yyyy-MM-dd');
  }
  return String(v == null ? '' : v).trim();
}
