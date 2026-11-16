import type { ReactNode } from "react";

type RecordValue = Record<string, unknown>;
type ResultField = { label: string; value: string };
type ResultColumn = { key: string; label: string };
type ResultSection = {
  title: string;
  columns: ResultColumn[];
  rows: Array<Record<string, string>>;
};

export type StructuredResultModel = {
  title: string;
  message: string;
  status: string;
  unavailable: boolean;
  summary: ResultField[];
  sections: ResultSection[];
};

function asRecord(value: unknown): RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue
    : {};
}

function asRows(value: unknown): RecordValue[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function text(value: unknown, empty = "—"): string {
  if (typeof value === "string") return value.trim() || empty;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => text(item, "")).filter(Boolean).join(", ") || empty;
  return empty;
}

function rowNumber(value: unknown): string {
  if (value == null || value === "") return "";
  const number = text(value, "");
  return /^\d+$/.test(number) ? `${number}행` : number;
}

function stateLabel(value: unknown): string {
  const key = text(value, "").toLowerCase();
  const labels: Record<string, string> = {
    linked: "연결됨",
    matched: "일치 후보 있음",
    ambiguous: "여러 후보 확인 필요",
    unmatched: "일치 후보 없음",
    source_unavailable: "원천 확인 필요",
    unverified: "확인 전",
    name_only: "이름만 확인",
    needs_check: "연결 확인 필요",
    confirmed: "확정",
    active: "사용 중",
    inactive: "중지됨",
    completed_or_expired: "계약 완료 또는 만료",
    pending: "확인 대기",
  };
  return labels[key] || (key ? text(value) : "—");
}

function count(value: unknown, suffix: string): string {
  return value == null || value === "" ? "—" : `${text(value)}${suffix}`;
}

function section(title: string, columns: ResultColumn[], rows: Array<Record<string, string>>): ResultSection {
  return { title, columns, rows };
}

function participantModel(data: RecordValue, summary: ResultField[], sections: ResultSection[]): void {
  const counts = asRecord(data.counts);
  const countLabels: Array<[string, string, string]> = [
    ["roster_confirmed", "확정 인원", "명"],
    ["linked", "수입 연결", "명"],
    ["name_only", "이름만 확인", "명"],
    ["needs_check", "연결 확인 대상", "명"],
    ["unlinked_income_rows", "미연결 수입 행", "건"],
    ["reviewed_income_rows", "검토 완료 수입 행", "건"],
    ["income_rows", "수입 행", "건"],
  ];
  for (const [key, label, suffix] of countLabels) {
    if (Object.prototype.hasOwnProperty.call(counts, key)) summary.push({ label, value: count(counts[key], suffix) });
  }

  const participants = asRows(data.participants);
  if (Array.isArray(data.participants)) {
    sections.push(section("참가자 명단", [
      { key: "participant", label: "참가자" },
      { key: "state", label: "대조 상태" },
      { key: "income", label: "연결 수입" },
      { key: "candidates", label: "후보" },
    ], participants.map((person) => {
      const links = asRows(person.links);
      const linkedIncome = links.map((link) => {
        const row = asRecord(link.row);
        const rowText = rowNumber(row.row ?? link.row_number ?? link.row_no);
        const name = text(row.name ?? link.name, "");
        const amount = text(row.amount ?? link.amount, "");
        return [rowText ? `수입 ${rowText}` : "수입", name, amount && `${amount}원`].filter(Boolean).join(" · ");
      }).filter(Boolean).join(" / ");
      const candidates = Array.isArray(person.candidate_refs) ? person.candidate_refs.length : 0;
      return {
        participant: text(person.display_name ?? person.name, "이름 미확인"),
        state: stateLabel(person.state),
        income: linkedIncome || "연결 없음",
        candidates: candidates ? `${candidates}건` : "없음",
      };
    })));
  }

  const incomeRows = Array.isArray(data.unlinked_income)
    ? asRows(data.unlinked_income)
    : asRows(data.income_rows);
  if (Array.isArray(data.unlinked_income) || Array.isArray(data.income_rows)) {
    sections.push(section("미연결 수입", [
      { key: "row", label: "행" },
      { key: "date", label: "날짜" },
      { key: "name", label: "입금자" },
      { key: "amount", label: "금액" },
      { key: "state", label: "상태" },
    ], incomeRows.map((income) => {
      const cells = asRecord(income.cells);
      return {
        row: rowNumber(income.row ?? income.row_number),
        date: text(income.date ?? cells.B),
        name: text(income.name, "이름 미확인"),
        amount: text(income.amount ?? cells.amount),
        state: stateLabel(income.state),
      };
    })));
  }

  const completion = asRecord(data.completion);
  if (typeof completion.complete === "boolean") {
    summary.push({ label: "대조 진행", value: completion.complete ? "완료" : "진행 중" });
  }
}

function insuranceModel(data: RecordValue, summary: ResultField[], sections: ResultSection[]): void {
  const counts = asRecord(data.counts);
  const countLabels: Array<[string, string]> = [
    ["contracts", "대조 계약"], ["rows", "대조 행"], ["matched", "일치 후보"],
    ["ambiguous", "여러 후보"], ["unmatched", "일치 후보 없음"], ["source_unavailable", "원천 확인 필요"],
  ];
  for (const [key, label] of countLabels) {
    if (Object.prototype.hasOwnProperty.call(counts, key)) summary.push({ label, value: count(counts[key], key === "contracts" ? "건" : "행") });
  }

  const contracts = asRows(data.contracts);
  if (Array.isArray(data.contracts)) {
    sections.push(section("보험 계약", [
      { key: "contract", label: "계약" },
      { key: "period", label: "여행 기간" },
      { key: "status", label: "보험 상태" },
      { key: "scope", label: "대조 범위" },
    ], contracts.map((contract, index) => ({
      contract: text(contract.contract_key, `계약 ${index + 1}`),
      period: [text(contract.travel_start, ""), text(contract.travel_end, "")].filter(Boolean).join(" ~ ") || "—",
      status: stateLabel(contract.insurance_status),
      scope: text(contract.scope_label),
    }))));
  }

  const matchRows = contracts.flatMap((contract) => asRows(contract.rows).map((row) => {
    const matches = asRows(row.matches).map((match) => {
      const trip = text(match.trip_name ?? match.trip, "");
      const date = text(match.date, "");
      const name = text(match.name ?? match.nickname, "");
      const amount = text(match.amount, "");
      return [trip, date, name, amount && `${amount}원`].filter(Boolean).join(" · ");
    }).filter(Boolean);
    return {
      contract: text(contract.contract_key),
      row: text(row.masked_name, "") || rowNumber(row.row ?? row.row_number) || "—",
      outcome: stateLabel(row.match_state),
      candidates: count(row.candidate_count, "명"),
      matches: matches.join(" / ") || "—",
    };
  }));
  if (contracts.some((contract) => Array.isArray(contract.rows))) {
    sections.push(section("이름 대조 결과", [
      { key: "contract", label: "계약" },
      { key: "row", label: "보험 명단" },
      { key: "outcome", label: "대조 상태" },
      { key: "candidates", label: "후보 수" },
      { key: "matches", label: "후보 수입(여행·날짜·이름·금액)" },
    ], matchRows));
  }
}

function reserveModel(path: string, data: RecordValue, summary: ResultField[], sections: ResultSection[]): void {
  const counts = asRecord(data.counts);
  if (path.endsWith("/state")) {
    summary.push({ label: "연결 설정", value: data.configured === false ? "미설정" : "설정됨" });
    if (data.link_version != null) summary.push({ label: "연결 버전", value: text(data.link_version) });
    if (data.link_revision != null) summary.push({ label: "수정 번호", value: text(data.link_revision) });
    if (Object.prototype.hasOwnProperty.call(counts, "links")) summary.push({ label: "저장된 연결", value: count(counts.links, "건") });
    return;
  }

  const countLabels: Array<[string, string]> = [
    ["persons", "예약자"],
    ["source_identifiers", "예약 식별자"],
    ["resolved_transactions", "연결 예약"],
    ["unlinked_identifiers", "미연결 식별자"],
  ];
  for (const [key, label] of countLabels) {
    if (Object.prototype.hasOwnProperty.call(counts, key)) summary.push({ label, value: count(counts[key], key === "persons" ? "명" : "건") });
  }
  if (typeof data.applicable === "boolean") {
    summary.push({ label: "적용 가능", value: data.applicable ? "가능" : "미연결 예약 확인 필요" });
  }
  const choiceNames = new Map(asRows(data.choices).map((choice) => [
    text(choice.tab_id, ""), text(choice.label ?? choice.title, ""),
  ]));

  if (Array.isArray(data.persons)) {
    sections.push(section("예약자", [
      { key: "name", label: "예약자" },
      { key: "active", label: "상태" },
      { key: "assignments", label: "예약 식별자" },
      { key: "connected", label: "연결된 여행" },
    ], asRows(data.persons).map((person) => ({
      name: text(person.display_name, "이름 미확인"),
      active: person.is_active === false ? "중지됨" : "사용 중",
      assignments: text(person.assignments),
      connected: Array.isArray(person.connected)
        ? person.connected.map((target) => {
          const row = asRecord(target);
          const tabId = text(row.tab_id ?? row.target_tab_id ?? target, "");
          return choiceNames.get(tabId) || tabId;
        }).filter(Boolean).join(", ") || "없음"
        : text(person.connected, "없음"),
    }))));
  }
  if (Array.isArray(data.resolved)) {
    sections.push(section("연결된 예약 식별자", [
      { key: "identifier", label: "예약 식별자" },
      { key: "trip", label: "연결 여행" },
      { key: "origin", label: "연결 근거" },
    ], asRows(data.resolved).map((item) => ({
      identifier: text(item.source_event_key ?? item.identifier),
      trip: text(item.target_tab_label, "") || choiceNames.get(text(item.target_tab_id, "")) || text(item.target_tab_id),
      origin: item.origin === "owner" ? "소유자가 지정한 연결" : text(item.origin),
    }))));
  }
  if (Array.isArray(data.unlinked)) {
    sections.push(section("미연결 예약 식별자", [
      { key: "identifier", label: "예약 식별자" },
      { key: "reason", label: "상태" },
    ], data.unlinked.map((value) => typeof value === "string" ? { source_event_key: value } : asRecord(value)).map((item) => ({
      identifier: text(item.source_event_key ?? item.identifier ?? item.code),
      reason: text(item.reason ?? item.message, "연결 대상 없음"),
    }))));
  }
}

export function buildStructuredResultModel(href: string, value: unknown): StructuredResultModel {
  const data = asRecord(value);
  const path = (() => {
    try { return new URL(href, "https://cost.invalid").pathname; }
    catch { return href.split("?", 1)[0]; }
  })();
  const summary: ResultField[] = [];
  const sections: ResultSection[] = [];
  let title = "조회 결과";

  if (path === "/api/participants/state") {
    title = "참가자 대조 결과";
    participantModel(data, summary, sections);
  } else if (path === "/api/participants/insurance-match") {
    title = "보험 대조 결과";
    insuranceModel(data, summary, sections);
  } else if (path === "/api/reserve-link/plan" || path === "/api/reserve-link/state") {
    title = path.endsWith("/state") ? "예약 연결 상태" : "예약 연결 계획 결과";
    reserveModel(path, data, summary, sections);
  }

  const unavailable = data.available === false || data.configured === false || data.readable === false;
  const status = unavailable ? "자료 연결 또는 원천 확인이 필요합니다." : "조회가 완료되었습니다.";
  const message = typeof data.message === "string" ? data.message : status;
  if (!summary.length) summary.push({ label: "조회 상태", value: status });
  return { title, message, status, unavailable, summary, sections };
}

function ResultTable({ section: table }: { section: ResultSection }) {
  return (
    <section className="e-feature-result-section" aria-label={table.title}>
      <h4>{table.title}</h4>
      {table.rows.length ? (
        <>
          <div className="e-feature-table-wrap" role="region" aria-label={`${table.title} 표`} tabIndex={0}>
            <table className="e-feature-table" aria-label={table.title}>
              <thead><tr>{table.columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
              <tbody>
                {table.rows.map((row, index) => (
                  <tr key={`${table.title}-${index}`}>
                    {table.columns.map((column) => (
                      <td key={column.key} className={/(amount|money|금액|합계)/i.test(`${column.key} ${column.label}`) ? "e-feature-money" : undefined}>
                        {row[column.key] || "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="e-feature-mobile-list" aria-label={`${table.title} 목록`}>
            {table.rows.map((row, index) => (
              <li className="e-feature-mobile-card" key={`${table.title}-mobile-${index}`}>
                {table.columns.map((column) => (
                  <div className="e-feature-mobile-line" key={column.key}>
                    <span>{column.label}</span>
                    <strong className={/(amount|money|금액|합계)/i.test(`${column.key} ${column.label}`) ? "e-feature-money" : undefined}>
                      {row[column.key] || "—"}
                    </strong>
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </>
      ) : <p className="e-feature-hint">현재 표시할 항목이 없습니다.</p>}
    </section>
  );
}

export function StructuredActionResult({ href, data }: { href: string; data: unknown }) {
  const model = buildStructuredResultModel(href, data);
  const statusRole = model.unavailable ? "alert" : "status";
  const children: ReactNode[] = [
    <h3 key="title">{model.title}</h3>,
    <p key="message" className={model.unavailable ? "e-feature-error" : "e-feature-status"} role={statusRole}>
      {model.message}
    </p>,
    <dl key="summary" className="e-feature-record-list">
      {model.summary.map((field) => (
        <div className="e-feature-record-line" key={field.label}>
          <dt>{field.label}</dt><dd>{field.value}</dd>
        </div>
      ))}
    </dl>,
    ...model.sections.map((table) => <ResultTable key={table.title} section={table} />),
  ];
  return <section className="cost-panel e-feature-action-result">{children}</section>;
}
