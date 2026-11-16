// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StructuredFeaturePage } from "./feature-ui";
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it("shows pending application context alongside existing accounts", async()=>{
 vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({title:"계정·권한",columns:[{key:"display_name",label:"이름"}],rows:[{user_id:"synthetic-existing",display_name:"합성 기존 계정"}],data:{pending_applications:[{application_id:"synthetic-application",requested_name:"합성 신청자",nickname:"합성 별명",user_id:"synthetic-pending",status:"pending"}]},actions:[]}),{headers:{"Content-Type":"application/json"}})));
 render(<StructuredFeaturePage bootstrap={{role:"owner",csrf:"synthetic",trips:[],capabilities:[],receipt_enabled:false}} endpoint="/api/plush/admin?view=accounts" pageTitle="계정·권한" />);
 expect(await screen.findByRole("heading",{name:"접근 신청"})).toBeTruthy();
 expect(screen.getAllByText("합성 기존 계정").length).toBeGreaterThan(0);
 expect(screen.getAllByText("합성 신청자").length).toBeGreaterThan(0);
});
