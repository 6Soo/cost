# Plush UI 구현·검증 현황

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
