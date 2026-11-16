export type FeatureRoute = "home" | "trips" | "ledger" | "transactions" | "receipts" | "admin" | "auxiliary" | "missing";

export function featureRoute(path: string, search: URLSearchParams): FeatureRoute {
  if (path === "/" || path === "") return "home";
  if (path === "/trips") return "trips";
  if (path === "/board") return search.get("tab") === "refunds" ? "transactions" : "ledger";
  if (["/cards/all", "/ota", "/flight-passengers"].includes(path)) return "transactions";
  if (path === "/receipts") return "receipts";
  if (path.startsWith("/access/") || path === "/access" || path === "/google-ledger" || path === "/review") return "admin";
  if (["/participants", "/participants/insurance-match", "/reserve-links", "/export",
    "/expense", "/expense/new", "/income", "/income/new", "/rules"].includes(path)) return "auxiliary";
  return "missing";
}
