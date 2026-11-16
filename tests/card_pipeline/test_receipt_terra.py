"""Provider/default and dispatch isolation contracts for receipt Terra runs."""
import json
import subprocess

from app import receipt_paseo


def test_terra_catalog_dispatch_and_recovery(tmp_path):
    harness = r'''
import {createHash} from 'node:crypto';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const {catalog,createBridge,restrictedConfig,billingEnvironment}=await import(process.argv[1]);
const {providerDefinition}=await import(new URL('./receipt_codex_provider.mjs',process.argv[1]));
const home=path.join(process.argv[2],'home');await mkdir(home);
process.env.CODEX_HOME=home;
await writeFile(path.join(home,'auth.json'),JSON.stringify({auth_mode:'chatgpt',tokens:{access_token:'synthetic',refresh_token:'synthetic'}}));
let captured,workspace,agent;
const api={config:{get:async()=>({config:{providers:{'cost-receipt-codex':providerDefinition()}}})},providers:{
 snapshot:async()=>({entries:[{provider:'claude',status:'ready'},{provider:'codex',status:'ready'},{provider:'cost-receipt-codex',status:'ready'}]}),
 listModels:async provider=>({models:provider==='codex'?[{id:'gpt-6.1-terra',label:'Terra current',thinkingOptions:[{id:'low'},{id:'high'}],defaultThinkingOptionId:'low'},{id:'unapproved',thinkingOptions:[]}]:[]}),
 diagnostic:async()=>({diagnostic:''})},
 workspaces:{create:async r=>{workspace=r;if('workspaceId' in r)throw new Error('SDK workspaceId refers to existing workspaces');return {id:'daemon-owned-workspace',directory:r.source.path,agents:{create:async r=>{
  captured=r;agent={id:r.agentId,workspaceId:'daemon-owned-workspace',cwd:workspace.source.path,provider:'cost-receipt-codex',model:'gpt-6.1-terra',labels:r.labels};return {id:r.agentId};
 }}}}},agents:{ref:()=>({refresh:async()=>({agent})})}};
const c=await catalog(api);
const dispatch=await createBridge(api,path.join(process.argv[2],'runs'));
const hash=x=>createHash('sha256').update(x).digest('hex');
const prompt='managed synthetic',data=Buffer.from('synthetic image');
const request={operation:'start',provider:'codex',model:'gpt-6.1-terra',thinking:'high',run_key:'terra-synthetic-run',prompt,prompt_metadata:{prompt_sha256:hash(prompt)},source_sha256:hash(data),image:{data:data.toString('base64'),mimeType:'image/png'}};
const handle=await dispatch(request);
const recovered=await dispatch({operation:'find',run_key:request.run_key});
let reusedCode;
try{await dispatch({...request,thinking:'low'})}catch(e){reusedCode=e.code}
await writeFile(path.join(home,'auth.json'),JSON.stringify({auth_mode:'apikey',OPENAI_API_KEY:'synthetic'}));
const noSubscription=await catalog(api,'codex');
console.log(JSON.stringify({c,config:captured.config,env:billingEnvironment(),handle,recovered,reusedCode,noSubscription}));
'''
    result = subprocess.run(
        ['node', '--input-type=module', '-e', harness,
         receipt_paseo.BRIDGE.as_uri(), str(tmp_path)],
        capture_output=True, text=True, encoding='utf-8', check=True,
    )
    value = json.loads(result.stdout)
    assert value['c']['default_provider'] == 'codex'
    assert value['c']['default_model'] == 'gpt-6.1-terra'
    assert value['c']['default_thinking'] == 'high'
    terra, unapproved = value['c']['models']
    assert terra['selectable'] is True
    assert terra['default_thinking'] == terra['effective_thinking'] == 'high'
    assert unapproved['selectable'] is False
    config = value['config']
    assert config['provider'] == 'cost-receipt-codex/gpt-6.1-terra'
    assert config['thinkingOptionId'] == 'high'
    assert config['options']['sandbox_mode'] == 'read-only'
    assert config['options']['approval_policy'] == 'never'
    assert config['options']['web_search'] == 'disabled'
    assert config['mcpServers'] == {}
    assert value['env']['OPENAI_API_KEY'] == ''
    assert value['env']['OPENAI_BASE_URL'] == ''
    assert value['handle'] == value['recovered']
    assert value['reusedCode'] == 'PASEO_RUN_KEY_REUSED'
    assert not any(row['selectable'] for row in value['noSubscription']['models'])


def test_model_selection_and_history_use_dynamic_identity():
    harness = r'''
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const nodes=new Map(),posts=[];
function node(id){if(!nodes.has(id))nodes.set(id,{
 value:'',textContent:'',disabled:false,events:{},html:'',
 set innerHTML(value){this.html=value;if(id==='rw-provider'||id==='rw-model')this.value=''},
 get innerHTML(){return this.html},addEventListener(event,handler){this.events[event]=handler}
});return nodes.get(id)}
const base={connected:true,providers:[{id:'claude',label:'Claude',available:true},{id:'codex',label:'Codex',available:true}],default_provider:'codex',default_model:'gpt-6.1-terra',default_thinking:'high'};
const models=[{provider:'codex',id:'gpt-6.1-terra',label:'Terra live',selectable:true,default_thinking:'high'},{provider:'codex',id:'different',label:'Other live',selectable:true,default_thinking:'medium'}];
const context={console,URLSearchParams,Uint8Array,Map,Set,Date,JSON,Math,
 document:{getElementById:node,querySelectorAll:s=>s==='[data-rw-image]:checked'?[{value:'a'.repeat(64)}]:[],querySelector:()=>null,addEventListener(){},activeElement:null},
 window:{addEventListener(){},setInterval(){},scrollTo(){},RECEIPT_WORKFLOW_TRIPS:[]},
 fetch:async(url,options)=>{if(options?.method==='POST')posts.push(url);let data;
 if(url.startsWith('/api/receipts/paseo/models'))data={...base,models};
 else if(url==='/api/receipts/workflow')data={batches:[{provider:'claude',model:'historic-opus',thinking:'medium',jobs:[],candidates:[]}]};
 else data={images:[],pdfs:[],uploads:[]};return {ok:true,status:200,json:async()=>data}}
};
vm.runInNewContext(await readFile(process.argv[1],'utf8'),context);
const flush=async()=>{for(let i=0;i<5;i++)await new Promise(setImmediate)};await flush();
const initial={provider:node('rw-provider').value,model:node('rw-model').value,selected:node('rw-selected-model').textContent,button:node('rw-run-model').textContent,disabled:node('rw-run-model').disabled,history:node('rw-batches').innerHTML};
node('rw-model').value='different';node('rw-model').events.change();
const other=node('rw-selected-model').textContent;
models[1].label='Renamed live';await node('rw-catalog-refresh').events.click();await flush();
console.log(JSON.stringify({initial,other,refreshed:node('rw-selected-model').textContent,model:node('rw-model').value,posts}));
'''
    result = subprocess.run(
        ['node', '--input-type=module', '-e', harness,
         str(receipt_paseo.ROOT / 'webapp/static/js/receipt_workflow.js')],
        capture_output=True, text=True, encoding='utf-8', check=True,
    )
    value = json.loads(result.stdout)
    assert value['initial']['provider'] == 'codex'
    assert value['initial']['model'] == 'gpt-6.1-terra'
    assert 'Terra live · high' in value['initial']['selected']
    assert 'Terra live · high' in value['initial']['button']
    assert value['initial']['disabled'] is False
    assert 'claude · historic-opus · medium' in value['initial']['history']
    assert 'Other live · medium' in value['other']
    assert value['model'] == 'different'
    assert 'Renamed live · medium' in value['refreshed']
    assert value['posts'] == []


def test_codex_tool_flags_and_provider_registration_are_isolated(tmp_path):
    from app import frontier_agent_provider

    harness = r'''
import path from 'node:path';
const launch=await import(new URL('./receipt_codex_launch.mjs',process.argv[1]));
const {configure,configured}=await import(new URL('./receipt_codex_provider.mjs',process.argv[1]));
process.env.LOCALAPPDATA=process.argv[2];process.env.WEBLEDGER_CODEX_EXE=process.execPath;
const original={enabled:true,models:[{id:'original-model'}],env:{OPENAI_BASE_URL:'https://synthetic-invalid.invalid',OPENAI_API_KEY:'synthetic-api-key'}};
const config={providers:{codex:original}};let patches=0;
const api={config:{get:async()=>({config}),patch:async patch=>{patches++;Object.assign(config.providers,patch.providers)}}};
await configure(api);await configure(api);
const ready=await configured(api);
const effectiveEnv={...original.env,...config.providers['cost-receipt-codex'].env};
config.providers['cost-receipt-codex'].env.OPENAI_BASE_URL='https://synthetic-invalid.invalid';
const changedEndpointAccepted=await configured(api);
config.providers['cost-receipt-codex'].env.OPENAI_BASE_URL='';
config.providers['cost-receipt-codex'].command=['unowned-command'];let conflict;
try{await configure(api)}catch(e){conflict=e.message}
console.log(JSON.stringify({original,normal:config.providers.codex,patches,ready,effectiveEnv,changedEndpointAccepted,conflict,args:launch.codexArgs(['app-server'])}));
'''
    result = subprocess.run(
        ['node', '--input-type=module', '-e', harness, receipt_paseo.BRIDGE.as_uri(), str(tmp_path)],
        capture_output=True, text=True, encoding='utf-8', check=True,
    )
    value = json.loads(result.stdout)
    assert value['normal'] == value['original']
    assert value['patches'] == 1
    assert value['ready'] is True
    assert value['effectiveEnv']['OPENAI_BASE_URL'] == ''
    assert value['effectiveEnv']['OPENAI_API_KEY'] == ''
    assert value['changedEndpointAccepted'] is False
    assert value['conflict'] == 'RECEIPT_CODEX_CONFIG_CONFLICT'
    assert set(frontier_agent_provider.config_args()[1::2]) <= set(value['args'])
    assert 'forced_login_method="chatgpt"' in value['args']
    assert 'model_provider="openai"' in value['args']
