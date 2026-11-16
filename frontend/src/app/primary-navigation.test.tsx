// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuxiliaryLinksPage } from "../features/auxiliary/links";
import type { Bootstrap } from "../api/types";
import { AppShell } from "./AppShell";
import { FeatureNav, DataRows } from "../features/transactions/feature-ui";
import { queryForSearch } from "../features/transactions";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("canonical existing URLs", () => {
  it("keeps participant linking mode in the bookmark after selecting a trip", async () => {
    window.history.replaceState(null,"","/participants");
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({participants:[],income_rows:[],configured:false}),{headers:{"content-type":"application/json"}})));
    const trips=["a","b"].map(id=>({id:`trip-${id}`,title:`Synthetic ${id}`,kind:"trip" as const,previous:false,starts_on:"2026-11-10",ends_on:"2026-11-20",income:"0",expense:"0",profit:"0",closed:false,archived:false}));
    const bootstrap:Bootstrap={role:"owner",csrf:"synthetic",trips,capabilities:[],receipt_enabled:false};
    render(<AuxiliaryLinksPage bootstrap={bootstrap} path="/participants" search={new URLSearchParams()} nav={[]} view="participants"/>);
    fireEvent.change(screen.getByRole("combobox",{name:"대조 여행 선택"}),{target:{value:"trip-b"}});
    expect(window.location.pathname).toBe("/participants");
    expect(new URLSearchParams(window.location.search).get("trip")).toBe("trip-b");
    expect(new URLSearchParams(window.location.search).get("view")).toBe("links");
  });
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
