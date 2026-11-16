# M4 UI-0 계약·기능 지도 — 2026-11-17

> 설계 [m4-plush-ui-20261116.md](m4-plush-ui-20261116.md) §9의 **UI-0(계약·기능 지도)** 산출물이다. 수락 정본은 [m4-ui-requirements.md](m4-ui-requirements.md)(HIGH 5·MEDIUM 8·LOW)와 설계 §10(P-01…P-10)이다. 이 문서는 현 화면을 패치하라는 지시가 아니라, 이미 main에 들어온 React 프런트를 수락 기준과 대조해 **검증된 것 / 코드 판독 / 렌더·서버 확인 필요 / 간극**을 가른 지도다.

## 0. 검증 환경과 결과 (실측)

| 항목 | 값 |
| --- | --- |
| 작업 worktree | `C:\AX\cost-m4-ui0` (detach, `origin/main`) |
| 기준 SHA | `7ec9d3ae98198b02c89dc7efc4c6fbd4b7179b6b` (Merge PR #978) |
| Node / npm | v24.22.1 / 11.19.1 |
| 의존성 설치 | `npm ci` — 179개 패키지 |
| 단위·통합 시험 | `vitest run --no-file-parallelism` — **21개 파일 / 130개 시험 통과, 실패 0** |
| 타입 검사 | `tsc --noEmit` — **오류 0** |
| 프로덕션 빌드 | `vite build` — **성공**(6228 모듈, `dist/` 산출) |
| 신규 수락 시험 | `tests/acceptance/contrast.test.ts`(38건), `shell-accessibility.test.tsx`(3건), `ledger-primary-action.test.tsx`(2건), `glossary.test.ts`(3건·#12), `ledger-not-found.test.tsx`(2건·#10), `render-prerequisites.test.ts`(4건·#3·#7 전제) |
| 백엔드 수락 시험 | `webapp/tests/test_plush_api.py::test_unknown_trip_and_row_answer_404`(#10 서버 404), 전체 22건 통과 |
| 서버 권한·정적 경로 확인 | `test_plush_integration.py` **4 passed**(P-01 viewer 거부·bootstrap allowlist·합계), `test_ledger_design.py::test_only_the_allowed_font_assets_are_served` **1 passed**(#7 폰트 정적 경로 allowlist) — 현재 브랜치 실측 |
| 브라우저 렌더 수락 시험 | `webapp/tests/test_plush_render_browser.py` **12 passed**(실제 Chromium·합성 미리보기·`WEBLEDGER_PRIMARY_UI=1`): 셸 부팅·브랜드 1회, #3 가로 overflow 0(320·390·640·720px), #7 계산 글꼴 Pretendard 로드, #9 건너뛰기 첫 초점+Tab 본문 이동, #11 행 서랍 Esc 닫기, #13 주 행동 1개, **#2 클립보드 거부→서버 산출 TSV 대체 textarea 복구**(합성 canonical Google 소스 설치·`install_canonical_source` 재사용), #8 입력 높이 48px 계산, LOW 모바일 입력 글꼴 ≥16px·금액 `inputmode=numeric`, #10 없는 주소→"화면을 찾을 수 없습니다"(`/ui/` 미등록 경로), #5 OTA 페이지 매김 구조(펼침 없음) |
| 렌더 간극 수정 | **#3 잘림**: 320px에서 24px 가로 overflow 실측(일반 금액에서도) → 원인 `.cost-ledger__totals` 2열×`min-width:140px`+gap+padding=328px 최소폭이 320px 내용 영역(288px) 초과. `ledger.css` ≤390px에서 totals 1열로 수정 → 6시험 통과·프런트 130시험 회귀 0 |

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
- viewer는 `여행` + 허용된 여행만 본다(AppShell `role==="viewer"` 분기). ✅ 시험 — **viewer 직접 URL·API 거부 서버 검증**(`test_plush_integration.py`: 타 여행·행 404, 카드/관리/보조 403·404, 자료 유출 없음, 허용 장부 읽기전용, bootstrap allowlist). 화면 렌더는 🖥.

## 3. 수락 결함 13건 대조

### HIGH (5)

| # | 상태 | 근거 | 남은 일 |
| --- | --- | --- | --- |
| 1 관리 탭 href | ✅ 시험 | shell-accessibility: 계정·권한(`/access/admin`)·Google 장부(`/google-ledger`)·검수 결과(`/review`) 링크가 정확한 href. 따옴표 누락 버그는 Python 문자열 문제였고 React는 정상. | 없음(회귀 시험 유지) |
| 2 사본 안내 문구 | ✅ 시험+브라우저 | ledger `copyForGoogle`→`/api/board/tsv`(row_count·total_krw), 클립보드+대체 textarea. client.test.ts가 TSV 계약 검증. `test_plush_render_browser.py`: 합성 canonical Google 소스(`install_canonical_source` 재사용) 설치 후 클립보드 거부→서버 산출 TSV가 대체 textarea(`서버가 만든 붙여넣기 내용`)에 렌더됨을 실측. **소스 없으면 서버가 빈 TSV(0건) 반환은 설계 동작**(검증된 Google 원장과 대조해 NEW_EXPENSE만 복사). | 없음(회귀 시험 유지) |
| 3 표 잘림 | ✅ 전제+브라우저 시험+수정 | `render-prerequisites.test.ts`: 잘림 기법 0건 + 셀 `overflow-wrap:anywhere`. `test_plush_render_browser.py`: 320·390·640·720px에서 가로 overflow 0 실측. **간극 수정**: 320px에서 totals 2열 최소폭 328px가 내용 영역 288px 초과(24px overflow) → `ledger.css` ≤390px totals 1열. | 없음(회귀 시험 유지). 셀 전체값 접근 브라우저 검증 완료 |
| 4 다크 글자 대비 | ✅ 시험 | contrast.test.ts: 라이트·다크 글자 15쌍 모두 ≥4.5:1(최저 4.57 = 라이트 보조글자/패널). 실패 0. | 없음(정적). 컴포넌트별 렌더 대비는 🖥 |
| 5 OTA 펼침 단서 | ✅ 코드+브라우저(구조) | React OTA는 "추가 조회" 펼침 대신 **페이지 매김+상세 링크**로 대체(펼침 패턴 없음). 존재하는 펼침은 `details/summary`(네이티브 단서)·google `aria-expanded`. `test_plush_render_browser.py`: `/ota`에서 페이지 매김(`nav[aria-label='페이지 이동']`)·검색 폼 렌더 실측(빈 상태). | 상세 링크(데이터 있음) 렌더는 OTA 시드 필요(🖥) |

### MEDIUM (8)

| # | 상태 | 근거 | 남은 일 |
| --- | --- | --- | --- |
| 6 제목·브랜드·식별자 | ✅ 부분 + 🖥 | shell-accessibility: 브랜드 마크(`.cost-brand`) 1회. 화면별 제목은 `titleForPath`+각 페이지 h1. 내부 식별자 대신 라벨 사용. | topbar "COST/제목"은 위치 표시(브랜드 마크 아님) — 모바일 브랜드 중복 여부 렌더 확인(🖥) |
| 7 글꼴 스택 하나 | ✅ 전제+서버+브라우저 시험 | `render-prerequisites.test.ts`: `--font-sans`==`--plush-font` 단일 Pretendard 스택 + `@font-face`. 폰트 정적 경로 ✅(`test_only_the_allowed_font_assets_are_served`: woff2 200·wOF2·allowlist 404). `test_plush_render_browser.py`: 계산 글꼴 Pretendard + `document.fonts.check` 로드 실측. | 화면별 본문 크기·행간 동일 렌더(🖥)만 남음 |
| 8 입력 테두리·높이·닫기 | ✅ 대비+브라우저 | contrast.test.ts: 테두리 ≥3:1(최저 3.33). 높이 토큰 일원화(`--plush-h-field` 48px 등). 닫기는 공용 `ActionButton`. `test_plush_render_browser.py`: 장부 검색 입력 계산 높이 48px 실측. | 없음(회귀 시험 유지) |
| 9 건너뛰기 첫 초점 | ✅ 시험+브라우저 | shell-accessibility: 건너뛰기 링크 DOM 순서 첫 초점, `#cost-main`(tabIndex -1). `test_plush_render_browser.py`: 실제 Tab 첫 초점=건너뛰기, Enter→`#cost-main` 초점 이동 실측. | 없음(회귀 시험 유지) |
| 10 없는 여행 404 | ✅ 시험+브라우저 | 서버: `plush_api._trip_for_query`가 없는 여행 id에 **404 RESOURCE_NOT_FOUND**("없는 여행이에요") 반환 — `test_plush_api.py::test_unknown_trip_and_row_answer_404` 검증(없는 행도 404). 클라이언트: ledger가 404 시 h1 **'여행을 찾을 수 없음'** — `ledger-not-found.test.tsx` 검증(404 아닌 오류는 일반 제목 유지). 없는 주소→"화면을 찾을 수 없습니다"(main.tsx) — `test_plush_render_browser.py`가 `/ui/` 미등록 경로에서 h1 렌더 실측. | 없음(회귀 시험 유지) |
| 11 menu 역할·Esc | ✅ 코드+브라우저 시험 | Drawer 네이티브 `<dialog>`+`showModal`, `onCancel`→Esc 닫기, Tab 초점 가둠, `role=menu` 없음, 단일 h2+닫기. `test_plush_render_browser.py`: 행 서랍 열기→`dialog[open]`→Esc→닫힘 실측. | 초점 가둠·역할 추가 렌더(🖥) |
| 12 용어집 통일 | ✅ 시험 | 용어집 정본 [m4-glossary-20261117.md](m4-glossary-20261117.md) 수립(item=항목·kind=구분·category=분류·XLSX=내보내기). 장부 '출력 작업'→'내보내기 작업' 통일. `glossary.test.ts`가 금지 문구(XLSX 출력 혼용·'관리자가 설정' 책임 전가) 0건 + 표준 라벨 대조. | 폐지 링크·책임 전가 문구 금지 시험 유지 |
| 13 주 행동 1개 | ✅ 시험+브라우저 | ledger-primary-action: 소유자 기본 강조 1개(수기 지출 추가), 복사=secondary·XLSX=ghost. **viewer는 동작 그룹 전체 없음**(owner 전용, P-01). `test_plush_render_browser.py`: 장부 toolbar 주 행동(`data-variant="default"`) 1개 실측. | 빈 상태 문장 수 렌더 확인(🖥) |

## 4. LOW 대조

| 항목 | 상태 | 근거/남은 일 |
| --- | --- | --- |
| 거래 서랍 제목·닫기 1회 | 🔎 코드 충족 | Drawer 단일 h2 + 닫기 1개 |
| 사이드바 여행 이름 잘림·title | 🔎 코드 충족 추정 | `overflow-wrap:anywhere` 줄바꿈. 렌더 확인(🖥) |
| 모바일 입력 16px | ✅ 브라우저 | `--plush-text-lg` 16px 등 토큰. `test_plush_render_browser.py`: 390px에서 장부 검색 입력 계산 글꼴 ≥16px 실측 |
| 금액 inputmode numeric·음수 | ✅ 코드+브라우저 | 입력 방식 코드 확인. `test_plush_render_browser.py`: 수기 지출 서랍 금액 입력 `inputmode=numeric`·라벨 '금액' 실측 |
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

- viewer(열람) 역할 화면 — 직접 URL·API 거부(P-01)는 ✅ 서버 시험(`test_plush_integration.py`). 화면 렌더만 🖥
- 운영 자료 상태(검수는 합성 미리보기만). 고객 원문은 보호 경로에만(P-09).
- 스크린리더 실청취 — 자동 DOM 검사와 구분해 기록.
- 실기기(모바일 브라우저·확대·고대비).

## 7. 남은 작업 (설계 묶음에 매핑)

| 묶음 | 이번 지도가 넘기는 일 |
| --- | --- |
| UI-1 토큰·공용 | 대비 시험 완료(전체 색 쌍). 모션 감소·초점 갤러리 브라우저 확인 |
| UI-2 셸·장부 대표 | 건너뛰기(#9)·관리 링크·주 행동 수(#13) 시험+브라우저 완료. 잘림(#3) 브라우저 검증+간극 수정, 글꼴(#7) 계산 로드 브라우저 완료. 모바일 입력 글꼴·금액 inputmode(LOW) 브라우저 완료. 입력 높이(#8) 브라우저 완료 |
| UI-3 장부·여행·산출물 | 사본 안내 문구(#2) 클립보드 거부→서버 TSV 대체 복구 브라우저 **완료**(합성 canonical 소스). 서버 합계·복사·내보내기 일치(P-03) 백엔드 대조만 남음(🗄) |
| UI-4 영수증 | 기존 영속 계약 연결(P-04) 서버 확인(🗄) |
| UI-5 거래·관리·보조 | 없는 여행 404(#10) 서버+프런트+없는 주소 화면 브라우저 **완료**, 용어집(#12) 수립+대조 시험 **완료**, viewer 거부(P-01) 서버 시험 **완료**(`test_plush_integration.py`). OTA 단서(#5) 페이지 매김 구조 브라우저 완료, 상세 링크(데이터 있음)는 OTA 시드 필요(🖥) |
| UI-6 최종 검증 | Esc(#11)·Tab(#9) 브라우저 시험 완료. 역할·초점 가둠 추가 렌더, 스크린리더·실기기, 되돌림 절차 남음 |

우선 간극(⚠) **해소**: #10 서버 404, #12 용어집, **#3 잘림(브라우저 실측 24px overflow→totals 1열 수정)**. **13결함 모두 핵심 수락 기준 시험 검증(브라우저 렌더 포함)**: #1·#2·#3·#4·#5(구조)·#6브랜드·#7·#8·#9·#10·#11·#12·#13. 이번 구간 추가 실측: #2 복사 복구(합성 canonical Google 소스)·#5 OTA 페이지 매김·#8 입력 높이 48px·LOW 모바일 글꼴 ≥16px·금액 inputmode·#10 없는 주소 화면. 남은 것은 **부가 렌더**(모바일 브랜드 중복·화면별 본문 크기·초점 가둠·빈 상태 문장 수·OTA 상세 링크 데이터)와 **P-03·P-04 서버 대조**, 스크린리더·실기기다. 서버 확인(P-01 viewer 거부·#7 폰트 정적 경로)은 기존 시험으로 완료.

## 8. 경계

- 고객 원문·금액·끝자리는 이 문서·Git·캡처에 넣지 않는다(P-09). fixtures는 완전 합성만.
- 미리보기에 운영 포트 8751·8752·8790을 쓰지 않는다. 브라우저 검증은 ego-browser 합성 미리보기.
- 이 문서는 지도이며 화면 코드 변경 지시가 아니다. 간극 수정은 해당 묶음 구현 요청에서 한다.