import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const ids = process.argv.slice(2);

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
const client = new Client({ name: "codex-ota-extract", version: "1.0.0" });
const unique = (values) => [...new Set(values.filter(Boolean))];

try {
  await client.connect(transport);
  for (const messageId of ids) {
    const result = await client.callTool(
      {
        name: "manage_email",
        arguments: {
          operation: "read",
          email: "kkokkohero6@gmail.com",
          messageId,
          bodyFormat: "plain",
        },
      },
      undefined,
      { timeout: 300000 },
    );
    const text = result.content?.find((item) => item.type === "text")?.text ?? "";
    const subject = text.match(/^## (.+)$/m)?.[1] ?? "";
    const bookingIds = unique([
      ...text.matchAll(/예약번호(?:\s|&nbsp;|<[^>]+>)*([0-9]{10,19})/gi),
      ...text.matchAll(/주문\s*번호[:\s]+([0-9]{3,6}(?:-[0-9]{3}){2})/gi),
      ...text.matchAll(/(?:orderid|orderId|oid|cid)(?:=|%22%3A%22)([0-9]{10,19})/g),
    ].map((match) => match[1]));
    const pnrs = unique(
      [...text.matchAll(/(?:항공사 참조번호|항공사 예약번호(?:\(PNR\))?)[^A-Z0-9]{0,20}([A-Z0-9]{5,8})/gi)]
        .map((match) => match[1]?.toUpperCase()),
    );
    const dates = unique(
      [...text.matchAll(/2026(?:년|[-/.])\s*(\d{1,2})(?:월|[-/.])\s*(\d{1,2})/g)]
        .map((match) => `${match[1].padStart(2, "0")}${match[2].padStart(2, "0")}`),
    );
    console.log(JSON.stringify({ messageId, subject, bookingIds, pnrs, dates }));
  }
} finally {
  await client.close();
}
