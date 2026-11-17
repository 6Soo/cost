// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AppShell, type AppTrip } from "./AppShell";

afterEach(cleanup);

it("shows the newest eight actual trips even when bootstrap is oldest first", () => {
  const trips: AppTrip[] = [
    { id: "undated", title: "날짜 없음" },
    ...Array.from({ length: 10 }, (_, index) => ({
      id: `trip-${index + 1}`, title: `여행 ${index + 1}`,
      starts_on: `2026-${String(index + 1).padStart(2, "0")}-01`,
    })),
    { id: "quarter:2026-Q4", title: "분기 기타비용", starts_on: "2026-12-01" },
    { id: "other-quarter", title: "기타비용", kind: "quarter", starts_on: "2026-12-01" },
  ];
  const before = structuredClone(trips);
  render(<AppShell role="owner" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  const links = [...document.querySelectorAll(".cost-sidebar .cost-trip-link")];
  expect(links.map((link) => link.textContent)).toEqual(
    [10, 9, 8, 7, 6, 5, 4, 3].map((number) => `여행 ${number}`),
  );
  expect(links[0].getAttribute("href")).toBe("/board?tab=trip-10");
  expect(trips).toEqual(before);
});

it("preserves the viewer's allowed navigation including quarter ledgers", () => {
  const trips: AppTrip[] = [{ id: "quarter:2026-Q4", title: "허용된 분기", kind: "quarter" }];
  render(<AppShell role="viewer" trips={trips} path="/trips"><h1>여행</h1></AppShell>);
  expect(document.querySelector(".cost-sidebar .cost-trip-link")?.textContent).toBe("허용된 분기");
});
