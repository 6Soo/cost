// Local, dependency-free checks for the pure OTA matching functions in Code.gs.
// Run: node tests/test_ota_matching.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

let uuidSeq = 0;
const context = {
  console, Date, Math, JSON, Set, RegExp, String, Number, Boolean, Array, Object,
  Utilities: { getUuid: () => `test-uuid-${++uuidSeq}` },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps-script/Code.gs', 'utf8'), context, { filename: 'Code.gs' });

const card = (overrides = {}) => ({
  merchant: 'AGODA COMPANY PTE LTD', krw: 100000, currency: 'KRW',
  last4: '1234', useDate: '2026-06-01', ...overrides,
});
const email = (overrides = {}) => ({
  source: 'agoda', type: 'charge', currency: 'KRW', amount: 100000,
  paidDate: '2026-06-01', useDate: '2026-06-20', bookingNo: '1234567890',
  messageId: 'mail-1', ...overrides,
});

{
  const e = email();
  const result = context.matchOtaEmail([e], card());
  assert.equal(result.status, 'EXACT');
  assert.equal(result.email, e);
  assert.equal(e._used, true);
}
{
  const e = email({ amount: 100500 }); // 1% 이내지만 정확한 금액은 아님
  const result = context.matchOtaEmail([e], card());
  assert.equal(result.status, 'PROBABLE');
  assert.equal(e._used, undefined);
}
{
  const result = context.matchOtaEmail([email({ messageId: 'mail-1' }), email({ messageId: 'mail-2' })], card());
  assert.equal(result.status, 'HOLD');
  assert.equal(result.candidateCount, 2);
}
{
  const result = context.matchOtaEmail([email({ card: '신용카드 9999' })], card());
  assert.equal(result.status, 'HOLD');
}
{
  const e = email({ currency: 'JPY', amount: 1200 });
  const result = context.matchOtaEmail([e], card({ currency: 'JPY', foreign: 1200, krw: 9500 }));
  assert.equal(result.status, 'EXACT');
}
{
  const e = email();
  assert.equal(context.matchOtaEmail([e], card()).status, 'EXACT');
  assert.equal(context.matchOtaEmail([e], card()).status, 'HOLD');
}
{
  const result = context.classify(card({ last4: '5836', rawRef: 'RAW:2' }), {}, [email()], [], {});
  assert.equal(result.status, 'HOLD');
  assert.match(result.reason, /strong lineage/);
}
{
  const result = context.classify(card({
    last4: '5836',
    rawRef: 'RAW:2',
    pythonProjectionStatus: 'confirmed_strong',
    pythonDirectLineage: 'verified',
    pythonProjectionReplay: {
      matchedFresh: true,
      currentDecisionVerified: true,
    },
  }), {}, [email()], [], {});
  assert.equal(result.status, 'CONFIRM');
  assert.equal(result.otaMatch.status, 'EXACT');
  assert.equal(result.bookingNo, '1234567890');
}
{
  const a = { eventId: 'CE-1', bookingNo: '', amount: 10000, date: '2026-06-01', merchant: 'SAME', card: '1234' };
  const b = { ...a, eventId: 'CE-2' };
  assert.equal(context.recordsMatch(a, b), ''); // 같은 금액·날짜라도 별도 카드 거래
  assert.equal(context.recordsMatch(a, { ...b, eventId: 'CE-1' }), '카드거래ID');
}
{
  const note = context.rawNoteWithEvent('사용자 메모', 'CE-1', '보류');
  assert.equal(context.cardEventIdFromText(note), 'CE-1');
  assert.match(note, /ENGINE_STATUS:보류/);
  assert.match(context.clearRawEngineStatus(note), /사용자 메모/);
  assert.doesNotMatch(context.clearRawEngineStatus(note), /ENGINE_STATUS/);
}
{
  const targets = { '취소환불': { mode: 'plain', existing: [], rows: [] } };
  const decision = { tripName: '취소환불', account: '취소환불', note: '취소' };
  const first = context.queueLedgerPosting(card({ cardEventId: 'CE-C1', krw: -10000 }), decision, targets, null);
  const second = context.queueLedgerPosting(card({ cardEventId: 'CE-C2', krw: -10000 }), decision, targets, null);
  const again = context.queueLedgerPosting(card({ cardEventId: 'CE-C1', krw: -10000 }), decision, targets, null);
  assert.equal(first.duplicate, false);
  assert.equal(second.duplicate, false); // 동일 금액이어도 별도 이벤트는 모두 기록
  assert.equal(again.duplicate, true);
  assert.equal(targets['취소환불'].rows.length, 2);
}
{
  const rows = [['가맹점', '업종', '예시일자', '금액', '보류사유', '계정과목(입력)', '구분(여행/기타)', '카드거래ID']];
  const sheet = {
    getDataRange: () => ({ getValues: () => rows.map((row) => row.slice()) }),
    getRange: (r) => ({
      setValues: (values) => { if (r === 1) rows[0] = values[0].slice(); return sheet.getRange(r); },
      setFontWeight: () => sheet.getRange(r),
    }),
    appendRow: (row) => rows.push(row.slice()),
  };
  const ss = { getSheetByName: () => sheet };
  context.flushReview(ss, {
    'CE-H1': { eventId: 'CE-H1', merchant: 'SAME', bizCat: '업종', date: '2026-06-01', krw: 1000, reason: '보류' },
    'CE-H2': { eventId: 'CE-H2', merchant: 'SAME', bizCat: '업종', date: '2026-06-02', krw: 2000, reason: '보류' },
  });
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.slice(1).map((row) => row[7]), ['CE-H1', 'CE-H2']);
}

console.log('Engine tests: 12 passed');
