import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";

const [toolName, rawArguments = "{}"] = process.argv.slice(2);
if (!toolName) throw new Error("Usage: node google-workspace-mcp-call.mjs TOOL JSON");

const sdkRoot =
  "C:\\Users\\kkokk\\AppData\\Roaming\\npm\\node_modules\\@aaronsb\\google-workspace-mcp\\node_modules\\@modelcontextprotocol\\sdk\\dist\\esm";
const { Client } = await import(pathToFileURL(`${sdkRoot}\\client\\index.js`).href);
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
const transport = new StdioClientTransport({
  command: "C:\\Users\\kkokk\\AppData\\Roaming\\npm\\google-workspace-mcp.cmd",
  env: {
    ...process.env,
    GOOGLE_CLIENT_ID: oauthClient.client_id,
    GOOGLE_CLIENT_SECRET: oauthClient.client_secret,
  },
});
const client = new Client({ name: "codex-workspace-call", version: "1.0.0" });

try {
  await client.connect(transport);
  const result = await client.callTool(
    {
      name: toolName,
      arguments: JSON.parse(
        rawArguments.startsWith("b64:")
          ? Buffer.from(rawArguments.slice(4), "base64").toString("utf8")
          : rawArguments,
      ),
    },
    undefined,
    { timeout: 300000 },
  );
  console.log(JSON.stringify(result, null, 2));
} finally {
  await client.close();
}
