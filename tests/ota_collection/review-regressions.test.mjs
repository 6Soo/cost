import { test } from 'node:test';
import assert from 'node:assert/strict';
import { access, mkdir, readFile, readdir, symlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { runCollection } from '../../tools/ota_collection/collector.mjs';
import { artifactPath, saveArtifacts } from '../../tools/ota_collection/storage.mjs';
import { runEgoJob, EGO_RUN_COMMAND } from '../../tools/collect_ota_portals.mjs';
import { assertAllowedUrl, resolveAccess } from '../../tools/ota_collection/providers.mjs';
import { cleanup, fakeFetch, makeTempDir, response } from './helpers.mjs';

const opts = { agodaDetailToken: 'synthetic-observed-token', tripOffsetField: 'ObservedOffset' };
const agodaDetail = (id) => ({ BookingDetails: { BookingQueryData: { CancellationReasonData: { BookingID: id } } } });
const tripEntry = (id) => ({ OrderID: id, OrderActions: [{ ActionURLH5: 'https://kr.trip.com/?tripsignature=synthetic-sign' }] });
const tripDetail = (id) => ({ orderCommonInfo: { orderId: id } });

for (const provider of ['agoda', 'trip']) {
  test(`${provider} rejects entire malicious IDs before detail requests or writes`, async () => {
    const dir = await makeTempDir();
    try {
      const ids = ['../../../12345678', '..\\..\\12345678', '/12345678', 'C:\\12345678',
        '\\\\server\\share\\12345678', '12345678/child', '12345678\n', 'x12345678', '1'.repeat(21),
        9007199254740992, { toString: '12345678' }, null];
      const fetchImpl = fakeFetch((url, init) => {
        if (url.includes('GetBookingsList')) return response(200, {
          bookings: ids.map((bookingId) => ({ bookingId, legacyBookingToken: bookingId })), pagination: { totalPages: 1 },
        });
        if (url.includes('getAllOrders')) return response(200, { OrderList: ids.map(tripEntry) });
        const body = JSON.parse(init.body);
        return response(200, provider === 'agoda' ? agodaDetail(body.BookingToken) : tripDetail(body.orderId));
      });
      const result = await runCollection({ providers: [provider], archiveRoot: path.join(dir, 'archive'), opts, fetchImpl });
      assert.equal(fetchImpl.calls.length, 1);
      assert.equal(result.rows[0].counts.items_invalid, ids.length);
      assert.equal(result.rows[0].counts.details_saved, 0);
      assert.deepEqual(await readdir(dir), ['archive']);
    } finally { await cleanup(dir); }
  });
}

test('artifact paths reject traversal, Windows absolute, drive-relative, ADS and provider escape', () => {
  for (const file of ['../outside.json', 'details/../../outside.json', '..\\outside.json',
    '/outside.json', 'C:\\outside.json', 'C:outside.json', '\\\\server\\share\\x.json',
    'details/x.json:stream', 'details/CON.json', 'details/x.json.']) {
    assert.throws(() => artifactPath('archive', 'agoda', file), (e) => e.code === 'OUTPUT_PATH_INVALID', file);
  }
  assert.throws(() => artifactPath('archive', '../outside', 'x.json'), (e) => e.code === 'OUTPUT_PATH_INVALID');
});

test('saveArtifacts refuses physical directory links and preserves the external target', async () => {
  const dir = await makeTempDir();
  try {
    const root = path.join(dir, 'archive');
    const outside = path.join(dir, 'outside');
    await mkdir(path.join(root, 'agoda'), { recursive: true });
    await mkdir(outside);
    // A Windows junction is a real directory redirect and needs no developer mode.
    await symlink(outside, path.join(root, 'agoda', 'details'), process.platform === 'win32' ? 'junction' : 'dir');
    await assert.rejects(saveArtifacts({ root, provider: 'agoda', files: [{ file: 'details/12345678.json', data: {} }] }),
      (e) => e.code === 'OUTPUT_PATH_INVALID');
    assert.deepEqual(await readdir(outside), []);
  } finally { await cleanup(dir); }
});

test('Trip next request sends the observed field and response cursor exactly', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = fakeFetch((url, init) => {
      const body = JSON.parse(init.body);
      if (!url.includes('getAllOrders')) return response(200, tripDetail(body.orderId));
      if (body.ObservedOffset === undefined) return response(200, { OrderList: [tripEntry('12345678')], Offset: 'synthetic-next' });
      assert.equal(body.ObservedOffset, 'synthetic-next');
      return response(200, { OrderList: [tripEntry('12345679')] });
    });
    const result = await runCollection({ providers: ['trip'], archiveRoot: dir, opts, fetchImpl });
    const calls = fetchImpl.calls.filter((c) => c.url.includes('getAllOrders'));
    assert.equal(calls.length, 2);
    assert.deepEqual(JSON.parse(calls[1].init.body), { OrderStatusClassify: 'All', Count: 20, ObservedOffset: 'synthetic-next' });
    assert.equal(result.rows[0].counts.listed, 2);
    assert.equal(result.rows[0].counts.details_saved, 2);
    assert.equal(result.manifest.status, 'ok');
  } finally { await cleanup(dir); }
});

for (const provider of ['agoda', 'trip']) {
  for (const stage of ['detail', 'second-list']) {
    test(`${provider} ${stage} login expiry stops every subsequent request and navigation`, async () => {
      const dir = await makeTempDir();
      try {
        let lists = 0;
        let details = 0;
        const goes = [];
        const fetchImpl = fakeFetch((url) => {
          if (url.includes('GetBookingsList') || url.includes('getAllOrders')) {
            lists += 1;
            if (stage === 'second-list' && lists === 2) return response(401, {});
            return response(200, provider === 'agoda'
              ? { bookings: [1, 2].map((n) => ({ bookingId: String(12345670 + n), legacyBookingToken: String(n) })), pagination: { totalPages: stage === 'second-list' ? 2 : 1 } }
              : { OrderList: [tripEntry('12345671'), tripEntry('12345672')], ...(stage === 'second-list' ? { Offset: 'synthetic-next' } : {}) });
          }
          details += 1;
          return response(403, {});
        });
        const result = await runCollection({ providers: [provider, 'booking'], archiveRoot: dir, opts, fetchImpl, goto: async (url) => goes.push(url) });
        assert.equal(details, stage === 'detail' ? 1 : 0);
        assert.equal(goes.length, 1);
        assert.equal(result.manifest.status, 'LOGIN_REQUIRED');
        assert.equal(result.rows[0].counts.details_saved, 0);
        assert.equal(result.rows[1].status, 'INTERRUPTED');
        assert.equal(result.rows[0].counts.details_skipped, stage === 'detail' ? 1 : 2);
      } finally { await cleanup(dir); }
    });
  }
}

test('public collection stops on the 31st failed detail, keeps prior files, and reports interruption', async () => {
  const dir = await makeTempDir();
  try {
    let details = 0;
    const fetchImpl = fakeFetch((url, init) => {
      if (url.includes('GetBookingsList')) return response(200, {
        bookings: Array.from({ length: 40 }, (_, i) => ({ bookingId: String(12345670 + i), legacyBookingToken: String(12345670 + i) })),
        pagination: { totalPages: 1 },
      });
      details += 1;
      return details === 1 ? response(200, agodaDetail(JSON.parse(init.body).BookingToken)) : response(400, {});
    });
    const result = await runCollection({ providers: ['agoda', 'trip'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(details, 32, 'one success then 31 failures, never the 32nd failure');
    assert.equal(result.manifest.status, 'INTERRUPTED');
    assert.equal(result.rows[0].counts.details_saved, 1);
    assert.equal(result.rows[1].status, 'INTERRUPTED');
    assert.ok(result.rows[0].diagnostics.includes('failure_limit_exceeded'));
    await access(path.join(dir, 'agoda', 'details', '12345670.json'));
  } finally { await cleanup(dir); }
});

test('partial write failure reports only actually saved details and preserves existing bytes', async () => {
  const dir = await makeTempDir();
  try {
    await mkdir(path.join(dir, 'agoda', 'details'), { recursive: true });
    const existing = path.join(dir, 'agoda', 'details', '12345672.json');
    await writeFile(existing, 'existing-original');
    const fetchImpl = fakeFetch((url, init) => url.includes('GetBookingsList')
      ? response(200, { bookings: [1, 2].map((n) => ({ bookingId: String(12345670 + n), legacyBookingToken: String(12345670 + n) })), pagination: { totalPages: 1 } })
      : response(200, agodaDetail(JSON.parse(init.body).BookingToken)));
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(result.rows[0].status, 'FAILED');
    assert.equal(result.rows[0].counts.details_saved, 1);
    assert.deepEqual(result.rows[0].files, ['details/12345671.json']);
    assert.equal(result.manifest.providers[0].counts.details_saved, 1);
    assert.equal(await readFile(existing, 'utf8'), 'existing-original');
  } finally { await cleanup(dir); }
});

test('list request limit includes transient retries, while detail retries remain at three', async () => {
  const dir = await makeTempDir();
  try {
    let lists = 0;
    let details = 0;
    let active = 0;
    let peak = 0;
    const fetchImpl = fakeFetch(async (url, init) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      active -= 1;
      if (url.includes('GetBookingsList')) {
        lists += 1;
        if (lists % 2 === 1) return response(503, {});
        const page = JSON.parse(init.body).pageIndex;
        return response(200, { bookings: [{ bookingId: String(12345670 + page), legacyBookingToken: 'synthetic' }], pagination: { totalPages: 10 } });
      }
      details += 1;
      return response(503, {});
    });
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts, fetchImpl });
    assert.ok(lists <= 5, `actual list attempts: ${lists}`);
    assert.equal(details, result.rows[0].counts.listed * 3);
    assert.ok(peak <= 6);
    assert.notEqual(result.manifest.status, 'ok');
  } finally { await cleanup(dir); }
});

test('31 detail identity failures stop through the same public failure budget', async () => {
  const dir = await makeTempDir();
  try {
    let details = 0;
    const fetchImpl = fakeFetch((url) => {
      if (url.includes('GetBookingsList')) return response(200, { bookings: Array.from({ length: 40 }, (_, i) => ({ bookingId: String(12345670 + i) })), pagination: { totalPages: 1 } });
      details += 1;
      return response(200, agodaDetail('99999999'));
    });
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(details, 31);
    assert.equal(result.manifest.status, 'INTERRUPTED');
  } finally { await cleanup(dir); }
});

test('page.fetch body transport is adapted by the actual runEgoJob entry', async () => {
  const dir = await makeTempDir();
  try {
    const result = await runEgoJob({ providers: ['agoda'], archiveDir: dir,
      page: { goto: async () => {}, fetch: async () => ({ status: 200, body: JSON.stringify({ bookings: [], pagination: { totalPages: 1 } }) }) } });
    assert.equal(result.manifest.status, 'ok');
    assert.match(EGO_RUN_COMMAND, /await mainEgo\(/);
  } finally { await cleanup(dir); }
});

test('entry refuses run ID traversal before creating or navigating a TaskSpace', async () => {
  const dir = await makeTempDir();
  try {
    let factories = 0;
    await assert.rejects(runEgoJob({ providers: ['agoda'], archiveDir: path.join(dir, 'base'), runId: '../outside',
      taskSpace: async () => { factories += 1; return {}; }, fetchImpl: async () => response(200, {}) }),
      (e) => e.code === 'OUTPUT_PATH_INVALID');
    assert.equal(factories, 0);
    assert.deepEqual(await readdir(dir), []);
  } finally { await cleanup(dir); }
});

test('failed navigation sends no requests and metadata excludes observed entry secrets', async () => {
  const dir = await makeTempDir();
  try {
    let requests = 0;
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts,
      goto: async () => { throw new Error('synthetic-navigation-secret'); },
      fetchImpl: async () => { requests += 1; return response(200, { bookings: [], pagination: { totalPages: 1 } }); } });
    assert.equal(requests, 0);
    assert.notEqual(result.manifest.status, 'ok');
    assert.ok(!JSON.stringify(result.manifest).includes('synthetic-navigation-secret'));
  } finally { await cleanup(dir); }
});

test('manifest never records entry query tokens, server content types or rejected ID text', async () => {
  const dir = await makeTempDir();
  try {
    const secret = 'synthetic-private-value';
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir,
      opts: { urls: { entry: `/ko-kr/account/bookings.html?token=${secret}#${secret}` } },
      fetchImpl: async () => response(200, null, { raw: 'non-json', headers: { 'content-type': `text/plain; x=${secret}` } }) });
    assert.ok(!JSON.stringify(result.manifest).includes(secret));
  } finally { await cleanup(dir); }
});

test('observed Trip entry/list/detail hosts are exact and cannot be swapped or extended', async () => {
  const dir = await makeTempDir();
  try {
    const goes = [];
    const fetchImpl = fakeFetch((url, init) => url.includes('getAllOrders')
      ? response(200, { OrderList: [tripEntry('12345678')] }) : response(200, tripDetail(JSON.parse(init.body).orderId)));
    await runCollection({ providers: ['trip'], archiveRoot: dir, opts, fetchImpl, goto: async (url) => goes.push(url) });
    assert.deepEqual(goes, ['https://kr.trip.com/account/signin']);
    assert.deepEqual(fetchImpl.calls.map((call) => call.url), [
      'https://online.trip.com/restapi/soa2/26974/getAllOrders.json',
      'https://kr.trip.com/restapi/soa2/27453/GetOrderDetailOnline',
    ]);
    const access = resolveAccess('trip');
    for (const url of ['https://kr.trip.com/restapi/soa2/26974/getAllOrders.json',
      'https://online.trip.com/restapi/soa2/27453/GetOrderDetailOnline', 'https://evil.invalid/restapi/soa2/26974/getAllOrders.json',
      'https://kr.trip.com/cancel', 'https://user:password@online.trip.com/restapi/soa2/26974/getAllOrders.json']) {
      assert.throws(() => assertAllowedUrl(url, access), (e) => e.code === 'URL_NOT_ALLOWED');
    }
    assert.ok(resolveAccess('trip', { urls: { list: 'https://kr.trip.com/restapi/soa2/26974/getAllOrders.json' } }).error);
  } finally { await cleanup(dir); }
});

test('archive root, provider, ancestor and final file links never redirect writes', async () => {
  const dir = await makeTempDir();
  try {
    const outside = path.join(dir, 'outside');
    await mkdir(outside);
    for (const kind of ['root', 'provider', 'ancestor']) {
      const base = path.join(dir, kind);
      await mkdir(base);
      const link = path.join(base, 'redirect');
      await symlink(outside, link, process.platform === 'win32' ? 'junction' : 'dir');
      const root = kind === 'provider' ? base : kind === 'root' ? link : path.join(link, 'new-run');
      const provider = kind === 'provider' ? 'redirect' : 'agoda';
      await assert.rejects(saveArtifacts({ root, provider, files: [{ file: 'details/12345678.json', data: {} }] }),
        (e) => e.code === 'OUTPUT_PATH_INVALID');
      assert.deepEqual(await readdir(outside), []);
    }
    // Directory junction coverage above is unconditional on Windows. A hard
    // link at the file boundary also must never be overwritten by wx.
    const { link } = await import('node:fs/promises');
    const original = path.join(outside, 'original.json');
    await writeFile(original, 'original-bytes');
    await mkdir(path.join(dir, 'files', 'agoda'), { recursive: true });
    await link(original, path.join(dir, 'files', 'agoda', '12345678.json'));
    await assert.rejects(saveArtifacts({ root: path.join(dir, 'files'), provider: 'agoda', files: [{ file: '12345678.json', data: {} }] }),
      (e) => e.code === 'OUTPUT_EXISTS');
    assert.equal(await readFile(original, 'utf8'), 'original-bytes');
  } finally { await cleanup(dir); }
});

test('Agoda keeps the observed includeArchive flag and invalid counts across pages', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = fakeFetch((url, init) => {
      const body = JSON.parse(init.body);
      if (url.includes('GetBookingsList')) {
        assert.equal(body.includeArchive, true);
        return response(200, { bookings: body.pageIndex === 1 ? [{ bookingId: 'invalid' }] : [], pagination: { totalPages: 2 } });
      }
      throw new Error('no details expected');
    });
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(result.rows[0].counts.items_invalid, 1);
    assert.notEqual(result.manifest.status, 'ok');
  } finally { await cleanup(dir); }
});

test('failure count continues across providers instead of resetting on a new portal', async () => {
  const dir = await makeTempDir();
  try {
    let attempts = 0;
    const fetchImpl = fakeFetch((url) => {
      attempts += 1;
      if (url.includes('GetBookingsList')) return response(200, {
        bookings: Array.from({ length: 30 }, (_, i) => ({ bookingId: String(12345670 + i) })), pagination: { totalPages: 1 },
      });
      return response(400, {});
    });
    const result = await runCollection({ providers: ['agoda', 'trip', 'booking'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(attempts, 32);
    assert.equal(result.rows[1].status, 'INTERRUPTED');
    assert.equal(result.rows[2].status, 'INTERRUPTED');
  } finally { await cleanup(dir); }
});

test('duplicate detail filenames count one saved file when the second write is refused', async () => {
  const dir = await makeTempDir();
  try {
    const fetchImpl = fakeFetch((url) => url.includes('GetBookingsList')
      ? response(200, { bookings: [{ bookingId: '12345678' }, { bookingId: '12345678' }], pagination: { totalPages: 1 } })
      : response(200, agodaDetail('12345678')));
    const result = await runCollection({ providers: ['agoda'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(result.manifest.providers[0].counts.details_saved, 1);
    assert.deepEqual(result.rows[0].files, ['details/12345678.json']);
    assert.equal(result.rows[0].status, 'FAILED');
  } finally { await cleanup(dir); }
});

test('a write conflict cannot erase an earlier login stop and restart subsequent providers', async () => {
  const dir = await makeTempDir();
  try {
    await mkdir(path.join(dir, 'agoda', 'details'), { recursive: true });
    await writeFile(path.join(dir, 'agoda', 'details', '12345678.json'), 'original');
    let details = 0;
    const fetchImpl = fakeFetch((url) => {
      if (url.includes('GetBookingsList')) return response(200, { bookings: [{ bookingId: '12345678' }, { bookingId: '12345679' }], pagination: { totalPages: 1 } });
      details += 1;
      return details === 1 ? response(200, agodaDetail('12345678')) : response(401, {});
    });
    const result = await runCollection({ providers: ['agoda', 'trip'], archiveRoot: dir, opts, fetchImpl });
    assert.equal(fetchImpl.calls.length, 3);
    assert.equal(result.manifest.status, 'LOGIN_REQUIRED');
    assert.equal(result.rows[0].counts.details_saved, 0);
    assert.equal(result.rows[1].status, 'INTERRUPTED');
    assert.equal(await readFile(path.join(dir, 'agoda', 'details', '12345678.json'), 'utf8'), 'original');
  } finally { await cleanup(dir); }
});

for (const provider of ['agoda', 'trip']) {
  for (const writeConflict of [false, true]) {
    test(`${provider} summary manifest excludes raw artifact identifiers after ${writeConflict ? 'partial write failure' : 'successful writes'}`, async () => {
      const dir = await makeTempDir();
      try {
        const ids = ['876543210123', '876543210124'];
        const guestName = 'SyntheticPrivateGuest';
        const token = 'synthetic-private-artifact-token';
        const items = ids.map((id) => provider === 'agoda'
          ? { bookingId: id, legacyBookingToken: token, guestName }
          : { OrderID: id, guestName, OrderActions: [{ ActionURLH5: `https://kr.trip.com/?tripsignature=${token}` }] });
        const details = ids.map((id) => ({ ...(provider === 'agoda' ? agodaDetail(id) : tripDetail(id)), guestName }));
        const fetchImpl = fakeFetch((url, init) => {
          if (url.includes('GetBookingsList')) return response(200, { bookings: items, pagination: { totalPages: 1 } });
          if (url.includes('getAllOrders')) return response(200, { OrderList: items });
          const index = provider === 'agoda'
            ? fetchImpl.calls.filter((call) => call.url.includes('/eb/details')).length - 1
            : ids.indexOf(JSON.parse(init.body).orderId);
          return response(200, details[index]);
        });
        const detailDir = path.join(dir, provider, 'details');
        if (writeConflict) {
          await mkdir(detailDir, { recursive: true });
          await writeFile(path.join(detailDir, `${ids[1]}.json`), 'preserved-original');
        }
        const result = await runCollection({ providers: [provider], archiveRoot: dir,
          opts: { ...opts, agodaDetailToken: token }, fetchImpl });
        const persisted = await readFile(path.join(dir, 'manifest.json'), 'utf8');
        assert.deepEqual(JSON.parse(persisted), result.manifest);
        for (const sensitive of [...ids, guestName, token]) {
          assert.ok(!persisted.includes(sensitive), 'summary manifest must not expose raw record identifiers or content');
        }
        assert.equal(result.manifest.status, writeConflict ? 'FAILED' : 'ok');
        assert.equal(result.manifest.providers[0].counts.details_saved, writeConflict ? 1 : 2);
        // The importer still receives its original filename and document shape.
        const saved = JSON.parse(await readFile(path.join(detailDir, `${ids[0]}.json`), 'utf8'));
        assert.deepEqual(saved[provider === 'agoda' ? 'list' : 'order'], items[0]);
        assert.deepEqual(saved.detail, details[0]);
        assert.ok(saved.observed_at);
        assert.deepEqual((await readdir(detailDir)).sort(), ids.map((id) => `${id}.json`));
        if (writeConflict) {
          assert.equal(await readFile(path.join(detailDir, `${ids[1]}.json`), 'utf8'), 'preserved-original');
        } else if (provider === 'trip') {
          assert.deepEqual(JSON.parse(await readFile(path.join(dir, provider, 'orders.json'), 'utf8')), items);
        }
      } finally { await cleanup(dir); }
    });
  }
}
