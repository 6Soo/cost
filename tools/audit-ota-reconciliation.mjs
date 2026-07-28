import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const root = process.cwd();
const outDir = path.join(root, "outputs", "codex_reconcile_20260727");
fs.mkdirSync(outDir, { recursive: true });

function readJson(rel) {
  return JSON.parse(fs.readFileSync(path.join(root, rel), "utf8"));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const header = rows.shift();
  return rows
    .filter((values) => values.some((value) => value !== ""))
    .map((values) => Object.fromEntries(header.map((key, i) => [key, values[i] ?? ""])));
}

function providerOf(row) {
  const text = `${row.merchant ?? ""} ${row.note ?? ""}`.toUpperCase();
  if (/(마이트립|MYTRIP|고투게이트)/.test(text)) return "mytrip";
  if (/(트립닷컴|TRIP\.COM|CTRIP)/.test(text)) return "trip";
  if (/(AGODA|아고다)/.test(text)) return "agoda";
  if (/BOOKING\.COM/.test(text)) return "booking";
  if (/(트래블로버|TRAVELROVER)/.test(text)) return "travelrover";
  return null;
}

function normalizedPeriod(period) {
  if (!period) return "";
  const isoDates = [...String(period).matchAll(/\d{4}-(\d{2})-(\d{2})/g)]
    .map((match) => `${match[1]}${match[2]}`);
  if (isoDates.length) return isoDates.slice(0, 2).join("_");
  const matches = String(period).match(/\d{4}/g) ?? [];
  return matches.slice(0, 2).join("_");
}

function expectedRowMatches(row, event) {
  const card = event.card_event ?? {};
  const differences = [];
  if (card.use_date && row.use_date !== card.use_date) differences.push("use_date");
  if (card.card4 && row.card4 !== String(card.card4)) differences.push("card4");
  if (card.currency && row.currency !== card.currency) differences.push("currency");
  if (card.foreign_amount != null && Number(row.foreign) !== Number(card.foreign_amount)) {
    differences.push("foreign_amount");
  }
  if (card.krw_amount != null && Math.round(Number(row.krw)) !== Math.round(Number(card.krw_amount))) {
    differences.push("krw_amount");
  }
  return differences;
}

const classified = parseCsv(
  fs.readFileSync(path.join(root, "ledger", "data", "classified_v14.csv"), "utf8"),
);
const byUid = new Map(classified.map((row) => [row.uid, row]));
// 원문(rawText 포함) 색인이 있으면 우선 사용하고, 없으면 추적되는 편집본으로 폴백한다.
// 편집본에는 rawText가 없어 evidenceContainsBooking 검증이 전건 실패한다(2026-07-29 실측).
const MAIL_INDEX_RAW = "ledger/data/ota_mail_index.raw.json";
const mailIndexPath = fs.existsSync(path.join(root, MAIL_INDEX_RAW))
  ? MAIL_INDEX_RAW
  : "ledger/data/ota_mail_index.json";
const mailIndex = readJson(mailIndexPath);
const mailsById = new Map(mailIndex.records.map((record) => [record.messageId, record]));
const existingLinks = readJson("ledger/data/ota_event_links_verified.json");
const tripDelta = readJson("outputs/terra_checkpoints/trip_verified_delta.json");
const tripHold = readJson("outputs/terra_checkpoints/trip_verified_hold.json");
const bookingDelta = readJson("outputs/terra_checkpoints/booking_receipts_verified_delta.json");
const bookingHold = readJson("outputs/terra_checkpoints/booking_receipts_held.json");

const mergeable = [];
const holds = [];
const relations = [];

for (const [uid, event] of Object.entries(tripDelta.verified_events ?? {})) {
  const row = byUid.get(uid);
  const mail = mailsById.get(event.evidence_location?.message_id);
  const differences = row ? expectedRowMatches(row, event) : ["missing_card_event"];
  const bookingId = String(event.booking_id ?? "");
  const evidenceContainsBooking =
    mail &&
    String(mail.rawText ?? "").includes(bookingId);
  const conflict = existingLinks[uid] &&
    String(existingLinks[uid].booking_id ?? existingLinks[uid].order_id ?? "") !== bookingId;
  if (!row || !mail || !evidenceContainsBooking || differences.length || conflict) {
    holds.push({
      uid,
      provider: "trip",
      reason: "checkpoint_revalidation_failed",
      details: {
        rowFound: Boolean(row),
        mailFound: Boolean(mail),
        evidenceContainsBooking,
        rowDifferences: differences,
        existingLinkConflict: Boolean(conflict),
      },
      source: "outputs/terra_checkpoints/trip_verified_delta.json",
    });
  } else if (!existingLinks[uid]) {
    mergeable.push({
      uid,
      provider: "trip",
      booking_id: bookingId,
      category: event.category,
      period: normalizedPeriod(event.period),
      source_message_id: event.evidence_location.message_id,
      verification: "card row + indexed Gmail raw text + booking number",
      source: "outputs/terra_checkpoints/trip_verified_delta.json",
    });
  }
}

for (const event of bookingDelta.confirmed_events ?? []) {
  const uid = event.card_event_id;
  const row = byUid.get(uid);
  const differences = row ? expectedRowMatches(row, event) : ["missing_card_event"];
  if (event.status === "CANCELLATION_PAIR_CONFIRMED") {
    const paired = byUid.get(event.paired_card_event_id);
    if (!row || !paired || differences.length) {
      holds.push({
        uid,
        provider: "booking",
        reason: "cancellation_pair_revalidation_failed",
        details: {
          rowFound: Boolean(row),
          pairedRowFound: Boolean(paired),
          rowDifferences: differences,
        },
        source: "outputs/terra_checkpoints/booking_receipts_verified_delta.json",
      });
    } else {
      relations.push({
        uid,
        paired_uid: event.paired_card_event_id,
        relation: event.event_type,
        rule: "retain_both_independent_events",
        source: "outputs/terra_checkpoints/booking_receipts_verified_delta.json",
      });
    }
    continue;
  }
  const bookingId = String(event.reservation_number ?? "");
  const mail = mailsById.get(event.email_evidence?.message_id);
  const evidenceContainsBooking =
    mail &&
    String(mail.rawText ?? "").includes(bookingId);
  const conflict = existingLinks[uid] &&
    String(existingLinks[uid].booking_id ?? existingLinks[uid].order_id ?? "") !== bookingId;
  if (!row || !mail || !evidenceContainsBooking || differences.length || conflict) {
    holds.push({
      uid,
      provider: "booking",
      reason: "checkpoint_revalidation_failed",
      details: {
        rowFound: Boolean(row),
        mailFound: Boolean(mail),
        evidenceContainsBooking,
        rowDifferences: differences,
        existingLinkConflict: Boolean(conflict),
      },
      source: "outputs/terra_checkpoints/booking_receipts_verified_delta.json",
    });
  } else if (!existingLinks[uid]) {
    mergeable.push({
      uid,
      provider: "booking",
      booking_id: bookingId,
      category: "숙박",
      period: normalizedPeriod(event.stay_period),
      source_message_id: event.email_evidence.message_id,
      verification: "card row + indexed Gmail raw text + booking number + exact amount",
      source: "outputs/terra_checkpoints/booking_receipts_verified_delta.json",
    });
  }
}

for (const item of tripHold.holds ?? []) {
  holds.push({ ...item, provider: "trip", source: "outputs/terra_checkpoints/trip_verified_hold.json" });
}
for (const item of bookingHold.held_events ?? []) {
  holds.push({
    uid: item.card_event_id,
    provider: "booking",
    reason: item.reason,
    source: "outputs/terra_checkpoints/booking_receipts_held.json",
  });
}

// 체크포인트가 선언한 HOLD 중, 그 사이 중앙 링크파일에 검증 링크가 생긴 건은 해소된 것이다.
// 체크포인트 파일은 정적이라 스스로 갱신되지 않으므로 여기서 대조해 분리 보고한다(2026-07-29).
// 해소 표시만 하고 목록에서 지우지는 않는다 — 무엇이 왜 풀렸는지 추적 가능해야 한다.
const resolvedHolds = [];
const openHolds = [];
for (const hold of holds) {
  const link = hold.uid ? existingLinks[hold.uid] : null;
  if (link) {
    resolvedHolds.push({
      ...hold,
      resolved_by_central_link: {
        booking_id: link.booking_id ?? link.order_id ?? "",
        verification: link.verification ?? link.verification_source ?? "",
      },
    });
  } else {
    openHolds.push(hold);
  }
}

const db = new DatabaseSync(path.join(root, "ledger", "data", "ota_checkpoints_agoda.db"), {
  readOnly: true,
});
const agodaRows = db.prepare("SELECT COUNT(*) AS n FROM agoda_checkpoints").get().n;
const agodaEvidence = db.prepare("SELECT COUNT(*) AS n FROM agoda_checkpoint_evidence").get().n;
db.close();

const otaRows = classified.filter((row) => providerOf(row));
const providers = ["agoda", "trip", "booking", "mytrip", "travelrover"];
const byProvider = {};
for (const provider of providers) {
  const rows = otaRows.filter((row) => providerOf(row) === provider);
  const linked = rows.filter((row) => existingLinks[row.uid]).length;
  const newlyMergeable = mergeable.filter((item) => item.provider === provider).length;
  const heldUids = new Set(
    holds.filter((item) => item.provider === provider).map((item) => item.uid ?? item.event_id),
  );
  byProvider[provider] = {
    card_events_total: rows.length,
    existing_verified_links: linked,
    newly_mergeable_links: newlyMergeable,
    explicitly_held_unique_events: [...heldUids].filter(Boolean).length,
    remaining_without_verified_link:
      rows.length - linked - newlyMergeable,
    completion_basis:
      "classified_v14 OTA rows minus existing verified links minus locally revalidated mergeable links",
  };
}

const report = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  immutable_rules: [
    "all card events retained",
    "OTA N:M intersections block automatic linkage",
    "pre-2025 service dates excluded",
    "Agoda priority retained",
    "cancellation and partial refund events remain independent",
  ],
  source_counts: {
    classified_rows: classified.length,
    ota_card_events: otaRows.length,
    mail_records: mailIndex.records.length,
    existing_verified_links: Object.keys(existingLinks).length,
    agoda_checkpoint_rows: Number(agodaRows),
    agoda_checkpoint_evidence_rows: Number(agodaEvidence),
  },
  result_counts: {
    newly_mergeable_links: mergeable.length,
    verified_cancellation_relation_records: relations.length,
    hold_records: openHolds.length,
    hold_records_declared: holds.length,
    hold_records_resolved_by_central_link: resolvedHolds.length,
  },
  by_provider: byProvider,
  warnings: [
    "Agoda checkpoint database contains schema only and zero booking rows; no Agoda browser result is persisted there.",
    "remaining_without_verified_link is not equivalent to user-review-required: it includes records not yet exhaustively processed by provider-specific checkpoints.",
    "No central ledger or classified CSV was modified by this audit.",
  ],
};

function writeJson(name, value) {
  fs.writeFileSync(path.join(outDir, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

writeJson("01_mergeable_verified_links.json", mergeable);
writeJson("02_holds_and_conflicts.json", openHolds);
writeJson("02b_holds_resolved_by_central_link.json", resolvedHolds);
writeJson("03_provider_completion.json", report);
writeJson("04_verified_transaction_relations.json", relations);

const evidence = {
  source_files: [
    "ledger/data/classified_v14.csv",
    mailIndexPath,
    "ledger/data/ota_event_links_verified.json",
    "ledger/data/ota_checkpoints_agoda.db",
    "outputs/terra_checkpoints/trip_verified_delta.json",
    "outputs/terra_checkpoints/trip_verified_hold.json",
    "outputs/terra_checkpoints/booking_receipts_verified_delta.json",
    "outputs/terra_checkpoints/booking_receipts_held.json",
  ].map((rel) => {
    const stat = fs.statSync(path.join(root, rel));
    return { path: rel, bytes: stat.size, modified_at: stat.mtime.toISOString() };
  }),
  validation: {
    all_mergeable_uids_exist: mergeable.every((item) => byUid.has(item.uid)),
    all_mergeable_mail_ids_exist: mergeable.every((item) => mailsById.has(item.source_message_id)),
    unique_mergeable_uids: new Set(mergeable.map((item) => item.uid)).size === mergeable.length,
    no_existing_link_overwrite: mergeable.every((item) => !existingLinks[item.uid]),
  },
};
writeJson("05_evidence_manifest.json", evidence);

const md = `# OTA reconciliation checkpoint — 2026-07-27

- Central ledger/classified CSV modified: **no**
- OTA card events: **${otaRows.length}**
- Existing verified links: **${Object.keys(existingLinks).length}**
- Newly mergeable after local revalidation: **${mergeable.length}**
- HOLD/conflict records (open): **${openHolds.length}**
- HOLD declared by checkpoints: **${holds.length}** (of which resolved by a central verified link since: **${resolvedHolds.length}**)
- Agoda persisted checkpoints: **${Number(agodaRows)}**

## Provider status

| Provider | Card events | Existing verified | New mergeable | Explicit HOLD | Remaining without verified link |
|---|---:|---:|---:|---:|---:|
${providers.map((provider) => {
  const item = byProvider[provider];
  return `| ${provider} | ${item.card_events_total} | ${item.existing_verified_links} | ${item.newly_mergeable_links} | ${item.explicitly_held_unique_events} | ${item.remaining_without_verified_link} |`;
}).join("\n")}

The remaining count is an exact file-state count, not a claim that every remaining row has been provider-by-provider investigated.
`;
fs.writeFileSync(path.join(outDir, "README.md"), md, "utf8");

console.log(JSON.stringify(report, null, 2));
