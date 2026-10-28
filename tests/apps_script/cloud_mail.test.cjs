const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../../cloud-mail/CloudMail.gs'), 'utf8');
const account = 'owner@example.invalid';
function message(id) {
  return {id, internalDate:'1793138400000', payload:{mimeType:'multipart/alternative',
    headers:[{name:'Authentication-Results', value:'synthetic pass'},
      {name:'Content-Type',value:'multipart/alternative'}],
    parts:[{mimeType:'text/plain', body:{data:'c3ludGhldGlj'}}]}};
}
function harness({pages=[{messages:[{id:'a1'}]}], held=null, originals={}, failSave=0,
                   privacy='private', accountName=account, failGet=null}={}) {
  const files=new Map(), calls=[], triggers=[];
  let serial=0, saves=0, released=false, folderCreates=0;
  function file(name,content) {
    const value={id:'file-'+(++serial),content, getId(){return this.id;},
      getBlob(){return {getDataAsString:()=>this.content};},
      setContent(value){if(++saves===failSave)throw Error('SYNTHETIC_SAVE_FAILURE');this.content=value;},
      getSharingAccess:()=> 'private',getEditors:()=>[],getViewers:()=>[],
      getOwner:()=>({getEmail:()=>account})};
    files.set(name,value);return value;
  }
  for(const [name,content] of Object.entries(originals))file(name,JSON.stringify(content));
  if(held)file('cloud-mail-manifest.json',JSON.stringify(held));
  const props=new Map([['COST_CLOUD_MAIL_FOLDER','folder'],['COST_CLOUD_MAIL_AFTER','2026-04-01'],
    ['COST_CLOUD_MAIL_ACCOUNT',account]]);
  const folder={getFilesByName(name){const found=files.has(name)?[files.get(name)]:[];return {
    hasNext:()=>found.length>0,next:()=>found.shift()};},
    createFile(name,content){calls.push({create:name});return file(name,content);},
    getId:()=> 'folder',getSharingAccess:()=>privacy,getEditors:()=>[],getViewers:()=>[],
    getOwner:()=>({getEmail:()=>account})};
  const context=vm.createContext({console, Date, LockService:{getScriptLock:()=>({tryLock:()=>true,
      releaseLock:()=>{released=true;}})},
    PropertiesService:{getScriptProperties:()=>({getProperty:k=>props.get(k)||null,
      setProperty:(k,v)=>props.set(k,v)})},
    DriveApp:{Access:{PRIVATE:'private'},getFolderById:()=>folder,
      createFolder:()=>{folderCreates++;return folder;}},
    ScriptApp:{getOAuthToken:()=> 'synthetic',getProjectTriggers:()=>triggers,
      deleteTrigger:trigger=>triggers.splice(triggers.indexOf(trigger),1),
      newTrigger:handler=>({timeBased(){return this;},everyHours(){return this;},
        create(){triggers.push({getHandlerFunction:()=>handler});}})},
    Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
      computeDigest:(_,text)=>[...crypto.createHash('sha256').update(text).digest()]},
    UrlFetchApp:{fetch(url,options){
      calls.push({url,method:options.method||'GET'});
      const suffix=url.split('/users/me/')[1];let result;
      if(suffix==='profile')result={emailAddress:accountName};
      else if(suffix.startsWith('messages?')){
        const pageToken=new URL(url).searchParams.get('pageToken');
        result=pages[pageToken?Number(pageToken):0];
      } else {const id=suffix.split('/')[1].split('?')[0];
        if(id===failGet)throw Error('SYNTHETIC_MESSAGE_FAILURE');result=message(id);}
      return {getResponseCode:()=>200,getContentText:()=>JSON.stringify(result)};
    }}});
  vm.runInContext(source,context);
  return {context,files,calls,props,triggers,folder,
    run:()=>JSON.parse(JSON.stringify(context.collectCostCloudMail())),
    manifest:()=>JSON.parse(files.get('cloud-mail-manifest.json').content),
    released:()=>released,folderCreates:()=>folderCreates};
}
function state(extra={}) {return {schema:'cost-cloud-mail-v1',messages:{},query:null,configured_after:'2026-04-01',
  pending:[],nextPageToken:null,query_revision:2,account,...extra};}

test('query includes every current collector discovery path',()=>{
  const h=harness(), query=h.context.costMailQuery_('2026-04-01');
  for(const term of ['forest.go.kr','foresttrip.go.kr','subject:토요코인',
      'from:nicepg.co.kr','자연휴양림','휴양시설'])assert.ok(query.includes(term),term);
});
test('all pages preserve full original headers MIME and internal date; repeat is immutable',()=>{
  const h=harness({pages:[{messages:[{id:'a1'}],nextPageToken:'1'}, {messages:[{id:'b2'}]}]});
  assert.equal(h.run().fetched,2);
  assert.deepEqual(JSON.parse(h.files.get('gmail-a1.json').content),{responses:[message('a1')]});
  const contents=h.files.get('gmail-a1.json').content;
  assert.equal(h.run().fetched,0);assert.equal(h.files.get('gmail-a1.json').content,contents);
  assert.equal(h.manifest().messages.a1.sha256.length,64);assert.ok(h.released());
  assert.ok(h.calls.filter(c=>c.url).every(c=>c.method==='GET'));
});
test('failure resumes pending IDs without advancing complete watermark',()=>{
  const h=harness({pages:[{messages:[{id:'a1'},{id:'b2'}]}],failGet:'b2'});
  assert.throws(()=>h.run(),/SYNTHETIC_MESSAGE_FAILURE/);
  assert.deepEqual(h.manifest().pending,['b2']);assert.equal(h.manifest().last_complete,null);
  assert.ok(h.files.has('gmail-a1.json'));assert.ok(h.released());
});
test('crash after original create recovers without duplicate or overwrite',()=>{
  const h=harness({held:state(),failSave:2});
  assert.throws(()=>h.run(),/SYNTHETIC_SAVE_FAILURE/);
  const original=h.files.get('gmail-a1.json');assert.ok(original);
  assert.equal(h.run().fetched,0);assert.equal(h.files.get('gmail-a1.json'),original);
});
test('broadened query backfills configured start and retains original map',()=>{
  const h=harness({held:state({query_revision:1,last_complete:'2026-10-28T00:00:00Z',
    query:'old-query',pending:['ff'],nextPageToken:'old-page'})});
  h.run();const url=h.calls.find(c=>c.url&&c.url.includes('messages?')).url;
  assert.ok(decodeURIComponent(url).includes('after:2026/03/30'));
  assert.ok(!url.includes('old-page'));assert.equal(h.manifest().query_revision,2);
});
test('indexed original missing stops before redownload and does not discard index',()=>{
  const h=harness({held:state({messages:{a1:{file_id:'gone',name:'gmail-a1.json'}}})});
  assert.throws(()=>h.run(),/CLOUD_MAIL_ORIGINAL_MISSING/);
  assert.ok(!h.calls.some(c=>c.url&&c.url.includes('messages/a1?')));
  assert.equal(h.manifest().messages.a1.file_id,'gone');
});
test('changed stored original digest never silently replaces trusted evidence',()=>{
  const h=harness({held:state({messages:{a1:{file_id:'file-1',name:'gmail-a1.json',sha256:'changed'}}}),
    originals:{'gmail-a1.json':{responses:[message('a1')]}}});
  const content=h.files.get('gmail-a1.json').content;
  assert.throws(()=>h.run(),/CLOUD_MAIL_ORIGINAL_CONFLICT/);
  assert.equal(h.files.get('gmail-a1.json').content,content);
});
test('orphaned incomplete original is rejected rather than indexed',()=>{
  const incomplete=message('a1');delete incomplete.payload.headers;
  const h=harness({originals:{'gmail-a1.json':{responses:[incomplete]}}});
  assert.throws(()=>h.run(),/CLOUD_MAIL_INCOMPLETE_ORIGINAL/);
  assert.equal(h.manifest().messages.a1,undefined);
});
test('nonprivate folder and account mismatch do not read/write originals',()=>{
  for(const options of [{privacy:'shared'},{accountName:'other@example.invalid'}]){
    const h=harness(options);assert.throws(()=>h.run(),/CLOUD_MAIL_(FOLDER_NOT_PRIVATE|ACCOUNT_MISMATCH)/);
    assert.equal(h.files.size,0);assert.ok(h.released());
  }
});
test('malformed manifest and message list cannot advance a checkpoint',()=>{
  for(const held of [state({messages:[]}),state({pending:{}}),state({nextPageToken:17})]){
    const h=harness({held});assert.throws(()=>h.run(),/CLOUD_MAIL_MANIFEST_INVALID/);
  }
  for(const pages of [[{messages:[{id:'invalid/path'}]}],[{messages:{}}],[{nextPageToken:17}]]){
    const h=harness({pages});assert.throws(()=>h.run(),/CLOUD_MAIL_(LIST_INVALID|INVALID_ID)/);
    assert.equal(h.files.size,0);
  }
});
test('setup rejects wrong identity before changing properties or creating a folder',()=>{
  const h=harness();h.props.delete('COST_CLOUD_MAIL_FOLDER');
  assert.throws(()=>h.context.setupCostCloudMail({after:'2026-04-01',account:'other@example.invalid'}),
    /CLOUD_MAIL_ACCOUNT_MISMATCH/);
  assert.equal(h.folderCreates(),0);assert.equal(h.props.get('COST_CLOUD_MAIL_ACCOUNT'),account);
});
test('setup creates exactly one hourly trigger and status does not collect',()=>{
  const h=harness();h.context.setupCostCloudMail({after:'2026-04-01',account});
  h.context.setupCostCloudMail({after:'2026-04-01',account});assert.equal(h.triggers.length,1);
  const before=h.calls.length;assert.equal(h.context.costCloudMailStatus().stored,1);
  assert.equal(h.calls.length,before);
});
test('invalid calendar dates cannot create folders or change setup',()=>{
  for(const after of ['2026-02-30','2026-13-01','2026-00-01','not-a-date']){
    const h=harness();h.props.delete('COST_CLOUD_MAIL_FOLDER');
    assert.throws(()=>h.context.setupCostCloudMail({after,account}),/CLOUD_MAIL_SETUP_INVALID/);
    assert.equal(h.folderCreates(),0);
  }
});
test('individual sharing of an indexed original is refused',()=>{
  const h=harness({originals:{'gmail-a1.json':{responses:[message('a1')]}}});
  h.files.get('gmail-a1.json').getSharingAccess=()=> 'shared';
  assert.throws(()=>h.run(),/CLOUD_MAIL_FOLDER_NOT_PRIVATE/);
});
test('moving configured start earlier restarts backfill without forgetting stored evidence',()=>{
  const h=harness({held:state({last_complete:'2026-10-28T00:00:00Z',configured_after:'2026-10-01'})});
  h.run();const url=h.calls.find(c=>c.url&&c.url.includes('messages?')).url;
  assert.ok(decodeURIComponent(url).includes('after:2026/03/30'));
});
test('time budget exit persists pending IDs and next run resumes the same enumeration',()=>{
  const h=harness();const ticks=[0,0,240001];
  h.context.Date=class extends Date {static now(){return ticks.length?ticks.shift():240001;}};
  assert.equal(h.run().status,'PARTIAL');assert.deepEqual(h.manifest().pending,['a1']);
  assert.equal(h.manifest().last_complete,null);
  h.context.Date=Date;assert.equal(h.run().status,'COMPLETE');
  assert.equal(h.calls.filter(c=>c.url&&c.url.includes('messages?')).length,1);
});
test('editor initializer derives owner and reuses existing configured collection start',()=>{
  const h=harness();h.props.set('COST_CLOUD_MAIL_AFTER','2026-05-01');
  assert.equal(h.context.initializeCostCloudMail().status,'COMPLETE');
  assert.equal(h.props.get('COST_CLOUD_MAIL_AFTER'),'2026-05-01');assert.equal(h.triggers.length,1);
});
test('pause removes only this collector trigger and preserves evidence and other schedules',()=>{
  const h=harness();h.run();const original=h.files.get('gmail-a1.json').content;
  h.triggers.push({getHandlerFunction:()=> 'collectCostCloudMail'},
    {getHandlerFunction:()=> 'unrelated-synthetic-handler'});
  assert.equal(h.context.pauseCostCloudMail().removed,1);
  assert.equal(h.triggers.length,1);assert.equal(h.triggers[0].getHandlerFunction(),'unrelated-synthetic-handler');
  assert.equal(h.files.get('gmail-a1.json').content,original);
});
