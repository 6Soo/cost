# Plush UI 구현·검증 현황

## 최종 코드 수락 — 운영 전환 준비

- 코드 후보 `a92c0b8773971d9abb71db131e070e46482c1f4f`에 C 후보 identity `a47f2f55`와 E 미저장 예약/집계 `a92c0b87` 수정을 포함했다. 조회 대상 ID 변경 시 이전 항공권 후보를 폐기하고, 미저장 예약 draft가 있으면 이전 저장 계획을 반영하지 못한다. 참가자 고유 수입 행 집계와 기존 이름·별칭·여행 교정/미연결 수입 검토 접근도 보존한다.
- 최종 전체 프런트 **72 passed (13 files)**, `tsc --noEmit`·Vite build exit0. `3c0672a2→a92c0b87` 최종 영향 검사 **45 passed, skip0, 실패0, pytest/compile exit0**. 앞선173/565/778건 영향 검사와 범위를 구분하며 각각 원본 근거를 보존한다.
- 최종 합성 실제 서버에서 참가자·예약·항공권390/1440px 렌더링·원천 없음 이유·가로 넘침0을 확인했다. TaskSpace54 모바일 항공권 캡처를 직접 시각 확인했다. 합성 접근 승인/해지, XLSX 이진 다운로드, 영수증 핵심 흐름의 앞선 실제 브라우저 근거를 함께 사용한다.
- 기능 구현·검사 완료 이후 소스 변경 없이 최종 문서 SHA 독립 승인을 받아 [공식 릴리스 절차](../../playbooks/plush-ui-release.md)를 실행한다. 현재 운영은 아직 `1f436426`이다. 이 절 자체가 배포 성공 근거는 아니다. 배포 후 운영 기록과 현재 상태에 실제 SHA/보호 표/HTTP/빌드 해시/인증 화면 결과를 추가한다.
- 제한: 실제 전경 paint p95 목표는 아래 자동화 측정에서 미달해 원인/범위를 기록했다. 실기기·스크린리더 실청취는 미실행이다. 원문·교정·금융 보호를 해제하거나 Google 최종 장부에 자동 기록하지 않는다.

## 2026-11-16 기존 업무 누락 보완·독립 재검수

- 규칙 사례/규칙/버전이 바뀌면 적용 미리보기를 폐기하고 처리 중 사례 입력을 잠근 `61e4c510`은 독립 sol medium이 직접 7건 검사 후 해당 결함 해소를 승인했다. Google `05ae7d19` 실제 정수 금액/links_revision 수정도 독립 12건 통과, OTA·항공권 URL 필터 `15536bd7`은 독립 2건 통과다.
- D 계정 `70fb972e→831e4666`, OTA/환불 `abe3d468→67689808`, 표시 후속 `25c672→3c0672a2` 통합. 신청별 hidden ID/revision과 실제 예약 담당자 선택지, 이름으로 구분한 승인/해지 동작을 제공한다. root `369bb8d6`은 기존 계정 목록과 대기 신청 표를 함께 표시한다.
- OTA는 실제 `detail_url`의 예약 상세·교정 원래 화면을 명시적 링크로 유지한다. 환불은 기존 `groups`와 `filter_refund_groups`를 그대로 사용해 검색 일치 시 전체 그룹을 보존하고 원결제 ID/역할/연결 근거·추론 경고와 실제 `/row`·`/cards/all` 경로를 제공한다. 새 환불 관계를 추정하거나 원본을 쓰지 않는다. 이 링크는 기존 업무 접근이며 React 편집 화면으로 새로 이식했다고 주장하지 않는다.
- 후속 영향 `50318f5f→3c0672a2`: **173 passed, skip0, 실패0, pytest exit0, compile exit0**. 원본 `.agents/quality-final-v11/`. 여기에는 접근 제어·부분 환불·OTA 보호·Plush API/정적 통합 검사가 포함된다. 이후 보완은 frontend만이며 최종 프런트 검사는 별도 기록한다.
- C 항공권 `9976e5b9`와 root 경로 `b604327b`: 기존 이름 검색/더보기, 예약 시스템 여행 ID의 명시적 입력, 실제 후보 조회·COST 내부 연결·취소/충돌/오래된 근거 차단을 연결했다. root 항공권6+URL3건과 타입 검사 통과. E 참가자/예약 `a8258425`는 실제 link/unlink·저장/반영을 연결했고 root 표적2건 통과. 독립 재검수에서 후보 입력 변경 시 이전 후보 폐기, 미저장 예약 변경 시 이전 저장 계획 반영 차단을 추가 요구했으며 이 두 수정 전에는 릴리스를 승인하지 않는다.
- 기존 TaskSpace53이 닫혀 없어졌음을 확인하고 ego 사용 절차의 closed-space 규칙으로 TaskSpace54를 만들었다. 사용자 제어 공간44는 재조작하지 않았다. 새 합성 DB에서 실제 UI 승인 후 pending0/연결 생성, 이어 해지 후 연결 제거·오류0을 확인했다. 이 작업은 운영 계정/금융 자료와 관계없다. 운영 인증은 읽기 전용 workflow200/ready200 코드만 확인했다.
- 릴리스 준비 도구는 빌드 전후 HEAD와 `frontend` 추적 변경뿐 아니라 미추적 파일도 없는지 확인하고, 소스 Git blob·추가 빌드 파일의 SHA-256을 검증한다. 별도 Vite `.env` 파일은 없었다. 최종 빌드 산출물과 실제 배포 결과는 아래 단계 근거를 최신 기록으로 대체한다.

## 2026-11-16 최종 통합 검증 (운영 전환 전)

- 선행 Terra 운영 SHA는 `1f43642605e72794452b71e38337829a9983c202`이다. 영수증 감독의 공식 배포 성공·보호14표 불변·health/ready200과 배포 소유권 해제를 확인했다. 해당 코드와 main PR973을 병합했고 완료 문서 `279eba41`은 `84f8d32e`로 반영했다.
- D 원본 `5e2aaacf` / `5e2bd55c` / `1c888f37`은 통합 `1b9e7487` / `5b94e67b` / `fd13cbee`다. 실제 원천 계약·월 정수 키·수입/지출 합계·장부 항목·allocation allowlist·Google 문자열 금액·만료 snapshot을 확인했다. 직접 Python Plush **41 passed**.
- 기준 `origin/main`→`1b9e7487` 영향 검사는 **778 passed, 35 subtests passed, skip0, 실패0, exit0**. 후속 `1b9e7487`→`50318f5f` 영향 검사는 **565 passed, 26 subtests passed, skip0, 실패0, exit0**, Python 컴파일과 Rust release build 통과다. 후속 실행 중 병합된 main 코드는 이미 통합한 Terra와 동일하며 이후 Python 변경은 없다. 원본 결과는 `.agents/quality-origin-1b9-preserved/`와 `.agents/quality-final-delta-v9/`에 보존했다.
- E `50318f5f`의 규칙·내보내기·GET 결과와 C `511df99`→`67dce2fd` Google 화면, `7a75d603` 경로 통합 후 프런트 **43 passed**, 타입 검사·빌드 통과. 글꼴 경고는 기존 런타임 경로이며 실제 font 응답200을 별도 확인했다.
- 독립 `gpt-6.1-sol` medium 검수는 `7a75d603`에서 Google 숫자 금액/연결 revision과 규칙 사례 전환 미리보기 오류, 참가자·예약 기존 쓰기 누락을 발견해 CHANGES_REQUIRED였다. Google은 실제 reconciliation 정수 금액과 객체 revision/정수 links_revision 응답으로 회귀5건 실패를 재현한 뒤 `05ae7d19`로 수정했다. Google **12 passed**, 타입 검사 통과. 대조 요약의 정밀 문자열은 숫자로 바꾸지 않으며 안전한 정수 응답만 문자열로 받아 표시한다. 나머지 보완과 최종 SHA 재검수 전까지 운영 배포를 하지 않는다.
- 새 임시 DB의 실제 서버+ego-browser53에서 내보내기·규칙·참가자·보험·예약 화면을 열었다. XLSX 생성은 서버 ready를 확인하고 다운로드 GET200, XLSX MIME·ZIP signature·36,837bytes를 확인했다. 연결된 원천이 없는 TSV·참가자/보험/예약은 실제 이유를 표시하며 성공으로 만들지 않는다. 합성 자료만 사용했다.
- Google 화면은 owner1440/390px 가로 넘침0·연결 없음 사유를 표시하고 viewer 직접 화면에서 관리자료를 노출하지 않으며 API403을 확인했다. Google 실데이터 동기화·최종 시트 쓰기·실제 금융 apply는 수행하지 않았다.
- P-08 자동화 성능 한계와 실기기·스크린리더 미검증은 아래 측정대로 유지한다. graph.json·graphify CLI가 없어 `graphify update .`는 명령 미발견으로 실패했다.

아래는 단계별 검사 이력이다. 현재 상태는 이 절과 최신 운영 기록을 우선한다.

## 2026-11-16 승계 후 직접 검증

- 통합 작업 폴더와 기존 C/D/E 소유권을 유지했다. 영수증 선행 운영 배포 `11267cd0`를 포함한 main을 `8d39ef5a`로 병합했고, 영수증 완료 문서 `27e15d74`는 `a9c31f7e`로 통합했다. Plush 운영 배포는 아직 하지 않았다.
- 기존 광범위 검사 기준 `b46e4a92`: pytest 본 검사 1,475건 통과·기존 간헐 실패 1건·하위 검사 106건 통과, skip0. 품질 도구의 요약은 알려진 실패 분리 정책에 따라 PASSED이나 pytest exit1을 함께 보존한다. 이 사실을 실패0으로 표현하지 않는다.
- 해당 업로드 복구 검사(`test_committed_upload_recovers_truncated_or_stalled_response_body`)를 현재 통합본과 기존 main 작업 폴더에서 각각 재실행해 각각 1 passed·2 subtests passed를 확인했다. 관련 구현과 테스트의 Git blob이 기준 main과 동일하고 원본 폴더에도 두 파일의 변경이 없었다. 테스트·기대값·운영 코드를 바꾸지 않았다.
- `a9c31f7e`의 후속 영향 검사 `python tools/run_quality_checks.py --base b46e4a92 --run`: **62 passed, skip0, 새 실패0**, 자료 보호·컴파일 통과. 기존 광범위 검사와 이 후속 검사의 범위를 구분한다. 최종 C/D/E 통합 후 영향 검사는 다시 필요하다.
- 프런트 **18 passed**, 타입 검사·정적 빌드 통과. 서버 Plush·배포 보호 표적 **41 passed**. 실제 실행 로그는 통합 worktree의 `.agents/`와 `quality-artifacts/`에 보존한다.
- ego-browser TaskSpace53의 실제 합성 서버에서 영수증 원본 너비를 키보드로 50%로 조절하고, 확대 창 Tab/ShiftTab 내부 유지·Esc 후 실행 버튼 초점 복귀를 확인했다. 320/390/720/1440px에서 문서 가로 넘침0. `accessibility-v8.png`를 직접 시각 확인했다.
- C Google 비교·연결·복사, E 규칙 대화·내보내기, D 실제 원천·편집 계약 보완은 기존 작업자가 계속한다. 최종 SHA 독립 검수·PR971 병합·검증 운영 배포는 대기 중이다. 실제 구독 모델 판독은 선행 영수증 작업에서 확인된 Claude 로그인 차단을 유지하며 합성 runtime 검증과 구분한다.

- `c733272e` PDF 회귀는 1건 실패를 먼저 확인한 뒤 수정, 영수증 표적3건·빌드 통과. 일반 이미지 목록과 PDF 페이지의 같은 SHA를 단일 원본 표시로 합치고 관련 PDF 원본 링크를 보존한다. 실제 합성 PDF 업로드/재업로드에서 원본 표시1·PDF 링크1·실패0, 원본 GET200/application/pdf/862bytes/`%PDF-`를 확인했다. 모션 감소에서는 테마 transition과 spring token이0초, 로컬 글꼴 GET200/font/woff2를 확인했다.
- 목록 성능(P-08): 같은 합성 DB(장부 반영 검사 후 해당 여행1,004행)에서 React는 DOM50행·서버 페이지, 기존 화면은 DOM1,006행(합계행 포함)이었다. 전경 입력20회→두 번째 animation frame p95는 React973.7ms·기존976.4ms로 200ms 목표를 충족하지 않았다. 양쪽에서 프레임 대기가 지배했으며 별도 무작업 scheduling probe도 frame170.1ms/microtask0.3ms/timer1.5ms였다. 이 자동화 환경의 수치를 JS 처리시간이나 실제 사용자 체감 향상으로 해석하지 않는다. 초기 navigation 단일 측정도 React6,677ms/기존2,667ms로 네트워크·자산·서버 업무 응답의 범위가 달라 성능 개선 근거가 아니다. 실제 전경 환경의 paint 성능은 미검증으로 남기며 페이지/필터·합계 정확성 검사와 구분한다.

아래는 앞선 통합 단계의 이력이며, 현재 수치와 남은 작업은 이 절을 우선한다.

정본: [전체 설계](../../design/m4-plush-ui-20261116.md), [실행 계약](plush-ui-implementation-contract-20261116.md). 현재 사용자 지시는 모든 구현 재개와 운영 배포다. 영수증 감독의 선행 배포를 통합한 뒤 Plush 배포를 수행한다. 운영 DB/고객 원본 변경·실제 모델 호출·Google 자동 쓰기는 범위 밖이다.

## 작업 상태

| 대상 | 상태 | 실제 근거 / 남은 일 |
| --- | --- | --- |
| UI-0 계약·기능 지도 | IN_PROGRESS | D/B/C/E 후속 세션이 실제 API·저장 payload·revision·산출물을 재대조 중. 계정 exact POST·binary 응답 수정 `088b1731` |
| UI-1 공용 기반 | INTEGRATED | `58fd9143`, 타입·빌드 통과, Plush 고정 소스/MIT·Pretendard/OFL 보존. 기존 글꼴 재사용 `648d5a13`, 본문 건너뛰기·단일 main `3c4c45ed` |
| UI-2 셸·대표 화면 | INTEGRATED | `/ui/*` 라우팅·인증 bootstrap·일곱 도메인 연결. ego-browser53에서 390/1440 light/dark, viewer 탐색·서랍 키보드·검색 확인 |
| UI-3 여행·장부·산출물 | IN_PROGRESS | HTTP 정확한 정수/부호/페이지 합계 통과. 브라우저 검색 조회1002/전체502500 분리 확인. B/D 후속의 교정·마감·산출물 계약 보완 대기 |
| UI-4 영수증 | IN_PROGRESS | React 구현 통합. C 후속이 최신 서버 계약/초점 보완 중. 영수증 감독의 실제 배포 SHA와 backend 통합 필요 |
| UI-5 거래·관리·보조 | IN_PROGRESS | 화면 통합·브라우저 진입 확인. D/E 후속이 실제 projection·descriptor·요청값을 보완 중 |
| UI-6 최종 검증·전환 준비 | IN_PROGRESS | 프런트10건·Python30건 통과. 독립 사전 검수 진행. 영향 검사는 영수증 테스트 파일 누락으로 실패; 최신 영수증 SHA 통합 후 재실행·최종 SHA 검수·배포 필요 |

## 감독 직접 실행 근거

- 통합 branch `integration/plush-ui-20261116`, 공식 worktree `C:/Users/kkokk/.paseo/worktrees/28lt5mey/plush-ui-integration-20261116`.
- D 공용 DTO/client 초안 `71f018ce`를 통합 `7295f5b3`으로 반영. 초안만으로 backend 완료를 주장하지 않는다.
- `python -m pytest webapp/tests/test_plush_ui.py -q` → **20 passed, 0 skipped**. 정적 build 경로 제한·인증·실제 HTTP owner/viewer 셸 제공·익명/미등록/만료 세션 차단·원본 소스 및 경로 탈출 차단·빌드 누락 503 검증. 앱 화면·API projection 전체 검증과 구분한다.
- 정적 HTML을 기존 서버 셸로 감싸지 않으며 업무 데이터를 HTML에 주입하지 않는다. 새 진입점은 `/ui/`이고 기존 업무 URL/작성 경로는 유지한다.

## 후속 직접 검증과 미검증

- `dfe6bc4f`: viewer fixture가 실제 신청→승인→활성 연결을 거치도록 보완했다. 권한 검사·기대값은 유지했다. jsdom Blob과 Node Response의 혼합을 제거하고 API 테스트는 Node 환경에서 수행한다.
- Python Plush 표적 30건, 프런트10건, 타입·빌드 통과. 다운로드는 이진 바이트까지 검증한다. Git 자료 보호 검사 차단0건. graphify 그래프·실행 파일은 이 worktree에 없으며 update 실행도 명령 미발견으로 실패했다.
- 합성 DB1,003행·ego-browser TaskSpace53. 1440/390px light/dark 캡처, 가로 넘침0, viewer 허용 여행만/쓰기 비노출, 상세 Tab·ShiftTab 순환/Esc/초점 복귀, 검색1행·조회1002/전체502500 확인. 홈·여행·거래·계정 화면 진입에 렌더 오류·가로 넘침 없음.
- 영수증 복귀·충돌·응답 유실·원자적 반영의 최신 서버 통합, 모든 업무 쓰기/산출물 완전성, 모션 감소·200% 확대·전체 대비, 영향 검사·독립 최종 SHA·실제 배포는 남아 있다. 실기기·스크린리더 실청취는 미실행이다.

## 다음 행동

후속 B/D/C/E 커밋과 선행 영수증 배포 SHA를 통합한다. 영향 검사의 실제 누락 파일 문제를 해소하고 독립 최종 SHA 검수·검증 배포·운영 smoke로 이어간다. 실행 가능한 항목이 남아 있으므로 이 문서는 완료 보고가 아니다. 로컬 복구 체크포인트는 `.agents/plush-integration-checkpoint.json`에 둔다.
