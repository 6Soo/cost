// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { endpointFor, queryForPage, queryForSearch } from "./index";

describe("transaction source query contracts", () => {
  it.each([
    ["refunds", "/board", { kind: "ex" }],
    ["ota", "/ota", { month: "2026-11", provider: "synthetic-provider", state: "unassigned", sort: "desc" }],
    ["flights", "/flight-passengers", { trip: "synthetic-trip", tab: "synthetic-tab" }],
  ])("keeps %s source filters on reads, paging and search", (view, path, filters) => {
    const query = new URLSearchParams({ ...filters, q: "old", page: "2", private_key: "never-forward" } as Record<string,string>);
    const urls = [endpointFor(view, query), queryForPage(path, view, query, 3, 50), queryForSearch(path, view, query, 50, "new")];
    for (const href of urls) {
      const actual = new URL(href, "http://localhost").searchParams;
      for (const [key,value] of Object.entries(filters)) expect(actual.get(key)).toBe(value);
      expect(actual.has("private_key")).toBe(false);
    }
    expect(new URL(urls[2], "http://localhost").searchParams.get("page")).toBe("1");
    expect(new URL(urls[2], "http://localhost").searchParams.get("q")).toBe("new");
  });
});
