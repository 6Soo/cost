import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

// 경로는 환경변수 → 기존 기본값(사용자 홈 기준) 순으로 해석한다.
//   GW_MCP_SDK_ROOT    @modelcontextprotocol/sdk 의 dist/esm 루트
//   GW_MCP_OAUTH_FILE  google-workspace-mcp OAuth 클라이언트 JSON
//   GW_MCP_COMMAND     google-workspace-mcp 실행 명령
const home = os.homedir();
const npmRoot = path.join(home, "AppData", "Roaming", "npm");
const sdkRoot =
  process.env.GW_MCP_SDK_ROOT ??
  path.join(
    npmRoot,
    "node_modules",
    "@aaronsb",
    "google-workspace-mcp",
    "node_modules",
    "@modelcontextprotocol",
    "sdk",
    "dist",
    "esm",
  );
const oauthFile =
  process.env.GW_MCP_OAUTH_FILE ??
  path.join(home, ".codex", "google-workspace-mcp", "oauth_client.json");
const mcpCommand =
  process.env.GW_MCP_COMMAND ?? path.join(npmRoot, "google-workspace-mcp.cmd");

const { Client } = await import(
  pathToFileURL(path.join(sdkRoot, "client", "index.js")).href
);
const { StdioClientTransport } = await import(
  pathToFileURL(path.join(sdkRoot, "client", "stdio.js")).href
);
const oauth = JSON.parse(await readFile(oauthFile, "utf8"));
const oauthClient = oauth.installed ?? oauth.web;
const transport = new StdioClientTransport({
  command: mcpCommand,
  env: {
    ...process.env,
    GOOGLE_CLIENT_ID: oauthClient.client_id,
    GOOGLE_CLIENT_SECRET: oauthClient.client_secret,
  },
});
const client = new Client({ name: "codex-workspace-inspect", version: "1.0.0" });

try {
  await client.connect(transport);
  const tools = await client.listTools();
  const selected = tools.tools.filter((tool) =>
    /gmail|mail|account/i.test(tool.name),
  );
  console.log(JSON.stringify(selected, null, 2));
} finally {
  await client.close();
}
