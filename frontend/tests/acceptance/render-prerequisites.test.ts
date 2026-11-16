// 수락 기준 #3(표 잘림)·#7(글꼴 스택 하나)의 렌더 전제 자동 시험.
// 잘림 기법(text-overflow:ellipsis·table-layout:fixed) 부재 + 셀 줄바꿈(overflow-wrap:anywhere),
// 본문·Plush의 단일 Pretendard 글꼴 스택을 CSS에서 검증한다.
// 실제 브라우저 렌더(셀 scrollWidth>clientWidth 전체값 접근·화면별 계산 글꼴/행간)는 UI-2/UI-6 합성 미리보기에서 별도 확인한다.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

function cssFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) out.push(...cssFiles(path));
    else if (entry.name.endsWith(".css")) out.push(path);
  }
  return out;
}

const css = cssFiles(SRC).map((path) => ({
  file: path.slice(SRC.length + 1),
  text: readFileSync(path, "utf-8"),
}));
const allCss = css.map((c) => c.text).join("\n");
const ledger = css.find((c) => c.file.endsWith("ledger.css"))?.text ?? "";
const tokens = css.find((c) => c.file.endsWith("tokens.css"))?.text ?? "";

describe("수락 #3 표 잘림 전제", () => {
  it("잘림 기법(text-overflow:ellipsis·table-layout:fixed)을 쓰지 않는다", () => {
    expect(allCss).not.toMatch(/text-overflow\s*:\s*ellipsis/);
    expect(allCss).not.toMatch(/table-layout\s*:\s*fixed/);
  });

  it("장부 셀·모바일 행은 줄바꿈(overflow-wrap:anywhere)으로 전체값 접근을 보장한다", () => {
    expect(ledger).toMatch(/\.cost-ledger__row-open strong\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(ledger).toMatch(/\.cost-ledger__mobile-row > strong\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(ledger).toMatch(/\.cost-ledger__mobile-bottom > span\s*\{[^}]*overflow-wrap:\s*anywhere/);
  });
});

describe("수락 #7 글꼴 스택 하나", () => {
  it("본문(--font-sans)·Plush(--plush-font) 스택이 동일하고 Pretendard 우선이다", () => {
    const sans = tokens.match(/--font-sans:\s*([^;]+);/)?.[1].trim() ?? "";
    const plush = tokens.match(/--plush-font:\s*([^;]+);/)?.[1].trim() ?? "";
    expect(sans).not.toBe("");
    expect(sans).toBe(plush);
    expect(sans.startsWith("Pretendard")).toBe(true);
  });

  it("Pretendard @font-face가 정의된다", () => {
    expect(tokens).toMatch(/@font-face\s*\{[^}]*font-family:\s*Pretendard/);
  });
});
