# Mytrip 이식 독립 검수 (2026-11-21)

- 검수자: opencode / deepseek-v4.1-flash-free (자식 `f68451f5`, high, 읽기 전용 plan 모드)
- 대상: PR #1079, 커밋 `00ab8525` + 후속 수정
- 구현자와 다른 모델·다른 세션. 수정·커밋·테스트 실행 없음(문서만).

## 판정: APPROVE — 차단 0건

### 확인한 것 (file:line 대조)

| 항목 | 결과 |
| --- | --- |
| `strip` 후 시작 고정 매치 | `mytrip.rs:90`, `:173-177` — `match` 앵커 + 위치 0 검사 |
| `$`의 말미 개행 | `:29` `(?:\n?\z)` |
| 미인증 skip | `:87-89` |
| 취소 → 본문 전 주문 전파 | `:92-95` |
| `_facts` 무효 leg·연도 0 전체 기각 | `:195`, `:253-259` |
| totals 원본 문자열 집합 + `.00`만 + `\b` 후처리 | `:224-238` |
| 366 초과·amount ≤ 0 기각 | `:198-208` |
| distinct에 (기간, **금액**) 둘 다 | `:113-125` ↔ Python `:58` |
| `rows.last`의 period/amount/digest | `:123`, `:144` |
| `sorted` 집계 | `:86`, `:113`, `:124` |
| 25키 이벤트 | `:126-149` |
| `pyre` strip = `White_Space + U+001C..U+001F` | `pyre.rs:15`, `:867-869` |
| traveloka·airbnb 골든 무변경 | git diff |
| 골든 독립성 | 미변경 `mytrip_mail.collect`(`mytrip_golden.py:11,39`), 합성 `owner_record`, 덮어쓰기 거부(`:118-119`) |
| digest 재계산 | 첫 사례의 `source_digest`/`ota_event_id`/`observation_ids`를 stdlib 해시로 재계산해 일치 |
| 추가 전용성 | `app/`·bridge·commands·스위치 변경 0, Python 삭제 0, `extract.rs`는 mod+pub use만 |

### 비차단 지적과 처리

| # | 지적 | 처리 |
| --- | --- | --- |
| 1 | `WITHDRAWN`을 strip된 subject로 검사(`:92`), Python은 원문(`:48`) | 동작 동일 — 앵커 없는 패턴이라 `strip`은 공백 제거만 하고 판정에 영향 없음. 기록만 |
| 2 | 금액 i64 초과 이론적 발산 | 조사 문서 §9에 남은 항목, 보호 기준 사건에 영향 없음 |
| 3 | 골든 건수 가드가 `>=20` | **26 고정으로 변경** |
| 4 | `mytrip_golden.rs`가 impact map paths에 미등재 | **등재**(`airbnb_golden.rs`·`traveloka_golden.rs`도 함께) |

### 확인하지 못한 것

- 검수자는 읽기 전용이라 `cargo test`·`pytest`를 실행하지 않았다. 정적 대조 + 골든 digest 재계산으로 대체했다.
- 유니코드 테이블 전수 대조는 구현자가 별도로 수행했다(`WORD_CLASSES` 불일치 0).
