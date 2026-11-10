import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runCollection } from '../../tools/ota_collection/collector.mjs';
import { fakeFetch, makeTempDir, readJson, response } from './helpers.mjs';

const AGODA_TOKEN = 'synthetic-observed-detail-token';

function agodaDetailBody(bookingId) {
  return {
    BookingDetails: {
      BookingQueryData: { CancellationReasonData: { BookingID: bookingId } },
      Dates: { CheckInDateNonCulture: '2026-02-01', CheckOutDateNonCulture: '2026-02-03' },
      BookingStatus: { Phase: 'Completed' },
    },
  };
}

async function removeTemp(dir) {
  await import('node:fs/promises').then((fs) => fs.rm(dir, { recursive: true, force: true }));
}

test('agoda list pagination follows pagination.totalPages and stores one detail per booking', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = fakeFetch((url, init) => {
      if (url.includes('GetBookingsList')) {
        const body = JSON.parse(init.body);
        const page = body.pageIndex;
        const bookings = page === 1
          ? [{ bookingId: '1000001', legacyBookingToken: 'lt-1', productTypeName: 'Hotel' },
             { bookingId: '1000002', legacyBookingToken: 'lt-2', productTypeName: 'Hotel' }]
          : page === 2
            ? [{ bookingId: '1000003', legacyBookingToken: 'lt-3', productTypeName: 'Hotel' }]
            : [];
        return Promise.resolve(response(200, { bookings, pagination: { totalPages: 3 } }));
      }
      if (url.includes('/eb/details')) {
        const body = JSON.parse(init.body);
        const known = { 'lt-1': '1000001', 'lt-2': '1000002', 'lt-3': '1000003' };
        return Promise.resolve(response(200, agodaDetailBody(known[body.BookingToken] ?? '0000000')));
      }
      throw new Error(`unexpected url ${url}`);
    });

    const outcome = await runCollection({
      providers: ['agoda'],
      archiveRoot: dir,
      opts: { agodaDetailToken: AGODA_TOKEN, agodaBookingPhase: 'Completed' },
      fetchImpl,
      clock: () => new Date('2026-11-11T00:00:00.000Z'),
    });

    assert.equal(outcome.manifest.status, 'ok');
    const row = outcome.rows[0];
    assert.equal(row.status, 'ok');
    assert.equal(row.counts.listed, 3);
    assert.equal(row.counts.details_saved, 3);
    assert.equal(row.counts.details_invalid, 0);
    assert.equal(row.counts.details_capture, 0);
    assert.equal(fetchImpl.calls.filter((call) => call.url.includes('GetBookingsList')).length, 3, 'collects up to totalPages');

    const manifest = await readJson(`${dir}/manifest.json`);
    assert.equal(manifest.tool, 'collect_ota_portals');
    assert.equal(manifest.status, 'ok');
    assert.equal(manifest.providers[0].provider, 'agoda');
    assert.equal(manifest.providers[0].counts.details_saved, 3);
    assert.match(manifest.started_at, /^\d{4}-\d{2}-\d{2}T/);

    for (const bookingId of ['1000001', '1000002', '1000003']) {
      const saved = await readJson(`${dir}/agoda/details/${bookingId}.json`);
      assert.equal(saved.list.bookingId, bookingId);
      assert.equal(saved.detail.BookingDetails.BookingQueryData.CancellationReasonData.BookingID, bookingId);
      assert.equal(saved.observed_at, '2026-11-11T00:00:00.000Z');
    }
  } finally {
    await removeTemp(dir);
  }
});

test('trip list stops at a missing Offset mapping rather than pretending completeness', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = fakeFetch((url) => {
      if (url.includes('getAllOrders')) {
        return Promise.resolve(response(200, {
          OrderList: Array.from({ length: 20 }, (_, index) => ({ OrderID: String(200000000000 + index) })),
          Offset: 'synthetic-next-offset-token',
        }));
      }
      throw new Error(`unexpected url ${url}`);
    });
    const outcome = await runCollection({ providers: ['trip'], archiveRoot: dir, opts: {}, fetchImpl });
    const row = outcome.rows[0];
    assert.ok(['partial', 'CAPTURE_REQUIRED'].includes(row.status), row.status);
    assert.equal(row.counts.listed, 20);
    assert.match(row.diagnostics.join('|'), /pagination_next_body_unobserved/);
    assert.ok(row.resume.some((line) => /not guessed/.test(line)));
    assert.equal(fetchImpl.calls.filter((call) => call.url.includes('GetOrderDetailOnline')).length, 0, 'no detail request without the observed sign');
  } finally {
    await removeTemp(dir);
  }
});
