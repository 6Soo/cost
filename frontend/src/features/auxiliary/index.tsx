import type { AuxiliaryResponse } from "../../api/types";
import { StructuredFeaturePage, type PageProps } from "../transactions/feature-ui";

const AUXILIARY_NAV = [
  { id: "participants", label: "참가자·수입", path: "/participants" },
  { id: "insurance", label: "보험 대조", path: "/participants/insurance-match" },
  { id: "reserve-links", label: "예약 연결", path: "/reserve-links" },
  { id: "expense-new", label: "수기 지출", path: "/expense/new" },
  { id: "income-new", label: "수기 수입", path: "/income/new" },
  { id: "export", label: "내보내기", path: "/export" },
  { id: "rules", label: "규칙 보조", path: "/rules" },
];

const TITLES: Record<string, string> = {
  participants: "참가자·수입 대조",
  insurance: "참가자·보험 대조",
  "reserve-links": "예약 연결",
  "expense-new": "수기 지출 추가",
  "income-new": "수기 수입 추가",
  export: "장부 내보내기",
  rules: "규칙 보조",
};

function selectedView(path: string, search: URLSearchParams) {
  if (path === "/participants/insurance-match") return "insurance";
  if (path === "/participants") return "participants";
  if (path === "/reserve-links") return "reserve-links";
  if (path === "/expense/new") return "expense-new";
  if (path === "/income/new") return "income-new";
  if (path === "/export") return "export";
  if (path === "/rules") return "rules";
  return search.get("view") || "participants";
}

function OwnerOnly() {
  return (
    <main className="e-feature-page">
      <section className="cost-panel e-feature-state" role="alert">
        <h1>이 보조 화면은 소유자 전용입니다</h1>
        <p>현재 계정에서 허용된 여행 화면을 열어 주세요.</p>
      </section>
    </main>
  );
}

export function AuxiliaryPage(props: PageProps) {
  const path = props.path.startsWith("/") ? props.path : `/${props.path}`;
  const view = selectedView(path, props.search);
  if (!Object.prototype.hasOwnProperty.call(TITLES, view)) {
    return (
      <main className="e-feature-page">
        <section className="cost-panel e-feature-state" role="alert">
          <h1>지원하지 않는 보조 화면입니다</h1>
          <p>보조 기능 탭에서 화면을 선택해 주세요.</p>
        </section>
      </main>
    );
  }
  if (props.bootstrap.role !== "owner") return <OwnerOnly />;

  const params = new URLSearchParams({ view });
  const trip = props.search.get("trip") || props.search.get("tab");
  if (trip) params.set("trip", trip);
  const endpoint = `/api/plush/auxiliary?${params.toString()}`;

  return (
    <StructuredFeaturePage
      bootstrap={props.bootstrap}
      endpoint={endpoint}
      pageTitle={TITLES[view]}
      nav={AUXILIARY_NAV}
      currentNav={view}
      readOnly={view === "insurance"}
      hideParticipantCreation={view === "participants"}
      hideClassificationDecisions={view === "rules"}
    />
  );
}

export type { AuxiliaryResponse };
