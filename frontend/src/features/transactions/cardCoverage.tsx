import { useResource } from "./feature-ui";

const SUMMARY_URL = "/api/cards/coverage/summary";
const BATCH_ID = /^batch-[a-f0-9]{24}$/;
const FILE_STATUS: Record<string, string> = {
  parsed: "원본 저장됨",
  uploaded: "원본 저장됨",
  classified: "거래 분류됨",
  failed: "파일 읽기 오류",
  error: "파일 읽기 오류",
  queued: "업로드 중",
  processing: "파일 읽는 중",
};

type CoveragePeriod = { start?: string; end?: string };
type CoverageFile = {
  batch_id?: string;
  filename?: string;
  status?: string;
  source_rows?: number;
  unique_transactions?: number;
  transaction_start?: string;
  transaction_end?: string;
  issuer_hint?: string;
  coverage_status?: string;
};
type CoverageCard = {
  card_id?: string;
  issuer?: string;
  date_basis?: string;
  identity_scope?: string;
  periods?: CoveragePeriod[];
  gaps?: CoveragePeriod[];
  files?: CoverageFile[];
};
type CardCoverageSummary = {
  available?: boolean;
  coverage_state?: string;
  cards?: CoverageCard[];
  files?: CoverageFile[];
};

type CardCoverageProps = { search: URLSearchParams };

function dateRange(period: CoveragePeriod): string {
  return `${period.start ?? ""} ~ ${period.end ?? ""}`;
}

function fileStatus(status: string | undefined): string {
  return FILE_STATUS[status ?? ""] ?? "파일 정보";
}

function fileDetail(file: CoverageFile): string {
  const parts = [
    file.issuer_hint,
    file.transaction_start
      ? `거래일자: ${file.transaction_start} ~ ${file.transaction_end ?? ""}`
      : "거래일자 없음",
    `${file.unique_transactions ?? 0}건`,
    file.source_rows !== undefined && file.source_rows !== file.unique_transactions
      ? `원천 ${file.source_rows}행`
      : undefined,
    /^(failed|error|queued|processing)$/.test(file.status ?? "") ? fileStatus(file.status) : undefined,
  ].filter((part): part is string => Boolean(part));
  return parts.join(" · ");
}

function UploadAction({ action }: { action: string }) {
  return (
    <a className="cost-button cost-button-secondary" href={action}>
      이 기간 업로드
    </a>
  );
}

function Gap({ card, gap, index }: { card: CoverageCard; gap: CoveragePeriod; index: number }) {
  const params = new URLSearchParams();
  params.set("gap_card", card.card_id ?? "");
  params.set("gap_start", gap.start ?? "");
  params.set("gap_end", gap.end ?? "");
  params.set("gap_issuer", card.issuer ?? "");
  params.set("gap_basis", card.date_basis ?? "");
  return (
    <p key={`${card.card_id ?? card.issuer ?? "card"}-${index}`}>
      <span className="e-feature-hint">
        비어 있는 기간 {gap.start ?? ""} ~ {gap.end ?? ""}
      </span>{" "}
      <UploadAction action={`/cards/all?legacy=1&panel=upload&${params.toString()}`} />
    </p>
  );
}

function CardRow({ card }: { card: CoverageCard }) {
  const gaps = card.gaps ?? [];
  const periods = card.periods ?? [];
  const cardName = card.issuer || "카드사 미상";
  return (
    <section className="cost-panel" aria-label={`${cardName} 수집 기간`}>
      <header className="e-feature-header">
        <div>
          <h3>{cardName}</h3>
          {card.identity_scope === "source_file" ? (
            <span className="e-feature-hint">
              {(card.files?.[0]?.filename) || "카드사를 식별하지 못한 파일"}
            </span>
          ) : null}
        </div>
        <span className="e-feature-hint">{gaps.length ? `빈 기간 ${gaps.length}곳` : "기간 사이 공백 없음"}</span>
      </header>
      {gaps.map((gap, gapIndex) => (
        <Gap card={card} gap={gap} index={gapIndex} key={`${card.card_id ?? card.issuer ?? "card"}-${gapIndex}`} />
      ))}
      {periods.length ? (
        <>
          <p className="e-feature-hint">수집된 기간{periods.length > 6 ? ` ${periods.length}개` : ""}</p>
          <ul className="e-feature-record-list">
            {periods.map((period, periodIndex) => (
              <li key={`${period.start ?? ""}-${period.end ?? ""}-${periodIndex}`}>
                {dateRange(period)}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

function CoverageFiles({ files, search }: { files: CoverageFile[]; search: URLSearchParams }) {
  const pending = files.filter((file) => file.coverage_status === "no_transaction_dates");
  const dated = files.filter((file) => file.coverage_status !== "no_transaction_dates");

  const batchLink = (file: CoverageFile) => {
    if (!BATCH_ID.test(file.batch_id ?? "")) return null;
    const params = new URLSearchParams(search);
    params.set("legacy", "1");
    params.set("panel", "upload");
    params.set("batch", file.batch_id ?? "");
    params.delete("review");
    return (
      <a
        className="e-feature-hint"
        href={`/cards/all?${params.toString()}`}
        aria-label={(file.filename || "이름 없는 원본") + " 처리 결과"}
      >
        처리 결과
      </a>
    );
  };

  if (!pending.length && !dated.length) return null;
  return (
    <>
      {pending.length ? (
        <section className="cost-panel" aria-label="기간을 확인할 수 없는 파일">
          <h3>기간을 확인할 수 없는 파일 {pending.length}개</h3>
          <p className="e-feature-hint">
            거래가 없거나 거래일자를 읽지 못한 파일입니다. 처리 결과를 확인해 주세요. 이 파일은 기간 계산에 포함되지
            않습니다.
          </p>
          <ul className="e-feature-record-list">
            {pending.map((file, index) => (
              <li className="e-feature-record-line" key={`${file.filename ?? "file"}-${index}`}>
                <strong>{file.filename || "이름 없는 원본"}</strong>
                <span className="e-feature-hint">{file.issuer_hint || "카드사 식별 정보 없음"}</span>
                {batchLink(file)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {dated.length ? (
        <details className="cost-panel">
          <summary className="e-feature-hint">업로드 파일 {dated.length}개</summary>
          <dl className="e-feature-record-list">
            {dated.map((file, index) => (
              <div className="e-feature-record-line" key={`${file.filename ?? "file"}-${index}`}>
                <dt>{file.filename || "이름 없는 원본"}</dt>
                <dd className="e-feature-hint">{fileDetail(file)}</dd>
                {batchLink(file)}
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </>
  );
}

function CoverageSummary({ data, search }: { data: CardCoverageSummary; search: URLSearchParams }) {
  if (!data.available) {
    return (
      <p className="e-feature-error" role="alert">
        수집 기간을 불러올 수 없습니다. 카드 파일 업로드는 계속할 수 있습니다.{" "}
        <a className="cost-button cost-button-secondary" href="/cards/all?legacy=1&panel=upload">
          카드 파일 업로드
        </a>
      </p>
    );
  }
  if (data.coverage_state === "needs_transactions" && (data.files?.length ?? 0) > 0) {
    return (
      <p className="e-feature-hint">
        파일에서 거래일자를 찾지 못했습니다. 아래 업로드 파일의 처리 결과를 확인해 주세요.
      </p>
    );
  }
  const cards = [...(data.cards ?? [])].sort(
    (a, b) => Number(Boolean((b.gaps ?? []).length)) - Number(Boolean((a.gaps ?? []).length)),
  );
  return (
    <>
      {cards.map((card, index) => (
        <CardRow card={card} key={`${card.card_id ?? card.issuer ?? "unknown"}-${index}`} />
      ))}
      <CoverageFiles files={data.files ?? []} search={search} />
      {cards.length > 0 ? (
        <p className="e-feature-hint">
          각 파일의 첫 거래일부터 마지막 거래일까지를 수집된 기간으로 봅니다. 한 파일 안의 거래 없는 날은 공백으로
          세지 않습니다.
        </p>
      ) : null}
      {cards.length === 0 && (data.files?.length ?? 0) === 0 ? (
        <p className="e-feature-hint">
          거래일자가 있는 카드 자료가 없습니다. 카드 내역 파일을 업로드하면 공백을 계산할 수 있습니다.
        </p>
      ) : null}
    </>
  );
}

export function CardCoverage({ search }: CardCoverageProps) {
  const { state, reload } = useResource<CardCoverageSummary>(SUMMARY_URL);
  return (
    <section className="cost-panel e-feature-state" aria-labelledby="card-coverage-heading">
      <header className="e-feature-header">
        <div>
          <p className="e-feature-eyebrow">COST · 카드</p>
          <h2 id="card-coverage-heading">수집 현황</h2>
          <p>카드사별 수집 기간을 확인하고, 빈 기간의 자료를 업로드하세요.</p>
        </div>
        <button type="button" className="cost-button cost-button-quiet" onClick={reload}>
          새로고침
        </button>
      </header>
      {state.kind === "loading" ? (
        <p className="e-feature-loading" role="status">
          수집 현황을 불러오는 중입니다…
        </p>
      ) : null}
      {state.kind === "error" ? (
        <div className="e-feature-error" role="alert">
          <p>{state.message} 다시 확인해 주세요.</p>
          <button type="button" className="cost-button cost-button-secondary" onClick={reload}>
            수집 현황 다시 불러오기
          </button>
        </div>
      ) : null}
      {state.kind === "ready" ? <CoverageSummary data={state.payload} search={search} /> : null}
    </section>
  );
}

export type { CardCoverageProps, CardCoverageSummary, CoverageCard, CoverageFile };
