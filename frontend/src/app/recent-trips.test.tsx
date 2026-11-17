// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AppShell, type AppTrip } from "./AppShell";

afterEach(cleanup);

it("restores the legacy earliest eight open trips and leaves bootstrap unchanged", () => {
  const trips: AppTrip[] = [
    { id: "undated", title: "날짜 없음" },
    ...Array.from({ length: 10 }, (_, index) => ({
      id: `trip-${index + 1}`, title: `여행 ${index + 1}`,
      starts_on: `2026-${String(index + 1).padStart(2, "0")}-01`,
    })).reverse(),
    { id: "previous", title: "이전 여행", starts_on: "2025-01-01", previous: true },
    { id: "closed", title: "마감 여행", starts_on: "2026-01-01", closed: true },
    { id: "archived", title: "보관 여행", starts_on: "2026-01-01", archived: true },
    { id: "quarter:2026-Q4", title: "분기 기타비용", starts_on: "2026-12-01" },
    { id: "other-quarter", title: "기타비용", kind: "quarter", starts_on: "2026-12-01" },
  ];
  const before = structuredClone(trips);
  render(<AppShell role="owner" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  const links = [...document.querySelectorAll(".cost-sidebar .cost-trip-link")];
  expect(links.map((link) => link.textContent)).toEqual(
    [1, 2, 3, 4, 5, 6, 7, 8].map((number) => `여행 ${number}`),
  );
  expect(links[0].getAttribute("href")).toBe("/board?tab=trip-1");
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

it("keeps the current closed archived previous trip as in the legacy sidebar", () => {
  const trips: AppTrip[] = [
    { id: "open", title: "진행 여행", starts_on: "2026-07-01" },
    { id: "past", title: "열어 둔 여행", starts_on: "2026-01-01", previous: true, closed: true, archived: true },
  ];
  render(<AppShell role="owner" trips={trips} path="/board" currentTripId="past"><h1>장부</h1></AppShell>);
  expect([...document.querySelectorAll(".cost-sidebar .cost-trip-link")].map(n => n.textContent))
    .toEqual(["열어 둔 여행", "진행 여행"]);
});

it("preserves the viewer's allowed navigation including quarter ledgers", () => {
  const trips: AppTrip[] = [{ id: "quarter:2026-Q4", title: "허용된 분기", kind: "quarter" }];
  render(<AppShell role="viewer" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  expect(document.querySelector(".cost-sidebar .cost-trip-link")?.textContent).toBe("허용된 분기");
});
