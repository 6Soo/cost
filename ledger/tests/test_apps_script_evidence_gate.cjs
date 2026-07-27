const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const context = { console, Set, Math, Number, JSON, Date };
vm.createContext(context);
const source = fs.readFileSync("apps-script/Code.gs", "utf8");
vm.runInContext(
  `${source}
globalThis.__directEmailEvidenceRef = directEmailEvidenceRef_;
globalThis.__matchEmail = matchEmail;
globalThis.__classify = classify;
globalThis.__classifyCandidate = classifyCandidate_;
`,
  context,
);

const ref = context.__directEmailEvidenceRef;
const match = context.__matchEmail;
const classify = context.__classify;
const classifyCandidate = context.__classifyCandidate;

const valid = {
  source: "mytrip",
  type: "charge",
  currency: "KRW",
  messageId: "msg-1122-610-807",
  bookingNo: "1122-610-807",
  amount: 163788,
  paidDate: "2026-06-24",
  useDate: "2026-06-25",
};
assert.equal(
  ref(valid),
  "gmail:msg-1122-610-807|booking:1122-610-807",
);
assert.equal(
  match([valid], { krw: 163788, useDate: "2026-06-24" }),
  valid,
);

// 신규 실사례 5건: legacy의 '상' 또는 메모의 '메일확정' 문구가 있더라도
// 직접 결제 실증의 세 요소를 충족하지 못하면 Apps Script 자동전기에 못 쓴다.
const reportedCases = [
  {
    uid: "KBD-0875",
    reason: "PG+manual amount only",
    source: "manual",
    type: "charge",
    amount: 30970,
    note: "메일확정",
  },
  {
    uid: "KBD-0964",
    reason: "partial refund card only",
    source: "card",
    type: "refund",
    amount: -325866,
    bookingNo: "30058437",
    note: "상",
  },
  {
    uid: "KBD-0871",
    reason: "passenger count 2 vs 6 conflict",
    source: "trip_flight",
    type: "charge",
    amount: 383700,
    messageId: "msg-kbd-0871",
    bookingNo: "1400827190108091",
    conflictFields: "passenger_count",
    note: "메일확정",
  },
  {
    uid: "HAN-3004",
    reason: "manual year 2024 vs card 2026 conflict",
    source: "legacy_manual",
    type: "charge",
    amount: 543947,
    messageId: "msg-han-3004",
    bookingNo: "MANUAL-2024",
    conflictFields: "service_year",
    note: "상",
  },
  {
    uid: "KBD-0742",
    reason: "internal email only",
    source: "internal_email",
    type: "evidence_only",
    amount: 312100,
    messageId: "msg-kbd-0742",
    bookingNo: "INTERNAL-0742",
    note: "메일확정",
  },
];

for (const item of reportedCases) {
  assert.equal(ref(item), "", `${item.uid}: ${item.reason}`);
  assert.equal(
    match(
      [item],
      { krw: Math.abs(item.amount), useDate: item.paidDate || "2026-05-20" },
    ),
    null,
    `${item.uid} must not be selected by amount/date`,
  );
}

// KBD-0875 같은 PG 행은 해외/여행기간·영구 학습규칙이 있어도 PG 게이트가
// 먼저 실행되어야 한다. 메모를 토대로 만든 규칙으로 우회 확정할 수 없다.
const pgResult = classify(
  {
    merchant: "KCP PG",
    krw: 30970,
    useDate: "2026-05-20",
    saleType: "",
    last4: "3820",
    overseas: true,
    bizCat: "전자상거래",
  },
  {},
  [reportedCases[0]],
  [{ name: "0520_여행", start: "2026-05-20", end: "2026-05-25" }],
  { KCPPG: { account: "여비교통비", kind: "여행" } },
);
assert.equal(pgResult.status, "HOLD");
assert.match(pgResult.reason, /직접 결제 메일/);

const leaderOtaResult = classify(
  {
    merchant: "TRIP.COM",
    krw: 312100,
    useDate: "2026-07-20",
    saleType: "",
    last4: "5836",
    overseas: true,
    bizCat: "",
  },
  {},
  [reportedCases[4]],
  [{ name: "0720_여행", start: "2026-07-20", end: "2026-07-25" }],
  {},
);
assert.equal(leaderOtaResult.status, "HOLD");
assert.match(leaderOtaResult.reason, /메일 (매칭|없음)/);

const latestReportedCases = [
  {
    uid: "KBD-0809",
    merchant: "KCP PG",
    reason: "PG/manual",
    source: "manual",
    type: "charge",
    amount: 30970,
    note: "메일확정 | 상",
  },
  {
    uid: "KBD-0994",
    merchant: "TRIP.COM",
    reason: "note only",
    source: "classified_note",
    type: "charge",
    amount: 299400,
    note: "메일확정 | 상",
  },
  {
    uid: "KBD-0806",
    merchant: "TRAVELOKA",
    reason: "Traveloka/manual",
    source: "legacy_manual",
    type: "charge",
    amount: 425000,
    note: "메일확정 | 상",
  },
  {
    uid: "KBD-0974",
    merchant: "TRIP.COM",
    reason: "payment/ticket split plus partial refund residual 364600",
    source: "trip_flight",
    type: "payment_confirmation",
    amount: 364600,
    messageId: "msg-payment-0974",
    bookingNo: "1400820974",
  },
  {
    uid: "KBD-0968",
    merchant: "TRIP.COM",
    reason: "payment/ticket split 25 minutes apart",
    source: "trip_flight",
    type: "payment_confirmation",
    amount: 364600,
    messageId: "msg-payment-0968",
    bookingNo: "1400820968",
  },
];

// AI/permanent rule/learned KB/card owner/overseas/travel heuristic가 모두
// 있어도 Python 확정투영과 direct lineage가 없으면 OTA/PG는 HOLD다.
for (const item of latestReportedCases) {
  const rec = {
    merchant: item.merchant,
    krw: item.amount,
    useDate: "2026-05-20",
    saleType: "",
    last4: "5836",
    overseas: true,
    bizCat: /PG/.test(item.merchant) ? "전자상거래" : "",
    note: item.note || "메일확정 | 상",
  };
  const key = item.merchant.replace(/[^0-9A-Z가-힣]/g, "");
  const email = {
    ...item,
    paidDate: "2026-05-20",
    useDate: "2026-05-21",
    account: "여비교통비",
  };
  const candidate = classifyCandidate(
    rec,
    { [key]: "여비교통비" },
    [{ ...email }],
    [{ name: "0520_여행", year: 2026, mm: 5, dd: 20, region: "합성", windowDays: 7 }],
    { [key]: { account: "여비교통비", kind: "여행", note: "permanent" } },
  );
  const result = classify(
    rec,
    { [key]: "여비교통비" },
    [{ ...email }],
    [{ name: "0520_여행", year: 2026, mm: 5, dd: 20, region: "합성", windowDays: 7 }],
    { [key]: { account: "여비교통비", kind: "여행", note: "permanent" } },
  );
  if (candidate.status === "CONFIRM") {
    assert.equal(result.status, "HOLD", `${item.uid}: final Python gate`);
    assert.match(result.reason, /manual provenance/);
  } else {
    assert.equal(result.status, "HOLD", `${item.uid}: candidate already held`);
  }
}

// 상태 문자열만 복사해서는 부족하고 Python이 검증한 direct lineage도 필요하다.
const projectionBase = {
  merchant: "MYTRIP",
  krw: 163788,
  useDate: "2026-06-24",
  saleType: "",
  last4: "5836",
  overseas: true,
  bizCat: "",
  pythonProjectionStatus: "confirmed_strong",
  pythonProjectionReplay: {
    matchedFresh: true,
    currentDecisionVerified: true,
  },
};
const projectionTrips = [
  { name: "0624_여행", year: 2026, mm: 6, dd: 24, region: "합성", windowDays: 7 },
];
assert.equal(
  classify(projectionBase, {}, [{ ...valid, _used: false }], projectionTrips, {}).status,
  "HOLD",
);
assert.equal(
  classify(
    { ...projectionBase, pythonDirectLineage: "verified" },
    {},
    [{ ...valid, _used: false }],
    projectionTrips,
    {},
  ).status,
  "CONFIRM",
);

// confirmed_manual은 직접 OTA message lineage 대신 대표자 append-only 판정의
// provenance/replay/supersedes 무결성으로 확정할 수 있다. 첫 판정도
// supersedesChainVerified=true로 "선행 판정 없음" 검증을 표현한다.
const manualDecision = {
  decisionId: "MANUAL-OTA-20260726-1",
  actor: "representative",
  reasonCode: "manual_review",
  rationale: "카드 원문과 수기장부 후보를 대표자가 육안 확인",
  replayVerified: true,
  matchedFresh: true,
  currentDecisionVerified: true,
  supersedesChainVerified: true,
};
assert.equal(
  classify(
    {
      ...projectionBase,
      pythonProjectionStatus: "confirmed_manual",
      pythonDirectLineage: "",
      pythonProjectionReplay: undefined,
      pythonManualDecision: manualDecision,
    },
    {},
    [{ ...valid, _used: false }],
    projectionTrips,
    {},
  ).status,
  "CONFIRM",
);

for (const missing of [
  "decisionId",
  "actor",
  "reasonCode",
  "rationale",
  "replayVerified",
  "matchedFresh",
  "currentDecisionVerified",
  "supersedesChainVerified",
]) {
  const incomplete = { ...manualDecision };
  delete incomplete[missing];
  const result = classify(
    {
      ...projectionBase,
      pythonProjectionStatus: "confirmed_manual",
      pythonDirectLineage: "",
      pythonManualDecision: incomplete,
    },
    {},
    [{ ...valid, _used: false }],
    projectionTrips,
    {},
  );
  assert.equal(result.status, "HOLD", `manual provenance missing ${missing}`);
}

// 신규 실건의 note/confidence를 confirmed_manual 문자열로 승격해도 append-only
// 판정 provenance가 없으면 확정되지 않는다.
for (const reported of latestReportedCases) {
  const result = classify(
    {
      merchant: reported.merchant,
      krw: reported.amount,
      useDate: "2026-05-20",
      saleType: "",
      last4: "5836",
      overseas: true,
      bizCat: /PG/.test(reported.merchant) ? "전자상거래" : "",
      note: reported.note || "메일확정 | 상",
      pythonProjectionStatus: "confirmed_manual",
    },
    {},
    [{
      ...reported,
      paidDate: "2026-05-20",
      useDate: "2026-05-21",
      account: "여비교통비",
    }],
    projectionTrips,
    {},
  );
  assert.equal(result.status, "HOLD", `${reported.uid}: no manual provenance`);
}

const mailReportedCases = [
  {
    uid: "KBO-2983",
    merchant: "TRIP.COM",
    source: "card",
    type: "charge",
    amount: 537210,
    reason: "separate card-only",
  },
  {
    uid: "KBO-2978",
    merchant: "TRIP.COM",
    source: "card",
    type: "charge",
    amount: 537210,
    reason: "separate card-only",
  },
  {
    uid: "HAN-3071",
    merchant: "TRIP.COM",
    source: "trip_flight",
    type: "payment_confirmation",
    amount: 544879,
    messageId: "msg-han-3071",
    bookingNo: "1400823071",
    conflictFields: "source_amount_conflict:classified=544879,raw=537210",
  },
  {
    uid: "KBD-1032",
    merchant: "TRIP.COM",
    source: "classified_note",
    type: "charge",
    amount: 537210,
    note: "메일확정 | 반복패턴",
  },
  {
    uid: "KBD-1099",
    merchant: "TRIP.COM",
    source: "trip_flight",
    type: "payment_confirmation",
    amount: 537210,
    messageId: "msg-kbd-1099",
    bookingNo: "1400821099",
    conflictFields: "대상미상_vs_strong_contradiction",
  },
];

for (const item of mailReportedCases) {
  assert.equal(ref(item), "", `${item.uid}: mail evidence blocker`);
  const result = classify(
    {
      merchant: item.merchant,
      krw: item.amount,
      useDate: "2026-05-20",
      saleType: "",
      last4: "5836",
      overseas: true,
      bizCat: "",
      note: item.note || "메일확정 | 상",
      pythonProjectionStatus: "confirmed_manual",
    },
    {},
    [{ ...item, paidDate: "2026-05-20", useDate: "2026-05-21" }],
    projectionTrips,
    {},
  );
  assert.equal(result.status, "HOLD", `${item.uid}: stale/unproven projection`);
}

// 이전 확정 판정의 상태만 남고 fresh replay/current decision이 어긋나면
// strong/manual 어느 쪽도 자동전기에 사용할 수 없다.
for (const replay of [
  { matchedFresh: false, currentDecisionVerified: true },
  { matchedFresh: true, currentDecisionVerified: false },
]) {
  const result = classify(
    {
      ...projectionBase,
      pythonProjectionReplay: replay,
      pythonDirectLineage: "verified",
    },
    {},
    [{ ...valid, _used: false }],
    projectionTrips,
    {},
  );
  assert.equal(result.status, "HOLD");
  assert.match(result.reason, /fresh\/current replay/);
}

// 서로 다른 messageId의 결제메일·발권메일은 시간 근접만으로 결합하지 않는다.
const splitMessages = [
  {
    ...valid,
    messageId: "msg-payment-split",
    bookingNo: "1400820968",
    amount: 364600,
    paidDate: "2026-05-20",
  },
  {
    ...valid,
    messageId: "msg-ticket-split",
    bookingNo: "1400820968",
    amount: 364600,
    paidDate: "2026-05-20",
  },
];
assert.equal(
  match(splitMessages, { krw: 364600, useDate: "2026-05-20" }),
  null,
);

console.log("Apps Script direct-email evidence gate: OK");
