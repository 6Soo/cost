import { Component, StrictMode, Suspense, lazy, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./app/AppShell";
import { featureRoute } from "./app/routes";
import { ApiError, getJSON } from "./api/client";
import type { Bootstrap } from "./api/types";
import "./styles/index.css";

// Pages load per route so the first screen does not ship every tab's code.
const HomePage = lazy(() => import("./features/home").then((m) => ({ default: m.HomePage })));
const TripsPage = lazy(() => import("./features/trips").then((m) => ({ default: m.TripsPage })));
const LedgerPage = lazy(() => import("./features/ledger").then((m) => ({ default: m.LedgerPage })));
const TransactionsPage = lazy(() => import("./features/transactions").then((m) => ({ default: m.TransactionsPage })));
const ReceiptsPage = lazy(() => import("./features/receipts").then((m) => ({ default: m.ReceiptsPage })));
const AdminPage = lazy(() => import("./features/admin").then((m) => ({ default: m.AdminPage })));
const AuxiliaryPage = lazy(() => import("./features/auxiliary").then((m) => ({ default: m.AuxiliaryPage })));

function pageFor(path: string, bootstrap: Bootstrap, search: URLSearchParams) {
  const props = { bootstrap, path, search };
  switch (featureRoute(path, search)) {
    case "home": return <HomePage {...props} />;
    case "trips": return <TripsPage {...props} />;
    case "ledger": return <LedgerPage {...props} />;
    case "transactions": return <TransactionsPage {...props} />;
    case "receipts": return <ReceiptsPage {...props} />;
    case "admin": return <AdminPage {...props} />;
    case "auxiliary": return <AuxiliaryPage {...props} />;
    default: return <main className="cost-panel"><h1>화면을 찾을 수 없습니다</h1><p><a href="/trips">여행 목록으로 이동</a></p></main>;
  }
}

// A page chunk can fail to load (offline, stale deploy). Say so instead of unmounting the tree.
class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  componentDidCatch(): void {}
  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return <main className="cost-main"><section className="cost-panel" role="alert"><h1>화면을 열 수 없습니다</h1><p>화면을 불러오지 못했습니다. 새로 고침해 주세요.</p></section></main>;
    }
    return this.props.children;
  }
}

function RootApp() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = useMemo(() => window.location.pathname.replace(/^\/ui(?=\/|$)/, "") || "/", []);
  const search = useMemo(() => new URLSearchParams(window.location.search), []);
  useEffect(() => {
    getJSON<Bootstrap>("/api/plush/bootstrap").then(setBootstrap).catch((reason: unknown) => {
      setError(reason instanceof ApiError ? reason.message : "COST 화면을 불러오지 못했습니다.");
    });
  }, []);
  if (error) return <main className="cost-main"><section className="cost-panel" role="alert"><h1>화면을 열 수 없습니다</h1><p>{error}</p></section></main>;
  if (!bootstrap) return <main className="cost-main"><p role="status">COST 화면을 준비하는 중입니다…</p></main>;
  return <AppShell role={bootstrap.role} trips={bootstrap.trips} path={path} currentTripId={search.get("tab") || search.get("trip") || ""}><PageBoundary><Suspense fallback={<main className="cost-main"><p role="status">화면을 준비하는 중입니다…</p></main>}>{pageFor(path, bootstrap, search)}</Suspense></PageBoundary></AppShell>;
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("COST UI root element is missing");

createRoot(rootElement).render(
  <StrictMode>
    <RootApp />
  </StrictMode>,
);
