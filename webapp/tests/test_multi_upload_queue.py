"""Execute the production upload queue with mixed asynchronous outcomes."""
import json
import shutil
import subprocess

import pytest

from webapp.card_flow import page


@pytest.mark.parametrize('mode', ['mixed', 'success', 'legacy-resume', 'refresh-required'])
def test_all_ten_files_are_attempted_and_unresolved_jobs_survive(mode):
    source = page('synthetic-csrf')
    source = source[source.index("const uploadJobKey="):source.index("el('ruleform').onsubmit=")]
    harness = r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const mode = MODE;
const storage = new Map(), nodes = new Map(), posts = [], entries = [];
const identity = n => '/api/imports/upload-status/'+String(n).padStart(32,'0');
function element(){return {disabled:false, textContent:'', append(...xs){entries.push(...xs)},
  setAttribute(){},removeAttribute(){},querySelector(){return this}}}
const el = id => {if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
const localStorage = {getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
if(mode==='legacy-resume')localStorage.setItem('cost-card-upload-job',JSON.stringify({status_url:identity(9),batch_id:'9',filename:'legacy.csv'}));
let rendered;
const context={el,localStorage,document:{createElement:element},Date,Error,JSON,Array,Math,RegExp,
  AbortSignal:{timeout(){}},setTimeout:fn=>{fn();},
  uploadInput:el('file'),uploadDrop:element(),uploadLabel:element(),batchGeneration:0,
  invalidateProposal(){},appendCoverageForm(){},render:j=>{rendered=j},renderUploadSystemError(){},
  renderUploadSelection:()=>Array.from({length:10},(_,i)=>({name:(i+1)+'.csv',arrayBuffer:async()=>Buffer.from('synthetic '+i)})),
  call:async(url,data,headers)=>{assert.equal(headers['X-Upload-Async'],'1');const n=Number(decodeURIComponent(headers['X-Filename']).split('.')[0]);posts.push(n);return {status_url:identity(n),batch_id:String(n)}},
  fetch:async url=>{const n=Number(url.split('/').at(-1));
    if(mode==='mixed'&&(n===2||n===4))throw Error('temporary disconnect');
    return {ok:true,status:200,json:async()=>mode==='refresh-required'&&(n===1||n===10)?{status:'done',result:{batch_id:String(n),refresh_required:true,upload_summary:{status:'refresh_required'}}}:mode==='mixed'&&n===1?{status:'error',message:'synthetic classification failure'}:{status:'done',result:{batch_id:String(n),upload_summary:{status:'passed'}}}};
  }
};
vm.createContext(context);vm.runInContext(SOURCE,context);
(async()=>{
  // Let automatic legacy resume complete before triggering another queue.
  for(let i=0;i<20;i++)await Promise.resolve();
  if(mode==='legacy-resume'){
    assert.equal(storage.size,0);assert.ok(entries.some(x=>x.href==='/import?batch=9#summary'));
  }
  await el('upload').onclick();
  assert.deepEqual(posts,[1,2,3,4,5,6,7,8,9,10]);
  assert.equal(rendered.batch_id,mode==='refresh-required'?'9':'10');
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
    context.fetch=async()=>({ok:true,status:200,json:async()=>({status:'done',result:{batch_id:'4',upload_summary:{status:'passed'}}})});
    await vm.runInContext('resumeUpload()',context);
    assert.equal(storage.size,0);
    assert.ok(entries.some(x=>x.href==='/import?batch=4#summary'));
  }else if(mode==='refresh-required'){
    assert.equal(storage.size,0);
    assert.ok(el('status').textContent.includes('8개 파일 처리 · 0개 파일 업로드 실패 · 2개 파일 접수 완료'));
    for(const n of [1,10])assert.ok(entries.some(x=>x.href==='/import?batch='+n+'#summary'));
  }else{assert.equal(storage.size,0);assert.ok(el('status').textContent.includes('10개 파일 처리'));}
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    harness = harness.replace('MODE', json.dumps(mode)).replace('SOURCE', json.dumps(source))
    node = shutil.which('node')
    assert node, 'Node is required to verify the production JavaScript queue'
    result = subprocess.run([node, '-e', harness], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
