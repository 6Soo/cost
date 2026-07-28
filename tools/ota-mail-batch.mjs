import { pathToFileURL, fileURLToPath } from "node:url";
import { readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

// 저장소 위치는 이 모듈 경로에서 유도한다(하드코딩 금지).
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// ★원문(rawText 포함) 색인은 .raw.json 에 쓴다. ota_mail_index.json 은 origin/main 이
//   추적하는 편집본이라 같은 경로에 쓰면 git 병합/체크아웃이 원문을 덮어쓴다(2026-07-29 실측).
const outputPath = path.join(repoRoot, "ledger", "data", "ota_mail_index.raw.json");
// MCP SDK·OAuth·실행명령 경로는 환경변수 → 기존 기본값(사용자 홈 기준) 순으로 해석한다.
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
const client = new Client({ name: "codex-ota-batch", version: "1.0.0" });
const unique = (values) => [...new Set(values.filter(Boolean))];
const monthRanges = [];
for (let year = 2025, month = 8; year < 2026 || month <= 7; ) {
  const nextYear = month === 12 ? year + 1 : year;
  const nextMonth = month === 12 ? 1 : month + 1;
  monthRanges.push({
    after: `${year}/${String(month).padStart(2, "0")}/01`,
    before: `${nextYear}/${String(nextMonth).padStart(2, "0")}/01`,
  });
  year = nextYear;
  month = nextMonth;
}
const providerQueries = [
  "예약 (트립닷컴 OR Trip.com)",
  "예약 (마이트립 OR Mytrip)",
  "예약 (Agoda OR 아고다)",
  "예약 Booking.com",
  "가입 (트래블로버 OR Travelrover)",
];

function textOf(result) {
  return result.content?.find((item) => item.type === "text")?.text ?? "";
}

function parseSearch(text) {
  return [...text.matchAll(/^([0-9a-f]{16}) \| (.+?) \| (.+?) \| (.+)$/gm)].map(
    (match) => ({
      messageId: match[1],
      sender: match[2],
      searchSubject: match[3],
      searchDate: match[4],
    }),
  );
}

function extract(messageId, raw) {
  const subject = raw.match(/^## (.+)$/m)?.[1] ?? "";
  const sender = raw.match(/^\*\*From:\*\* (.+)$/m)?.[1] ?? "";
  const sentAt = raw.match(/^\*\*Date:\*\* (.+)$/m)?.[1] ?? "";
  const bookingRefs = unique([
    ...[...raw.matchAll(/예약번호(?:\s|&nbsp;|<[^>]+>)*([0-9][0-9\s]{9,25})/gi)].map(
      (match) => match[1].replace(/\s/g, ""),
    ),
    ...[...raw.matchAll(/주문\s*번호[:\s]+([0-9]{3,6}(?:-[0-9]{3}){2})/gi)].map(
      (match) => match[1],
    ),
    ...[...raw.matchAll(/Booking(?:\s*ID)?[:\s#]+([0-9]{8,19})/gi)].map(
      (match) => match[1],
    ),
  ]);
  const pnrs = unique(
    [
      ...raw.matchAll(
        /(?:항공사 참조번호|항공사 예약번호(?:\(PNR\))?)[^A-Z0-9]{0,20}([A-Z0-9]{5,8})/gi,
      ),
    ].map((match) => match[1]?.toUpperCase()),
  );
  const travelDates = unique(
    [...raw.matchAll(/20(?:25|26)(?:년|[-/.])\s*(\d{1,2})(?:월|[-/.])\s*(\d{1,2})/g)]
      .map((match) => `${match[1].padStart(2, "0")}${match[2].padStart(2, "0")}`),
  );
  const amounts = unique(
    [...raw.matchAll(/(?:합계|결제금액|총액|KRW|원)[^0-9]{0,30}([0-9][0-9,]{3,})|([0-9][0-9,]{3,})\s*(?:KRW|원)/gi)]
      .map((match) => Number((match[1] ?? match[2]).replace(/,/g, "")))
      .filter((amount) => amount >= 1000 && amount < 100000000),
  );
  const provider = /mytrip|마이트립/i.test(raw)
    ? "mytrip"
    : /trip\.com|트립닷컴/i.test(raw)
      ? "trip"
      : /agoda|아고다/i.test(raw)
        ? "agoda"
        : /booking\.com/i.test(raw)
          ? "booking"
          : /트래블로버|travelrover/i.test(raw)
            ? "travelrover"
            : "other";
  return {
    messageId,
    subject,
    sender,
    sentAt,
    provider,
    bookingRefs,
    pnrs,
    travelDates,
    amounts,
    rawText: raw,
  };
}

try {
  await client.connect(transport);
  const found = new Map();
  for (const range of monthRanges) {
    for (const providerQuery of providerQueries) {
      const result = await client.callTool(
        {
          name: "manage_email",
          arguments: {
            operation: "search",
            email: "kkokkohero6@gmail.com",
            query: `${providerQuery} after:${range.after} before:${range.before}`,
            maxResults: 50,
          },
        },
        undefined,
        { timeout: 300000 },
      );
      for (const message of parseSearch(textOf(result))) {
        found.set(message.messageId, message);
      }
    }
    console.error(`searched ${range.after}: ${found.size} unique`);
  }

  const ids = [...found.keys()];
  const records = [];
  for (let index = 0; index < ids.length; index += 20) {
    const batch = ids.slice(index, index + 20);
    const results = await Promise.all(
      batch.map(async (messageId) => {
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
        return extract(messageId, textOf(result));
      }),
    );
    records.push(...results);
    if (records.length % 100 < 20 || records.length === ids.length) {
      console.error(`read ${records.length}/${ids.length}`);
    }
  }
  await writeFile(
    outputPath,
    `${JSON.stringify({ generatedAt: new Date().toISOString(), records }, null, 2)}\n`,
    "utf8",
  );
  console.log(JSON.stringify({ outputPath, messages: records.length }));
} finally {
  await client.close();
}
