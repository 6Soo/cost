/** Raw Gmail evidence -> private Drive. No sheet, Gmail-label, or financial writes. */
const COST_CLOUD_MAIL = {
  folderProperty: 'COST_CLOUD_MAIL_FOLDER',
  afterProperty: 'COST_CLOUD_MAIL_AFTER',
  accountProperty: 'COST_CLOUD_MAIL_ACCOUNT',
  handler: 'collectCostCloudMail',
  manifest: 'cloud-mail-manifest.json',
  schema: 'cost-cloud-mail-v1',
  budgetMs: 240000,
};

function costMailJson_(response) {
  if (response.getResponseCode() !== 200) throw new Error('CLOUD_MAIL_API_FAILED');
  return JSON.parse(response.getContentText());
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

function costMailManifest_(folder) {
  const file = costMailUniqueFile_(folder, COST_CLOUD_MAIL.manifest);
  const data = file ? JSON.parse(file.getBlob().getDataAsString('UTF-8')) : {
    schema: COST_CLOUD_MAIL.schema, messages: {}, query: null, pending: [], nextPageToken: null,
  };
  if (data.schema !== COST_CLOUD_MAIL.schema || !data.messages || typeof data.messages !== 'object') {
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
  const suppliers = ['trip.com', 'trip.co.kr', 'klook.com', 'agoda.com', 'booking.com',
    'agoda-messaging.com', 'toyoko-inn.com', 'toyoko-inn.co.jp'];
  const recipients = ['kew2000@hanmail.net', 'kew2000@daum.net'];
  return 'after:' + after.replace(/-/g, '/') + ' (' + suppliers.map(x => 'from:' + x).concat(
    recipients.map(x => 'to:' + x + ' OR cc:' + x)).join(' OR ') + ')';
}

function collectCostCloudMail() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {status: 'BUSY'};
  try {
    const props = PropertiesService.getScriptProperties();
    const folderId = props.getProperty(COST_CLOUD_MAIL.folderProperty);
    const after = props.getProperty(COST_CLOUD_MAIL.afterProperty);
    const expectedAccount = props.getProperty(COST_CLOUD_MAIL.accountProperty);
    if (!folderId || !/^\d{4}-\d{2}-\d{2}$/.test(after || '') || !expectedAccount) {
      throw new Error('CLOUD_MAIL_NOT_CONFIGURED');
    }
    const profile = costMailGet_('profile');
    if (profile.emailAddress !== expectedAccount) throw new Error('CLOUD_MAIL_ACCOUNT_MISMATCH');
    const folder = DriveApp.getFolderById(folderId);
    const held = costMailManifest_(folder), state = held.data;
    if (state.account && state.account !== expectedAccount) throw new Error('CLOUD_MAIL_ACCOUNT_MISMATCH');
    state.account = expectedAccount;
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
        state.pending = (page.messages || []).map(x => x.id);
        state.nextPageToken = page.nextPageToken || null;
        costMailSave_(folder, held);
      }
      while (state.pending.length && Date.now() - started < COST_CLOUD_MAIL.budgetMs) {
        const id = state.pending[0];
        if (!/^[a-f0-9]+$/i.test(id)) throw new Error('CLOUD_MAIL_INVALID_ID');
        if (!state.messages[id]) {
          const name = 'gmail-' + id + '.json';
          let file = costMailUniqueFile_(folder, name);
          if (file) {
            const saved = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
            if (!saved.responses || saved.responses.length !== 1 || saved.responses[0].id !== id) {
              throw new Error('CLOUD_MAIL_ORIGINAL_CONFLICT');
            }
          } else {
            const message = costMailGet_('messages/' + id + '?format=full');
            if (message.id !== id || !message.payload || !message.internalDate) {
              throw new Error('CLOUD_MAIL_INCOMPLETE_ORIGINAL');
            }
            file = folder.createFile(name, JSON.stringify({responses: [message]}), 'application/json');
            fetched++;
          }
          state.messages[id] = {file_id: file.getId(), name: name};
        }
        state.pending.shift();
        costMailSave_(folder, held);
      }
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
  if (!options || !/^\d{4}-\d{2}-\d{2}$/.test(options.after || '') || !options.account) {
    throw new Error('CLOUD_MAIL_SETUP_INVALID');
  }
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty(COST_CLOUD_MAIL.folderProperty)) {
    const folder = DriveApp.createFolder('COST private mail evidence');
    props.setProperty(COST_CLOUD_MAIL.folderProperty, folder.getId());
  }
  props.setProperty(COST_CLOUD_MAIL.afterProperty, options.after);
  props.setProperty(COST_CLOUD_MAIL.accountProperty, options.account);
  const result = collectCostCloudMail();
  if (!ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === COST_CLOUD_MAIL.handler)) {
    ScriptApp.newTrigger(COST_CLOUD_MAIL.handler).timeBased().everyHours(1).create();
  }
  return result;
}

function costCloudMailStatus() {
  const props = PropertiesService.getScriptProperties();
  const folderId = props.getProperty(COST_CLOUD_MAIL.folderProperty);
  if (!folderId) return {configured: false};
  const held = costMailManifest_(DriveApp.getFolderById(folderId));
  return {configured: true, folder_id: folderId, manifest_file_id: held.file ? held.file.getId() : null,
    stored: Object.keys(held.data.messages).length, last_complete: held.data.last_complete || null,
    trigger_count: ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === COST_CLOUD_MAIL.handler).length};
}
