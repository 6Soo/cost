import {
  TOOL_NAME,
  TOOL_VERSION,
  PROVIDER_LIST,
  STATUS,
  severityOf,
  maxStatus,
} from './constants.mjs';

function unique(values, cap = 6) {
  const out = [];
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue;
    if (!out.includes(value)) out.push(value);
    if (out.length >= cap) break;
  }
  return out;
}

export function buildManifest({ runId, startedAt = new Date(), archiveRoot, rows = [] }) {
  const providers = {};
  for (const row of rows) {
    providers[row.provider] = {
      status: row.status,
      navigation: row.navigation ? {
        origin: row.navigation.origin,
        entry: row.navigation.entry,
        verified: Boolean(row.navigation.verified),
      } : undefined,
      counts: {
        listed: row.counts?.listed ?? 0,
        details_saved: row.counts?.details_saved ?? 0,
        details_invalid: row.counts?.details_invalid ?? 0,
        details_capture: row.counts?.details_capture ?? 0,
        details_skipped: row.counts?.details_skipped ?? 0,
        details_login_required: row.counts?.details_login_required ?? 0,
        details_failed: row.counts?.details_failed ?? 0,
        details_interrupted: row.counts?.details_interrupted ?? 0,
        items_invalid: row.counts?.items_invalid ?? 0,
      },
      // Raw artifact filenames contain booking IDs; keep them out of summaries.
      diagnostics: unique(row.diagnostics ?? [], 6),
      resume: unique(row.resume ?? [], 4),
    };
  }
  const overall = maxStatus(rows.map((row) => row.status));
  const order = PROVIDER_LIST.filter((name) => providers[name]);
  return {
    tool: TOOL_NAME,
    version: TOOL_VERSION,
    run_id: runId,
    started_at: new Date(startedAt).toISOString(),
    archive_root: archiveRoot,
    providers: order.map((name) => ({ provider: name, ...providers[name] })).map((entry) => {
      if (!entry.navigation) { delete entry.navigation; return entry; }
      return entry;
    }),
    status: overall,
    notes: [
      'credentials, account identifiers, request headers/bodies and opaque tokens/templates are never recorded',
      'entry points that require an observed template (agoda detail token, booking query) are reported as CAPTURE_REQUIRED, never guessed',
      'collection is read-only: no booking changes, payments, messages, coupon use, DB apply, booking registration, or deploy',
      'saved records reuse the formats of tools/import_agoda_api_details.py and tools/import_trip_api_details.py',
    ],
    severity: severityOf(overall),
  };
}

export function aggregateRows(rows) {
  return maxStatus(rows.map((row) => row.status));
}

export function isSuccessStatus(status) {
  return status === STATUS.OK;
}
