# M3·M4·M5 보완 실행판

현재 승인: 2026-11-17 사용자 “네 판단대로 보완사항 모두 진행해”, 낮은 추론 난도의 구현·검사는 Luna xhigh, 주 에이전트는 통합 감독. 기준 main `81ea5c9f26d67cd952e1786b4b9303243a543370`. 정본 SPEC/DECISION_POLICY와 감사 보고서 F-01~07을 따른다. 과거 완료 작업은 재실행하지 않는다.

## 실행 큐

| ID | 요구사항 | 상태 | 작성자/완료 조건 |
| --- | --- | --- | --- |
| R1 | F-02 저장 완전성 진단과 안전한 decisions-only 보완 | PARTIAL | 새 운영 복사본 감사 missing 2,585·분류변경 필요 60·보호/보존 3,984. 신선한 기간 근거 확인과 운영 누락0은 남음. 복사본 복원·보완·재실행 검사 진행 |
| R2 | F-03/04/05/06 React 저장기간·404·320px·분류대기 | PARTIAL | 저장기간 DTO·404·대기 의미 제거·CSS 보완과 표적 테스트 통과. Windows Chromium 재검증 남음 |
| R3 | F-07 추출기 고정 입력/출력/의존성 재현 manifest | PARTIAL | 이전 입력 사본 경로 소실 확인. 1.76GB 생산 DB 읽기 전용 새 capture/검증 진행. 긴 원문 전체 정렬 대신 typed 행 해시 multiset으로 논리 지문 계산 |
| R4 | F-01 M5 영속 큐·임대·상한·재시도 | COMPLETE(코드/합성 범위) | 원자 claim·만료/경합·토큰 fencing·중복/예산·재시작 테스트 통과 |
| R5 | F-01 M5 server/node·P2 실행기·이식 패키지·역방향 백업 | PARTIAL | 누락된 P2 adapter·백업 HTTP/노드 연결 및 Windows WAL/fsync 수정. 실제 Rust 실행 파일/HTTP/node/복원 합성 검사 통과. 실제 클라우드·PC-off·신선한 일일 스냅샷 운영 검증 남음 |
| R6 | F-01 요청 계수기·실측 시작 | COMPLETE(코드/합성 범위) | 고정 ID·상태·본문 바이트 계측과 재시작/오류/비노출 테스트 통과. 운영 배포 미실행 |
| R7 | M4 P-01~10 미검증 수락 보완 | PARTIAL | 1,000행/10페이지 전체 집합·순서·중복 및 검색100행 통과, API 내부 p95 25.392ms. 프런트151건/빌드 통과. TSV/XLSX·느린 응답·재시도 검사 추가 중, 실기기/SR/브라우저p95 미검증 |
| R8 | 통합 검사·정확SHA 독립 검수·병합·공식 배포 | PARTIAL | 구현 7dd4c3b6 통합. 독립 sol 36건 PASS, HTTPStatus/백업 임시사본 누적 추가 수정 중. 문서 EOF 공백 게이트 수정 후 최종 SHA 영향검사·검수 필요. 운영 미배포 |
| R9 | 실제 클라우드 이전 | BLOCKED | 제공자/계약/과금/국외처리 사용자 결정과 요청량 실측 필요. 정본 게이트로 실제 이전을 실행하지 않으며 전체 M5 완료를 선포하지 않음 |

## 소유권과 보호

- 모든 구현은 공식 Paseo worktree `m3-m5-remediation-20261117`에서 파일 소유권을 분리한다. git index/commit은 감독만 쓴다. 기존 C:/AX/cost의 dirty 변경은 보존한다.
- Luna는 고객 원문·운영 호스트를 읽지 않는다. 운영 조회/자료 보완은 감독만, DB/config/runtime 작성자는 배타적으로 조율한다.
- 테스트 기대값/골든·보호 경계를 낮추지 않는다. 운영 포트8751/8752/8790을 시험에 바인딩하지 않는다.
- 실제 실행·SHA·로그·미완료/차단·다음 명령을 이 파일과 인계에 누적한다. 자원 전환 전에 체크포인트를 남긴다.

## 검증 기록

아직 새 보완 코드의 PASS/배포를 주장하지 않는다. 감사 때의 검사 결과는 원인 파악 근거이며 새 변경 검사를 대체하지 않는다.

## 2026-11-17 후속 세션 복구 체크포인트

- 정본 인계 d0070ad6 handoff.json과 family manifest 확인. 이전 부모는 재개하지 않았다. originalScopeVerified=true.
- 대상 작업공간: `C:/Users/kkokk/.paseo/worktrees/28lt5mey/m3-m5-remediation-20261117`, 브랜치 `integration/m3-m5-remediation-20261117`, 복구 HEAD `1558fd98`, 완료 커밋(현재 HEAD). `C:/AX/cost-recent-trips`는 다른 세션의 최근 여행 배포 작업공간으로, 이 작업의 구현 대상으로 삼지 않는다.
- 초안 29개 항목 보존. R1 completeness/decisions-only와 R2 화면, R3 manifest, R4 queue, R6 counter는 구현 초안이며 완료·배포를 주장하지 않는다. 이전 native 작업자 셋은 모두 usage-limit FAILED이고 실행이 이관되지 않았다.
- 기존 완료 감사 결과는 보고서와 실제 파일 근거로 재사용. 실패 queue 이벤트 `411d24b25348207a0d11c3f52d8a46ae304951ab0513ffc4210b38ebf3e5c100` 소비.
- 새 Luna xhigh salvage 작업자: `/root/m4_salvage` R2, `/root/m5_queue_salvage` R4, `/root/metrics_baseline_salvage` R3/R6. 같은 파일의 기존 초안을 이어받으며 index/commit/운영 작성 금지. 감독은 R1·HTTP 계수 배선·R5·R7·통합 검수 소유.
- R5/R7/R8 미실행. R9 실제 이전은 제공자·국외처리·과금 사용자 결정이 필요하며 독립 구현은 계속한다. 제공자를 임의 선택하거나 전체 M5 완료로 표시하지 않는다.
- 운영 배포 우선권은 최근여행 후속 `9957ecb9`가 유지한다. 본 세션은 아직 DB/config/runtime 쓰기 없음. 준비 완료 후 actual SHA와 단일 작성자 창을 다시 조율한다.
- 바로 다음: R1 completeness의 합성 반례/계약을 검수하고 audit/repair CLI 검증 → R6 handler/runtime 연결 → R5 server/node/P2 replay와 백업 이식 구현. 표적검사 이후 영향검사·최종SHA 독립검수.

## 2026-11-17 통합 검증 결과

- 작업자 위임은 `gpt-6-luna` 호출 용량 초과로 실행되지 않았고, 동일 범위의 구현·검증은 감독자가 직접 이어서 수행했다. 사용자 요청의 Luna 위임 의도는 유지했으나 실제 작업자 완료를 주장하지 않는다.
- `python -m pytest tests/test_m5_runtime.py tests/test_http_request_counts.py tests/test_extractor_baseline_manifest.py tests/test_plush_periods.py tests/test_stored_period_records.py webapp/tests/test_http_counting.py webapp/tests/test_plush_api.py webapp/tests/test_plush_primary_routes.py webapp/tests/test_plush_ui.py -q` → **120 passed**.
- `npm test -- --run` → **24 files / 143 tests passed**. `npm run build` → 성공(폰트 런타임 경고와 번들 500kB 경고는 기능 실패가 아님).
- `cargo test --workspace` → **전체 통과**(core 110, jobs 15, apply 14 등 포함). `cargo clippy --workspace --all-targets -- -D warnings` → **통과**. P2 어댑터 오류 문자열이 임시 JSON 버퍼를 참조하던 컴파일 오류를 정적 오류 코드 매핑으로 고쳤고, `chunks_exact` clippy 오류도 수정했다.
- `git diff --check` → 통과. 운영 포트·운영 DB·고객 원문·배포는 사용하지 않았다. graphify 실행 파일(`graphifyy 0.9.111`)의 Python Scripts 경로 누락을 사용자 PATH와 `C:/Users/kkokk/.local/bin/graphify.cmd` shim으로 복구했고, `graphify update .` 및 제한 질의를 성공시켰다. 갱신 시 SQL parser 미설치 경고 1건은 남았지만 Python/Rust/TypeScript 그래프는 재생성됐다.

### 요구사항별 현재 판정

| 항목 | 상태 | 근거와 남은 조건 |
| --- | --- | --- |
| R1/F-02 저장 누락 진단·decisions-only 경로 | PARTIAL | Rust 저장 감사/보완·보호·재실행 0건 합성 테스트 통과. 실제 2,636행 운영 backfill과 신선 백업·복원은 실행하지 않음. |
| R2/F-03~06 React/API 계약 | PARTIAL | 저장 기간·수동 공란·stale/inferred/verified DTO, HTML 404, 분류대기 의미 제거, 320px CSS 보완 및 표적 테스트 통과. ego-browser 320px probe도 overflow=0으로 통과했지만 P-01~10 전체 수락은 남음. |
| R3/F-07 재현 manifest | PARTIAL | 추출 baseline manifest 표적 테스트 통과. 생산 입력 사본과 live 원본의 동일성 결속은 운영 자료 없이 확정하지 않음. |
| R4/F-01 Rust 영속 큐 | COMPLETE(코드/합성 범위) | 원자 claim, fencing, dedupe, retry, budget, restart 테스트와 P2 계약 테스트 통과. |
| R5/F-01 server/node·P2·백업 | PARTIAL | provider-independent server/node, HTTPS 경계, P2 Codex/Replay, 백업 pull/복원 코드가 존재하고 표적 런타임 테스트 통과. 실제 클라우드 이전·PC-off·일일 운영 백업은 미실행. |
| R6 요청 계수기 | COMPLETE(코드/합성 범위) | 실제 read/write 경계에서 고정 route·method·상태·본문 바이트만 집계하고 재시작/오류/비노출 테스트 통과. 운영 계측 배포는 미실행. |
| R7 M4 P-01~10 전체 수락 | NOT_STARTED | 이번 검증은 발견 결함과 표적 계약만 다룸. 1,000행 p95·확대·실기기·스크린리더 전수 근거 필요. |
| R8 통합 커밋/배포 | PARTIAL | 통합 커밋은 완료했지만 push·공식 배포·운영 smoke는 실행하지 않음. |
| R9 실제 클라우드 이전 | BLOCKED | 제공자·계약·과금·국외 처리·운영 인증과 사용자 결정이 필요. |

다음 정확한 작업은 R1의 운영 적용 전용 백업·복원 게이트를 감독하고, R2의 Windows Chromium 320px 재현을 독립 실행한 뒤, R7 수락 증거를 범위별로 채우는 것이다. 이 문서의 PARTIAL을 M3~M5 전체 COMPLETE로 승격하지 않는다.
- 추가 브라우저 검증: `frontend/dist`를 loopback `127.0.0.1:60204`의 일회성 정적 서버로 제공하고 ego-browser Chromium을 320px로 고정했다. `innerWidth=320`, `clientWidth=320`, `scrollWidth=320`, `overflow=0`을 확인한 뒤 서버·TaskSpace·스크립트를 종료했다. 운영 포트는 사용하지 않았다.
