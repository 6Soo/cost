// 수락 기준 #3(표 잘림)·#7(글꼴 스택 하나)의 렌더 전제 자동 시험.
// 잘림 기법(text-overflow:ellipsis·table-layout:fixed) 부재 + 셀 줄바꿈(overflow-wrap:anywhere),
// 본문·Plush의 단일 Pretendard 글꼴 스택을 CSS에서 검증한다.
// 셀 수준 전체값 접근(scrollWidth>clientWidth 셀마다 줄바꿈·펼침·title)·화면별 고유 제목의
// 실제 브라우저 렌더 검증은 webapp/tests/test_plush_render_browser.py에서 합성 미리보기로 수행한다.
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
  it("데이터 표에 잘림 기법(text-overflow:ellipsis·table-layout:fixed)을 쓰지 않는다", () => {
    // 수락 #3의 대상은 데이터 표 셀이다(요구사항: "표 셀이 잘리지 않거나 전체 값 볼 수단").
    // 셸 상단바 위치 표시(.cost-topbar-location)의 모바일 ellipsis는 main이 도입한 내비게이션
    // 크롬(표 셀 아님·전체 제목은 페이지 h1)이라 그 규칙만 예외로 두고, 나머지 모든 CSS
    // (공용 표·여행 목록·장부 포함)에서 ellipsis를 금지한다. table-layout:fixed는 전역 금지.
    const withoutTopbarLocation = allCss.replace(/\.cost-topbar-location\s*\{[^}]*\}/g, "");
    expect(withoutTopbarLocation).not.toMatch(/text-overflow\s*:\s*ellipsis/);
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
