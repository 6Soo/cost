# Plush UI 병렬 구현 계약 — 2026-11-16

사용자가 [전체 설계](../../design/m4-plush-ui-20261116.md)의 구현을 다수 Luna xhigh에게 위임하고 주 세션을 컨트롤 타워로 지정했다. 이후 “모든 작업 재개하고 운영배포까지해”로 구현·합성 검사·독립 검수·운영 배포까지 승인했다. 영수증 감독의 선행 배포 뒤 최신 SHA를 통합하고 한 세션이 검증 배포를 수행한다. 고객 원본/운영 DB 변경·M3 작성자 전환은 포함하지 않는다. 구현 세부 선택은 감독이 정하며 사용자에게 다시 승인받지 않는다.

## 1. 소유권과 통합

모든 작업자는 공식 Paseo worktree에서 `codex/gpt-6-luna`, `xhigh`로 실행한다. 재귀 위임 금지. 소유 파일만 커밋하고 SHA·검사·남은 사항을 보고한다. 실제 동작으로 완료를 입증하고 예시 데이터/클릭해도 작동하지 않는 버튼으로 완료 처리하지 않는다.

| 작업 | 단독 소유 |
| --- | --- |
| A 기반 | `frontend/package*.json`, 각종 build/TS config, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/app/`, `frontend/src/components/`, `frontend/src/styles/`, `frontend/public/`, `frontend/licenses/`, 기반 전용 검사 |
| B 장부 | `frontend/src/features/home/`, `trips/`, `ledger/`, B 전용 검사 |
| C 영수증 | `frontend/src/features/receipts/`, C 전용 검사. 기존 receipt_* 서버·JS 파일은 읽기만 |
| D API | `webapp/plush_api.py`, `webapp/plush_projection*.py`, `webapp/tests/test_plush_api*.py`, `frontend/src/api/` |
| E 거래·관리 | `frontend/src/features/transactions/`, `admin/`, `auxiliary/`, E 전용 검사 |
| 감독 | docs, `webapp/plush_ui.py` 정적 자산·경로 hook, `ledger_board.py` 최소 연결, 영향 맵·통합·preview·브라우저 검증 |

기존 영수증 감독 `77abc586-a18e-4b57-94f7-c9c8c3fa210e`가 receipt_*와 기존 `ledger_board.py`를 진행 중이다. 해당 branch를 임의 병합/수정하거나 원본 폴더 branch를 전환하지 않는다. 필요한 서버 연결점은 감독에게 요청한다. 통합 branch는 `integration/plush-ui-20261116`이다.

## 2. 앱과 경로

- React/TypeScript + Tailwind v4 + 실제 고정 Plush 소스. upstream `125a22ce151b719077637da38ffe9ec06a1a08c5`의 코드/라이선스를 반입. 설치 도구/라이브러리의 추가 유료 경로 금지.
- 정적 배포 결과는 `frontend/dist/`, URL base는 `/ui/`, API는 같은 origin. Next 서버를 추가하지 않는다. React 개발 서버는 운영 포트를 사용하지 않는다.
- 개발/검증 진입은 `/ui/`와 `/ui/<기존 path>`다. 예: `/ui/board?tab=...`, `/ui/receipts`, `/ui/access/admin`. 기존 주소와 기능은 유지한다. 이번 범위에서 새 UI 진입이 기본이 되도록 하는 전환은 감독이 전체 검사 후 결정한다. 운영 전환과 구분한다.
- 화면에서 실제 연결로 새 UI/기존 주소 호환을 검증한다. iframe/HTML 파싱/원격 데모 embed를 구현 대체로 쓰지 않는다. 아직 API가 없는 기능은 감독/D에게 정확한 계약을 요청하고 그동안 독립 UI를 진행한다.
- A는 root 조립을 위한 `AppShell`과 `App`를 제공한다. 각 도메인은 named export `HomePage`, `TripsPage`, `LedgerPage`, `ReceiptsPage`, `TransactionsPage`, `AdminPage`, `AuxiliaryPage`를 자기 폴더 `index.tsx`에서 제공한다. 감독이 최종 route mapping을 연결한다.
- 도메인 Page props: `{ bootstrap: Bootstrap; path: string; search: URLSearchParams }`. 공통 `Bootstrap`은 D의 `frontend/src/api/types.ts`. React 없이 정의 가능한 타입이다. A는 일단 children을 받는 AppShell/갤러리로 기반 build를 확인하고 최종 기능 imports는 감독과 합친다.

## 3. 공통 API 계약

D는 `frontend/src/api/types.ts`/`client.ts`를 구현하고 초기 인터페이스를 감독에게 즉시 알린다. 다른 작업자는 `api` 폴더를 작성하지 않는다. 필요한 새 endpoint/필드는 먼저 감독/D에게 알린다.

- `GET /api/plush/bootstrap` → `{role:'owner'|'viewer', csrf:string, trips:TripSummary[], capabilities:string[], receipt_enabled:boolean, screen_titles?:Record<string,string>}`. viewer는 허용 여행만 반환하고 owner 자료/기능을 내려주지 않는다.
- `TripSummary`: `{id:string,title:string,starts_on:string,ends_on:string,income:string,expense:string,profit:string,closed:boolean,archived:boolean}`. 금액은 KRW 정수 문자열. 통화 변환/원문 원화 환산은 기존 서버 계약대로 유지.
- `GET /api/plush/home` → `{trips:TripSummary[],jobs:JobSummary[],updated_at:string}`. 미확인 자동화는 성공으로 만들지 않는다.
- `GET /api/plush/ledger?tab=...&kind=expense|income&q=...&page=1&page_size=50&sort=...` → `{trip:TripSummary,rows:LedgerRow[],total_count:number,page:number,page_size:number,filtered_total:string,total:string,closed:boolean}`.
- `LedgerRow`: `{id:string,date:string,merchant:string,description:string,category:string,amount:string,currency:string,payment:string,period:string,evidence_summary:string,revision?:string|number,read_only:boolean}`. 원본/상세는 `GET /api/plush/row?id=...`의 `{row,source,decision,history,actions}`. source/decision은 안전한 정형 DTO, 고객 원문은 인증 경로에만.
- `GET /api/plush/transactions?view=cards|ota|refunds|flights&q=...&page=...` → `{view,columns:[{key,label}],rows:Record<string,unknown>[],total_count,page,page_size,actions:ActionDescriptor[],status?:{code,message}}`. 내용·금액·정렬은 서버에서 만들고 rows의 금액 문자열 유지.
- `GET /api/plush/admin?view=accounts|profile|google|review` 및 `GET /api/plush/auxiliary?view=...&trip=...` → `{title,columns?,rows?,fields?:FieldDescriptor[],actions:ActionDescriptor[],status?,data?:Record<string,unknown>}`. 필드/동작은 실제 현 서버 기능과 일치시킨다.
- `ActionDescriptor`: `{id,label,method:'GET'|'POST',href,fields?:FieldDescriptor[],disabled?:boolean,reason?:string}`. `FieldDescriptor`: `{name,label,type:'text'|'number'|'date'|'select'|'checkbox'|'file'|'hidden',value?,options?:{value,label}[],required?,read_only?}`. href는 동일 origin의 허용 기존 경로만; 임의 사용자가 입력한 URL로 요청 금지. 실행 payload/업로드 방식은 기존 handler 계약을 유지한다. destructive 동작을 새로운 범용 프록시에 통과시키지 않는다.
- 기존 복사·XLSX·교정·수기·계정·연결 API를 재사용한다. 새 쓰기가 필요하면 감독이 계약·기존 보호를 확인한 뒤 담당 소유권을 정한다. 백엔드와 UI 모두 단순 링크를 완성된 편집 기능으로 주장하지 않는다.
- `client.ts`: `getJSON<T>(path:string, signal?:AbortSignal):Promise<T>`, `postJSON<T>(path:string,payload:unknown,csrf:string):Promise<T>`, `ApiError`의 `code`, `status`, `message`. 민감 응답은 캐시하지 않고 오류 시 원문을 로그에 찍지 않는다.
- 실제 계정 JSON POST인 `/access/applications`, `/access/decision`, `/access/logout` 세 경로는 D가 기존 `_phase7_write` 처리임을 확인했다. 이 세 경로만 exact allowlist로 기존 인증·CSRF·응답을 재사용한다. `/api/` prefix 제한을 이유로 계정 기능을 누락하거나 새 범용 프록시를 만들지 않으며 다른 `/access/*`는 허용하지 않는다.

## 4. 영수증

현재 진행 중인 [영수증 구현 계약](receipt-paseo-implementation-contract-20261116.md)의 실제 API를 재사용한다. `GET /api/receipts/paseo/models`, workflow 목록·batches·review·apply·retry, 기존 원본 업로드/보기/직접 입력의 실제 요청 형식을 조사한다. model 선택 시 실행·관리 프롬프트·영속 복귀·revision·선택 묶음 원자성·멱등·사진/모델 보존을 바꾸지 않는다. 원본과 결과 나란히, 모바일 전환으로 구현한다. 백엔드 미도착이면 통합 때 감독이 영수증 완료 SHA를 가져온다. 합성 API fixture는 검사에서만 사용하며 제품 runtime fallback으로 넣지 않는다.

## 5. 디자인·검사

- Pretendard 로컬 글꼴, 기본 밝은 Plush·COST 다크, PC 48px 행·44px 조작 영역. 의미 토큰·공통 UI 사용. A는 다른 작업자가 import할 공용 컴포넌트 목록/props를 빠르게 공개한다.
- 각 도메인은 공통 `cost-*` 기본 클래스와 자기 feature CSS만 사용해 충돌을 피한다. A 파일이 아직 없으면 읽기 가능한 로컬 native HTML로 작성하고 뒤에 공용 컴포넌트로 연결한다.
- 고객 자료·운영 포트(8751/8752/8790)·운영 DB·실제 모델 호출·Google 자동 쓰기·원본 삭제 금지. 합성 fixture에도 기존 코드의 실제 카드 끝자리/사용자 이름을 재사용하지 않는다.
- 카드/분기 판정을 사용자 확인함으로 만들지 않는다. 영수증 사용자 선택만 최신 명세대로 유지. 직원 정산·여행 생성 등 새 업무 기능 금지.
- 컴파일/표적 검사 필수. 표적 Python은 해당 신규 파일만. 프런트 typecheck/build, 의미 있는 API/상태/권한 검사. 시험 기대값을 낮춰 통과시키지 않는다.
- 최종 감독이 390/1440px·light/dark·키보드·영수증 복귀·표/합계·권한을 직접 검증한다. 발견 오류는 수정 후 같은 경로 재검증한다.
- 이행 큐 UI-0~6은 설계 그대로이며 각 완료 근거를 남긴다. 실행 가능한 일을 다음 세션으로 미루거나 초기 위임만으로 종료하지 않는다.
