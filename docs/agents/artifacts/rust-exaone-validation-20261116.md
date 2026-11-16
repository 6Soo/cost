# Rust 미결 구현 검증 — 2026-11-16

## 범위와 결과

사용자 요청 “rust관령 미결작업 exaone 다수에게 위임하여 구현”에 따라 SPEC M3 U12~14의 실제 미결 배선을 구현했다. 운영 Rust 전환·배포와 실자료 C1/C2 측정은 실행하지 않았다.

- 환불: `a55de0c6` Python 배선 + `056253df` Rust CLI. `refund-entries`와 `refund-check`가 기존 apply_pairs/check_groups/scope_group/비공개 issue_group을 소비한다. 응답은 귀속·차단·환불 표시만 갱신하고 원행 금액·부호·ID·수동 교정은 보존한다. 기존 Python 게시 트랜잭션에서 봉인 묶음의 최종 권한 상실 시 전부 롤백하며 Rust 실패의 조용한 Python 대체는 없다.
- 전환 사전검사: ExaOne `31feca83` → `a360f055`, 감독 보완 `c391d415`. 명시 사본·입력·바이너리·설정의 해시와 불변성을 확인하고 live alias/하드링크/심볼릭 링크/SQLite sidecar를 거부한다. 실제 그림자 실행과 양 영역의 동일한 양수 건수·PASS·목록 밖 차이 0을 요구한다. READY는 운영 승인·C2·백업/복원·전환 완료를 대체하지 않는다.
- 기준선: ExaOne `60492d7d` → `437125da`. PythonBridge 자식만 producer/classification_writer를 Python으로 고정해 Rust 대 Rust 비교를 막는다. 부모 환경은 바꾸지 않는다.
- 검사 중 발견한 기존 구형 스키마 읽기 계약: `8fbf60f0`. manual_rows가 이력 없는 row_id-only 스키마에서 field 열을 요구하지 않도록 보완했다. origin/main과 성능 이전 코드에서도 동일 오류를 재현했으며 성능 변경의 회귀로 분류하지 않았다.

## 위임과 통합

실제 모델은 OpenCode `exaone/k-exaone_v2.5`, build/medium 3명이다(high 조사 반복 후 추론만 조정). 모두 합성 자료만 사용했고 고객 원문·운영 폴더·운영 포트에 접근하지 않았다.

- 전환 사전검사 작업자는 구현과 20건 검사를 완료했다. 감독이 경계 5건을 추가해 25건으로 검증했다.
- OTA 작업자는 이미 main에 있는 e2a43e10/f5c91d95 수정의 합성 동등성을 확인하고, 별도로 발견된 Python 기준선 환경 결함을 구현했다.
- 환불 작업자는 초안을 작성했으나 컴파일·검증이 지연됐다. 감독이 소유권을 회수해 JSON 구문/참조 오류·null 입력·묶음 실패 전파·recordable 검사와 비공개 발급 경계를 완성했다. 새 초안의 잘못된 기대/fixture는 확정 계약에 맞춰 수정했고 기존 테스트·골든은 완화하지 않았다.

## 직접 실행한 검사

| 근거 | 실제 결과 |
| --- | --- |
| 기존 환불 골든 53 + 실제 장부 게시/멱등 재실행/권한 상실 롤백 3 | 실제 release 바이너리로 56 passed, skip0 |
| Python 환불 배선/기존 게시 + preflight | 50 passed, skip0 |
| 새 Rust CLI / core DTO | 4 / 1 passed |
| 기준선 환경 회귀 | 감독 직접 1 passed, 작업자 shadow CLI 전체8 passed |
| OTA 기존 Rust 골든 | 감독 직접7 passed, 작업자 differential9/9 |
| 구형 스키마 보완 | 새 회귀 red 확인 후 기존 포함8 passed |
| 공식 영향 검사 `--base origin/main --run` | cce2744f에서 Python923 passed, skip0/known0/오류0; release build·fmt·clippy·cargo workspace test 모두 exit0. Rust191 passed(compile-fail 문서 검사4 포함), ignored0 |
| 최신 UI main d088e1cb 통합 ddc22536 후 교차 검사 | 실제 바이너리 환불·기존 게시·manual reads·Plush API/통합97 passed, skip0 |
| 독립 코드 검수 | gpt-6.1-sol medium, 056253df 및8fbf60f0 APPROVE, 독립 표적42 passed. 최종 SHA 판정은 동일 PR에 기록 |

공식 검사 기준 SHA는 d088e1cb, 대상 SHA는 cce2744f다. 그 뒤 UI main을 충돌 없이 통합했다. 이 병합에서 Rust·환불 Python·사전검사 소스와 회귀 파일의 blob은 그대로이며 교차 검사97건을 추가했다. UI 자체의 변경은 해당 세션이 검증·배포한 upstream 내용을 보존했고 중복 프런트 빌드/브라우저 검사를 하지 않았다.

첫 공식 검사는 Python845 passed/기존 구형 스키마2 failed였다. 해당 실패를 면제하거나 known 목록에 넣지 않고 코드 보완 뒤 위923건을 통과했다. 원래 실패와 성공 로그는 로컬 검증 기록에 별도로 보존했다.

## 실제 합성 사전검사

release 바이너리 SHA256 `b3ec0c63b796cc32ae33d566ee1ac8e42b8cbca1fc928dcafc8a62bf99b5eb8d`를 명시해 실행했다. 원래 합성 fixture의 WAL은 DB_SIDECAR_PRESENT로 차단했고, 원본 보존 후 별도 DELETE-mode 사본에서 READY/exit0, 환불 Python1=Rust1·OTA Python1=Rust1, changed=[], 입력·설정 불변을 확인했다. 부모 환경을 Rust와 존재하지 않는 합성 costcore 경로로 지정해도 Python 기준선을 유지했다.

이는 보호 경로의 합성 DB/OTA 입력 검사이며 운영 사본·고객 자료 측정이 아니다. 과거 미해소 차이1648건은 e2a43e10/f5c91d95 이전 측정으로 확인했지만 현재 실자료 해소 여부는 미검증이다. C1/C2·승인①②·신선 백업/복원 확인과 운영 전환은 그대로 남는다. graphify graph.json과 CLI가 없었으며 graphify update는 명령 미발견으로 실행하지 못했다.
