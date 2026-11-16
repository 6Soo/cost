import { describe, expect, it } from "vitest";
import { featureRoute } from "./routes";

describe("existing COST deep links", () => {
  it.each(["/participants/insurance-match", "/expense/new", "/income/new", "/rules", "/reserve-links", "/export"])(
    "keeps %s in its feature instead of silently opening home", (path) => {
      expect(featureRoute(path, new URLSearchParams())).toBe("auxiliary");
    },
  );
  it("distinguishes the refund board from a trip ledger", () => {
    expect(featureRoute("/board", new URLSearchParams("tab=refunds"))).toBe("transactions");
    expect(featureRoute("/board", new URLSearchParams("tab=trip-synthetic"))).toBe("ledger");
  });
  it("does not silently substitute a home page for an unknown URL", () => {
    expect(featureRoute("/unknown-screen", new URLSearchParams())).toBe("missing");
  });
});
