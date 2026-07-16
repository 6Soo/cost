// ─────────────────────────────────────────────────────────────
// PinLinks.gs — 부킹닷컴 PIN 내장 딥링크 생성 (사용자 본인 계정에서 실행)
//
// 무엇을 하나:
//  1) collectBookingPins():
//     내 지메일에서 부킹닷컴 확정메일을 스캔해 (예약번호, PIN) 쌍을 추출하고,
//     진행장부 스프레드시트에 'BookingPIN' 탭을 만들어
//     [예약번호 | PIN | 바로가기(로그인 불필요) | 호텔 | 수집일] 를 기록한다.
//     바로가기 = https://secure.booking.com/mybooking.html?bn=예약번호&pincode=PIN&lang=ko
//     → 계정·이메일 표기와 무관하게 권한벽 없이 예약 상세가 열린다.
//  2) applyPinLinks(spreadsheetId):
//     지정한 스프레드시트(예: 비용분류 워크북을 시트로 올린 사본)의 모든 탭에서
//     '예약번호' 열의 10자리 부킹 번호를 찾아 PIN 내장 링크로 하이퍼링크를 교체한다.
//
// ⚠ 보안 주의: PIN이 적힌 시트/파일은 예약 열람·변경 권한 그 자체입니다.
//   외부(세무법인 등)에 전달할 사본에서는 BookingPIN 탭을 지우거나
//   applyPinLinks를 적용하지 않은 원본을 쓰세요.
// ─────────────────────────────────────────────────────────────

const PIN_CFG = {
  LEDGER_ID: '1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU',  // 진행장부
  SINCE: '2026/01/01',
  SHEET: 'BookingPIN',
};

// 1) 지메일 → (예약번호, PIN) 수집
function collectBookingPins() {
  const q = '{from:booking.com from:booking from:부킹닷컴} after:' + PIN_CFG.SINCE;
  const found = {};   // resno -> {pin, hotel, date}
  let start = 0;
  while (true) {
    const threads = GmailApp.search(q, start, 100);
    if (!threads.length) break;
    threads.forEach(function (th) {
      th.getMessages().forEach(function (gm) {
        const body = gm.getPlainBody() || '';
        const subj = gm.getSubject() || '';
        // 본문에서 예약번호·PIN 쌍 추출 (여러 예약이 한 메일에 있을 수 있어 블록 단위로)
        const re = /예약\s*번호[^\d]{0,20}(\d{10})[\s\S]{0,300}?PIN[^\d]{0,20}(\d{4})/g;
        let m;
        while ((m = re.exec(body)) !== null) {
          if (!found[m[1]]) {
            found[m[1]] = { pin: m[2], hotel: subj.replace(/\[.*?\]\s*/g, '').slice(0, 40),
                            date: Utilities.formatDate(gm.getDate(), 'Asia/Seoul', 'yyyy-MM-dd') };
          }
        }
        // 영문 포맷 보조
        const re2 = /(?:confirmation|booking)\s*(?:number|no\.?)[^\d]{0,20}(\d{10})[\s\S]{0,300}?PIN\s*(?:code)?[^\d]{0,20}(\d{4})/gi;
        while ((m = re2.exec(body)) !== null) {
          if (!found[m[1]]) {
            found[m[1]] = { pin: m[2], hotel: subj.slice(0, 40),
                            date: Utilities.formatDate(gm.getDate(), 'Asia/Seoul', 'yyyy-MM-dd') };
          }
        }
      });
    });
    start += 100;
    if (start > 2000) break;   // 안전 상한
  }

  const ss = SpreadsheetApp.openById(PIN_CFG.LEDGER_ID);
  let sh = ss.getSheetByName(PIN_CFG.SHEET);
  if (!sh) sh = ss.insertSheet(PIN_CFG.SHEET);
  sh.clear();
  sh.appendRow(['예약번호', 'PIN', '바로가기(로그인 불필요)', '호텔(메일제목)', '수집메일일',
                '⚠ 이 탭이 있는 파일을 외부에 공유하지 마세요']);
  const rows = Object.keys(found).sort().map(function (no) {
    const f = found[no];
    const url = 'https://secure.booking.com/mybooking.html?bn=' + no + '&pincode=' + f.pin + '&lang=ko';
    return [no, f.pin, '=HYPERLINK("' + url + '","예약 열기")', f.hotel, f.date, ''];
  });
  if (rows.length) sh.getRange(2, 1, rows.length, 6).setValues(rows);
  sh.setFrozenRows(1);
  Logger.log('부킹 예약 %s건의 PIN 수집 완료 → %s 탭', rows.length, PIN_CFG.SHEET);
}

// 2) 다른 스프레드시트의 '예약번호' 열에 PIN 링크 일괄 적용
//    사용: applyPinLinks('대상 스프레드시트 ID')
function applyPinLinks(spreadsheetId) {
  const ledger = SpreadsheetApp.openById(PIN_CFG.LEDGER_ID);
  const pinSh = ledger.getSheetByName(PIN_CFG.SHEET);
  if (!pinSh) throw new Error('먼저 collectBookingPins()를 실행하세요.');
  const pins = {};
  pinSh.getDataRange().getValues().slice(1).forEach(function (r) {
    if (r[0] && r[1]) pins[String(r[0])] = String(r[1]);
  });

  const target = SpreadsheetApp.openById(spreadsheetId);
  let applied = 0;
  target.getSheets().forEach(function (sh) {
    const vals = sh.getDataRange().getValues();
    if (!vals.length) return;
    const head = vals[0].map(String);
    const col = head.indexOf('예약번호');
    if (col < 0) return;
    for (let i = 1; i < vals.length; i++) {
      const no = String(vals[i][col] || '').trim();
      if (/^\d{10}$/.test(no) && pins[no]) {
        const url = 'https://secure.booking.com/mybooking.html?bn=' + no + '&pincode=' + pins[no] + '&lang=ko';
        sh.getRange(i + 1, col + 1)
          .setRichTextValue(SpreadsheetApp.newRichTextValue().setText(no).setLinkUrl(url).build());
        applied++;
      }
    }
  });
  Logger.log('PIN 링크 %s건 적용 완료 (대상: %s)', applied, target.getName());
}
