// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

afterEach(() => {
  cleanup();
  document.documentElement.classList.remove("dark");
  window.localStorage.removeItem("cost-theme");
});

const trips = [{ id: "trip-a", title: "합성 여행" }];

function renderShell(path = "/trips") {
  return render(
    <AppShell role="owner" trips={trips} path={path}>
      <h1>합성 본문</h1>
    </AppShell>,
  );
}

describe("Plush UI audit regressions", () => {
  it("replaces decorative nav marks with meaningful aria-hidden SVG icons", () => {
    renderShell();
    const navLinks = document.querySelectorAll(".cost-nav-link");
    expect(navLinks.length).toBeGreaterThan(0);
    for (const link of navLinks) {
      const svg = link.querySelector("svg");
      expect(svg).not.toBeNull();
      expect(svg?.getAttribute("aria-hidden")).toBe("true");
    }
    const bottomLinks = document.querySelectorAll(".cost-bottom-link");
    expect(bottomLinks.length).toBeGreaterThan(0);
    for (const link of bottomLinks) {
      expect(link.querySelector("svg")).not.toBeNull();
    }
    for (const link of document.querySelectorAll(".cost-trip-link")) {
      expect(link.querySelector("svg")).not.toBeNull();
    }
    expect(document.querySelectorAll(".cost-nav-mark").length).toBe(0);
    expect(document.querySelectorAll(".cost-trip-mark").length).toBe(0);
    expect(document.querySelectorAll(".cost-theme-dot").length).toBe(0);
  });

  it("keeps navigation labels, hrefs and aria-current alongside the icons", () => {
    renderShell("/trips");
    for (const label of ["홈", "여행", "거래", "영수증", "계정·권한", "Google 장부", "검수 결과"]) {
      expect(screen.getAllByRole("link", { name: label }).length).toBeGreaterThan(0);
    }
    const active = screen.getAllByRole("link", { name: "여행" }).filter((link) => link.getAttribute("aria-current") === "page");
    expect(active.length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "합성 여행" }).length).toBeGreaterThan(0);
  });

  it("gives the trip switcher and theme toggle accessible names with icons", () => {
    renderShell();
    // The label lives on the summary (aria-label) so the control stays named on
    // mobile where the visible .cost-topbar-label span is display:none.
    const switcher = document.querySelector("details.cost-trip-switcher");
    expect(switcher).not.toBeNull();
    const summary = switcher!.querySelector("summary")!;
    expect(summary.getAttribute("aria-label")).toBe("여행 전환");
    expect(summary.textContent).toContain("여행 전환");
    expect(summary.querySelector("svg")).not.toBeNull();
    const themeButtons = screen.getAllByRole("button", { name: /모드로 전환/ });
    expect(themeButtons.length).toBeGreaterThan(0);
    for (const button of themeButtons) {
      expect(button.querySelector("svg")).not.toBeNull();
    }
  });

  it("closes the trip switcher popover on Escape and restores focus to its summary", () => {
    renderShell();
    const details = document.querySelector("details.cost-trip-switcher") as HTMLDetailsElement;
    details.open = true;
    fireEvent.keyDown(document, { key: "Escape" });
    expect(details.open).toBe(false);
    expect(document.activeElement).toBe(details.querySelector("summary"));
  });

  it("closes the trip switcher popover on an outside pointer press", () => {
    renderShell();
    const details = document.querySelector("details.cost-trip-switcher") as HTMLDetailsElement;
    details.open = true;
    fireEvent.pointerDown(document.body);
    expect(details.open).toBe(false);
  });

  it("keeps the trip switcher open when pressing inside its panel", () => {
    renderShell();
    const details = document.querySelector("details.cost-trip-switcher") as HTMLDetailsElement;
    details.open = true;
    const panelLink = details.querySelector(".cost-trip-link") as HTMLElement;
    fireEvent.pointerDown(panelLink);
    expect(details.open).toBe(true);
  });

  it("closes the bottom more popover on Escape", () => {
    renderShell();
    const details = document.querySelector("details.cost-bottom-more") as HTMLDetailsElement;
    details.open = true;
    fireEvent.keyDown(document, { key: "Escape" });
    expect(details.open).toBe(false);
  });

  it("does not leave shell popover listeners attached after unmount", () => {
    const { unmount } = renderShell();
    const details = document.querySelector("details.cost-trip-switcher") as HTMLDetailsElement;
    unmount();
    // After unmount the document-level Escape handler must be gone: a stale handler
    // would throw on the removed shell ref. Dispatching must be a no-op.
    expect(() => fireEvent.keyDown(document, { key: "Escape" })).not.toThrow();
    expect(details.open).toBe(false);
  });
});
