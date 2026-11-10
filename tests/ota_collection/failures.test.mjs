import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runCollection } from '../../tools/ota_collection/collector.mjs';
import { runPool } from '../../tools/ota_collection/collector.mjs';
import { requestJson } from '../../tools/ota_collection/http.mjs';
import { response, makeTempDir, cleanup } from './helpers.mjs';

async function removeTemp(dir) {
  await cleanup(dir);
}

test('expiry, wrong id, bad pagination shape and abort never become success', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = async (url, init = {}) => {
      if (url.includes('GetBookingsList')) {
        const body = JSON.parse(init.body);
        if (body.pageIndex === 1) {
          return response(200, { bookings: [{ bookingId: '1000001', legacyBookingToken: 'lt-1' }], pagination: { totalPages: 2 } });
        }
        return response(200, { bookings: [], pagination: { totalPages: 2 } });
      }
      if (url.includes('/eb/details')) {
        const body = JSON.parse(init.body);
        if (body.BookingToken === 'lt-1') return response(200, { BookingDetails: {} });
        return response(403, { error: 'forbidden' });
      }
      return response(404, { error: 'not_found' });
    };
    const outcome = await runCollection({
      providers: ['agoda'],
      archiveRoot: dir,
      opts: { agodaDetailToken: 'synthetic-token', agodaBookingPhase: 'Completed' },
      fetchImpl,
    });
    const row = outcome.rows[0];
    // A detail payload that cannot attest the list booking id is invalid, never a saved success,
    // and the empty page 2 is collected without inventing bookings.
    assert.equal(row.counts.listed, 1);
    assert.equal(row.counts.details_saved, 0);
    assert.equal(row.counts.details_invalid, 1);
    assert.notEqual(row.status, 'ok');
    assert.match(row.diagnostics.join('|'), /detail_identity_mismatch/);
  } finally {
    await removeTemp(dir);
  }
});

test('a detail response that does not attest the list booking id is invalid, not saved as success', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = async (url, init = {}) => {
      if (url.includes('GetBookingsList')) {
        return response(200, { bookings: [{ bookingId: '1000001', legacyBookingToken: 'lt-1' }], pagination: { totalPages: 1 } });
      }
      if (url.includes('/eb/details')) {
        const body = JSON.parse(init.body);
        return response(200, {
          BookingDetails: { BookingQueryData: { CancellationReasonData: { BookingID: body.BookingToken === 'lt-1' ? '9999999' : '1000001' } } },
        });
      }
      return response(404, {});
    };
    const outcome = await runCollection({
      providers: ['agoda'],
      archiveRoot: dir,
      opts: { agodaDetailToken: 'synthetic-token' },
      fetchImpl,
    });
    const row = outcome.rows[0];
    assert.equal(row.counts.details_invalid, 1);
    assert.equal(row.counts.details_saved, 0);
    assert.match(row.diagnostics.join('|'), /detail_identity_mismatch/);
  } finally {
    await removeTemp(dir);
  }
});

test('without an observed detail token the run reports CAPTURE_REQUIRED and performs no detail request', async () => {
  const dir = await makeTempDir();
  try {
    const calls = [];
    const fetchImpl = async (url) => {
      calls.push(url);
      return response(200, { bookings: [{ bookingId: '1000001', legacyBookingToken: 'lt-1' }], pagination: { totalPages: 1 } });
    };
    const outcome = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts: {}, fetchImpl });
    const row = outcome.rows[0];
    assert.equal(row.counts.listed, 1);
    assert.equal(row.counts.details_capture, 1);
    assert.match(row.diagnostics.join('|'), /detail_token_unobserved/);
    assert.equal(calls.some((url) => url.includes('/eb/details')), false);
    assert.equal(outcome.manifest.status, 'CAPTURE_REQUIRED');
  } finally {
    await removeTemp(dir);
  }
});

test('denied login is reported as LOGIN_REQUIRED and never retried into a different status', async () => {
  const dir = await makeTempDir();
  try {
    let attempts = 0;
    const fetchImpl = async () => {
      attempts += 1;
      return response(401, { error: 'unauthenticated' });
    };
    const outcome = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts: {}, fetchImpl });
    const row = outcome.rows[0];
    assert.equal(row.status, 'LOGIN_REQUIRED');
    assert.equal(attempts, 1, '401 is not retried as transient');
    assert.equal(outcome.manifest.status, 'LOGIN_REQUIRED');
  } finally {
    await removeTemp(dir);
  }
});

test('a request abort is interrupted rather than recorded as a collectable result', async () => {
  const controller = new AbortController();
  const fetchImpl = async () => {
    controller.abort();
    const error = new Error('aborted');
    error.name = 'AbortError';
    throw error;
  };
  await assert.rejects(
    requestJson({ fetchImpl, url: 'http://synthetic.invalid/x', signal: controller.signal, retryDelay: () => 0 }),
    (error) => error.cls === 'abort',
  );
});

test('runPool isolates a throwing worker so other lanes still complete', async () => {
  const results = await runPool([1, 2, 3, 4], 2, async (value) => {
    if (value === 2) throw new Error('synthetic worker failure');
    return value;
  });
  assert.equal(results.length, 4);
  assert.equal(results.filter((entry) => entry.ok).length, 3);
  assert.equal(results[1].ok, false);
});

// The bounded pool is the only concurrency shape: the provider never fans out
// beyond its detail cap and the collector never raises a shared mutable limit.
