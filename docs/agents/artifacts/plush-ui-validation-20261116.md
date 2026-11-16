# Plush UI 구현·검증 현황

정본: [전체 설계](../../design/m4-plush-ui-20261116.md), [실행 계약](plush-ui-implementation-contract-20261116.md). 현재 사용자 지시는 다수 Luna xhigh 병렬 구현과 감독 통합이다. 설계 문서만 완료했던 과거 상태는 이번 승인으로 갱신됐다. 운영 배포·운영 DB 변경·실제 모델 호출·Google 자동 쓰기는 범위 밖이다.

## 작업 상태

| 대상 | 상태 | 실제 근거 / 남은 일 |
| --- | --- | --- |
| UI-0 계약·기능 지도 | IN_PROGRESS | 기존 경로·폼·권한을 D/E/B/C가 대조 중. JSON/form/multipart·CSRF·응답 유형 확장, 원본 PDF 읽기 공백 조정 필요 |
| UI-1 공용 기반 | IN_PROGRESS | A `d6edc1f8-9362-4e49-aa05-767c6db03e27`, 공용 props 공개. 완료 SHA·빌드·표적 검사 대기 |
| UI-2 셸·대표 화면 | IN_PROGRESS | A/B 구현 중. 감독 정적 경로·인증 hook `b5f781b6`; 기능 imports·route 조립 및 실제 렌더링 대기 |
| UI-3 여행·장부·산출물 | IN_PROGRESS | B `9d3ec45e-26c0-4fe0-92b5-28a9e3772ad7`, 서버 합계·복사·XLSX·교정·마감 검증 대기 |
| UI-4 영수증 | IN_PROGRESS | C `ebd6753e-df76-4cd1-8c97-9a62231851a2`, 별도 기존 영수증 서버 작성자와 최종 API·원본 PDF 연결 필요 |
| UI-5 거래·관리·보조 | IN_PROGRESS | E `0faa7c92-a628-4053-92ac-d974987b0e48`, D `74203d2b-cc24-461d-9824-a4cdade59c93`와 실제 descriptor 대조 중 |
| UI-6 최종 검증·전환 준비 | IN_PROGRESS | 도메인 통합·타입·빌드·영향 검사·ego-browser·최종 SHA 독립 검수 대기. 기존 주소의 기본 렌더러 전환은 아직 안 함 |

## 감독 직접 실행 근거

- 통합 branch `integration/plush-ui-20261116`, 공식 worktree `C:/Users/kkokk/.paseo/worktrees/28lt5mey/plush-ui-integration-20261116`.
- D 공용 DTO/client 초안 `71f018ce`를 통합 `7295f5b3`으로 반영. 초안만으로 backend 완료를 주장하지 않는다.
- `python -m pytest webapp/tests/test_plush_ui.py -q` → **20 passed, 0 skipped**. 정적 build 경로 제한·인증·실제 HTTP owner/viewer 셸 제공·익명/미등록/만료 세션 차단·원본 소스 및 경로 탈출 차단·빌드 누락 503 검증. 앱 화면·API projection 전체 검증과 구분한다.
- 정적 HTML을 기존 서버 셸로 감싸지 않으며 업무 데이터를 HTML에 주입하지 않는다. 새 진입점은 `/ui/`이고 기존 업무 URL/작성 경로는 유지한다.

## 아직 실행하지 않은 검사

React 타입 검사·프런트 테스트·빌드, 각 도메인 API 검증, viewer 허용 여행만 반환하는 projection, 합계·복사·내보내기 대조, 영수증 복귀·충돌·응답 유실·원자적 반영, 390/1440px·두 테마·키보드·모션 감소, 전체 영향 검사는 통합 후 실행한다. 실기기·스크린리더 실청취를 자동 DOM 검사로 대체해 통과라고 기록하지 않는다.

## 다음 행동

A/D의 검증된 중간 SHA부터 통합하고 B/C/E를 연결한다. 실제 실패를 해당 소유자와 수정한 뒤 표적 검사를 재실행한다. 실행 가능한 항목이 남아 있으므로 이 문서는 완료 보고가 아니다. 로컬 복구 체크포인트는 `.agents/plush-integration-checkpoint.json`에 둔다.
