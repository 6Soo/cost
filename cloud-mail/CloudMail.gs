/** Raw Gmail evidence -> private Drive. No sheet, Gmail-label, or financial writes. */
const COST_CLOUD_MAIL = {
  folderProperty: 'COST_CLOUD_MAIL_FOLDER',
  afterProperty: 'COST_CLOUD_MAIL_AFTER',
  accountProperty: 'COST_CLOUD_MAIL_ACCOUNT',
  handler: 'collectCostCloudMail',
  manifest: 'cloud-mail-manifest.json',
  schema: 'cost-cloud-mail-v1',
  budgetMs: 240000,
  queryRevision: 2,
};

function costMailJson_(response) {
  const status = response.getResponseCode();
  if (status !== 200) {
    let reason = '';
    try {
      const raw = response.getContentText();
      if (raw.length <= 16384) {
        const error = JSON.parse(raw).error || {};
        const reasons = (Array.isArray(error.errors) ? error.errors : []).map(item => item.reason)
          .concat((Array.isArray(error.details) ? error.details : []).map(item => item.reason));
        reason = ['accessNotConfigured', 'SERVICE_DISABLED', 'insufficientPermissions',
          'ACCESS_TOKEN_SCOPE_INSUFFICIENT', 'rateLimitExceeded', 'dailyLimitExceeded']
          .find(value => reasons.includes(value)) || '';
      }
    } catch (_) {}
    throw new Error('CLOUD_MAIL_API_HTTP_' + status + (reason ? '_' + reason : ''));
  }
  return JSON.parse(response.getContentText());
}

function costMailValidDate_(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + 'T00:00:00Z');
  return !isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function costMailGet_(suffix) {
  return costMailJson_(UrlFetchApp.fetch('https://gmail.googleapis.com/gmail/v1/users/me/' + suffix, {
    headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()},
    muteHttpExceptions: true,
  }));
}

function costMailUniqueFile_(folder, name) {
  const found = folder.getFilesByName(name);
  if (!found.hasNext()) return null;
  const file = found.next();
  if (found.hasNext()) throw new Error('CLOUD_MAIL_DUPLICATE_FILE');
  return file;
}

function costMailFileIndex_(folder) {
  const files = folder.getFiles(), index = new Map();
  while (files.hasNext()) {
    const file = files.next(), name = file.getName();
    if (index.has(name)) throw new Error('CLOUD_MAIL_DUPLICATE_FILE');
    index.set(name, file);
  }
  return index;
}

function costMailManifest_(folder, account) {
  const file = costMailUniqueFile_(folder, COST_CLOUD_MAIL.manifest);
  if (file && account) costMailPrivateFolder_(file, account);
  const data = file ? JSON.parse(file.getBlob().getDataAsString('UTF-8')) : {
    schema: COST_CLOUD_MAIL.schema, messages: {}, query: null, pending: [], nextPageToken: null,
  };
  if (data.schema !== COST_CLOUD_MAIL.schema || !data.messages || typeof data.messages !== 'object'
      || Array.isArray(data.messages) || !Array.isArray(data.pending)
      || (data.nextPageToken !== null && typeof data.nextPageToken !== 'string')) {
    throw new Error('CLOUD_MAIL_MANIFEST_INVALID');
  }
  return {file: file, data: data};
}

function costMailSave_(folder, held) {
  const content = JSON.stringify(held.data);
  if (held.file) held.file.setContent(content);
  else held.file = folder.createFile(COST_CLOUD_MAIL.manifest, content, 'application/json');
}

function costMailQuery_(after) {
  if (!costMailValidDate_(after)) throw new Error('CLOUD_MAIL_DATE_INVALID');
  const suppliers = ['trip.com', 'trip.co.kr', 'klook.com', 'agoda.com', 'booking.com',
    'agoda-messaging.com', 'toyoko-inn.com', 'toyoko-inn.co.jp', 'forest.go.kr', 'foresttrip.go.kr'];
  const recipients = ['kew2000@hanmail.net', 'kew2000@daum.net'];
  return 'after:' + after.replace(/-/g, '/') + ' (' + suppliers.map(x => 'from:' + x).concat(
    recipients.map(x => 'to:' + x + ' OR cc:' + x)).join(' OR ')
    + ' OR subject:토요코인 OR (from:nicepg.co.kr ("자연휴양림" OR "휴양시설")))';
}

function costMailOriginal_(document, id) {
  const message = document && document.responses && document.responses[0];
  if (!Array.isArray(document && document.responses) || document.responses.length !== 1
      || !message || message.id !== id || !/^\d+$/.test(String(message.internalDate || ''))
      || !message.payload || !Array.isArray(message.payload.headers)
      || !message.payload.headers.length) {
    throw new Error('CLOUD_MAIL_INCOMPLETE_ORIGINAL');
  }
  return message;
}

function costMailDigest_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8)
    .map(value => ('0' + ((value + 256) % 256).toString(16)).slice(-2)).join('');
}

function costMailPrivateFolder_(folder, account) {
  if (folder.getSharingAccess() !== DriveApp.Access.PRIVATE || folder.getEditors().length
      || folder.getViewers().length || !folder.getOwner()
      || folder.getOwner().getEmail() !== account) {
    throw new Error('CLOUD_MAIL_FOLDER_NOT_PRIVATE');
  }
  return folder;
}

/** Keep the editor's first selectable function read-only. */
function logCostCloudMailStatus() {
  const status = costCloudMailStatus();
  console.log(JSON.stringify(status));
  return status;
}

function collectCostCloudMail() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {status: 'BUSY'};
  try {
    const props = PropertiesService.getScriptProperties();
    const folderId = props.getProperty(COST_CLOUD_MAIL.folderProperty);
    const after = props.getProperty(COST_CLOUD_MAIL.afterProperty);
    const expectedAccount = props.getProperty(COST_CLOUD_MAIL.accountProperty);
    if (!folderId || !costMailValidDate_(after) || !expectedAccount) {
      throw new Error('CLOUD_MAIL_NOT_CONFIGURED');
    }
    const profile = costMailGet_('profile');
    if (profile.emailAddress !== expectedAccount) throw new Error('CLOUD_MAIL_ACCOUNT_MISMATCH');
    const folder = costMailPrivateFolder_(DriveApp.getFolderById(folderId), expectedAccount);
    const held = costMailManifest_(folder, expectedAccount), state = held.data;
    const files = costMailFileIndex_(folder), prefetched = new Map();
    let batchAllowed = true;
    if (state.account && state.account !== expectedAccount) throw new Error('CLOUD_MAIL_ACCOUNT_MISMATCH');
    state.account = expectedAccount;
    // A broader query must backfill from the configured start, including after a
    // partial old enumeration. Already stored originals are retained and verified.
    if (state.query_revision !== COST_CLOUD_MAIL.queryRevision || state.configured_after !== after) {
      state.query = null;
      state.last_complete = null;
      state.pending = [];
      state.nextPageToken = null;
      state.query_revision = COST_CLOUD_MAIL.queryRevision;
      state.configured_after = after;
    }
    if (!state.query) {
      // Advance only after complete enumeration; overlap catches delayed arrivals.
      const anchor = state.last_complete || after;
      const day = new Date(anchor.slice(0, 10) + 'T00:00:00Z');
      day.setUTCDate(day.getUTCDate() - 2);
      state.query = costMailQuery_(day.toISOString().slice(0, 10));
      state.started_at = new Date().toISOString();
      state.pending = [];
      state.nextPageToken = null;
    }
    const started = Date.now();
    let fetched = 0, complete = false;
    while (Date.now() - started < COST_CLOUD_MAIL.budgetMs) {
      if (!state.pending.length) {
        const suffix = 'messages?maxResults=50&q=' + encodeURIComponent(state.query)
          + (state.nextPageToken ? '&pageToken=' + encodeURIComponent(state.nextPageToken) : '');
        const page = costMailGet_(suffix);
        if (page.messages !== undefined && !Array.isArray(page.messages)) {
          throw new Error('CLOUD_MAIL_LIST_INVALID');
        }
        state.pending = (page.messages || []).map(x => x && x.id);
        if (state.pending.some(id => typeof id !== 'string' || !/^[a-f0-9]+$/i.test(id))) {
          throw new Error('CLOUD_MAIL_INVALID_ID');
        }
        if (page.nextPageToken !== undefined && typeof page.nextPageToken !== 'string') {
          throw new Error('CLOUD_MAIL_LIST_INVALID');
        }
        state.nextPageToken = page.nextPageToken || null;
        costMailSave_(folder, held);
      }
      // Originals are installed first; orphan recovery verifies any unsaved group.
      // Flush on group, page, time-budget exit, and failure.
      let unsaved = 0;
      try {
        while (state.pending.length && Date.now() - started < COST_CLOUD_MAIL.budgetMs) {
          const id = state.pending[0];
          if (!/^[a-f0-9]+$/i.test(id)) throw new Error('CLOUD_MAIL_INVALID_ID');
          {
            const name = 'gmail-' + id + '.json';
            let file = files.get(name);
            let content;
            if (file) {
              costMailPrivateFolder_(file, expectedAccount);
              content = file.getBlob().getDataAsString('UTF-8');
              costMailOriginal_(JSON.parse(content), id);
              if (state.messages[id] && (state.messages[id].file_id !== file.getId()
                  || (state.messages[id].sha256 && state.messages[id].sha256 !== costMailDigest_(content)))) {
                throw new Error('CLOUD_MAIL_ORIGINAL_CONFLICT');
              }
            } else {
              if (state.messages[id]) throw new Error('CLOUD_MAIL_ORIGINAL_MISSING');
              if (batchAllowed && !prefetched.has(id)) {
                const ids = Array.from(new Set(state.pending.slice(0, 10))).filter(candidate =>
                  !files.has('gmail-' + candidate + '.json') && !state.messages[candidate]);
                if (ids.some(candidate => typeof candidate !== 'string' || !/^[a-f0-9]+$/i.test(candidate))) {
                  throw new Error('CLOUD_MAIL_INVALID_ID');
                }
                if (ids.length > 1) {
                  let responses = null;
                  try {
                    const token = ScriptApp.getOAuthToken();
                    responses = UrlFetchApp.fetchAll(ids.map(candidate => ({
                      url: 'https://gmail.googleapis.com/gmail/v1/users/me/messages/' + candidate + '?format=full',
                      method: 'get', headers: {Authorization: 'Bearer ' + token},
                      muteHttpExceptions: true, followRedirects: false,
                    })));
                  } catch (_) {batchAllowed = false;}
                  if (responses !== null) {
                    if (!Array.isArray(responses) || responses.length !== ids.length) {
                      throw new Error('CLOUD_MAIL_BATCH_INVALID');
                    }
                    ids.forEach((candidate, index) => prefetched.set(candidate, responses[index]));
                  }
                }
              }
              const message = prefetched.has(id) ? costMailJson_(prefetched.get(id))
                : costMailGet_('messages/' + id + '?format=full');
              prefetched.delete(id);
              costMailOriginal_({responses: [message]}, id);
              content = JSON.stringify({responses: [message]});
              file = folder.createFile(name, content, 'application/json');
              files.set(name, file);
              fetched++;
            }
            state.messages[id] = {file_id: file.getId(), name: name, sha256: costMailDigest_(content)};
          }
          state.pending.shift();
          if (++unsaved >= 10) {
            costMailSave_(folder, held);
            unsaved = 0;
          }
        }
      } catch (error) {
        costMailSave_(folder, held);
        throw error;
      }
      if (unsaved) costMailSave_(folder, held);
      if (!state.pending.length && !state.nextPageToken) {complete = true; break;}
    }
    state.last_run = new Date().toISOString();
    if (complete) {
      state.last_complete = state.started_at;
      state.query = null;
      state.started_at = null;
    }
    costMailSave_(folder, held);
    return {status: complete ? 'COMPLETE' : 'PARTIAL', fetched: fetched,
      stored: Object.keys(state.messages).length, manifest_file_id: held.file.getId()};
  } finally {lock.releaseLock();}
}

function setupCostCloudMail(options) {
  if (!options || !costMailValidDate_(options.after) || !options.account) {
    throw new Error('CLOUD_MAIL_SETUP_INVALID');
  }
  const props = PropertiesService.getScriptProperties();
  const profile = costMailGet_('profile');
  if (profile.emailAddress !== options.account) throw new Error('CLOUD_MAIL_ACCOUNT_MISMATCH');
  const currentAccount = props.getProperty(COST_CLOUD_MAIL.accountProperty);
  if (currentAccount && currentAccount !== options.account) throw new Error('CLOUD_MAIL_ACCOUNT_MISMATCH');
  if (!props.getProperty(COST_CLOUD_MAIL.folderProperty)) {
    const folder = DriveApp.createFolder('COST private mail evidence');
    props.setProperty(COST_CLOUD_MAIL.folderProperty, folder.getId());
  }
  costMailPrivateFolder_(DriveApp.getFolderById(props.getProperty(COST_CLOUD_MAIL.folderProperty)), options.account);
  props.setProperty(COST_CLOUD_MAIL.afterProperty, options.after);
  props.setProperty(COST_CLOUD_MAIL.accountProperty, options.account);
  const result = collectCostCloudMail();
  if (!ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === COST_CLOUD_MAIL.handler)) {
    ScriptApp.newTrigger(COST_CLOUD_MAIL.handler).timeBased().everyHours(1).create();
  }
  return result;
}

/** Run manually after reviewing the dedicated project's Google consent screen. */
function initializeCostCloudMail() {
  const props = PropertiesService.getScriptProperties();
  const account = props.getProperty(COST_CLOUD_MAIL.accountProperty) || costMailGet_('profile').emailAddress;
  return setupCostCloudMail({account: account,
    after: props.getProperty(COST_CLOUD_MAIL.afterProperty) || '2026-04-01'});
}

/** Stop only this collector's future runs. Evidence and other triggers remain. */
function pauseCostCloudMail() {
  let removed = 0;
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === COST_CLOUD_MAIL.handler) {
      ScriptApp.deleteTrigger(trigger);
      removed++;
    }
  });
  return {status: 'PAUSED', removed: removed};
}

function costCloudMailStatus() {
  const props = PropertiesService.getScriptProperties();
  const folderId = props.getProperty(COST_CLOUD_MAIL.folderProperty);
  if (!folderId) return {configured: false};
  const account = props.getProperty(COST_CLOUD_MAIL.accountProperty);
  const folder = costMailPrivateFolder_(DriveApp.getFolderById(folderId), account);
  const held = costMailManifest_(folder, account);
  return {configured: true, folder_id: folderId, manifest_file_id: held.file ? held.file.getId() : null,
    stored: Object.keys(held.data.messages).length, last_complete: held.data.last_complete || null,
    trigger_count: ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === COST_CLOUD_MAIL.handler).length};
}
