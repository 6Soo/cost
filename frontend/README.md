# COST Plush UI 기반

정적 React + TypeScript + Tailwind CSS v4 앱입니다. Vite의 개발 서버는 `127.0.0.1:4173`만 사용하고 빌드 결과는 `frontend/dist/`에 생성됩니다. 실제 API 연결은 `src/api/` 소유자인 D가 제공합니다. 이 폴더에는 제품용 예시 데이터나 서버 fallback이 없습니다.

## 공용 컴포넌트

도메인 화면은 `src/components/index.ts`에서 import합니다. 실제 Plush 소스는 `src/components/plush/`에 고정 커밋 그대로 보존합니다.

| Export | Props / 동작 |
| --- | --- |
| `ActionButton` | `ButtonHTMLAttributes` + `variant?: 'primary' \| 'secondary' \| 'ghost' \| 'danger'`, `size?: 'sm' \| 'md' \| 'lg'`, `pending?: boolean`, `pendingLabel?: string`; pending이면 비활성·`aria-busy` 표시 |
| `Checkbox`, `Switch` | 각각 Plush/Radix 컨트롤 props + 필수 `label`; 선택 `description`, `error`; 전체 라벨 행이 조작 영역 |
| `RadioGroup` | `{ options: { value, label, description? }[]; value; onChange(value); name; label; disabled? }` |
| `InlineNotice` | `{ tone: 'info' \| 'success' \| 'warning' \| 'error'; title; children?; action?: { label, onClick } }` |
| `EmptyState` | `{ title; description?; action?: ReactNode }` |
| `JobStatus` | `{ state: 'queued' \| 'running' \| 'succeeded' \| 'failed' \| 'cancelled' \| 'unknown'; label?; message?; updatedAt?; completed?; total? }`; 진행률은 두 수치가 모두 유효할 때만 노출 |
| `FormField` | `{ id; label; required?; hint?; error?; children: ReactElement }`; 자식 입력에 라벨·힌트·오류·필수 상태를 연결 |
| `Input`, `Select` | 각 표준 HTML input/select props + `invalid?: boolean`; 한국어 모바일 확대를 막도록 16px 이상 |
| `Tabs` | `{ items: { id, label, disabled? }[]; value; onChange(value); ariaLabel }`; 키보드 화살표·Home·End 지원 |
| `Amount` | `{ value: string; currency?: string }`; 부동소수점 변환 없이 정수·소수 문자열 정밀도 보존 |
| `Loading` | `{ label?: string; size?: 'sm' \| 'md' }`; 상태 설명을 접근성 트리에 제공 |
| `DataTable<T>` | `{ columns: { key, header, cell(row), align? }[]; rows; getRowKey(row); caption }`; 빈 상태는 명시적으로 표시 |
| `Drawer` | `{ open; title; description?; onOpenChange(open); children }`; native dialog의 Esc·초점 반환 제공 |
| `AppShell` | `{ role: 'owner' \| 'viewer'; trips: { id, title }[]; path; children }`; PC 사이드바, 작은 화면 탐색, light/dark 테마 |

공통 CSS prefix는 `cost-*`; 원본 Plush 컴포넌트는 `plush-*` 토큰을 `src/styles/tokens.css`의 COST 의미 토큰에 연결합니다. 화면별 색상 값을 직접 추가하지 않습니다.

## 스크립트

- `npm run dev` — 로컬 개발 서버 (`127.0.0.1:4173`)
- `npm run typecheck` — TypeScript 검사
- `npm run test:run` — Vitest 표적 검사
- `npm run build` — `/ui/` base의 정적 산출물

## 소스·라이선스

- Plush UI 컴포넌트 출처와 고정 upstream SHA는 `licenses/UPSTREAM.md` 참고. MIT 원문은 `licenses/plush-ui-MIT.txt`.
- Pretendard Variable은 기존 `webapp/static/fonts/`의 로컬 파일을 사용하며 OFL 1.1 고지는 `licenses/Pretendard-OFL.txt`에 보존합니다.
- 프런트 패키지 버전은 2026-11-16 npm registry 최신 안정판을 확인해 고정했습니다. Plush가 직접 요구한 CVA, Radix, Hugeicons는 upstream package의 범위/버전과 일치하게 lockfile로 고정합니다.
