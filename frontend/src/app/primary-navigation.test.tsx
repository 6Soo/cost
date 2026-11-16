// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";
import { FeatureNav, DataRows } from "../features/transactions/feature-ui";
import { queryForSearch } from "../features/transactions";

afterEach(cleanup);

describe("canonical existing URLs", () => {
  it("keeps desktop/mobile navigation and encoded trip links on existing addresses", () => {
    render(<AppShell role="owner" trips={[{id:"trip a&b",title:"합성 여행"}]} path="/trips"><h1>합성</h1></AppShell>);
    const links = screen.getAllByRole("link").map(link=>link.getAttribute("href"));
    expect(links).toContain("/");
    expect(links).toContain("/trips");
    expect(links).toContain("/cards/all");
    expect(links).toContain("/receipts");
    expect(links).toContain("/board?tab=trip%20a%26b");
    expect(links.some(href=>href?.startsWith("/ui"))).toBe(false);
  });
  it("keeps feature tabs, search and refund state at canonical URLs", () => {
    render(<FeatureNav label="업무" items={[{id:"refunds",label:"환불",path:"/board",query:{tab:"refunds"}}]} current="refunds"/>);
    expect(screen.getByRole("link",{name:"환불"}).getAttribute("href")).toBe("/board?tab=refunds");
    const href=queryForSearch("/cards/all","cards",new URLSearchParams(),50,"합성 검색");
    expect(href.startsWith("/cards/all?")).toBe(true);
    expect(new URL(href,"http://localhost").searchParams.get("q")).toBe("합성 검색");
  });
  it("keeps detailed legacy correction links distinct from the primary refund screen", () => {
    render(<DataRows payload={{title:"환불",columns:[{key:"source_href",label:"상세 교정"}],rows:[{id:"demo",source_href:"/board?tab=refunds&row=demo"}],actions:[]}}/>);
    expect(screen.getAllByRole("link",{name:"상세 교정"}).every(link=>new URL(link.getAttribute("href")!,"http://localhost").searchParams.get("legacy")==="1")).toBe(true);
  });
});
