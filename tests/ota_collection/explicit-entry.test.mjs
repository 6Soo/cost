import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mainEgo } from '../../tools/ota_collection/entry-runner.mjs';
import {
  buildPlanText,
  parseProviders,
  runEgoJob,
} from '../../tools/collect_ota_portals.mjs';
import { makeTempDir, cleanup } from './helpers.mjs';

const COLLECT_PATH = fileURLToPath(new URL('../../tools/collect_ota_portals.mjs', import.meta.url));
const ENTRY_PATH = fileURLToPath(new URL('../../tools/ota_collection/entry-runner.mjs', import.meta.url));

function response(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: () => null },
    text: async () => JSON.stringify(payload),
  };
}

function makePage(goes, calls) {
  return {
    goes,
    calls,
    async goto(url) { goes.push(String(url)); },
    async fetch(url, init) {
      calls.push({ url: String(url), init });
      if (String(url).includes('GetBookingsList')) {
        return response(200, { bookings: [{ bookingId: '1000001', legacyBookingToken: 'lt-1' }], pagination: { totalPages: 1 } });
      }
      if (String(url).includes('/eb/details')) {
        return response(200, { BookingDetails: { BookingQueryData: { CancellationReasonData: { BookingID: '1000001' } } } });
      }
      if (String(url).includes('getAllOrders')) {
        return response(200, { OrderList: [{ OrderID: '2000000001' }] });
      }
      if (String(url).includes('dml/graphql')) {
        return response(200, { data: { userTrips: { trips: [{ id: 'T1' }], hasMore: false } } });
      }
      return response(404, { error: 'not_found' });
    },
  };
}

test('importing collect_ota_portals.mjs has no browser side effects', async () => {
  let calls = 0;
  const spy = async () => { calls += 1; throw new Error('import must not run'); };
  const previous = globalThis.taskSpace;
  globalThis.taskSpace = spy;
  try {
    const module = await import(pathToFileURL(COLLECT_PATH).href);
    assert.equal(typeof module.runEgoJob, 'function');
    assert.equal(typeof module.parseProviders, 'function');
    assert.equal(calls, 0, 'import must not create or resume a TaskSpace');
    assert.deepEqual(module.parseProviders('agoda,trip'), ['agoda', 'trip']);
    assert.match(module.buildPlanText(['booking']), /entry-runner\.mjs/);
    assert.match(module.buildPlanText(['booking']), /import만으로는 브라우저나 TaskSpace가 기동하지 않는다/);
  } finally {
    if (previous === undefined) delete globalThis.taskSpace;
    else globalThis.taskSpace = previous;
  }
});

test('an injected TaskSpace page is navigated per provider before its requests', async () => {
  const dir = await makeTempDir();
  const goes = [];
  const calls = [];
  const page = makePage(goes, calls);
  try {
    const outcome = await runEgoJob({
      providers: 'agoda,trip,booking',
      archiveDir: dir,
      opts: { agodaDetailToken: 'synthetic-token', bookingQuery: 'query synthetic { userTrips { trips { id } } }' },
      page,
      clock: () => new Date('2026-11-11T00:00:00.000Z'),
    });
    assert.deepEqual(goes, [
      'https://www.agoda.com/ko-kr/account/bookings.html',
      'https://kr.trip.com/account/signin',
      'https://secure.booking.com/mytrips.ko.html',
    ]);

    const allowedHosts = new Set(['www.agoda.com', 'kr.trip.com', 'secure.booking.com']);
    assert.ok(calls.length > 0);
    for (const call of calls) {
      const { hostname } = new URL(call.url);
      assert.ok(allowedHosts.has(hostname), `request left documented hosts: ${hostname}`);
    }

    assert.ok(['CAPTURE_REQUIRED', 'PARTIAL'].includes(outcome.manifest.status), outcome.manifest.status);
    assert.equal(outcome.manifest.providers.length, 3);
    for (const row of outcome.manifest.providers) {
      assert.equal(row.navigation.verified, true);
    }
    assert.ok(outcome.rows.some((row) => row.provider === 'agoda' && row.status === 'ok'));
    const saved = await readdir(path.join(outcome.manifest.archive_root, 'agoda', 'details'));
    assert.deepEqual(saved, ['1000001.json']);
  } finally {
    await cleanup(dir);
  }
});

test('a resumed taskSpaceId is reused and only the factory call is recorded', async () => {
  const dir = await makeTempDir();
  const seen = [];
  const calls = [];
  const goes = [];
  const page = makePage(goes, calls);
  try {
    const outcome = await runEgoJob({
      taskSpace: async (id) => { seen.push(id); return { page: () => page, finish: async () => { } }; },
      taskSpaceId: '42',
      providers: 'trip',
      archiveDir: dir,
    });
    assert.deepEqual(seen, ['42']);
    assert.ok(outcome.rows.length === 1);
    assert.ok(goes.length >= 1);
  } finally {
    await cleanup(dir);
  }
});

test('name reuse uses the stable goal name and an unresolved conflict is not worked around', async () => {
  const dir = await makeTempDir();
  const seen = [];
  const page = makePage([], []);
  try {
    await runEgoJob({
      taskSpace: async (name) => { seen.push(name); return { page: () => page, finish: async () => { } }; },
      providers: 'booking',
      archiveDir: dir,
      opts: { bookingQuery: 'query synthetic { userTrips { trips { id } } }' },
    });
    assert.deepEqual(seen, ['ota portal collection booking']);

    seen.length = 0;
    const conflict = async (name) => { seen.push(name); const error = new Error('space is user-owned'); error.code = 'EGO_TASK_SPACE_NAME_IN_USE'; throw error; };
    await assert.rejects(
      runEgoJob({ taskSpace: conflict, providers: 'agoda', archiveDir: dir, opts: { agodaDetailToken: 'synthetic-token' } }),
      (error) => { assert.match(error.message, /EGO_TASK_SPACE_NAME_IN_USE/); assert.match(error.message, /ask the user/); return true; },
    );
    assert.deepEqual(seen, ['ota portal collection agoda']);
  } finally {
    await cleanup(dir);
  }
});

test('importing both entry modules has no browser side effects, even with an ego-like global present', () => {
  const script = [
    "globalThis.__factoryCalls = 0;",
    "globalThis.taskSpace = async () => { globalThis.__factoryCalls += 1; throw new Error('factory must not be called on import'); };",
    `const collectUrl = ${JSON.stringify(pathToFileURL(COLLECT_PATH).href)};`,
    `const entryUrl = ${JSON.stringify(pathToFileURL(ENTRY_PATH).href)};`,
    'const collect = await import(collectUrl);',
    'const entry = await import(entryUrl);',
    "if (typeof collect.runEgoJob !== 'function' || typeof entry.mainEgo !== 'function') throw new Error('missing expected exports');",
    "console.log('IMPORT_OK factoryCalls=' + globalThis.__factoryCalls);",
  ].join('\n');
  const result = spawnSync(process.execPath, ['--input-type=module', '--eval', script], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /IMPORT_OK factoryCalls=0/);
});

test('mainEgo without an ego-like factory fails loudly', async () => {
  const dir = await makeTempDir();
  const previous = globalThis.taskSpace;
  try {
    delete globalThis.taskSpace;
    await assert.rejects(
      mainEgo({ providers: 'agoda', archiveDir: dir }),
      /no ego-browser taskSpace/,
    );
  } finally {
    if (previous !== undefined) globalThis.taskSpace = previous;
    await cleanup(dir);
  }
});

test('documented instance: global factory used once per run and a name resumes instead of duplicating', async () => {
  const dir = await makeTempDir();
  const names = [];
  const finished = [];
  const page = makePage([], []);
  const previous = globalThis.taskSpace;
  globalThis.taskSpace = async (id) => {
    names.push(String(id));
    if (String(id) === '42' || String(id).startsWith('ota portal collection')) {
      return { page: () => page, finish: async () => { finished.push(1); } };
    }
    throw new Error(`unexpected name ${id}`);
  };
  const opts = { agodaDetailToken: 'synthetic-token' };
  try {
    const clock = () => new Date('2026-11-11T00:00:00.000Z');
    const first = await mainEgo({ providers: 'agoda', archiveDir: dir, opts, clock });
    const second = await mainEgo({ providers: 'agoda', archiveDir: dir, opts, clock });
    assert.deepEqual(names, ['ota portal collection agoda', 'ota portal collection agoda']);
    assert.notEqual(first.archiveRoot, second.archiveRoot);
    assert.equal(finished.length, 2, 'one completion call per run');

    const third = await mainEgo({ taskSpaceId: '42', providers: 'agoda', archiveDir: dir, opts, clock, taskSpace: undefined });
    assert.equal(names[2], '42');
    assert.ok(third.rows.length === 1);
  } finally {
    if (previous === undefined) delete globalThis.taskSpace;
    else globalThis.taskSpace = previous;
    await cleanup(dir);
  }
});

test('a user-owned space conflict is reported, never worked around', async () => {
  const dir = await makeTempDir();
  const seen = [];
  const conflict = async (name) => {
    seen.push(String(name));
    const error = new Error('space is user-owned');
    error.code = 'EGO_TASK_SPACE_NAME_IN_USE';
    throw error;
  };
  try {
    await assert.rejects(
      mainEgo({ taskSpace: conflict, providers: 'agoda', archiveDir: dir, opts: { agodaDetailToken: 'synthetic-token' } }),
      (error) => { assert.match(error.message, /EGO_TASK_SPACE_NAME_IN_USE/); assert.match(error.message, /ask the user/); return true; },
    );
    assert.deepEqual(seen, ['ota portal collection agoda']);
  } finally {
    await cleanup(dir);
  }
});

test('runEgoJob without an injected page or fetch fails cleanly instead of guessing browser access', async () => {
  await assert.rejects(
    runEgoJob({ providers: 'agoda', opts: { agodaDetailToken: 'synthetic-token' } }),
    /no browser page available/,
  );
});
