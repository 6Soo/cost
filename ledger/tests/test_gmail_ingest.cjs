const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const context = {
  console,
  Set,
  Math,
  Number,
  JSON,
  Date,
  num: (value) => Number(String(value || 0).replace(/,/g, "")),
  digits: (value) => String(value || "").replace(/\D/g, ""),
  pad: (value) => String(value).padStart(2, "0"),
};
vm.createContext(context);
const source = fs.readFileSync("apps-script/GmailIngest.gs", "utf8");
vm.runInContext(`${source}\nglobalThis.__PARSERS = PARSERS;`, context);

const parser = context.__PARSERS.find((item) => item.id === "mytrip");
const parsed = parser.parse({
  from: "Mytrip <no-reply@support.kr.mytrip.com>",
  subject: "1122-610-807 (1) 주문에 대한 추가 서비스 영수증",
  date: "2026-06-24",
  body: [
    "서비스 수수료 - 변경 63,451.00 KRW",
    "항공료 100,336.77 KRW",
    "Thu, 25 Jun - KE2197",
    "Thu, 9 Jul - KE2198",
    "합계",
    "결제액",
    "163,787.77 KRW",
    "163,788.00 KRW",
  ].join("\n"),
});

assert.equal(parsed.bookingNo, "1122-610-807");
assert.equal(parsed.item, "항공권 변경 추가서비스 (1) 수수료 63451원 운임차액 100337원");
assert.equal(parsed.amount, 163788);
assert.equal(parsed.useDate, "2026-06-25");

const cancelPending = parser.parse({
  from: "Mytrip <no-reply@support.kr.mytrip.com>",
  subject: "Order 1080-211-623",
  date: "2025-08-28",
  body: [
    "9GR946 예약을 취소했습니다.",
    "항공권 가격에서 1인당 서비스 수수료 57681 KRW가 차감된 금액이 환불될 예정입니다.",
  ].join("\n"),
});
assert.equal(cancelPending.bookingNo, "1080-211-623");
assert.equal(cancelPending.type, "cancel_pending");
assert.equal(cancelPending.amount, 0);
assert.match(cancelPending.item, /PNR 9GR946/);
assert.match(cancelPending.item, /57681원/);

const pending = parser.parse({
  from: "Mytrip <no-reply@support.kr.mytrip.com>",
  subject: "고객님의 주문(1119-921-343)을 처리 중입니다",
  date: "2026-01-29",
  body: "주문해 주셔서 감사합니다(1119-921-343). 항공사 처리에는 최대 72시간이 소요되며 확정되면 확인 이메일을 보내드립니다.",
});
assert.equal(pending.bookingNo, "1119-921-343");
assert.equal(pending.type, "pending");
assert.equal(pending.amount, 0);

// Trip.com HTML occasionally inserts multiple kinds of invisible characters
// between reservation-number digits. They must not erase or truncate the ID.
const tripHotel = context.__PARSERS.find((item) => item.id === "trip_hotel");
const tripWithInvisibleBookingNo = tripHotel.parse({
  from: "KR_HTL_NoReply@trip.com",
  subject: "[\uC608\uC57D \uD655\uC815 \uC548\uB0B4] Test Hotel \uC608\uC57D\uC774 \uD655\uC815",
  date: "2026-05-22",
  body: [
    "\uC608\uC57D\uBC88\uD638 140082\u200B6296\u206021\uFEFF9155",
    "\uCCB4\uD06C\uC778: 2026\uB144 5\uC6D4 23\uC77C",
  ].join("\n"),
});
assert.equal(tripWithInvisibleBookingNo.bookingNo, "1400826296219155");

const kbd1029ConfirmedBooking = tripHotel.parse({
  from: "KR_HTL_NoReply@trip.com",
  subject: "[\uD2B8\uB9BD\uB2F7\uCEF4] \uB9AC\uD2C0 \uD504\uB9B0\uC2A4 \uD638\uD154 \uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-06-11",
  body: [
    "\uC608\uC57D\uBC88\uD638 1400826669398170",
    "\uCCB4\uD06C\uC778: 2026\uB144 8\uC6D4 27\uC77C",
    "\uC628\uB77C\uC778 \uC0AC\uC804 \uACB0\uC81C 1,299,640\uC6D0",
  ].join("\n"),
});
assert.equal(kbd1029ConfirmedBooking.bookingNo, "1400826669398170");
assert.equal(kbd1029ConfirmedBooking.bookingStatus, "confirmed");
assert.equal(kbd1029ConfirmedBooking.serviceStartOn, "2026-08-27");

const kbd1089ConfirmedBooking = tripHotel.parse({
  from: "KR_HTL_NoReply@trip.com",
  subject: "[\uD2B8\uB9BD\uB2F7\uCEF4] \uAC00\uB8E8\uC774\uC790\uC640 \uD638\uD154 \uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-06-18",
  body: [
    "\uC608\uC57D\uBC88\uD638 1400826831996226",
    "\uCCB4\uD06C\uC778: 2026\uB144 10\uC6D4 31\uC77C",
    "\uC628\uB77C\uC778 \uC0AC\uC804 \uACB0\uC81C 587,314\uC6D0",
  ].join("\n"),
});
assert.equal(kbd1089ConfirmedBooking.bookingStatus, "confirmed");
assert.equal(kbd1089ConfirmedBooking.serviceStartOn, "2026-10-31");

const tripFlight = context.__PARSERS.find((item) => item.id === "trip_flight");
const paymentEvidence = tripFlight.parse({
  from: "kr_flt_noreply@trip.com",
  subject: "[\uD2B8\uB9BD\uB2F7\uCEF4] \uACB0\uC81C \uC644\uB8CC \uC548\uB0B4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 140082\u200C3700455419",
});
assert.equal(paymentEvidence.type, "payment_confirmation");
assert.equal(paymentEvidence.bookingNo, "1400823700455419");
assert.equal(paymentEvidence.amount, 0);

const repeatedAmountPayment = tripFlight.parse({
  from: "kr_flt_noreply@trip.com",
  subject: "[트립닷컴] 결제 완료 안내",
  date: "2026-05-28",
  body: [
    "예약번호 1‌400‌827‌190‌108‌091",
    "총 금액",
    "383,700원",
    "출발：2026년 6월 25일 09:40, 인천국제공항",
  ].join("\n"),
});
assert.equal(repeatedAmountPayment.bookingNo, "1400827190108091");
assert.equal(repeatedAmountPayment.amount, 383700);
assert.equal(repeatedAmountPayment.useDate, "2026-06-25");

const tripHotelUpdate = tripHotel.parse({
  from: "KR_HTL_NoReply@trip.com",
  subject: "\uD638\uD154 \uC608\uC57D \uC815\uBCF4\uAC00 \uC5C5\uB370\uC774\uD2B8\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 140082\u200C0102489680",
});
assert.equal(tripHotelUpdate.type, "update");
assert.equal(tripHotelUpdate.bookingNo, "1400820102489680");
assert.equal(tripHotelUpdate.amount, 0);
assert.equal(tripHotelUpdate.serviceStartOn, undefined);

const booking = context.__PARSERS.find((item) => item.id === "booking");
const bookingNoCharge = booking.parse({
  from: "Booking.com <noreply@booking.com>",
  subject: "\uCDE8\uC18C\uB428 - Test Hotel \uC608\uC57D",
  date: "2026-04-20",
  body: [
    "\uC608\uC57D \uBC88\uD638",
    "5121231665",
    "\uCE74\uB4DC\uC5D0 \uCCAD\uAD6C\uB418\uC9C0 \uC54A\uC74C",
    "\uAE08\uC561 \u00A50",
  ].join("\n"),
});
assert.equal(bookingNoCharge.bookingNo, "5121231665");
assert.equal(bookingNoCharge.type, "cancel_no_charge");
assert.equal(bookingNoCharge.amount, 0);

const confirmedRefundableDeposit = booking.parse({
  from: "Booking.com <noreply@booking.com>",
  subject: "\uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-06-11",
  body: [
    "\uC608\uC57D \uBC88\uD638: 5502442589",
    "\uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
    "\uCCB4\uD06C\uC778 2026\uB144 8\uC6D4 27\uC77C",
    "\uBCF4\uC99D\uAE08 \uACB0\uC81C\uAC00 \uC644\uB8CC\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
    "\uCCB4\uD06C\uC544\uC6C3 \uD6C4 \uBC18\uD658\uB429\uB2C8\uB2E4",
  ].join("\n"),
});
assert.equal(confirmedRefundableDeposit.bookingStatus, "confirmed");
assert.equal(confirmedRefundableDeposit.serviceStartOn, "2026-08-27");
assert.equal(
  confirmedRefundableDeposit.settlementCondition,
  "refundable_deposit_pending",
);

const forwardedBookingSupport = booking.parse({
  from: '"뭉게구름" <kew2000@hanmail.net>',
  subject: "FW: [중요 업데이트] Motosu Phoenix Hotel 예약 건",
  date: "2025-12-20",
  body: [
    "보낸사람: Booking.com Customer Service <case@support.booking.com>",
    "Confirmation: 5324474058",
    "현재 숙소 측에 환불 가능 여부를 문의한 상태입니다.",
  ].join("\n"),
});
assert.equal(forwardedBookingSupport.bookingNo, "5324474058");
assert.equal(forwardedBookingSupport.type, "evidence_only");
assert.equal(forwardedBookingSupport.amount, 0);

const forwardedBookingFlight = booking.parse({
  from: '"강나진" <forwarder@example.com>',
  subject: "FW: 3/12~16 인천-고베 왕복 예약정보",
  date: "2026-02-24",
  body: [
    'From: "Booking.com"<noreply@booking.com>',
    "Osaka행 항공권 예약이 확정되었습니다",
    "고객 확인번호",
    "40-894243710",
    "3월 12일 (목) · 08:25 - 3월 12일 (목) · 10:10",
    "탑승객 1명 총 요금: KRW528,297.00",
  ].join("\n"),
});
assert.equal(booking.match({
  from: '"강나진" <forwarder@example.com>',
  body: forwardedBookingFlight ? "Booking.com" : "",
}), true);
assert.equal(forwardedBookingFlight.bookingNo, "40-894243710");
assert.equal(forwardedBookingFlight.useDate, "2026-03-12");

const thbReceipt = booking.parse({
  from: '"Booking.com" <noreply-payments@booking.com>',
  subject: "고객님의 영수증입니다",
  date: "2025-09-21",
  body: [
    "예약 번호",
    "5812320319",
    "체크인",
    "2025년 9월 23일 화요일",
    "2025년 9월 21일에 결제된 금액",
    "THB 972",
  ].join("\n"),
});
assert.equal(thbReceipt.bookingNo, "5812320319");
assert.equal(thbReceipt.currency, "THB");
assert.equal(thbReceipt.amount, 972);
assert.equal(thbReceipt.useDate, "2025-09-23");

const paymentOnly = booking.parse({
  from: '"Booking.com" <noreply-payments@booking.com>',
  subject: "결제가 완료되었습니다",
  date: "2026-05-18",
  body: [
    "예약번호: 5502442589",
    "Hotel Hakuba의 예약 요금이 결제되었습니다.",
    "총 지불 금액",
    "¥272,320",
  ].join("\n"),
});
assert.equal(paymentOnly.bookingNo, "5502442589");
assert.equal(paymentOnly.amount, 272320);
assert.equal(paymentOnly.currency, "JPY");
assert.equal(paymentOnly.useDate, "");

const forwardedMytrip = parser.parse({
  from: '"강나진" <forwarder@example.com>',
  subject: "FW: 4/13~16 인천-나고야 왕복 예약정보",
  date: "2026-02-21",
  body: [
    'From: "Mytrip"<no-reply@support.kr.mytrip.com>',
    "여행이 확정되었습니다. 주문 번호 1117-227-848",
    "예약이 확인되었습니다!",
    "이 이메일에 첨부된 영수증을 확인해 주시기 바랍니다.",
    "주문 상태 주문 번호",
    "확인됨",
    "1117-227-848",
    "합계",
    "1,185,597.00 KRW",
  ].join("\n"),
});
assert.equal(forwardedMytrip.bookingNo, "1117-227-848");
assert.equal(forwardedMytrip.amount, 1185597);

const generic = context.__PARSERS.find((item) => item.id === "generic");
const kcpEvidence = generic.parse({
  from: "Travelrover <receipt@example.com>",
  subject: "\uAC70\uB798\uBA85\uC138\uC11C",
  date: "2026-06-18",
  body: "https://admin8.kcp.co.kr/x?tno=26793065420473&order_no=TRV19794858&trade_mony=30970",
});
assert.equal(kcpEvidence.type, "evidence_only");
assert.equal(kcpEvidence.bookingNo, "TRV19794858");
assert.equal(kcpEvidence.amount, 30970);

const skyticket = context.__PARSERS.find((item) => item.id === "skyticket");
const skyticketPurchased = skyticket.parse({
  from: "SKYTICKET <info@skyticket.com>",
  subject: "\u3010skyticket\u3011\uAD6C\uC785 \uC644\uB8CC \uC548\uB0B4\u3010\uC2E0\uCCAD\uBC88\uD638\uFF1A32071283\u3011",
  date: "2026-05-27",
  body: [
    "\u3010\uBCF8 \uBA54\uC77C\uB85C \uAD6C\uC785\uC774 \uC644\uB8CC\uB429\uB2C8\uB2E4.\u3011",
    "\u25CF\uC2E0\uCCAD\uBC88\uD638 32071283",
    "2026-11-27 \uD6C4\uCFE0\uC624\uCE74 \uCD9C\uBC1C - \uC57C\uCFE0\uC2DC\uB9C8 \uB3C4\uCC29",
    "2026-11-30 \uC57C\uCFE0\uC2DC\uB9C8 \uCD9C\uBC1C - \uD6C4\uCFE0\uC624\uCE74 \uB3C4\uCC29",
    "1 \uD56D\uACF5\uB8CC \uD569\uACC4 : KRW 395,506",
    "2 \uD56D\uACF5\uB8CC \uD569\uACC4 : KRW 395,506",
    "\uACB0\uC81C \uAE08\uC561\uFF1AKRW 791,012",
  ].join("\n"),
});
assert.equal(skyticketPurchased.type, "charge");
assert.equal(skyticketPurchased.bookingNo, "32071283");
assert.equal(skyticketPurchased.amount, 791012);
assert.equal(skyticketPurchased.useDate, "2026-11-27");

const skyticketAutoCancelled = skyticket.parse({
  from: "SKYTICKET <info@skyticket.com>",
  subject: "\u3010skyticket\u3011\uC790\uB3D9\uCDE8\uC18C \uC548\uB0B4\u3010\uC2E0\uCCAD\uBC88\uD638\uFF1A31731557\u3011",
  date: "2026-03-01",
  body: "\uACB0\uC81C\uAE30\uD55C\uC774 \uC9C0\uB098 \uC790\uB3D9\uC801\uC73C\uB85C \uCDE8\uC18C\uB418\uC5C8\uC2B5\uB2C8\uB2E4. \uACB0\uC81C\uC804 \uCDE8\uC18C\uC2DC\uB294 \uC218\uC218\uB8CC\uAC00 \uBC1C\uC0DD\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.",
});
assert.equal(skyticketAutoCancelled.type, "cancel_no_charge");
assert.equal(skyticketAutoCancelled.amount, 0);

const bookingFailed = booking.parse({
  from: "Booking.com <noreply-payments@booking.com>",
  subject: "\uC608\uC57D \uC694\uAE08\uC744 \uC9C0\uAE08 \uACB0\uC81C\uD574 \uC8FC\uC138\uC694",
  date: "2026-04-20",
  body: [
    "\uC608\uC57D\uBC88\uD638 6304757512",
    "\uACB0\uC81C \uAE08\uC561 \uCCAD\uAD6C\uC5D0 \uC2E4\uD328",
    "\uCD1D \uACB0\uC81C \uAE08\uC561 \u00A5267,264",
  ].join("\n"),
});
assert.equal(bookingFailed.type, "payment_failed");
assert.equal(bookingFailed.bookingNo, "6304757512");
assert.equal(bookingFailed.amount, 0);
assert.equal(bookingFailed.currency, "JPY");
assert.match(bookingFailed.item, /267264/);

const bookingPayAtProperty = booking.parse({
  from: "Booking.com <noreply@booking.com>",
  subject: "\uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: [
    "\uC608\uC57D\uBC88\uD638 6304757513",
    "\uC120\uACB0\uC81C\uAC00 \uD544\uC694 \uC5C6\uC2B5\uB2C8\uB2E4. \uC219\uC18C\uC5D0\uC11C \uACB0\uC81C",
    "\uCD1D \uACB0\uC81C \uAE08\uC561 \u00A5267,264",
  ].join("\n"),
});
assert.equal(bookingPayAtProperty.type, "pay_at_property");
assert.equal(bookingPayAtProperty.amount, 0);

const bookingScheduled = booking.parse({
  from: "Booking.com <noreply-payments@booking.com>",
  subject: "\uACB0\uC81C \uC77C\uC815\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 6304757514\n\uC790\uB3D9 \uCCAD\uAD6C \uC608\uC815 \uAE08\uC561 \u00A5267,264",
});
assert.equal(bookingScheduled.type, "payment_scheduled");
assert.equal(bookingScheduled.amount, 0);
assert.equal(bookingScheduled.currency, "JPY");
assert.match(bookingScheduled.item, /267264/);

const bookingHoldPossible = booking.parse({
  from: "Booking.com <noreply@booking.com>",
  subject: "\uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 6304757515\n\uC219\uC18C\uAC00 \uBCF4\uC99D\uAE08\uC744 \uCCAD\uAD6C\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uAE08\uC561 \u00A510,000",
});
assert.equal(bookingHoldPossible.type, "authorization_hold_possible");
assert.equal(bookingHoldPossible.amount, 0);

// The real Booking template combines pay-at-property terms with a possible
// card hold. The booking total is due at the property, not a captured hold.
const bookingPayAtPropertyWithPossibleHold = booking.parse({
  from: "Booking.com <noreply@booking.com>",
  subject: "\uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: [
    "\uC608\uC57D\uBC88\uD638 5895361455",
    "The Gran Resort Elegante Shirahama\uC5D0\uC11C \uACB0\uC81C\uD558\uC2DC\uBA74 \uB429\uB2C8\uB2E4",
    "\uD569\uACC4 \u00A5129,002",
    "\uC120\uACB0\uC81C\uAC00 \uD544\uC694 \uC5C6\uC2B5\uB2C8\uB2E4. \uC219\uC18C \uCE21\uC5D0\uC11C \uC608\uC57D \uC2DC \uC0AC\uC6A9\uD55C \uCE74\uB4DC\uB85C \uBCF4\uC99D\uAE08\uC744 \uCCAD\uAD6C\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
    "\uCCAD\uAD6C\uB41C \uAE08\uC561\uC740 \uC7A0\uC2DC \uBB36\uC5EC\uC788\uB294 \uC0C1\uD0DC\uC77C \uBFD0\uC774\uBA70, \uC804\uC561 \uD658\uBD88\uB420 \uC608\uC815\uC785\uB2C8\uB2E4.",
  ].join("\n"),
});
assert.equal(bookingPayAtPropertyWithPossibleHold.type, "pay_at_property");
assert.equal(bookingPayAtPropertyWithPossibleHold.amount, 0);
assert.equal(bookingPayAtPropertyWithPossibleHold.currency, "JPY");
assert.match(bookingPayAtPropertyWithPossibleHold.item, /129002/);
assert.match(bookingPayAtPropertyWithPossibleHold.item, /\uCE74\uB4DC\uC0AC\uC804\uC2B9\uC778 \uAC00\uB2A5/);

// "Full refund is expected" in an ordinary policy is not by itself evidence
// of an authorization hold.
const bookingRefundPolicyOnly = booking.parse({
  from: "Booking.com <noreply@booking.com>",
  subject: "\uC608\uC57D\uC774 \uD655\uC815\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 5895361456\n\uBB34\uB8CC \uCDE8\uC18C \uC2DC \uC804\uC561 \uD658\uBD88 \uC608\uC815",
});
assert.notEqual(bookingRefundPolicyOnly.type, "authorization_hold_possible");

const bookingCancelledScheduledPayment = booking.parse({
  from: "Booking.com <noreply-payments@booking.com>",
  subject: "\uCDE8\uC18C\uB428 - Test Hotel \uC608\uC57D",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 5895361457\n\uCD94\uD6C4 \uC608\uC815 \uACB0\uC81C \uCDE8\uC18C\n\uAE08\uC561 \u00A50",
});
assert.equal(bookingCancelledScheduledPayment.type, "cancel_no_charge");
assert.equal(bookingCancelledScheduledPayment.amount, 0);

const tripFlightFailed = tripFlight.parse({
  from: "kr_flt_noreply@trip.com",
  subject: "\uACB0\uC81C \uC2E4\uD328 \uC548\uB0B4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 1400823700455420\n\uACB0\uC81C \uAE08\uC561 300,000\uC6D0",
});
assert.equal(tripFlightFailed.type, "payment_failed");
assert.equal(tripFlightFailed.amount, 0);

const tripHotelRefundPending = tripHotel.parse({
  from: "KR_HTL_NoReply@trip.com",
  subject: "\uD658\uBD88\uC774 \uC2DC\uC791\uB418\uC5C8\uC2B5\uB2C8\uB2E4",
  date: "2026-04-20",
  body: "\uC608\uC57D\uBC88\uD638 1400820102489681\n\uD658\uBD88 \uAE08\uC561 100,000\uC6D0\n\uC785\uAE08\uAE4C\uC9C0 7\uC601\uC5C5\uC77C \uC18C\uC694",
});
assert.equal(tripHotelRefundPending.type, "refund_pending");
assert.equal(tripHotelRefundPending.amount, 0);

// Some completed Trip hotel refunds still retain "refund requested" and
// "1-7 business days" boilerplate. Explicit completion must win.
const tripHotelRefundCompleted = tripHotel.parse({
  from: "KR_HTL_NoReply@trip.com",
  subject: "\uC694\uCF54\uD14C \uD50C\uB77C\uC790 \uD638\uD154 \uC608\uC57D\uC774 \uBB34\uB8CC\uB85C \uCDE8\uC18C\uB418\uC5C8\uC2B5\uB2C8\uB2E4-NoReply",
  date: "2026-04-20",
  body: [
    "\uC608\uC57D\uBC88\uD638 1400826306447225",
    "\uD2B8\uB9BD\uB2F7\uCEF4\uC5D0\uC11C \uD658\uBD88\uC744 \uC694\uCCAD\uD588\uC2B5\uB2C8\uB2E4.",
    "\uD658\uBD88\uAE08\uC774 \uACC4\uC815\uC5D0 \uC785\uAE08\uB418\uB294 \uB370 \uC601\uC5C5\uC77C \uAE30\uC900 1~7\uC77C\uC774 \uC18C\uC694\uB429\uB2C8\uB2E4.",
    "\uD658\uBD88 \uAE08\uC561 68,720\uC6D0",
    "\uD658\uBD88 \uC644\uB8CC 68,720\uC6D0",
    "\uCDE8\uC18C \uC644\uB8CC",
  ].join("\n"),
});
assert.equal(tripHotelRefundCompleted.type, "refund");
assert.equal(tripHotelRefundCompleted.amount, -68720);

const mytripInfo = parser.parse({
  from: "Mytrip <info@mytrip.com>",
  subject: "\uD56D\uACF5\uD3B8 Tokyo - Okinawa: \uC5EC\uD589 \uC815\uBCF4",
  date: "2026-02-01",
  body: "\uC8FC\uBB38 \uD56D\uACF5\uD3B8 1119-921-343",
});
assert.equal(mytripInfo.type, "evidence_only");
assert.equal(mytripInfo.bookingNo, "1119-921-343");
assert.equal(mytripInfo.amount, 0);

const toss = context.__PARSERS.find((item) => item.id === "toss");
const tossPartial = toss.parse({
  from: "Toss Payments <bill@bill-mail.tosspayments.com>",
  subject: "\uBD80\uBD84\uCDE8\uC18C",
  date: "2026-05-27",
  body: [
    "\uACB0\uC81C\uAE08\uC561 1,983,330\uC6D0",
    "\uBD80\uBD84\uCDE8\uC18C\uAE08\uC561 325,866\uC6D0",
    "\uC2B9\uC778\uBC88\uD638 30058437",
    "\uC8FC\uBB38\uBC88\uD638 da-gb-1779-8284-8651-10-20260527054857955",
  ].join("\n"),
});
assert.equal(tossPartial.type, "refund");
assert.equal(tossPartial.amount, -325866);
assert.equal(
  tossPartial.bookingNo,
  "da-gb-1779-8284-8651-10-20260527054857955"
);

const kicc = context.__PARSERS.find((item) => item.id === "kicc_easypay");
const kiccCancel = kicc.parse({
  from: "easypay_noreturn@easypay.co.kr",
  subject: "[\uC2E0\uC6A9\uCE74\uB4DC]\uCDE8\uC18C\uD558\uC2E0 \uB0B4\uC5ED",
  date: "2026-03-27",
  body: [
    "\uC0C1\uD488\uAE08\uC561 100,000\uC6D0",
    "\uCDE8\uC18C\uAE08\uC561 34,500\uC6D0",
    "\uC2B9\uC778\uBC88\uD638 30098139",
    "https://easypay.co.kr/x?controlNo=26032717434810777974",
  ].join("\n"),
});
assert.equal(kiccCancel.amount, -34500);
assert.match(kiccCancel.item, /26032717434810777974/);

// Apps Script may use a mail record only when one direct receipt remains.
// Nearest-date selection among duplicate candidates is deliberately forbidden.
const codeContext = { console, Set, Math, Number, JSON, Date, String, RegExp };
vm.createContext(codeContext);
const codeSource = fs.readFileSync("apps-script/Code.gs", "utf8");
vm.runInContext(
  `${codeSource}\nglobalThis.__matchEmail = matchEmail; globalThis.__classify = classify; globalThis.__loadRules = loadRules;`,
  codeContext,
);
const directReceipt = {
  source: "trip_hotel", type: "charge", messageId: "gmail-1",
  bookingNo: "1400826000000001", amount: 523000,
  paidDate: "2026-04-03", useDate: "2026-06-20", account: "숙박비",
};
const card = { krw: 523000, useDate: "2026-04-03" };
const uniqueReceipt = [Object.assign({}, directReceipt)];
assert.equal(codeContext.__matchEmail(uniqueReceipt, card).messageId, "gmail-1");
assert.equal(uniqueReceipt[0]._used, true);

const duplicateReceipts = [
  Object.assign({}, directReceipt, { messageId: "gmail-2" }),
  Object.assign({}, directReceipt, { messageId: "gmail-3" }),
];
assert.equal(codeContext.__matchEmail(duplicateReceipts, card), null);
assert.equal(duplicateReceipts[0]._used, undefined);
assert.equal(duplicateReceipts[1]._used, undefined);

// A PG mail hit stays review-only until the external confirmed projection is
// available; the Apps Script process itself never creates that projection.
const pgResult = codeContext.__classify(
  {
    merchant: "TOSS PAYMENTS", saleType: "", krw: 523000, last4: "0000",
    useDate: "2026-04-03", overseas: false, bizCat: "전자상거래PG",
  },
  {}, [Object.assign({}, directReceipt)], [], {},
);
assert.equal(pgResult.status, "HOLD");

// All historical auto-confirmation routes must be downstream of the OTA/PG
// gate. These cases deliberately provide a permanent rule, owner profile,
// learned map, or travel-window signal without a direct receipt.
const bypassCases = [
  {
    label: "permanent_rule",
    rec: { merchant: "SKYTICKET WEB", saleType: "", krw: 300000, last4: "0000", useDate: "2026-05-01", overseas: false, bizCat: "" },
    kb: {}, rules: { "SKYTICKET WEB": { account: "여비교통비", kind: "여행" } }, trips: [],
  },
  {
    label: "owner_profile",
    rec: { merchant: "MYTRIP", saleType: "", krw: 300000, last4: "5836", useDate: "2026-05-01", overseas: false, bizCat: "" },
    kb: {}, rules: {}, trips: [],
  },
  {
    label: "learned_kb",
    rec: { merchant: "KLOOK", saleType: "", krw: 300000, last4: "0000", useDate: "2026-05-01", overseas: false, bizCat: "" },
    kb: { KLOOK: "교통비" }, rules: {}, trips: [],
  },
  {
    label: "overseas_window",
    rec: { merchant: "TOSS PAYMENTS", saleType: "", krw: 300000, last4: "0000", useDate: "2026-05-01", overseas: true, bizCat: "" },
    kb: {}, rules: {}, trips: [{ name: "trip", region: "JP", start: "2026-04-30", end: "2026-05-03" }],
  },
];
for (const sample of bypassCases) {
  const result = codeContext.__classify(sample.rec, sample.kb, [], sample.trips, sample.rules);
  assert.equal(result.status, "HOLD", sample.label);
}

const ruleSheet = {
  getDataRange: () => ({ getValues: () => [
    ["가맹점", "계정과목", "구분", "비고"],
    ["AI SHOP", "식비", "여행", "AI:2026-07-26"],
    ["HUMAN SHOP", "식비", "여행", "manual:reviewed"],
  ] }),
};
const rulesAfterAiBlock = codeContext.__loadRules({ getSheetByName: () => ruleSheet });
assert.equal(rulesAfterAiBlock["AI SHOP"], undefined);
assert.equal(rulesAfterAiBlock["HUMAN SHOP"].account, "식비");
console.log("Mytrip parser regression: OK");
