# M4 UI-0 계약·기능 지도 — 2026-11-17

> 설계 [m4-plush-ui-20261116.md](m4-plush-ui-20261116.md) §9의 **UI-0(계약·기능 지도)** 산출물이다. 수락 정본은 [m4-ui-requirements.md](m4-ui-requirements.md)(HIGH 5·MEDIUM 8·LOW)와 설계 §10(P-01…P-10)이다. 이 문서는 현 화면을 패치하라는 지시가 아니라, 이미 main에 들어온 React 프런트를 수락 기준과 대조해 **검증된 것 / 코드 판독 / 렌더·서버 확인 필요 / 간극**을 가른 지도다.

## 0. 검증 환경과 결과 (실측)

| 항목 | 값 |
| --- | --- |
| 작업 worktree | `C:\AX\cost-m4-ui0` (detach, `origin/main`) |
| 기준 SHA | `7ec9d3ae98198b02c89dc7efc4c6fbd4b7179b6b` (Merge PR #978) |
| Node / npm | v24.22.1 / 11.19.1 |
| 의존성 설치 | `npm ci` — 179개 패키지 |
| 단위·통합 시험 | `vitest run` — **18개 파일 / 121개 시험 통과, 실패 0** |
| 타입 검사 | `tsc --noEmit` — **오류 0** |
| 프로덕션 빌드 | `vite build` — **성공**(2.74s, 6228 모듈, `dist/` 산출) |
| 신규 수락 시험 | `tests/acceptance/contrast.test.ts`(38건), `shell-accessibility.test.tsx`(3건), `ledger-primary-action.test.tsx`(2건) |

> 병렬 실행은 시스템 부하(운영 OTA 대조 등)가 높으면 워커 종료 timeout으로 기존 시험이 간헐 flake할 수 있다. 격리·순차(`--no-file-parallelism`) 재실행으로 전체 121건 통과를 재확인했다(프로젝트 설정 변경 없이 CLI 플래그만).

재현 명령(워크트리에서):

```bat
cd /d C:\AX\cost-m4-ui0\frontend
npm ci --no-audit --no-fund
npm run test:run
npm run typecheck
```

## 1. 핵심 결론

- **React 프런트(`frontend/`)는 이미 main에 존재한다.** 설계 문서(2026-11-16)는 이 구조를 "제안 경로이며 아직 구현되지 않았다"고 전제했으나, 실제 코드에는 `app/·components/plush/·features/·api/·styles/`가 구현되어 있고 자체 시험 78건이 통과한다. 따라서 M4의 남은 일은 **화면 재작성이 아니라** ① 수락 기준이 요구하는 자동 검증 시험 보강, ② 소수 간극 수정, ③ 렌더(브라우저)·서버 확인이다.
- 수락 결함 13건 중 다수가 **이미 코드 수준에서 충족**되어 있다(아래 표). 이번 세션에 대비 계산(#4·#8), 셸 접근성(#9·#1·#6 브랜드), 장부 주 행동 수(#13)를 자동 시험으로固化해 검증된 것으로 올렸다.
- **전체 브라우저 수락 통과를 주장하지 않는다.** jsdom 단위 시험은 레이아웃(잘림·대비 렌더·Tab 순서·Esc)을 계산하지 못한다. 설계 §11의 "일부 색쌍만 정적 대비 계산" 상태를, 이번에는 **전체 색 토큰 쌍 정적 대비 계산 완료**로 확장했으나 브라우저 수락은 별개다.

상태 범례: ✅ 시험 = 자동 시험 검증 · 🔎 코드 = 코드 판독 충족(브라우저 미확인) · 🖥 렌더 = 합성 미리보기 브라우저 확인 필요 · 🗄 서버 = 백엔드 확인 필요 · ⚠ 간극 = 수정·보강 필요

## 2. 기능·경로·권한 지도 (기존 경로 보존, P-01)

`frontend/src/app/routes.ts`의 `featureRoute`와 `AppShell` 탐색 기준. 모든 기존 COST deep link를 보존하며 `/ui` 프리픽스를 정규화한다.

| 기능 | 경로 | 소유자 | 열람(viewer) | 근거 |
| --- | --- | --- | --- | --- |
| 홈 | `/` | ✅ | ✕(여행만) | routes.test.ts |
| 여행 | `/trips` | ✅ | ✅(허용 여행만) | primary-navigation.test.tsx |
| 장부 | `/board?tab=<여행id>` | ✅ | 허용 여행 | routes.test.ts(→ledger) |
| 환불 거래 | `/board?tab=refunds` | ✅ | ✕ | routes.test.ts(→transactions) |
| 카드·OTA·항공 | `/cards/all`, `/ota`, `/flight-passengers` | ✅ | ✕ | transactions/README.md |
| 영수증 | `/receipts` | ✅ | ✕ | receipts/catalog.test.tsx |
| 계정·권한 | `/access/admin` | ✅ | ✕ | shell-accessibility.test.tsx(#1) |
| Google 장부 | `/google-ledger` | ✅ | ✕ | admin/google.test.tsx |
| 검수 결과 | `/review` | ✅ | ✕ | shell-accessibility.test.tsx(#1) |
| 보조(참가자·보험·수기·규칙·예약연결·내보내기) | `/participants`, `/participants/insurance-match`, `/expense/new`, `/income/new`, `/rules`, `/reserve-links`, `/export` | ✅ | ✕ | routes.test.ts(→auxiliary) |
| 없는 주소 | 그 외 | "화면을 찾을 수 없습니다" 화면 | 동일 | main.tsx, routes.test.ts(→missing) |

- 탐색 링크는 인코딩된 여행 id(`/board?tab=trip%20a%26b`)를 보존하고 `/ui`로 새지 않는다(primary-navigation.test.tsx). ✅
- viewer는 `여행` + 허용된 여행만 본다(AppShell `role==="viewer"` 분기). 🔎 코드 — **viewer 직접 URL·API 거부는 서버 확인 필요**(P-01, §3 미검증).

## 3. 수락 결함 13건 대조

### HIGH (5)

| # | 상태 | 근거 | 남은 일 |
| --- | --- | --- | --- |
| 1 관리 탭 href | ✅ 시험 | shell-accessibility: 계정·권한(`/access/admin`)·Google 장부(`/google-ledger`)·검수 결과(`/review`) 링크가 정확한 href. 따옴표 누락 버그는 Python 문자열 문제였고 React는 정상. | 없음(회귀 시험 유지) |
| 2 사본 안내 문구 | 🔎 코드 + ✅ API | ledger `copyForGoogle`→`/api/board/tsv`(row_count·total_krw), 클립보드+대체 textarea. client.test.ts가 TSV 계약 검증. 안내가 실제 복구 수단을 가리킴. | 안내 문구·링크 존재 렌더 확인(🖥) |
| 3 표 잘림 | 🔎 코드 | `base.css` td/th `overflow-wrap:anywhere`(줄바꿈). `text-overflow:ellipsis`·`table-layout:fixed` 없음. `nowrap`은 헤더·금액(tabular-nums)·시각숨김에만. | 320·390·640~720px에서 `scrollWidth>clientWidth` 셀 전체값 접근 렌더 시험(🖥, P-07) |
| 4 다크 글자 대비 | ✅ 시험 | contrast.test.ts: 라이트·다크 글자 15쌍 모두 ≥4.5:1(최저 4.57 = 라이트 보조글자/패널). 실패 0. | 없음(정적). 컴포넌트별 렌더 대비는 🖥 |
| 5 OTA 펼침 단서 | 🔎 코드 | React OTA는 "추가 조회" 펼침 대신 **페이지 매김+상세 링크**로 대체(펼침 패턴 없음). 존재하는 펼침은 `details/summary`(네이티브 단서)·google `aria-expanded`. | OTA 화면 렌더 확인(🖥) |

### MEDIUM (8)

| # | 상태 | 근거 | 남은 일 |
| --- | --- | --- | --- |
| 6 제목·브랜드·식별자 | ✅ 부분 + 🖥 | shell-accessibility: 브랜드 마크(`.cost-brand`) 1회. 화면별 제목은 `titleForPath`+각 페이지 h1. 내부 식별자 대신 라벨 사용. | topbar "COST/제목"은 위치 표시(브랜드 마크 아님) — 모바일 브랜드 중복 여부 렌더 확인(🖥) |
| 7 글꼴 스택 하나 | 🔎 코드 | tokens.css `--font-sans`·`--plush-font` 단일 Pretendard 스택. | 화면별 계산 글꼴·본문 크기·행간 동일 렌더 시험(🖥). 폰트 woff2는 `webapp/static/fonts/`에 있고 CSS는 `/assets/fonts/` 참조 — 호스트 정적 경로 매핑 런타임 확인(🗄), 미로드 시 폴백 스택 |
| 8 입력 테두리·높이·닫기 | ✅ 대비 + 🔎 코드 | contrast.test.ts: 테두리 ≥3:1(최저 3.33). 높이 토큰 일원화(`--plush-h-field` 48px 등). 닫기는 공용 `ActionButton`. | 입력 높이 계산 렌더 시험(🖥) |
| 9 건너뛰기 첫 초점 | ✅ 시험 | shell-accessibility: 건너뛰기 링크가 DOM 순서 첫 초점, `#cost-main`(tabIndex -1)이 본문 포함. | 실제 Tab 순서 브라우저 확인(🖥, jsdom은 Tab 이동 미구현) |
| 10 없는 여행 404 | 🔎 부분 + ⚠ 서버 | 클라이언트: 없는 주소→"화면을 찾을 수 없습니다" h1(main.tsx). routes.test.ts unknown→missing. | **없는 여행 id의 404 상태 코드는 서버 책임 — 백엔드 시험 필요**(🗄). 제목 문구 '찾을 수 없음' 정합 확인 |
| 11 menu 역할·Esc | 🔎 코드 | Drawer 네이티브 `<dialog>`+`showModal`, `onCancel`→Esc 닫기, Tab 초점 가둠, `role=menu` 없음, 단일 h2+닫기. | 실제 Esc·역할 브라우저 시험(🖥, jsdom `showModal` 미구현으로 단위 시험 fragile) |
| 12 용어집 통일 | ⚠ 간극 | 코드는 분류 등 일관 용어를 쓰나 **용어집 대조 시험이 없음**. | 용어집 한 벌 수립 + 대조 시험(분류·구분·항목, XLSX 출력/내보내기), 폐지 링크·책임 전가 문구 제거 |
| 13 주 행동 1개 | ✅ 시험 | ledger-primary-action: 소유자 기본 강조 1개(수기 지출 추가), 복사=secondary·XLSX=ghost. **viewer는 동작 그룹 전체 없음**(owner 전용, P-01). 빈 탭 없음. | 빈 상태 문장 수 렌더 확인(🖥) |

## 4. LOW 대조

| 항목 | 상태 | 근거/남은 일 |
| --- | --- | --- |
| 거래 서랍 제목·닫기 1회 | 🔎 코드 충족 | Drawer 단일 h2 + 닫기 1개 |
| 사이드바 여행 이름 잘림·title | 🔎 코드 충족 추정 | `overflow-wrap:anywhere` 줄바꿈. 렌더 확인(🖥) |
| 모바일 입력 16px | 🖥 | `--plush-text-lg` 16px 등 토큰. 모바일 계산 크기 렌더 확인 |
| 금액 inputmode numeric·음수 | 🖥 | 입력 방식 코드 확인 + 렌더 |
| 업로드 숨긴 입력 width | 🔎 코드 | 확인 필요 |
| 영수증 직접 입력 라벨 | 🖥 | 가시 라벨·접근 이름 일치(P-06) |
| 카드 상세 링크 붙어 보임 | 🖥 | 렌더 |
| OTA 머리 정렬 버튼 12px | 🖥 | 렌더(터치 대상 크기) |
| 오류 H1 32px·/rules 셸 | 🔎 코드 | main.tsx 오류 화면 h1, `/rules`는 auxiliary로 셸 포함. 렌더 확인 |

## 5. API 계약 대조 (설계 §8.2, P-02·P-03)

`frontend/src/api/client.ts`는 same-origin·`no-store`·CSRF 헤더/필드·허용 경로만 쓰는 클라이언트다. client.test.ts가 아래를 검증한다. ✅

| 계약 대상 | 검증됨(client.test.ts) | 서버 확인 필요(🗄) |
| --- | --- | --- |
| 세션·권한 | `/api/plush/bootstrap` 조회, 계정 POST 3종(`/access/applications`·`/decision`·`/logout`)만 허용 | 모든 조회·쓰기의 서버 권한 검증, viewer 거부 |
| 여행·장부 | 행 저장(`/api/rows/{id}/save`)이 서버 광고 필드+revision+멱등 키만 전송(rowDrawer.test.tsx) | 안정 ID·통화·부호·정밀도 보존 합계, JS 부동소수점 합산 금지 |
| 복사·내보내기 | `/api/board/tsv`(tab·q·kind 쿼리), `/api/exports/xlsx`(다중 tab_ids), 다운로드 blob 바이트 보존 | 서버가 만든 집합·건수·합계·산출 시점(P-03), 로드된 일부 행으로 전체 파일 생성 금지 |
| 거래·근거 | `/api/rows/{id}/lineage` 경로 인코딩 | 근거 원문 인증 경로만 조회 |
| 작업 | 내보내기 job GET 확인 후 다운로드(export.test.ts) | 실제 상태·단계·갱신 시각, 허위 진행률 금지(P-05) |
| 영수증 | multipart 파일 필드, boundary 헤더 미설정 | 기존 영속 계약 재사용·별도 큐 금지(P-04) |
| 오류 | 서버 JSON 오류→`ApiError`(code·status·message) 정규화 | 404(없는 여행) 등 상태 코드 정합(#10) |

**API 빈틈:** endpoint 전체 목록과 JSON 스키마는 백엔드(`webapp`/Rust) 대조가 필요하다. 설계 §8.2대로 "구현 직전 현재 API를 대조해 확정"하며, 위 표는 client 시험이 검증한 계약 범위만이다.

## 6. 미검증 항목 (수락 §3 그대로)

- viewer(열람) 역할 화면 — 직접 URL·API 거부 포함(P-01). 🗄 서버 + 🖥
- 운영 자료 상태(검수는 합성 미리보기만). 고객 원문은 보호 경로에만(P-09).
- 스크린리더 실청취 — 자동 DOM 검사와 구분해 기록.
- 실기기(모바일 브라우저·확대·고대비).

## 7. 남은 작업 (설계 묶음에 매핑)

| 묶음 | 이번 지도가 넘기는 일 |
| --- | --- |
| UI-1 토큰·공용 | 대비 시험 완료(전체 색 쌍). 모션 감소·초점 갤러리 브라우저 확인 |
| UI-2 셸·장부 대표 | 건너뛰기·관리 링크·주 행동 수(#13) 시험 완료. 잘림(#3)·글꼴(#7)·모바일 입력(LOW) 렌더 시험(🖥) |
| UI-3 장부·여행·산출물 | 서버 합계·복사·내보내기 일치(P-03) 백엔드 대조(🗄), 사본 안내 문구(#2) 렌더 |
| UI-4 영수증 | 기존 영속 계약 연결(P-04) 서버 확인(🗄) |
| UI-5 거래·관리·보조 | **없는 여행 404(#10) 서버 시험**, **용어집(#12) 수립+대조 시험**, viewer 거부(P-01), OTA 단서(#5) 렌더 |
| UI-6 최종 검증 | Esc·Tab·역할(#9·#11) 브라우저 시험, 스크린리더·실기기, 되돌림 절차 |

우선 간극(⚠): **#10 서버 404**, **#12 용어집**. 나머지는 렌더(🖥)·서버(🗄) 확인으로 검증 상태를 올리는 일이다.

## 8. 경계

- 고객 원문·금액·끝자리는 이 문서·Git·캡처에 넣지 않는다(P-09). fixtures는 완전 합성만.
- 미리보기에 운영 포트 8751·8752·8790을 쓰지 않는다. 브라우저 검증은 ego-browser 합성 미리보기.
- 이 문서는 지도이며 화면 코드 변경 지시가 아니다. 간극 수정은 해당 묶음 구현 요청에서 한다.