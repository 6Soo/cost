import assert from "node:assert/strict";
import test from "node:test";

import {
  SaturatedMailRangeError,
  exhaustiveMailSearch,
} from "../../tools/ota-mail-search-plan.mjs";

test("accepts only results below the API limit", async () => {
  const result = await exhaustiveMailSearch({
    start: "2026-01-01T00:00:00Z",
    end: "2026-02-01T00:00:00Z",
    search: async () => [{ messageId: "one" }],
  });
  assert.equal(result.queryCount, 1);
  assert.equal(result.records.length, 1);
  assert.equal(result.coverageComplete, true);
});

test("splits saturated ranges and deduplicates messages", async () => {
  const result = await exhaustiveMailSearch({
    start: "2026-01-01T00:00:00Z",
    end: "2026-01-03T00:00:00Z",
    limit: 2,
    search: async ({ after, before }) =>
      after === "2026/01/01" && before === "2026/01/03"
        ? [{ messageId: "one" }, { messageId: "two" }]
        : before === "2026/01/02"
          ? [{ messageId: "one" }]
          : [{ messageId: "two" }],
  });
  assert.equal(result.queryCount, 3);
  assert.deepEqual(
    result.records.map((row) => row.messageId).sort(),
    ["one", "two"],
  );
});

test("fails loudly when a one-day range remains saturated", async () => {
  await assert.rejects(
    exhaustiveMailSearch({
      start: "2026-01-01T00:00:00Z",
      end: "2026-01-02T00:00:00Z",
      limit: 2,
      search: async () => [{ messageId: "one" }, { messageId: "two" }],
    }),
    SaturatedMailRangeError,
  );
});
