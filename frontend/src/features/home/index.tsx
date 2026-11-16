import { useEffect, useState } from 'react';
import type { Bootstrap, JobSummary, TripSummary } from '../../api/types';
import { Amount, EmptyState, InlineNotice, JobStatus, Loading } from '../../components';
import { getJSON, ApiError } from '../../api/client';
import { humanDate } from '../ledger/urlState';
import './home.css';

type HomePayload = {
  trips: TripSummary[];
  jobs: JobSummary[];
  updated_at: string;
};

type PageProps = {
  bootstrap: Bootstrap;
  path: string;
  search: URLSearchParams;
};

function tripHref(id: string): string {
  return `/ui/board?${new URLSearchParams({ tab: id }).toString()}`;
}

function tripState(trip: TripSummary & { kind?: 'trip' | 'quarter' }): string {
  if (trip.kind === 'quarter' || trip.id.startsWith('quarter:')) return '분기 기타비용';
  if (trip.archived) return '보관';
  return trip.closed ? '마감' : '진행 중';
}

function isInternalHref(value?: string): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return null;
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : null;
  } catch {
    return null;
  }
}

export function HomePage({ bootstrap }: PageProps) {
  const [data, setData] = useState<HomePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getJSON<HomePayload>('/api/plush/home', controller.signal)
      .then((payload) => setData(payload))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof ApiError ? reason.message : '정산 현황을 불러오지 못했습니다. 연결 상태를 확인해 주세요.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const trips = (data?.trips ?? bootstrap.trips)
    .slice()
    .sort((a, b) => b.starts_on.localeCompare(a.starts_on))
    .slice(0, 6);

  return (
    <main className="cost-home">
      <header className="cost-home__header">
        <div>
          <p className="cost-eyebrow">COST · 정산</p>
          <h1>정산 현황</h1>
            <p className="cost-home__updated">
            {data?.updated_at ? `마지막 갱신 ${new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(data.updated_at))}` : '여행별 손익과 실제 자동화 실행 상태'}
          </p>
        </div>
        <a className="cost-home__all-trips" href="/ui/trips">여행 전체 보기</a>
      </header>

      {error && <InlineNotice tone="error" title="정산 현황을 불러오지 못했습니다">{error}</InlineNotice>}

      <section className="cost-home__section" aria-labelledby="cost-home-trips-title">
        <div className="cost-section-heading">
          <div>
            <p className="cost-eyebrow">여행별 손익</p>
            <h2 id="cost-home-trips-title">최근 여행</h2>
          </div>
          <a href="/ui/trips">모든 여행</a>
        </div>
        {loading && !data ? <Loading label="여행 현황 불러오는 중" /> : trips.length ? (
          <div className="cost-home__trip-grid">
            {trips.map((trip) => (
              <a className="cost-home__trip-card" href={tripHref(trip.id)} key={trip.id}>
                <span className="cost-home__trip-status">{tripState(trip)}</span>
                <strong title={trip.title}>{trip.title}</strong>
                <span className="cost-home__trip-period">{humanDate(trip.starts_on)}–{humanDate(trip.ends_on)}</span>
                <span className="cost-home__trip-profit-label">차액</span>
                <span className="cost-home__trip-profit"><Amount value={trip.profit} currency="KRW" /></span>
              </a>
            ))}
          </div>
        ) : (
          <EmptyState title="표시할 여행이 없습니다" description="권한이 있는 여행이 여기에 표시됩니다." />
        )}
      </section>

      <section className="cost-home__section" aria-labelledby="cost-home-jobs-title">
        <div className="cost-section-heading">
          <div>
            <p className="cost-eyebrow">실행 기록</p>
            <h2 id="cost-home-jobs-title">자동화 상태</h2>
          </div>
        </div>
        {loading && !data ? <Loading label="자동화 상태 불러오는 중" /> : data?.jobs.length ? (
          <ul className="cost-home__jobs">
            {data.jobs.map((job) => {
              const href = isInternalHref(job.href);
              return (
                <li className="cost-home__job" key={job.id}>
                  <div className="cost-home__job-status">
                    <JobStatus
                      state={job.state ?? (job.status === 'running' ? 'running' : job.status === 'success' ? 'succeeded' : job.status === 'error' ? 'failed' : 'unknown')}
                      label={job.label}
                      message={job.message ?? job.detail}
                      updatedAt={job.updated_at}
                      completed={job.completed}
                      total={job.total}
                    />
                  </div>
                  {href && <a href={href}>관련 화면 열기</a>}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState title="실행 기록이 없습니다" description="실제 확인된 작업 상태가 아직 없습니다." />
        )}
      </section>

      {bootstrap.role === 'viewer' && (
        <p className="cost-home__role-note">열람 권한이 있는 여행의 정보만 표시합니다.</p>
      )}
    </main>
  );
}
