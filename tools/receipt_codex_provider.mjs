/** Register only the receipt-specific provider, without changing normal Codex. */
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {homedir} from 'node:os';
import {mkdir,readFile,writeFile,rename} from 'node:fs/promises';
import {codexExecutable} from './receipt_codex_launch.mjs';

export const RECEIPT_CODEX_PROVIDER = 'cost-receipt-codex';
const sourceLauncher=path.join(path.dirname(fileURLToPath(import.meta.url)),'receipt_codex_launch.mjs');
const installedLauncher=()=>path.join(process.env.LOCALAPPDATA || path.join(homedir(),'AppData','Local'),'Cost','receipt-paseo','launcher','receipt_codex_launch.mjs');
export function providerDefinition() {
  return {extends:'codex',label:'COST receipt Codex',enabled:true,
    command:[process.execPath,installedLauncher()],
    // A custom provider inherits its base's runtime env. Clear the endpoint
    // here too, before Paseo can turn it into a thread-level model provider.
    env:{CODEX_HOME:process.env.CODEX_HOME || path.join(homedir(),'.codex'),OPENAI_API_KEY:'',OPENAI_BASE_URL:''},
    options:{approval_policy:'never',sandbox_mode:'read-only',web_search:'disabled'},
    disallowedTools:['*'],paseoTools:{enabled:false}};
}
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])) : value;
const sameCommand = (a,b) => Array.isArray(a) && a.length === b.length && a.every((part,index)=>
  process.platform === 'win32' ? path.resolve(part).toLowerCase() === path.resolve(b[index]).toLowerCase() : part === b[index]);
export async function configured(api) {
  const {config} = await api.config.get();
  const actual = config.providers?.[RECEIPT_CODEX_PROVIDER];
  const expected = providerDefinition();
  return actual && Object.keys(actual.env || {}).length === Object.keys(expected.env).length && path.isAbsolute(actual.env.CODEX_HOME || '')
    && Object.entries(expected).every(([key,value])=>key === 'env' ? actual.env.OPENAI_API_KEY === '' && actual.env.OPENAI_BASE_URL === '' : key === 'command' ? sameCommand(actual[key],value)
      : JSON.stringify(canonical(actual[key]))===JSON.stringify(canonical(value)));
}
export async function configuredHome(api) {
  if (!await configured(api)) return null;
  const {config}=await api.config.get();
  return config.providers[RECEIPT_CODEX_PROVIDER].env.CODEX_HOME;
}
export async function configure(api,allowUpdate=false) {
  codexExecutable();
  const {config} = await api.config.get();
  const actual=config.providers?.[RECEIPT_CODEX_PROVIDER];
  if (actual) {
    const expected=providerDefinition();
    const owned=actual.extends === 'codex' && (sameCommand(actual.command,expected.command)
      || sameCommand(actual.command,[process.execPath,sourceLauncher]));
    if (!await configured(api) && (!allowUpdate || !owned)) throw new Error('RECEIPT_CODEX_CONFIG_CONFLICT');
  }
  const launcher=installedLauncher();
  await mkdir(path.dirname(launcher),{recursive:true,mode:0o700});
  const contents=await readFile(sourceLauncher);
  const temp=`${launcher}.${process.pid}.tmp`;
  await writeFile(temp,contents,{mode:0o600});await rename(temp,launcher);
  if (!contents.equals(await readFile(launcher))) throw new Error('RECEIPT_CODEX_CONFIG_INVALID');
  if (actual && await configured(api)) return;
  await api.config.patch({providers:{[RECEIPT_CODEX_PROVIDER]:providerDefinition()}});
  if (!await configured(api)) throw new Error('RECEIPT_CODEX_CONFIG_INVALID');
}
