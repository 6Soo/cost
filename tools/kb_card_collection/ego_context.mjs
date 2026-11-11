// Shipped default browser context: connects the entry seam (./entry_kb.mjs) to ego-browser's
// TaskSpace/Page operations as documented by the installed guidance (ego-browser skill, version
// 2.2.0 Windows section): taskSpace(name), page.goto/snapshot/fill/click, page.waitForEvent("download"),
// download.saveAs(absolutePath), snapshot refs/role/text semantics. It is imported automatically by
// entry_kb.mjs when no KB_CARD_BROWSER_CONTEXT / injection is supplied, so operators do not author
// a context module.
//
// Live-shape honesty (NOT_VERIFIED until the user-run real session; read/observe/save only, no
// site, login, new space, or customer data is touched by this code path or by verification):
//   - snapshot normalization is best-effort over documented snapshot role/name/text-like fields;
//     unrecognized shapes fail loudly instead of yielding guessed presence.
//   - user selector vocabulary is passed through verbatim for actions (ego accepts snapshot refs,
//     loc=/css=/xpath=/text= and raw CSS); this module supplies none and never guesses.
//     Opaque roles are read through the snapshot scan; an optional "css" sub-map lets users read
//     specific roles via page.evaluate querySelector, which is merged with the scan results.
//   - one TaskSpace per goal; rounds are separate processes; read/observe/save only; no credential,
//     cert, OTP or login automation; saveAs receives an absolute, JS-safe path.
//
// Test seam (synthetic verification only; never an operations path):
//   setContextRuntime({ taskSpace }). taskSpace may be a factory function
//   (async (space, operation) => task) that is actually invoked, or an already-created context
//   object exporting createCapture({ space, selectors, operation, args }).

import { AdapterError } from "./adapter.mjs";
import { SOURCE_URLS } from "./policy.mjs";

let injectedTaskSpace = null;

export function setContextRuntime({ taskSpace = null } = {}) {
  injectedTaskSpace = taskSpace ?? null;
}

export function resetContextRuntime() {
  injectedTaskSpace = null;
}

function errMessage(err) {
  if (err && typeof err === "object" && typeof err.code === "string" && typeof err.message === "string") {
    return `${err.code}: ${err.message}`;
  }
  return String(err && err.message ? err.message : err);
}

function contextRequired(message) {
  return new AdapterError(
    "CAPTURE_REQUIRED",
    `${message} (run under the ego-browser node runtime, inject a context for tests, or set KB_CARD_BROWSER_CONTEXT; live binding is NOT_VERIFIED)`,
  );
}

function protocolFailure(message) {
  return new AdapterError("EGO_PROTOCOL", message);
}

async function defaultTaskSpace(space) {
  const factory = (globalThis).taskSpace;
  if (typeof factory !== "function") {
    throw contextRequired('ego-browser runtime helper "taskSpace" is unavailable');
  }
  return factory(space);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeSnapshot(raw, roles) {
  if (typeof raw === "string") return scanTextSnapshot(raw, roles);
  if (raw !== null && typeof raw === "object") return scanNodeSnapshot(raw, roles, 0, {});
  throw protocolFailure("page.snapshot() must return text or an object");
}

function scanTextSnapshot(text, roles) {
  const found = {};
  for (const line of text.split(/\r?\n/)) {
    for (const role of roles) {
      if (Object.prototype.hasOwnProperty.call(found, role)) continue;
      const pattern = new RegExp(`(^|[^A-Za-z0-9_-])${escapeRegExp(role)}(?=$|[^A-Za-z0-9_-])`, "i");
      const match = pattern.exec(line);
      if (match) {
        const rest = line
          .slice(match.index + match[0].length)
          .replace(/^[\s:=~-]+/, "")
          .replace(/[\s;|,]+$/, "")
          .trim();
        found[role] = { present: true, text: rest.length > 0 && rest !== role ? rest.slice(0, 200) : null };
      }
    }
  }
  return finalize(found, roles);
}

function scanNodeSnapshot(node, roles, depth, found) {
  if (depth > 8 || node === null || typeof node !== "object") return found;
  // role-keyed payloads (e.g. a seam model emitting { role: {present,count,text} }) are read first
  for (const role of roles) {
    if (Object.prototype.hasOwnProperty.call(found, role)) continue;
    const direct = node[role];
    if (typeof direct === "boolean") {
      found[role] = { present: direct, text: null };
      continue;
    }
    if (direct !== null && typeof direct === "object") {
      const hasValue = direct.present !== undefined || direct.text !== undefined
        || direct.count !== undefined || direct.value !== undefined;
      const text = typeof direct.text === "string" && direct.text.trim() !== ""
        ? direct.text.trim().slice(0, 200)
        : null;
      found[role] = { present: hasValue ? (typeof direct.present === "boolean" ? direct.present : true) : false, text };
    }
  }
  for (const role of roles) {
    if (Object.prototype.hasOwnProperty.call(found, role)) continue;
    const candidate = role.toLowerCase();
    for (const key of ["role", "name", "label", "type"]) {
      const value = node[key];
      if (typeof value === "string" && (value === role || value.toLowerCase() === candidate)) {
        const text = typeof node.text === "string" ? node.text : (typeof node.value === "string" ? node.value : null);
        found[role] = { present: true, text: text && text.trim() !== "" ? text.trim().slice(0, 200) : null };
        break;
      }
    }
  }
  for (const value of Object.values(node)) {
    if (value === null || typeof value !== "object") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (Object.keys(found).length === roles.length) return found;
        scanNodeSnapshot(item, roles, depth + 1, found);
      }
    } else {
      if (Object.keys(found).length === roles.length) return found;
      scanNodeSnapshot(value, roles, depth + 1, found);
    }
  }
  return found;
}

function finalize(found, roles) {
  const out = {};
  for (const role of roles) {
    out[role] = Object.prototype.hasOwnProperty.call(found, role) ? found[role] : { present: false, text: null };
  }
  return out;
}

async function resolvePage(task, operation) {
  if (typeof task.tabs === "function") {
    try {
      const tabs = await task.tabs();
      if (Array.isArray(tabs)) {
        const hit = tabs.find((item) => item && item.label === "p1" && item.page);
        if (hit) return hit.page;
      }
    } catch { /* fall through to pages */ }
  }
  if (typeof task.pages === "function") {
    try {
      const pages = await task.pages();
      if (Array.isArray(pages)) {
        const hit = pages.find((item) => {
          if (!item) return false;
          if (item.page) return item.page.label === "p1" || item.label === "p1";
          return item.label === "p1";
        });
        if (hit) return hit.page ? hit.page : hit;
      }
    } catch { /* fall through to the handle */ }
  }
  let page = null;
  try {
    page = task.page("p1");
  } catch { page = null; }
  if (page !== null && typeof page === "object") {
    try {
      if (typeof page.snapshot === "function") await page.snapshot();
      return page;
    } catch { page = null; }
  }
  throw protocolFailure(
    `cannot resolve a Page for ${operation}: p1 is the contract's starting label and none was usable (no replacement Page is fabricated)`,
  );
}

function buildCapture(space, page, selectorMap, operation, args) {
  const context = { space, page, selectors: selectorMap ?? {}, operation, args: args ?? {} };

  const requireRole = (role) => {
    const value = context.selectors[role];
    if (typeof value !== "string" || value.trim() === "") {
      throw contextRequired(`selector role "${role}" is not configured; user-supplied only, never guessed`);
    }
    return value;
  };

  const capability = (name) => {
    if (typeof page[name] !== "function") {
      throw protocolFailure(`Page API lacks ${name}(); the installed ego-browser contract may have changed`);
    }
  };

  const cssRoleMap = (() => {
    const css = context.selectors.css ?? Object.fromEntries(Object.entries(context.selectors)
      .filter(([, value]) => typeof value === "string" && /^(?:loc=css:|css=)/.test(value))
      .map(([key, value]) => [key, value.replace(/^(?:loc=css:|css=)/, "")]));
    if (css === null || typeof css !== "object" || Array.isArray(css)) return {};
    const out = {};
    for (const [role, value] of Object.entries(css)) {
      if (context.selectors[role] !== undefined && typeof value === "string" && value.trim() !== "") out[role] = value;
    }
    return out;
  })();

  const evaluatedRoles = async (roles) => {
    const entries = roles.filter((role) => cssRoleMap[role]);
    if (entries.length === 0) return null;
    capability("evaluate");
    const map = {};
    for (const role of entries) map[role] = cssRoleMap[role];
    const result = await page.evaluate(({ map: input }) => {
      const out = {};
      for (const [role, selector] of Object.entries(input)) {
        let nodes = [];
        try { nodes = Array.from(document.querySelectorAll(selector)); } catch { nodes = []; }
        const first = nodes.length > 0 ? nodes[0] : null;
        out[role] = {
          present: nodes.length === 1,
          count: nodes.length,
          text: first ? String(first.value ?? first.textContent ?? "").trim().slice(0, 200) || null : null,
        };
      }
      return out;
    }, { map });
    return normalizeSnapshot(result, roles);
  };

  const narrowShape = (map, roleList) => {
    const out = {};
    for (const role of roleList) {
      const entry = map ? map[role] : null;
      const text = entry && typeof entry === "object" && typeof entry.text === "string" && entry.text.trim() !== ""
        ? entry.text.trim().slice(0, 200)
        : null;
      out[role] = { present: Boolean(entry && entry.present === true), text };
    }
    return out;
  };

  const snapshot = async (roles) => {
    if (!Array.isArray(roles)) throw protocolFailure("snapshot(roles) requires a role list");
    const evaluated = await evaluatedRoles(roles);
    if (evaluated !== null && roles.every((role) => Object.prototype.hasOwnProperty.call(evaluated, role))) return narrowShape(evaluated, roles);
    if (rawSnapshot === null) {
      capability("snapshot");
      rawSnapshot = await page.snapshot();
    }
    const base = evaluated !== null
      ? Object.assign({}, normalizeSnapshot(rawSnapshot, roles), evaluated)
      : normalizeSnapshot(rawSnapshot, roles);
    return narrowShape(base, roles);
  };

  const fill = async (role, value) => { capability("fill"); await page.fill(requireRole(role), value); invalidateSnapshot(); };
  const query = async (role) => { capability("click"); await page.click(requireRole(role)); invalidateSnapshot(); };
  const activate = async (role) => { capability("click"); await page.click(requireRole(role)); invalidateSnapshot(); };
  const armDownloadEvent = (options) => {
    capability("waitForEvent");
    const pending = page.waitForEvent("download", options);
    pending.catch(() => {});
    let artifact;
    return {
      async wait() {
        artifact = await pending;
        return { suggestedFilename: artifact.suggestedFilename() };
      },
      async saveAs(destination) {
        artifact ??= await pending;
        return artifact.saveAs(destination);
      },
    };
  };

  const saveAs = async (event, destinationPath) => {
    if (event === null || typeof event !== "object" || typeof event.saveAs !== "function") {
      throw contextRequired("download artifact exposes no saveAs(); live binding is NOT_VERIFIED");
    }
    const absolute = String(destinationPath);
    await event.saveAs(absolute.replace(/\\/g, "/"));
    return { savedPath: absolute };
  };

  let navigated = false;
  let rawSnapshot = null;
  const invalidateSnapshot = () => { rawSnapshot = null; };
  const ensureSource = async (label) => {
    if (navigated) return;
    if (label === undefined || label === null) return;
    const url = SOURCE_URLS[label];
    if (url === undefined) return;
    capability("goto");
    await page.goto(url);
    navigated = true;
    invalidateSnapshot();
  };

  const bound = {
    space,
    pageLabel: "p1",
    snapshot,
    fill,
    query,
    armDownloadEvent,
    activate,
    saveAs,
  };

  if (operation === "readScreenAllowedDates" || operation === "download") {
    return {
      space,
      pageLabel: "p1",
      snapshot: async (roles) => {
        await ensureSource(args.source);
        const result = await snapshot(roles);
        if (operation === "download" && roles.includes("periodEchoStart")) {
          for (const [role, expected] of [["periodEchoStart", args.startDate], ["periodEchoEnd", args.endDate]]) {
            if (result[role]?.text !== expected) throw contextRequired("query period does not match the requested ISO dates");
          }
        }
        return result;
      },
      fill: async (role, value) => { await ensureSource(args.source); return fill(role, value); },
      query: async (role) => { await ensureSource(args.source); return query(role); },
      armDownloadEvent,
      activate,
      saveAs,
    };
  }
  return bound;
}

export async function createCapture({ space, selectors: selectorMap, operation, args } = {}) {
  if (injectedTaskSpace !== null && typeof injectedTaskSpace !== "function" && typeof injectedTaskSpace.createCapture === "function") {
    const bound = await injectedTaskSpace.createCapture({ space, selectors: selectorMap ?? {}, operation, args: args ?? {} });
    if (bound === null || typeof bound !== "object") throw protocolFailure("injected context createCapture must return a capture object");
    const rawSnapshot = bound.snapshot;
    bound.snapshot = async (roleList) => normalizeSnapshot(await rawSnapshot(roleList), roleList);
    return Object.assign({}, bound, { space, pageLabel: "p1" });
  }
  const factory = injectedTaskSpace !== null ? injectedTaskSpace : defaultTaskSpace;
  if (typeof factory !== "function") {
    throw protocolFailure("injected taskSpace must be a factory function or a context object");
  }
  const task = await factory(space);
  if (task === null || typeof task !== "object") {
    throw protocolFailure("injected taskSpace factory must return a TaskSpace");
  }
  const page = await resolvePage(task, operation);
  return buildCapture(space, page, selectorMap, operation, args);
}

export default { createCapture, setContextRuntime, resetContextRuntime };
