#!/usr/bin/env node
/**
 * Side-effect-free explicit entry helpers for OTA portal collection.
 *
 * Importing this module (or collect_ota_portals.mjs) has no side effects:
 * no TaskSpace is created and no run starts. The documented execution is one
 * explicit call that supplies (or resolves) the ego-browser taskSpace() factory:
 *
 *   const { mainEgo } = await import('file:///C:/.../tools/ota_collection/entry-runner.mjs');
 *   await mainEgo({ taskSpace: globalThis.taskSpace });
 *
 * An omitted factory is resolved from the ego environment's global taskSpace
 * (globalThis first, then the ambient global) so the same call works under the
 * SDK loader; anywhere else it fails loudly instead of guessing browser access.
 *
 * TaskSpace lifecycle (ego-browser skill):
 *   - one goal -> one TaskSpace, created once and reused by later rounds;
 *   - an existing/resumable id is reused, never duplicated;
 *   - a user-owned/name-in-use conflict is surfaced, never worked around.
 * Navigation uses only the provider entry/templates carried by the provider
 * access descriptors (SPEC section 7 procedure); nothing is guessed here.
 */
import { TOOL_NAME } from './constants.mjs';
import { parseProviders, runEgoJob } from '../collect_ota_portals.mjs';

function resolveFactory(factory) {
  if (typeof factory === 'function') return factory;
  if (typeof globalThis.taskSpace === 'function') return globalThis.taskSpace.bind(globalThis);
  if (typeof taskSpace === 'function') return taskSpace.bind(globalThis);
  return null;
}

export async function mainEgo({
  taskSpace = undefined,
  taskSpaceId = null,
  providers,
  archiveDir = null,
  opts = {},
  clock,
  fetchImpl = null,
  page = null,
  runId = null,
} = {}) {
  const factory = resolveFactory(taskSpace);
  if (!factory) {
    throw new Error(`${TOOL_NAME}: no ego-browser taskSpace() factory found; call this entry from the ego-browser environment or pass taskSpace explicitly`);
  }
  const selected = providers === undefined ? undefined : Array.isArray(providers) ? providers.join(',') : providers;
  const goalName = `ota portal collection${selected ? ` ${selected}` : ''}`;
  let handle;
  if (taskSpaceId !== null && taskSpaceId !== undefined) {
    try {
      handle = await factory(taskSpaceId);
    } catch (error) {
      throw new Error(`${TOOL_NAME}: TASK_SPACE_RESUME_FAILED: cannot resume the collection TaskSpace '${taskSpaceId}'; if it is user-owned ask the user instead of working around it`, { cause: error });
    }
  } else {
    try {
      handle = await factory(goalName);
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
