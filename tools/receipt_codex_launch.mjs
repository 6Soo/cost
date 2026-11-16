/** Dedicated Paseo Codex launch: subscription only, receipt data, no tools. */
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// Keep aligned with app/frontier_agent_provider.py's verified tool restriction.
export const DISABLED_FEATURES = [
  'shell_tool','unified_exec','unified_exec_tty','shell_snapshot',
  'apps','plugins','remote_plugin','plugin_sharing',
  'browser_use','browser_use_external','browser_use_full_cdp_access',
  'computer_use','in_app_browser','in_app_local_automation','view_image',
  'image_generation','multi_agent','multi_agent_v2','agent_message_board',
  'hooks','code_mode','code_mode_host','code_mode_only','code_mode_prewarm',
  'skill_search','skill_mcp_dependency_install','workspace_dependencies',
  'request_permissions_tool','default_mode_request_user_input','auth_elicitation',
  'tool_suggest','tool_call_mcp_elicitation','sleep_tool','goals','memories',
  'standalone_web_search','realtime_conversation','daemon_auto_start',
];
export function codexArgs(args) {
  if (args[0] !== 'app-server') throw new Error('RECEIPT_CODEX_COMMAND_INVALID');
  // App-server has no exec-only --ignore-user-config/--ignore-rules switches.
  // These CLI overrides take precedence over user/project config and rules.
  const values = ['approval_policy="never"','sandbox_mode="read-only"',
    'web_search="disabled"','mcp_servers={}','project_doc_max_bytes=0',
    'skills.bundled.enabled=false','analytics.enabled=false','feedback.enabled=false',
    'features.skip_host_skill_discovery=true',
    'model_provider="openai"','forced_login_method="chatgpt"',
    ...DISABLED_FEATURES.map(name=>`features.${name}=false`)];
  return [...args,'--strict-config',...values.flatMap(value=>['-c',value])];
}
export async function inheritedMcpNames(executable,args,env) {
  // Empty TOML tables merge rather than erase inherited MCP entries. Ask the
  // native config reader (no thread/turn/model call) and disable every name.
  const probe = spawn(executable,args,{env,stdio:['pipe','pipe','ignore'],windowsHide:true});
  try {
    return await new Promise((resolve,reject)=>{
      let buffer='',bytes=0;
      const timer=setTimeout(()=>reject(new Error('RECEIPT_CODEX_CONFIG_TIMEOUT')),10000);
      const finish=(error,names)=>{clearTimeout(timer);error?reject(error):resolve(names)};
      const send=value=>probe.stdin.write(JSON.stringify(value)+'\n');
      probe.on('error',error=>finish(error));
      probe.on('exit',()=>finish(new Error('RECEIPT_CODEX_CONFIG_CLOSED')));
      probe.stdout.on('data',chunk=>{
        bytes+=chunk.length;
        if(bytes>1024*1024){finish(new Error('RECEIPT_CODEX_CONFIG_SIZE'));return}
        buffer+=chunk.toString('utf8');
        let end;
        while((end=buffer.indexOf('\n'))>=0){
          const line=buffer.slice(0,end);buffer=buffer.slice(end+1);
          let reply;try{reply=JSON.parse(line)}catch{finish(new Error('RECEIPT_CODEX_CONFIG_INVALID'));return}
          if(reply.id===1){
            if(reply.error){finish(new Error('RECEIPT_CODEX_CONFIG_INVALID'));return}
            send({method:'initialized'});
            send({id:2,method:'config/read',params:{includeLayers:false}});
          }
          if(reply.id===2){
            const config=reply.result?.config;
            if(!config){finish(new Error('RECEIPT_CODEX_CONFIG_INVALID'));return}
            finish(null,Object.keys(config.mcp_servers ?? {}));
          }
        }
      });
      send({id:1,method:'initialize',params:{clientInfo:{name:'cost_receipt_config',version:'1'},capabilities:{experimentalApi:true}}});
    });
  } finally { probe.stdin.end();probe.kill(); }
}
export function codexExecutable() {
  const executable = process.env.WEBLEDGER_CODEX_EXE || path.join(
    process.env.APPDATA || path.join(homedir(),'AppData','Roaming'),
    'npm','node_modules','@openai','codex','node_modules','@openai','codex-win32-x64',
    'vendor','x86_64-pc-windows-msvc','bin','codex.exe');
  if (!path.isAbsolute(executable) || !existsSync(executable)) throw new Error('RECEIPT_CODEX_NOT_FOUND');
  return executable;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const env = {...process.env};
    for (const name of Object.keys(env)) if (/^(OPENAI_|CODEX_API_KEY|CODEX_ACCESS_TOKEN|CODEX_AUTH|AZURE_|ANTHROPIC_|CLAUDE_CODE_)/i.test(name)) delete env[name];
    const executable=codexExecutable();
    const args=codexArgs(process.argv.slice(2));
    const names=await inheritedMcpNames(executable,args,env);
    if (names.some(name=>!/^[A-Za-z0-9_-]+$/.test(name))) throw new Error('RECEIPT_CODEX_MCP_NAME_INVALID');
    const disabled=names.flatMap(name=>['-c',`mcp_servers.${name}.enabled=false`]);
    const child = spawn(executable,[...args,...disabled],{env,stdio:'inherit',windowsHide:true});
    child.on('error',()=>{process.exitCode=1});
    child.on('exit',code=>{process.exitCode=code ?? 1});
  } catch { process.stderr.write('RECEIPT_CODEX_LAUNCH_FAILED\n');process.exitCode=1; }
}
