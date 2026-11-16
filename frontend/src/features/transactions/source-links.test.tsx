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
  it.each(["https://example.invalid/ota/booking", "//example.invalid/board", "/api/receipts/workflow", "javascript:alert(1)"])("rejects non-source target %s", (href) => {
    render(<DataRows payload={{title:"OTA",columns:[{key:"source_href",label:"상세"}],rows:[{id:"demo",source_href:href}],actions:[]}} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(href)).toBeNull();
  });
});
