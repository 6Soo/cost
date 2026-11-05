"""Execute the production upload queue with mixed asynchronous outcomes."""
import json
import shutil
import subprocess

import pytest

from webapp.card_flow import page


@pytest.mark.parametrize('status', [401, 403])
def test_auth_refusal_preserves_received_job_without_mislabeling_permission(status):
    source = page('synthetic-csrf')
    source = source[source.index('const uploadJobKey='):source.index('function savedUploadLink')]
    harness = r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),storage=new Map();
const context={localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
  Date,Error,JSON,Array,RegExp,AbortSignal:{timeout(){}},fetch:async()=>({status:STATUS})};
vm.createContext(context);vm.runInContext(SOURCE,context);
(async()=>{
 let error;
 try{await vm.runInContext("awaitUpload({status_url:'/api/imports/upload-status/'+'a'.repeat(32),batch_id:'received'}, {})",context)}catch(e){error=e}
 assert.ok(error.terminal);assert.equal(error.savedBatch,'received');
 assert.ok(error.auth);
 assert.equal(error.message,'STATUS'==='401'?'로그인 필요':'조회 권한 필요');
 assert.equal(JSON.parse(storage.get('cost-card-upload-job'))[0].batch_id,'received');
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace('STATUS', str(status)).replace('SOURCE', json.dumps(source))
    node = shutil.which('node')
    assert node, 'Node is required to verify authentication recovery'
    result = subprocess.run([node, '-e', harness], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode', ['mixed', 'success', 'legacy-resume', 'refresh-required', 'background', 'restart-expired', 'recovery-offline', 'recovery-refresh-offline', 'recovery-pending', 'recovery-auth'])
def test_all_ten_files_are_attempted_and_unresolved_jobs_survive(mode):
    source = page('synthetic-csrf')
    source = source[source.index("const uploadJobKey="):source.index("el('ruleform').onsubmit=")]
    harness = r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const mode = MODE;
const storage = new Map(), nodes = new Map(), posts = [], entries = [];
const waiting = [];
const identity = n => '/api/imports/upload-status/'+String(n).padStart(32,'0');
function element(){return {disabled:false, dataset:{}, textContent:'', replaceChildren(){},append(...xs){entries.push(...xs)},prepend(...xs){entries.push(...xs)},
  setAttribute(){},removeAttribute(){},querySelector(){return this},addEventListener(name,fn){this[name]=fn},scrollIntoView(){this.scrolled=true}}}
const el = id => {if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
const localStorage = {getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
if(mode==='legacy-resume'||mode==='restart-expired'||mode.startsWith('recovery-'))localStorage.setItem('cost-card-upload-job',JSON.stringify({status_url:identity(9),batch_id:'9',filename:'legacy.csv'}));
let rendered;
const context={el,localStorage,document:{createElement:element},Date,Error,JSON,Array,Math,RegExp,
  FormData:class{constructor(){this.files=[]}append(key,file){assert.equal(key,'files');this.files.push(file)}},
  AbortSignal:{timeout(){}},setTimeout:fn=>{fn();},
  uploadInput:el('file'),uploadDrop:element(),uploadLabel:element(),batchGeneration:0,
  invalidateProposal(){},appendCoverageForm(){},render:j=>{rendered=j},renderUploadSystemError(){},loadBatch:async batch=>{context.loaded=batch},
  renderUploadSelection:()=>Array.from({length:10},(_,i)=>({name:(i+1)+'.csv',arrayBuffer:async()=>Buffer.from('synthetic '+i)})),
  call:async(url,data)=>{assert.equal(url,'/api/imports/upload-batch');return {files:data.files.map(file=>{const n=Number(file.name.split('.')[0]);posts.push(n);return {filename:file.name,status_url:identity(n),batch_id:String(n)}})}},
  fetch:async url=>{const n=Number(url.split('?')[0].split('/').at(-1));
    if(url.includes('?batch=')){
      if(mode==='recovery-offline'||mode==='recovery-refresh-offline')throw Error('offline');
      if(mode==='recovery-auth')return {ok:false,status:401};
      return {ok:true,status:200,json:async()=>({status:'saved',result:{batch_id:String(n),recovery:{pending:mode==='recovery-pending'}}})};
    }
    if(mode==='recovery-refresh-offline'&&n===9)return {ok:true,status:200,json:async()=>({status:'done',result:{refresh_required:true}})};
    if((mode==='restart-expired'||mode.startsWith('recovery-'))&&n===9)return {ok:false,status:404};
    if(mode==='background')await new Promise(resolve=>{waiting.push(resolve)});
    if(mode==='mixed'&&(n===2||n===4))throw Error('temporary disconnect');
    return {ok:true,status:200,json:async()=>mode==='refresh-required'&&(n===1||n===10)?{status:'done',result:{batch_id:String(n),refresh_required:true,upload_summary:{status:'refresh_required'}}}:mode==='mixed'&&n===1?{status:'error',message:'synthetic classification failure'}:{status:'done',result:{batch_id:String(n),upload_summary:{status:'passed'}}}};
  }
};
vm.createContext(context);vm.runInContext(SOURCE,context);
(async()=>{
  // Let automatic legacy resume complete before triggering another queue.
  for(let i=0;i<150;i++)await Promise.resolve();
  if(mode==='legacy-resume'){
    assert.equal(storage.size,0);assert.ok(entries.some(x=>x.href==='/import?batch=9#summary'));
  }
  if(mode==='restart-expired'||mode.startsWith('recovery-')){
    assert.equal(storage.size,mode==='restart-expired'?0:1,'unavailable or unfinished recovery must preserve the checkpoint');
    const detail=entries.find(x=>x.href==='/import?batch=9#summary');
    assert.ok(detail,'expired status must retain a link to the saved batch');
    assert.ok(entries.some(x=>x.textContent===(mode==='restart-expired'?'저장된 결과 조회 완료':mode==='recovery-auth'?'로그인 필요':mode==='recovery-pending'?'접수 완료 · 분류 결과 확인 필요':'접수 완료 · 결과 조회 대기')));
    assert.ok(!entries.some(x=>x.textContent?.includes('서버가 재시작')));
    return;
  }
  const finished=el('upload').onclick();
  for(let i=0;i<30;i++)await Promise.resolve();
  if(mode==='background'){
    assert.equal(waiting.length,10,'every file is accepted before classification finishes');
    assert.equal(JSON.parse(storage.get('cost-card-upload-job')).length,10);
    assert.equal(el('upload').disabled,false);assert.equal(el('file').disabled,false);
    assert.ok(el('status').textContent.includes('다른 페이지로 이동해도'));
    assert.equal(rendered,undefined);
    while(waiting.length)waiting.pop()();
  }
  await finished;
  assert.deepEqual(posts,[1,2,3,4,5,6,7,8,9,10]);
  assert.equal(rendered.batch_id,mode==='refresh-required'?'9':'10');
  assert.ok(!rendered.recovered_upload,'Counts-only recovery must not reach the full transaction renderer');
  assert.ok(!rendered.refresh_required,'Unavailable projection must never reach the renderer');
  assert.equal(el('upload').disabled,false);assert.equal(el('file').disabled,false);
  assert.ok(!el('status').textContent.includes('미업로드'));
  if(mode==='mixed'){
    assert.ok(el('status').textContent.includes('7개 파일 처리 · 0개 파일 업로드 실패 · 3개 파일 접수 완료'));
    const jobs=JSON.parse(storage.get('cost-card-upload-job'));
    assert.deepEqual(jobs.map(j=>j.batch_id),['2','4']);
    // Completing one job must not erase the other job's restart checkpoint.
    vm.runInContext('saveUploadJob(readUploadJobs()[0],true)',context);
    assert.deepEqual(JSON.parse(storage.get('cost-card-upload-job')).map(j=>j.batch_id),['4']);
    assert.ok(entries.some(x=>x.href==='/import?batch=1#summary'));
    const detail=entries.find(x=>x.href==='/import?batch=1#summary');
    assert.equal(detail.textContent,'상세 보기');
    context.fetch=async()=>({ok:true,status:200,json:async()=>({status:'done',result:{batch_id:'4',upload_summary:{status:'passed'}}})});
    await vm.runInContext('resumeUpload()',context);
    assert.equal(storage.size,0);
    assert.ok(entries.some(x=>x.href==='/import?batch=4#summary'));
  }else if(mode==='refresh-required'){
    assert.equal(storage.size,0);
    assert.ok(el('status').textContent.includes('10개 파일 처리 · 0개 파일 업로드 실패'));
    for(const n of [1,10])assert.ok(entries.some(x=>x.href==='/import?batch='+n+'#summary'));
  }else{assert.equal(storage.size,0);assert.ok(el('status').textContent.includes('10개 파일 처리'));}
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    harness = harness.replace('MODE', json.dumps(mode)).replace('SOURCE', json.dumps(source))
    node = shutil.which('node')
    assert node, 'Node is required to verify the production JavaScript queue'
    result = subprocess.run([node, '-e', harness], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
