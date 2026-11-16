import type { AdminResponse } from "../../api/types";
import { StructuredFeaturePage, type PageProps } from "../transactions/feature-ui";

const ADMIN_NAV = [
  { id: "accounts", label: "계정·권한", path: "/access/admin", query: { view: "accounts" } },
  { id: "profile", label: "기본 정보", path: "/access/admin", query: { view: "profile" } },
  { id: "google", label: "Google 장부", path: "/google-ledger" },
  { id: "review", label: "AI 검수 결과", path: "/review" },
];

function selectedView(path: string, search: URLSearchParams) {
  if (path === "/google-ledger") return "google";
  if (path === "/review") return "review";
  if (path === "/access/admin/profile") return "profile";
  return search.get("view") || "accounts";
}

function safeQuery(value: string | null) {
  return value && value.length <= 160 ? value : "";
}

function OwnerOnly() {
  return (
    <main className="e-feature-page">
      <section className="cost-panel e-feature-state" role="alert">
        <h1>관리 화면은 소유자 전용입니다</h1>
        <p>현재 계정에서 사용할 수 있는 관리 기능이 없습니다.</p>
      </section>
    </main>
  );
}

export function AdminPage(props: PageProps) {
  const path = props.path.startsWith("/") ? props.path : `/${props.path}`;
  const view = selectedView(path, props.search);
  const supported = new Set(["accounts", "profile", "google", "review"]);
  if (!supported.has(view)) {
    return (
      <main className="e-feature-page">
        <section className="cost-panel e-feature-state" role="alert">
          <h1>지원하지 않는 관리 화면입니다</h1>
          <p>관리 탭을 선택해 주세요.</p>
        </section>
      </main>
    );
  }

  // The current /api/plush/admin projection is owner-only for every view.
  // Keep direct viewer URLs from issuing a request the server will forbid.
  if (props.bootstrap.role !== "owner") return <OwnerOnly />;

  const params = new URLSearchParams({ view });
  const trip = safeQuery(props.search.get("trip") || props.search.get("tab"));
  if (trip) params.set("trip", trip);
  const endpoint = `/api/plush/admin?${params.toString()}`;
  return (
    <StructuredFeaturePage
      bootstrap={props.bootstrap}
      endpoint={endpoint}
      pageTitle={view === "google" ? "Google 장부 비교·복사" : view === "review" ? "AI 분기 검수 결과" : view === "profile" ? "기본 정보" : "계정·권한"}
      nav={ADMIN_NAV}
      currentNav={view}
      readOnly={view === "review"}
      hideReviewWrites={view === "review"}
    />
  );
}

export type { AdminResponse };
