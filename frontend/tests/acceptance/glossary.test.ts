// 수락 기준 #12(용어집 통일)의 대조 시험.
// 용어집 한 벌: 하나의 뜻에 하나의 이름 — item=항목, kind=구분, category=분류, XLSX 산출=내보내기(출력 금지).
// 책임 전가 문구("관리자가 설정하면" 등)와 XLSX '출력' 혼용을 화면 소스에서 금지하고, 라벨 사전이 표준 용어를 쓰는지 대조한다.
// 용어집 정본은 docs/design/m4-glossary-20261117.md.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) out.push(...sourceFiles(path));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\./.test(entry.name)) out.push(path);
  }
  return out;
}

const sources = sourceFiles(SRC).map((path) => ({
  file: path.slice(SRC.length + 1),
  text: readFileSync(path, "utf-8"),
}));

// 금지 문구: XLSX '출력' 혼용(내보내기로 통일), 책임 전가 표현.
const FORBIDDEN: { name: string; pattern: RegExp }[] = [
  { name: "XLSX '출력 작업' 혼용(내보내기 통일)", pattern: /출력\s*작업/ },
  { name: "XLSX '출력' 혼용(내보내기 통일)", pattern: /XLSX\s*출력/ },
  { name: "책임 전가 문구 '관리자가 설정'", pattern: /관리자가\s*설정/ },
];

describe("수락 #12 용어집 대조", () => {
  it("화면 소스에 금지 문구(XLSX 출력 혼용·책임 전가)가 없다", () => {
    const violations: string[] = [];
    for (const { file, text } of sources) {
      for (const { name, pattern } of FORBIDDEN) {
        if (pattern.test(text)) violations.push(`${file}: ${name}`);
      }
    }
    expect(violations).toEqual([]);
  });

  it("XLSX 산출 동작은 '내보내기'로 통일한다", () => {
    const types = sources.find((s) => s.file === "api/types.ts")?.text ?? "";
    expect(types).toContain('label: "XLSX 내보내기"');
    expect(types).toContain('label: "내보내기 상태"');
    expect(types).toContain('label: "내보내기 다운로드"');
    const ledger = sources.find((s) => s.file === "features/ledger/index.tsx")?.text ?? "";
    expect(ledger).toContain("XLSX 내보내기");
    expect(ledger).toContain("내보내기 작업");
  });

  it("라벨 사전이 표준 용어를 쓴다(item=항목, kind=구분, category=분류)", () => {
    const rules = sources.find((s) => s.file === "features/auxiliary/rules.tsx")?.text ?? "";
    expect(rules).toContain('item: "항목"');
    expect(rules).toContain('category: "분류"');
    expect(rules).toContain('card_kind: "카드 구분"');
    const types = sources.find((s) => s.file === "api/types.ts")?.text ?? "";
    expect(types).toContain('name: "item", label: "항목"');
    expect(types).toContain('name: "income_kind", label: "수입 구분"');
    expect(types).toContain('name: "kind", label: "구분"');
  });
});
