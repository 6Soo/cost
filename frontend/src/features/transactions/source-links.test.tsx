// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DataRows } from "./feature-ui";
afterEach(cleanup);
describe("existing authenticated source navigation", () => {
  it("opens the server-provided OTA detail without embedding legacy HTML", () => {
    render(<DataRows payload={{ title: "OTA", columns: [{key:"source_href",label:"예약 상세·교정(기존 화면)"}], rows:[{id:"demo",source_href:"/ota/booking?provider=agoda&ref=synthetic-ref"}],actions:[] }} />);
    expect(screen.getAllByRole("link",{name:"예약 상세·교정(기존 화면)"}).every(a=>a.getAttribute("href")==="/ota/booking?provider=agoda&ref=synthetic-ref")).toBe(true);
    expect(document.querySelector("iframe")).toBeNull();
  });
  it.each([
    ["/board?tab=refunds&kind=ex&page=2", "/board?tab=refunds&kind=ex&page=2"],
    ["/board?tab=refunds&row=card-demo", "/board?tab=refunds&row=card-demo&legacy=1"],
    ["/cards/all", "/cards/all?legacy=1"],
  ])("routes source %s to %s", (source_href, target) => {
    render(<DataRows payload={{
      title: "Source",
      columns: [{ key: "source_href", label: "Source" }],
      rows: [{ id: "demo", source_href }],
      actions: [],
    }} />);
    expect(screen.getAllByRole("link").map(link => link.getAttribute("href")))
      .toEqual(expect.arrayContaining([target]));
  });
  it.each(["https://example.invalid/ota/booking", "//example.invalid/board", "/api/receipts/workflow", "javascript:alert(1)"])("rejects non-source target %s", (href) => {
    render(<DataRows payload={{title:"OTA",columns:[{key:"source_href",label:"상세"}],rows:[{id:"demo",source_href:href}],actions:[]}} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(href)).toBeNull();
  });
});
