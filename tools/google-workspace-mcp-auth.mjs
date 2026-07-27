import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";

const sdkRoot =
  "C:\\Users\\kkokk\\AppData\\Roaming\\npm\\node_modules\\@aaronsb\\google-workspace-mcp\\node_modules\\@modelcontextprotocol\\sdk\\dist\\esm";
const { Client } = await import(
  pathToFileURL(`${sdkRoot}\\client\\index.js`).href
);
const { StdioClientTransport } = await import(
  pathToFileURL(`${sdkRoot}\\client\\stdio.js`).href
);

const oauth = JSON.parse(
  await readFile(
    "C:\\Users\\kkokk\\.codex\\google-workspace-mcp\\oauth_client.json",
    "utf8",
  ),
);
const oauthClient = oauth.installed ?? oauth.web;
if (!oauthClient?.client_id || !oauthClient?.client_secret) {
  throw new Error("OAuth client credentials are invalid");
}

const transport = new StdioClientTransport({
  command:
    "C:\\Users\\kkokk\\AppData\\Roaming\\npm\\google-workspace-mcp.cmd",
  env: {
    ...process.env,
    GOOGLE_CLIENT_ID: oauthClient.client_id,
    GOOGLE_CLIENT_SECRET: oauthClient.client_secret,
  },
});
const client = new Client({ name: "codex-oauth-setup", version: "1.0.0" });

try {
  await client.connect(transport);
  const tools = await client.listTools();
  const accountTool = tools.tools.find((tool) => tool.name === "manage_accounts");
  if (!accountTool) {
    throw new Error("manage_accounts tool is unavailable");
  }
  console.log("MCP_READY");
  const result = await client.callTool({
    name: "manage_accounts",
    arguments: { operation: "authenticate" },
  }, undefined, { timeout: 300000 });
  console.log(JSON.stringify(result));
} finally {
  await client.close();
}
