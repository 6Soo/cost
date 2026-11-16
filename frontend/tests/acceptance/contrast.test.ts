// 수락 기준 #4(글자 대비 4.5:1)·#8(입력 테두리 대비 3:1)의 자동 대비 계산 시험.
// tokens.css의 라이트(:root)·다크(:root.dark) 색 토큰을 읽어 WCAG 2.x 대비비를 계산하고,
// 모든 글자 쌍은 4.5:1 이상, 테두리 쌍은 3:1 이상이어야 한다(실패 0건).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  fileURLToPath(new URL("../../src/styles/tokens.css", import.meta.url)),
  "utf-8",
);

function tokens(selector: RegExp): Record<string, string> {
  const body = css.match(selector)?.[1] ?? "";
  const out: Record<string, string> = {};
  for (const match of body.matchAll(/(--cost-[\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[match[1]] = match[2];
  }
  return out;
}

const light = tokens(/:root\s*\{([\s\S]*?)\}/);
const dark = tokens(/:root\.dark\s*\{([\s\S]*?)\}/);

function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const channel = (offset: number) => {
    const c = parseInt(value.slice(offset, offset + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function ratio(fg: string, bg: string): number {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const textPairs: ReadonlyArray<readonly [string, string]> = [
  ["--cost-text", "--cost-surface"],
  ["--cost-text", "--cost-panel"],
  ["--cost-text", "--cost-background"],
  ["--cost-text-secondary", "--cost-surface"],
  ["--cost-text-secondary", "--cost-panel"],
  ["--cost-text-secondary", "--cost-background"],
  ["--cost-success-text", "--cost-surface"],
  ["--cost-success-text", "--cost-panel"],
  ["--cost-danger-text", "--cost-surface"],
  ["--cost-danger-text", "--cost-panel"],
  ["--cost-warning-text", "--cost-surface"],
  ["--cost-warning-text", "--cost-panel"],
  ["--cost-on-action", "--cost-action"],
  ["--cost-selection-text", "--cost-selection-start"],
  ["--cost-selection-text", "--cost-selection-end"],
];

const borderPairs: ReadonlyArray<readonly [string, string]> = [
  ["--cost-border-control", "--cost-surface"],
  ["--cost-border-control", "--cost-panel"],
  ["--cost-border-control", "--cost-background"],
];

describe("수락 #4·#8 색 대비", () => {
  for (const [name, theme] of [["라이트", light], ["다크", dark]] as const) {
    describe(name, () => {
      it("색 토큰이 모두 정의되어 있다", () => {
        for (const [fg, bg] of [...textPairs, ...borderPairs]) {
          expect(theme[fg], fg).toMatch(/^#[0-9a-fA-F]{6}$/);
          expect(theme[bg], bg).toMatch(/^#[0-9a-fA-F]{6}$/);
        }
      });
      it.each(textPairs)("%s on %s ≥ 4.5:1", (fg, bg) => {
        expect(ratio(theme[fg], theme[bg])).toBeGreaterThanOrEqual(4.5);
      });
      it.each(borderPairs)("%s on %s ≥ 3:1", (fg, bg) => {
        expect(ratio(theme[fg], theme[bg])).toBeGreaterThanOrEqual(3);
      });
    });
  }
});
