// @vitest-environment jsdom
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HomePage } from "./index";
import type { Bootstrap, TripSummary } from "../../api/types";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("replaces recent cards with every unarchived trip in start order after the home response", async () => {
  const trips: TripSummary[] = Array.from({ length: 14 }, (_, i) => ({
    id: `trip-${i}`, title: `여행 ${i}`, kind: "trip", previous: i < 5,
    starts_on: `2026-01-${String(i + 1).padStart(2, "0")}`, ends_on: "2026-02-01",
    income: "0", expense: "0", profit: "0", closed: i < 8, archived: false,
  }));
  const excluded: TripSummary[] = [
    { ...trips[0], id: "archived", title: "보관 여행", archived: true },
    { ...trips[0], id: "quarter:2026-Q1", title: "분기", kind: "quarter" },
  ];
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    trips: [...trips].reverse().concat(excluded), jobs: [], updated_at: "2026-11-17T00:00:00Z",
  }), { headers: { "Content-Type": "application/json" } })));
  const bootstrap: Bootstrap = { role: "owner", csrf: "synthetic", trips: [], capabilities: [], receipt_enabled: false };
  render(<HomePage bootstrap={bootstrap} path="/" search={new URLSearchParams()} />);
  await waitFor(() => expect(document.querySelectorAll(".cost-home__trip-card").length).toBe(14));
  expect([...document.querySelectorAll(".cost-home__trip-card strong")].map(node => node.textContent))
    .toEqual(trips.map(trip => trip.title));
  expect(document.querySelector("#cost-home-trips-title")?.textContent).toBe("여행 목록");
});
