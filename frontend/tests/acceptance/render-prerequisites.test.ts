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
  it("장부 표에 잘림 기법(text-overflow:ellipsis·table-layout:fixed)을 쓰지 않는다", () => {
    // 수락 #3의 대상은 데이터 표 셀이다(요구사항: "표 셀이 잘리지 않거나 전체 값 볼 수단").
    // 셸 상단바 위치 표시(.cost-topbar-location)의 모바일 ellipsis는 main이 도입한
    // 내비게이션 크롬으로 표 셀이 아니며, 전체 제목은 페이지 h1에 그대로 있다.
    // 따라서 ellipsis 금지는 장부 표 CSS에 적용하고, table-layout:fixed는 전역 금지한다.
    expect(ledger).not.toMatch(/text-overflow\s*:\s*ellipsis/);
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
