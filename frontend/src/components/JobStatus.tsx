export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";
export type JobStatusProps = {
  state: JobState;
  label?: string;
  message?: string;
  updatedAt?: string;
  completed?: number;
  total?: number;
  className?: string;
};

const defaultLabels: Record<JobState, string> = {
  queued: "대기 중",
  running: "처리 중",
  succeeded: "완료",
  failed: "실패",
  cancelled: "취소됨",
  unknown: "상태 확인 중",
};

function getProgress(completed?: number, total?: number): { now: number; max: number; percent: number } | undefined {
  if (!Number.isSafeInteger(completed) || !Number.isSafeInteger(total) || total === undefined || total <= 0 || completed === undefined || completed < 0 || completed > total) {
    return undefined;
  }
  return { now: completed, max: total, percent: Math.floor((completed / total) * 100) };
}

function formatUpdatedAt(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(timestamp);
}

export function JobStatus({ state, label, message, updatedAt, completed, total, className }: JobStatusProps) {
  const progress = getProgress(completed, total);
  const displayLabel = label ?? defaultLabels[state];
  return (
    <section className={`cost-job-status cost-job-status-${state}${className ? ` ${className}` : ""}`} data-state={state}>
      <div className="cost-job-status-heading">
        <span className="cost-job-status-indicator" aria-hidden="true" />
        <strong>{displayLabel}</strong>
      </div>
      {message && <p className="cost-job-status-message">{message}</p>}
      {progress && (
        <div className="cost-job-progress-row">
          <progress aria-label="작업 진행" value={progress.now} max={progress.max} />
          <span>{progress.percent}%</span>
        </div>
      )}
      {updatedAt && <p className="cost-job-updated"><time dateTime={updatedAt}>{formatUpdatedAt(updatedAt)}</time> 갱신</p>}
    </section>
  );
}
