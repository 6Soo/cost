# 2026-11-16 브랜치·작업공간 통합 및 보존 근거

현재 사용자 요청은 모든 임시 workspace·브랜치 병합/정리와 전체 문서 정리다. 이 기록은 통합한 변경과 실제 미병합·보존을 구분한다. [현재 상태](../session_handoff.md), [작업판](../agents/BOARD.md), [PR #967](https://github.com/6Soo/cost/pull/967)을 함께 따른다.

## 시작과 복구 사본

- 시작: `origin/main 36ae40e8`, worktree 23개(존재 폴더 22개), 로컬·원격 추적 브랜치 참조 213개. stash 없음.
- Git 전체 bundle을 만들고 `git bundle verify` 성공을 확인했다. 원래 브랜치 tip은 `refs/archive/20261116/local/<이름>`·`remote/<이름>`에 보존했다. detached worktree는 제거 전 별도 `worktrees/<폴더>` 참조도 만들었다.
- 존재 폴더 22개의 작업/index binary patch, 미커밋·미추적·ignored 파일을 ZIP에 보존하고 파일별 SHA-256 및 ZIP 재읽기를 대조했다. 원본 `C:/AX/cost`의 기존 ignored 자료는 그 위치에 계속 보존했다. 재생성 가능한 `core/target` 산출물만 사본에서 제외했다.
- 비공개 정본: `C:/AX/cost/.local-archive/workspace-cleanup-20261116/`의 시작 인벤토리·검수·검사 근거, `D:/CostWorkspaceArchive/20261116/`의 `manifest.json`·폴더별 ZIP·`refs-before.bundle`. 고객 원문은 Git·PR에 넣지 않았다.

## 병합·보존 판정

| 대상 | 처리와 실제 근거 |
| --- | --- |
| 영수증 판독 #966 | `4ea64c90` 병합. 최종 `0ac0a6be` agy Claude Opus 4.6 Thinking high APPROVE, 표적127+17 subtests·구현 영향1298 PASS. 이후 최종커밋 차이는 인계 문서뿐. 운영 배포 아님 |
| 카드 수집 #850 | #967 `d470eee2` 병합 완료. 실제 공급자·조회 기간·건수·원본 해시가 맞지 않으면 거부하는 경계 유지. 352/352 영향 검사 PASS·skip0·Rust 빌드. 라이브 로그인·다운로드 미실행 |
| Booking identity `595a3cb0` | 미병합 보존. 합성 실제 gated importer에서 번호 없는 예약→명시 번호 A→다른 명시 번호 B를 각각 단독 재수집하면 모두 rc0, 최초 inserted1 뒤 duplicate1·duplicate1, 저장 행 수1·conflict0. 서로 다른 예약번호를 조용히 합쳐 예약이 소실되는 결함. 표적27 PASS만으로 승인 불가 |
| 승객 한글 이름 `be3a582a`·`cc6db329`·`b3b59167` | 미병합 보존. 오래된 입력의 별칭 저장이 최신 수동 별칭을 덮을 수 있음. 통합 후보9c5ef60d 영향1064 PASS/2 FAIL/16 subtests/skip0. 실패 테마 검사2건은 main4ea64c90에서도 동일 재현했지만 통과로 면제하지 않음 |
| 모바일 `18d7fc6f`·`98e4c7ff` | 미병합 보존. 긴 거래처와 날짜 겹침 검사 실패를 main4ea64c90에서도 재현(2 PASS/1 FAIL). 기대값을 낮추거나 정리를 위한 증상별 UI 패치를 추가하지 않음 |
| 화면 검사 정리 #849 / suite3 | 미병합 보존. #849는 실제24실패가 남은 검사 기대값 변경이며 닫음. suite3도 미완료·중단 기록과 검사 변경이므로 통째 병합하지 않음. owner_alias 검색 한 줄도 이 보존 범위에 남아 있으며 반영 완료라 하지 않음 |
| 테스트 격리 `bae02bd0` | 보존. 모듈 시간/상태 격리와 기존 UI 검사를 API로 바꾸는 변경이 섞여 있어 일괄 반영하지 않음 |
| `cards-all-static-assets` | main f83d6c0a의 실제 응답·MIME 검사로 상위 대체되어 옛 helper를 되살리지 않음 |
| OpenCode 격리 `65651278` | main fa675353이 실행기 자체를 제거. 죽은 경로 재도입 없이 보존 |
| P2 offline/stream | c34cd008 및 과거 작업판의 명시 중단 범위. 실험 코드를 재활성화하지 않고 보존 |
| 오래된 flight 추론·메일수집 설정 | 현재 저장 판정/연결 경로와 사용자 수집 OFF 결정을 되돌리므로 재병합하지 않음 |
| 분기검수 workbook `2408a6bf` | #818 계열로 상위 대체. 사용자 건별 검토 시트를 다시 넣지 않음 |
| 패치 동등·이미 main 조상인 브랜치 | 현재 코드를 덮지 않고 tip·전체 이력을 보존한 뒤 작업 브랜치만 정리 |
| 조사·운영·부분 작업 기록 | 정본·history의 기록과 원본 tip/bundle에 보존. 과거 제안·진행 상태를 현재 구현 완료로 바꾸지 않음 |

Booking 포함 2번째 영향 검사는 독립 검수가 실제 결함을 재현한 뒤 자체 검사 프로세스만 종료했다. 완료/통과로 세지 않는다. 최종 #967의 코드는 카드 수집 변경뿐이며, 352건 통과 이후 추가 변경은 문서다. 최종 SHA·모델·추론·판정은 PR 기록에 남긴다.

## 공간·브랜치 정리 결과와 남은 항목

- worktree **23→5**: 존재 폴더17개 제거, 이미 없던 등록1개 prune. 보호 사본·tip·사용 여부를 확인한 뒤 Git worktree 절차를 사용했다.
- Paseo workspace **12개 공식 archive**: 디렉터리 소유가 없는 등록은 archive 후 별도 Git 정리, 비공개 로컬 작업 폴더는 등록만 archive하고 자료를 삭제하지 않았다.
- 사용하지 않는 로컬 브랜치72개·원격130개 정리. 이 세션이 만든 중간 브랜치2개도 별도 보존 후 제거. main과 현재 체크아웃된 사용자/사용 중 브랜치는 남긴다. #850·#966·#967의 GitHub MERGED를 확인했고 #850/#967 원격 브랜치와 자체 통합 브랜치도 제거했다. 후속 문서 PR의 임시 브랜치를 제외하면 원격은 main과 HEAD 별칭만, 로컬은 main과 사용자/사용 중 체크아웃 브랜치4개만 남았다. 문서 PR 임시 브랜치도 병합 뒤 제거한다. 추가 삭제한 원격 tip도 시작 bundle·archive refs에 보존돼 있다.
- `C:/AX/cost`의 사용자 변경15개 파일은 원래 상태로 보존한다. 이 원본 폴더에서 main 강제 checkout·reset·stash를 하지 않는다.
- 남은 임시 폴더3개: `C:/AX/cost-wt-receipt-trip`(시작 시 확인 PID9456), `C:/AX/cost-wt-receipt-paseo`(agy·도구 프로세스), Paseo `receipt-uiux-integrated-20261116`(미리보기 PID11228·22404). 현재 `C:/AX/cost-wt-ota-perf`는 이 세션의 clean 검증 checkout이다(후속 문서 PR 동안 임시 브랜치를 사용하고 병합 뒤 main으로 돌아간다). 그 폴더도 현재 세션을 archive할 때 정리할 수 있도록 인계·검사·복구 근거를 원본 비공개 폴더에 복사해 두었다.
- 프로젝트 지침의 **내가 시작하지 않은 프로세스를 종료하지 않는다**에 따라 위3개 폴더를 강제 제거하지 않았다. 전체 임시 공간 정리가 완료됐다고 보고하지 않는다.

## 앞선 정리 시점의 재개 조건 (아래 후속 결과로 갱신)

1. 완료 코드 병합 `d470eee2fc0e4da6481ad409a41944e102d40216`에서 재개한다. 최종 `010a1693383864cab360d3bf7d7b3455f0e430da` 독립 gpt-6.1-sol / medium APPROVE와 동일 트리, #850·#966·#967 MERGED, 통합 원격 브랜치 제거를 확인했다. 실제 CI 검사 실패는 면제하지 않았고 최종 두 check 모두 결제 한도 미시작 annotation을 직접 확인했다.
2. 남은 것은 아래 사용 중 공간과 미병합 기능이다. 새로운 운영 배포·Rust 전환·원본 DB 쓰기는 하지 않는다.
3. 남은3개 폴더는 소유 세션이 프로세스를 종료했거나 소유자가 해당 프로세스 종료를 명시한 뒤, 새 미커밋/미추적 파일과 HEAD·사본을 다시 확인한다. Paseo 관리 폴더는 공식 archive, 수동 worktree는 Git worktree 절차로 정리한다.
4. 미병합 코드를 다시 검토할 때는 bundle을 먼저 검증하고 해당 archive ref에서 새 승인 범위의 브랜치를 만든다. 원본 복원은 별도 폴더에 ZIP을 풀어 `_snapshot/files.json`의 해시를 비교한다. 고객 원문을 추적 파일로 추가하지 않는다.

운영 `77865bfa` 유지, Rust 전환 승인① 대기. 이 요청을 운영 배포·Rust 전환·원본 DB 쓰기 승인으로 해석하지 않았다.

## 후속 완료 — 남은 4개 공간 제거·원본 폴더 최신화

- 사용자가 같은 정리 요청을 이어가며, 별도 질문에 임시 프로세스 종료를 명시 승인했다. 질문의 "8개"는 집계 오류였고 실제 열거·재확인·종료 대상은 **7개**다: Python PID9456·11228·22404, 도구 PID22752·29604·33976·36592. 이름·cwd·생성 시각이 모두 일치하고 운영 포트의 리스너가 아님을 확인했다. 공용 Codex app-server9192와 다른 프로젝트에서 PID가 재사용된 부모25860은 보존했다.
- `C:/AX/cost-wt-receipt-paseo`는 실행 중인 프로세스가 없음을 확인하고 공식 workspace archive 후 Git worktree 절차로 제거했다. 나머지 프로세스가 종료된 뒤 사용 중인 cwd가 0임을 재확인했다. Paseo `receipt-uiux-integrated-20261116`은 공식 archive로 폴더까지 제거, `cost-wt-ota-perf`는 공식 archive 후 Git 절차로 제거, 수동 `cost-wt-receipt-trip`은 Git 절차로 제거했다. 폴더의 절대 경로·공유 Git 저장소·clean 상태·main 조상·복구 사본 해시를 확인했으며 강제 제거하지 않았다.
- worktree **5→1**, 처음부터 누적 **23→1**. 원본 `C:/AX/cost`와 그 기존 local workspace 등록2개를 보존했다. 이번 Paseo 임시 workspace archive3개로 누적15개다. 다른 프로젝트 workspace는 정리 대상에 넣지 않았다.
- 남은 로컬 브랜치4개는 모두 main 조상이며, 기존 tip을 복구 참조와 bundle에 보존한 뒤 제거했다. 사용 중인 worktree는 같은 SHA의 detached 상태로 먼저 바꿔 파일 내용을 바꾸지 않고 브랜치를 해제했다. main은 원본 폴더로 옮겼다. 남은 PR 검수용 추적 참조7개도 `refs/archive/20261116-final/review-tracking/`으로 옮겼다. 이번 문서 PR 자체의 브랜치는 최종 검수·병합 후 제거한다.
- 원본 폴더의 미커밋15파일을 신선 ZIP에 보존했다. `core-bridge-golden` 영향 맵의 경로·검사 목록은 main 목록의 부분집합임을 확인했다. OTA 취소 예외3곳·설정형 제한시간·시간 초과 처리도 main의 확장된 자식 실행 경로에 반영돼 있다. 미커밋 코드2파일을 재적용해 옛 코드로 되돌리지 않았다. 오래된 로컬 인계와 감사 원문은 비공개 사본으로 보존하고 최신 문서로 맞췄다. 나머지11파일은 원래 경로에서 이전 해시와 동일하다. `.qwen/tmp/board-copy.sqlite` 등 기존 ignored 자료에도 쓰거나 지우지 않았다.
- 이번 복구 사본은 `D:/CostWorkspaceArchive/20261116-final/`의 `manifest.json`·`refs.bundle`·ZIP, 종료 후 사본은 `after-stop/`이다. ZIP의 파일 해시와 Git bundle을 검증하고, `restore-verified/`에 실제 복원하여 `_snapshot/files.json`의 SHA-256을 대조했다. 원본·작업/index 패치·HEAD도 보존했다. `restore-verification.json`에 결과를 남겼다. 재생성 가능한 `core/target`만 제외했다.
- 문서 검사는 README·AGENTS·docs뿐 아니라 `core/`·`ledger/`·`webapp/`·`tools/` README까지 추적 Markdown216개 전체로 넓혔다. 판정 정본을 역사적 금융/OTA 계약으로 안내하던 링크, 고정 여행 건수, 개발 당시 계획을 현재 상태로 읽게 하는 문구를 정리했다. 설계의 착수·미결 표시는 그 당시 기록임을 명시했다. 문서만 변경했으므로 앱 검사·브라우저·배포·운영 DB 조회는 실행하지 않았다.

최종 실행 근거는 `C:/AX/cost/.local-archive/workspace-cleanup-final-20261116/`에 보존한다. 이 후속 정리는 위의 Booking·승객 이름·모바일 실패나 중단 실험을 해결·병합한 것으로 간주하지 않는다. 해당 변경을 다시 다루려면 위 bundle과 archive ref에서 별도 폴더로 복원하고 현재 승인 범위·검사를 적용한다. 운영 `77865bfa` 및 Rust 전환 승인① 대기는 그대로다.
