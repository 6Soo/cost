// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AppShell, type AppTrip } from "./AppShell";

afterEach(cleanup);

// The owner retired the recent/open/eight-item contract on 2026-11-17.
it("lists every unarchived trip including previous and closed trips without changing bootstrap", () => {
  const trips: AppTrip[] = [
    { id: "undated", title: "날짜 없음" },
    ...Array.from({ length: 10 }, (_, index) => ({
      id: `trip-${index + 1}`, title: `여행 ${index + 1}`,
      starts_on: `2026-${String(index + 1).padStart(2, "0")}-01`,
    })).reverse(),
    { id: "previous", title: "이전 여행", starts_on: "2025-01-01", previous: true },
    { id: "closed", title: "마감 여행", starts_on: "2025-12-01", closed: true },
    { id: "archived", title: "보관 여행", starts_on: "2026-01-01", archived: true },
    { id: "quarter:2026-Q4", title: "분기 기타비용", starts_on: "2026-12-01" },
    { id: "other-quarter", title: "기타비용", kind: "quarter", starts_on: "2026-12-01" },
  ];
  const before = structuredClone(trips);
  render(<AppShell role="owner" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  const links = [...document.querySelectorAll(".cost-sidebar .cost-trip-link")];
  expect(links.map((link) => link.textContent)).toEqual(
    ["이전 여행", "마감 여행", ...Array.from({ length: 10 }, (_, index) => `여행 ${index + 1}`), "날짜 없음"],
  );
  expect(links[0].getAttribute("href")).toBe("/board?tab=previous");
  expect([...document.querySelectorAll(".cost-trip-switcher-panel .cost-trip-link")].map(link => link.textContent))
    .toEqual(links.map(link => link.textContent));
  expect(trips).toEqual(before);
});

it("uses legacy display_key ties rather than renamed titles, and dates before undated trips", () => {
  const trips: AppTrip[] = [
    { id: "undated", title: "날짜 없음", starts_on: "" },
    { id: "b", title: "가 표시명", display_key: "0701_B", starts_on: "2026-07-01" },
    { id: "a", title: "나 표시명", display_key: "0701_A", starts_on: "2026-07-01" },
  ];
  render(<AppShell role="owner" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  expect([...document.querySelectorAll(".cost-sidebar .cost-trip-link")].map(n => n.textContent))
    .toEqual(["나 표시명", "가 표시명", "날짜 없음"]);
});

it("excludes an archived trip even when its ledger is currently open", () => {
  const trips: AppTrip[] = [
    { id: "open", title: "진행 여행", starts_on: "2026-07-01" },
    { id: "past", title: "열어 둔 여행", starts_on: "2026-01-01", previous: true, closed: true, archived: true },
  ];
  render(<AppShell role="owner" trips={trips} path="/board" currentTripId="past"><h1>장부</h1></AppShell>);
  expect([...document.querySelectorAll(".cost-sidebar .cost-trip-link")].map(n => n.textContent))
    .toEqual(["진행 여행"]);
});

it("preserves the viewer's allowed navigation including quarter ledgers", () => {
  const trips: AppTrip[] = [{ id: "quarter:2026-Q4", title: "허용된 분기", kind: "quarter" }];
  render(<AppShell role="viewer" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  expect(document.querySelector(".cost-sidebar .cost-trip-link")?.textContent).toBe("허용된 분기");
});

it("shows all permitted viewer trips in date order without an eight-item cap", () => {
  const trips: AppTrip[] = Array.from({ length: 14 }, (_, i) => ({
    id: `allowed-${i}`, title: `허용 ${i}`, starts_on: `2026-01-${String(i + 1).padStart(2, "0")}`,
  })).reverse();
  trips.push({ id: "archived", title: "보관", archived: true });
  render(<AppShell role="viewer" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  const expected = Array.from({ length: 14 }, (_, i) => `허용 ${i}`);
  for (const selector of [".cost-sidebar", ".cost-trip-switcher-panel", ".cost-tablet-menu-panel"]) {
    expect([...document.querySelectorAll(`${selector} .cost-trip-link`)].map(link => link.textContent)).toEqual(expected);
  }
});
