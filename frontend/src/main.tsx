import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./app/AppShell";
import { featureRoute } from "./app/routes";
import { ApiError, getJSON } from "./api/client";
import type { Bootstrap } from "./api/types";
import { HomePage } from "./features/home";
import { TripsPage } from "./features/trips";
import { LedgerPage } from "./features/ledger";
import { TransactionsPage } from "./features/transactions";
import { ReceiptsPage } from "./features/receipts";
import { AdminPage } from "./features/admin";
import { AuxiliaryPage } from "./features/auxiliary";
import "./styles/index.css";

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
  return <AppShell role={bootstrap.role} trips={bootstrap.trips} path={path}>{pageFor(path, bootstrap, search)}</AppShell>;
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("COST UI root element is missing");

createRoot(rootElement).render(
  <StrictMode>
    <RootApp />
  </StrictMode>,
);
