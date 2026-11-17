# 2026-11-18 — M6 장부 테이블 통합

## 요청과 범위

사용자: "B를 별도 claude code opus 5.5 high 여럿에게 병렬 위임해서 빠르게 진행해. 겹치지 않는 범위에서 최대한 많은 병렬 에이전트를 생성해"

B = `transactions`·`ledger_entries`·`board_rows` 세 저장소를 단일 정본 `ledger` 테이블로 통합.

## 완료

브랜치 `m6-merge-20261118` (origin/main `259bc187` 분기), 커밋 9개, 21파일 +1,228줄.

| 커밋 | 내용 |
| --- | --- |
| `dc0b907f` | 공통 계약 `docs/design/m6-ledger-merge-contract.md` |
| `5a1c2a96` | `ledger` 스키마(41컬럼) + 이관 도구 `tools/migrate_to_ledger.py` |
| `79a3b1b3` | 이관 결함 2건(trip_id 누락·예행 롤백) |
| `050d11f3` | 기장 경로 이중 쓰기(ledger.py·quarter_tab.py·card_flow.py) |
| `f48954ef` | 교정 경로 동기화 5곳 |
| `8f1c1d24` | 저장소 화면 행 쓰기 16지점 동기화 |
| `63268a0a` | 수입·수기 필드 6개 + 품질 검사 그룹 등록 |
| `1f52b85e` | 판정 근거·OTA 근거 유실 방지 |
| `f73b93ea` | 중복 정리·일괄 확인 경로 보완 |

## 운영 적용 (2026-11-18)

- 백업 `D:/WebLedgerHost/data/backups/operational-20261117T203625318410Z` (board+core 2DB, 36파일, 복원 검증 `restored_review_binding_equal=true`)
- 적용 `D:/WebLedgerHost/data/board.sqlite`: 3,378행
- 검증: `board_rows` 3,378 = `ledger` 3,378, `transaction_id` 중복 0, 누락 0, 금액 425,696,924 불변, 탭별 합계 차이 0
- 근거 보존: `classification_source` 2,493 = 2,493, `ota_evidence` 12 = 12, 수기 행 4건 `transaction_id` NULL
- 서비스: readyz 200, 프로세스 유지, 보호 API 401(정상)

## 잡은 결함

| # | 결함 | 영향 |
| --- | --- | --- |
| 1 | `trip_id` 컬럼 누락 | 이관 행의 여행 연결 빈값 |
| 2 | 예행이 테이블을 남김(중첩 트랜잭션) | 예행이 DB를 바꿔 되돌릴 근거 소실 |
| 3 | 멱등 replay에서 UNIQUE 위반 | 환불 재시도 실패 |
| 4 | 미이관 DB에서 예외 | 기존 테스트 3건 실패 |
| 5 | `classification_source`·`basis` 누락 | 판정 근거 5,069건 유실 |
| 6 | `ota_evidence` 누락 | OTA 근거 12건 유실 |
| 7 | `ledger_entries`의 `trip_id` 미보완 | 134건 여행 정보 손실 |

5·6번은 운영 사본 전수 대조에서만 드러났다. 테스트로는 잡히지 않았다. `tests/card_pipeline/test_ledger_parity.py`가 고정하며, 고친 부분을 일부러 되돌려 검사가 실제로 실패하는 것을 확인했다.

## 검사

- 공식 `python tools/run_quality_checks.py --base origin/main --run`: **PASSED**, 2,004건, skip 0, 새 실패 0
- known 실패 1건: `test_an_audit_event_left_waiting_goes_out_through_the_old_path` — 저장소에 이미 등록된 항목. 단독·반복·baseline에서 모두 통과, 전체 스위트 순서에서만 실패하는 간헐 항목. 이번 변경과 무관함을 확인했다.
- 위임: 계정 동시 실행 한도(11/10)와 524 타임아웃으로 U2·U3·U4·U5가 반복 실패해, 대부분을 직접 구현했다.

## 미해결

**호남 0원은 해결되지 않았다.** 이관은 있는 행을 옮길 뿐 없던 기장을 만들지 않는다.

- `0118_호남`: 카드 거래 108건 배정, 장부 0건. 108건 전부가 2025년(17건)·2026년 1분기(91건)다.
- 원인은 테이블 구조가 아니라 **PROC-072**(`docs/policy/process.md:735`) 완료 기간 선행 제외다.
- 같은 상태의 여행 4개: 0107_대만(1,703)·0118_호남(108)·0124_아키타(136)·0214_조신에쓰(251).

### 다음 결정 (사용자)

| 선택 | 결과 |
| --- | --- |
| A. 완료 기간도 화면에 표시 | 호남 108건이 장부에 나온다. 세무 자료가 수정 가능해진다 |
| B. 규칙 유지, 화면에 안내 | 장부는 비고 "세무 제출 완료 · 카드 내역에서 확인" 표시 |

### 읽기 경로 전환

`board_rows` → `ledger` 읽기 전환은 아직 하지 않았다. 이관이 끝났으므로 이제 안전하지만, 별도 작업 단위다. 남은 `board_rows` 직접 참조 46곳(생산 코드).

## 확인한 것과 하지 않은 것

- 확인: 운영 DB 읽기 전용 조회, 일관 사본 백업 API, 이관 전후 전수 대조, 백업 복원 검증, 서비스 readyz.
- 원문·카드 행·금액·부호·ID는 바꾸지 않았다. 기존 `board_rows`·`ledger_entries` 데이터도 삭제하지 않았다(이중 쓰기 유지).
- 원격 push·PR·배포는 하지 않았다.
