import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";

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
