# Plush UI 구현·검증 현황

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
