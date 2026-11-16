// @vitest-environment jsdom
// 수락 기준 #9(건너뛰기 링크 첫 초점)·#1(관리 탭 링크 올바른 대상)·#6(브랜드 마크 1회)의 셸 시험.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "../../src/app/AppShell";

afterEach(cleanup);

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]';

describe("수락 #9 건너뛰기 링크", () => {
  it("건너뛰기 링크가 DOM 순서상 첫 초점 요소이고 본문으로 이동한다", () => {
    render(<AppShell role="owner" trips={[]} path="/"><h1>합성 본문</h1></AppShell>);
    const first = document.querySelectorAll(FOCUSABLE)[0];
    expect(first).toBeInstanceOf(HTMLAnchorElement);
    expect(first.getAttribute("href")).toBe("#cost-main");
    expect(first.textContent).toContain("건너뛰기");
    const target = document.getElementById("cost-main");
    expect(target).not.toBeNull();
    expect(target?.tabIndex).toBe(-1);
    expect(target?.contains(screen.getByRole("heading", { name: "합성 본문" }))).toBe(true);
  });
});

describe("수락 #1 관리 탭 링크", () => {
  it("계정·권한·Google 장부·검수 결과 링크가 올바른 대상으로 열린다", () => {
    render(<AppShell role="owner" trips={[]} path="/access/admin"><h1>합성</h1></AppShell>);
    const expected: ReadonlyArray<readonly [string, string]> = [
      ["계정·권한", "/access/admin"],
      ["Google 장부", "/google-ledger"],
      ["검수 결과", "/review"],
    ];
    for (const [name, href] of expected) {
      const links = screen.getAllByRole("link", { name });
      expect(links.length, name).toBeGreaterThan(0);
      for (const link of links) {
        expect(link.getAttribute("href"), name).toBe(href);
      }
    }
  });
});

describe("수락 #6 브랜드", () => {
  it("브랜드 마크는 한 번만 나타난다", () => {
    const { container } = render(<AppShell role="owner" trips={[]} path="/"><h1>합성</h1></AppShell>);
    expect(container.querySelectorAll(".cost-brand")).toHaveLength(1);
    expect(container.querySelectorAll(".cost-brand-name")).toHaveLength(1);
  });
});
