#!/usr/bin/env node
/**
 * Explicit ego-browser entry point for OTA portal collection.
 *
 * Importing collect_ota_portals.mjs has no side effects; this file is the one
 * place the ego-browser TaskSpace workflow runs when the operator evaluates it.
 * TaskSpace lifecycle (ego-browser skill):
 *   - one goal -> one TaskSpace, created once and reused by later rounds;
 *   - an existing/resumable id is reused, never duplicated;
 *   - a user-owned/name-in-use conflict is surfaced, never worked around.
 * Navigation uses only the provider entry/templates carried by the provider
 * access descriptors (SPEC §7 procedure); nothing is guessed here.
 */
import { realpathSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TOOL_NAME } from './constants.mjs';
import { parseProviders, runEgoJob } from '../collect_ota_portals.mjs';

function isEntryExecution() {
  const entry = process.argv[1];
  if (!entry || entry === '-e' || entry === '--eval') return true;
  try {
    return realpathSync(path.resolve(entry)) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

export async function mainEgo({
  taskSpace,
  taskSpaceId = null,
  providers,
  archiveDir = null,
  opts = {},
  clock,
  fetchImpl = null,
  page = null,
  runId = null,
} = {}) {
  if (typeof taskSpace !== 'function') {
    throw new Error('entry-runner requires the ego-browser taskSpace() factory; import runEgoJob with a custom page/fetch for another driver');
  }
  const selected = providers === undefined ? undefined : Array.isArray(providers) ? providers.join(',') : providers;
  const goalName = `ota portal collection${selected ? ` ${selected}` : ''}`;
  let handle;
  if (taskSpaceId !== null && taskSpaceId !== undefined) {
    handle = await taskSpace(taskSpaceId);
  } else {
    try {
      handle = await taskSpace(goalName);
    } catch (error) {
      throw new Error(`${error?.code ?? 'TASK_SPACE_ERROR'}: cannot resume or create the collection TaskSpace '${goalName}'; if it is user-owned (for example EGO_TASK_SPACE_NAME_IN_USE) ask the user instead of creating another space`, { cause: error });
    }
  }
  return runEgoJob({
    providers: selected === undefined ? undefined : parseProviders(selected),
    archiveDir,
    opts,
    clock,
    fetchImpl,
    task: handle,
    page,
    runId,
  });
}

if (isEntryExecution()) {
  try {
    await mainEgo();
  } catch (error) {
    console.error(`${TOOL_NAME}: ${error?.message ?? 'entry failed'}`);
    process.exitCode = 1;
  }
}
