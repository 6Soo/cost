# 현재 상태

작성 기준: `2026-08-11`, `Asia/Seoul`

## 한 줄 상태

현재는 **Phase 1 연도 오류 차단까지 구현·독립 최종검증 완료** 상태다. Phase 2는
대만 여행탭 승격 설계가 Sol high에서 FAIL하여 구현하지 않았다. 후보는 게시하지 않았고,
실제 장부 전기·운영 배포도 하지 않았다.

## 저장소 상태

- 저장소: `C:/AX/cost`
- 브랜치: `codex/p07-canonical-cutover-candidate`
- 기준 HEAD: `243fb8240eddbbcd71133c0788f8561064c5a2e4`
- tracked modified: `41`
- untracked: `40` (인계 패키지 8개 파일 포함)
- worktree: dirty
- 변경사항은 사용자 작업으로 간주하며 reset/checkout/삭제하지 않는다.

## 현재 비용 분류 기준

활성 분류 축은 다음 세 가지다.

1. `account`
2. `cost_type`
3. `allocation_target`

VAT는 분류 축에서 제외한다. 수기·과거 장부는 거래 증거가 아니라 학습·대상 분류
자료다. 단, 사용자가 확정한 여행탭의 존재·지역·날짜는 강한 `allocation_target`
분류 근거로 사용할 수 있다.

## Phase 1: 연도 무결성

### 구현 내용

- 연도 없는 OTA MMDD는 결제일이나 메시지 발송일에서 연도를 추론하지 않고 보류한다.
- OTA의 명시적 ISO 행사일은 행사일의 실제 연도를 사용한다.
- 2025년 행사일을 2026년 일정에 연결하지 않는다.
- 2025년 결제일이라도 메일에 명시된 2026년 ISO 행사일은 유지한다.
- Gmail, 해외 현장 이용일, 여행 클러스터, 지역·숙박·예약·fallback 경로에 같은 연도
  검사를 적용했다.
- raw payload와 raw hash는 바꾸지 않고 `service_year=2026`을 파생값으로만 사용한다.

### 변경 파일

- `ledger/domain/direct_verified_ota_lodging.py`
- `ledger/domain/direct_geographic_trip_context.py`
- `ledger/domain/direct_high_coverage_classifier.py`
- `ledger/domain/direct_trip_cluster_registry.py`
- `ledger/domain/direct_projection.py`
- `ledger/tests/test_direct_high_coverage_classifier.py`

### 수치 비교

| 지표 | baseline | Phase 1 | delta |
|---|---:|---:|---:|
| prediction final eligible | 1,567 | 1,501 | -66 |
| prediction nonfinal | 3,078 | 3,144 | +66 |
| 기존 final → nonfinal | - | 67 | 보수적 보류 |
| 기존 nonfinal → final | - | 1 | 신규 확정 |
| Gate 5 final resolved | 2,250 | 2,184 | -66 |
| Gate 5 nonfinal | 3,078 | 3,144 | +66 |

기존 final → nonfinal 67건과 nonfinal → final 1건이라는 전이는 보존 DB와 재현 검토에서
확인된다. 다만 `55건 연도 미확인 + 12건 중복 방지`라는 세부 분해는 현재 보존 DB에서
동일 기준으로 재현되지 않으므로 검증된 숫자로 사용하지 않는다. 이 세부 설명은 역사적
검토 메모로만 남긴다. 확인된 전이는 잘못된 연도 확정을 제거한 보수적 보류 결과다.

### 수치의 모집단 정의

- `prediction`은 `direct_high_coverage_classifier_predictions`의 4,645행이다.
- Gate 5의 전체 후보는 5,328 payment다.
- prediction에 들어가지 않는 683건은 Phase 1 전후 모두 Gate 5 final로 유지됐다.
- 따라서 이 실행에서 `Gate 5 final resolved = prediction final eligible + 683`이고,
  `Gate 5 nonfinal = prediction nonfinal`이다.
- 두 수치를 같은 모집단의 비율로 해석하지 않는다.

### Phase 1 검증

- 로컬 대상 테스트: `57 tests, OK`
- Sol high 독립 최종검증: 관련 테스트 60개 통과
- Sol 판정: `VERDICT: PASS`
- Gate 5: `accepted_with_auto_provisional_queue`
- 전체 run: 완전 PASS 아님

### 남은 게이트 차단

- Gate 4: `han_equality_validation_missing_or_stale`
- Gate 6: 승인 baseline 부재
- 따라서 candidate 게시, 정본 반영, 운영 전기, 배포를 하지 않았다.

## Phase 2 후보: 대만

현재 후보는 `current_card_geography_context_exact_2026` 경로다.

- 실제 후보: 65건
- `overseas_default`: 57건
- `card_taxonomy`: 8건
- 2026-01-07~14 기간과 대만 표식을 가진 purchase
- 예시: `2026-01-11 TUNG PU HAI AN TAIPEI`, `2026-01-14 MODERN Taichung`

모집단은 세 가지를 혼동하지 않는다.

- 분류기 지리표식 후보: 65건
- 그중 계정 분류 경로 `overseas_default`: 57건
- 별도 `direct_taiwan_cluster_candidate.py` 후보 산출물: 66건
  - 대만 표식 65건에 Agoda 앵커 `AGODA.COM CHERNG YUA` 1건이 추가됨
  - 이 66건은 candidate-only 산출물이며 final·Gate 5 credit으로 승격하지 않음

Sol 설계검증은 `VERDICT: FAIL`이다.

실패 사유:

1. `0107_대만`은 canonical 일정표가 아니라 별도 geographic context target이다.
2. 일반 geographic context 전체를 final로 풀면 안 된다.
3. OTA·항공·결제대행·선결제 예약형을 새 경로에서 명시적으로 제외해야 한다.
4. 57건이 아닌 65건의 차이를 데이터 조건으로 설명해야 한다.
5. 새 경로에서만 배분 가능한 검증 일정으로 인정해야 한다.

Phase 2는 아직 구현하지 않는다.

## Kimi 검토

Kimi K2.7 전체 파이프라인 검토의 최종 판정은 `KIMI_VERDICT: FAIL`이다.

- unresolved를 provisional이라는 이름으로 바꾸는 것만으로는 해결되지 않는다.
- Yakushima `JPY 395,506`: 카드 2건 대 후보 1건이라 자동 확정 금지.
- Mongolia `578,500`: 카드 1건 대 후보 2건이라 자동 확정 금지.
- 0616 동일금액 3건은 동일 대상 불변 M:N 사례.
- 0813 일부는 실제 서비스일이 2025년이라 2026 대상 확정 금지.

## 주요 코드·데이터 상태

Phase 1과 이전 작업으로 다음 계열이 현재 worktree에 있다.

- direct current-card evidence/classifier
- direct cancellation settlement
- direct geographic trip context
- direct OTA lodging/reservation authority
- direct trip cluster registry
- direct independent evidence
- historical admission/replay/census 후보 코드
- current owner decisions 및 OTA live data

정확한 modified/untracked 목록은 `04_artifact_manifest.md`와 외부 snapshot을 기준으로 한다.

## 하지 않은 일

- 후보 DB를 운영 정본으로 승격하지 않음
- 워크북 생성·수정하지 않음
- 실제 장부에 전기하지 않음
- 외부 메일·드라이브에 메시지를 보내지 않음
- Phase 2 설계 FAIL 상태에서 대만 65건을 자동 확정하지 않음

## 인계 검증 결과

- 문서·JSONL·stable artifact 해시: `handoff-files.sha256` 8/8 및
  `manifest.sha256` 26/26 검증 완료
- 두 후보 DB `pragma quick_check`: 통과
- 두 후보 DB payment count: 각각 5,328
- 새 독립 검토자의 제한적 복원: `HANDOFF_RECONSTRUCTION: PASS`
- 전체 채팅은 66 turn 비식별 export와 그 이후 표시 continuation, 저장소 밖 보호 원문으로 보존했다.
- Kimi 두 세션은 내부 사고 필드를 제거한 보이는 이벤트 JSONL로 보호 보관했다.
- 대만 Phase 2는 읽기 전용 Sol 재현 원문을 보호 보관했고 `VERDICT: FAIL`를 확인했다.
- Sol Phase 1 재현은 첫 300초 wait가 시간초과했지만 지연 완료 응답이 도착해
  `VERDICT: PASS` 원문을 보관했다. 첫 시간초과 artifact도 삭제하지 않았다.
- 최신 독립 복원검사는 archive·handoff 해시는 통과했지만 역사적 Sol 원문 전체 부재와
  위 `55+12` 세부 분해 미재현 때문에 `HANDOFF_RECONSTRUCTION_FINAL: FAIL`이었다.
- 역사적 Sol 원래 반환값 전체는 앱 export에 노출되지 않았고, 전체 unittest discover는
  WSL 9P SQLite 대기에서 SIGINT로 중단되어 `exit_code=130`이므로
  `LOSSLESS_HANDOFF`는 아님
