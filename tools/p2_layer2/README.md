# P2 2층 오프라인 도구

운영 반영 경로는 없다. 고객 자료 입출력은 Git 제외 `.local-archive` 안에 둔다.

- `python -m tools.p2_layer2.index --backup <검증 백업 SQLite> --output <새 private SQLite>`: 메일 원문을 한 번 읽어 색인한다. 원본은 읽기 전용이며 기존 출력은 덮지 않는다.
- `python -m tools.p2_layer2.reachability --index <색인> --cases <private JSON>`: `rows`, `trips` 입력에서 T1~T4를 각각 측정한다. 금액 후보는 예약 연결 확정이 아니다. 원화 청구와 외화 원금액은 통화별로 따로 비교한다. 2026-04-01 이전 카드일은 제외한다.
- `python -m tools.p2_layer2.offline --case <private JSON> --output <새 private JSON>`: `case`와 `allowed_items` 입력을 도구 없는 구독 sol 실행기에 넘기고 원 응답과 가드 결과를 보존한다. `case`에는 `candidate_trips`, `existing_trip`, `evidence` (`ref`, `excerpt`)를 준다. 근거 없음은 스키마에서 기존 유지로 제한한다.
- `tools/p2_rules/register.mjs`: 승인된 규칙을 로그인된 ego-browser Page의 인증·CSRF API로 등록하는 helper다. 자동 재시도하지 않으며 체크포인트를 먼저 저장한다. 기존 211개는 이미 등록됐으므로 재등록하지 않는다.

2026-11-12 실측은 당시 임시 실행기로 수행했다. 이 재사용 도구를 운영 자료로 다시 실행하거나 추가 모델 호출을 한 것은 아니다. 역사적 결과와 정리 후 도구의 합성 검증을 구분한다.

## 이용기간 저장 경로 제안 (구현하지 않음)

P2 이용기간은 `app/ai_classification.py`의 `P2_METADATA`에 출처 `ai_inference`·근거 참조·실행 ID와 함께 보존하고, 인증된 `app/classification_correction.py` 경로에서 수동 값 우선으로 저장할 수 있다. `webapp/ledger_stay_evidence.py`의 `period_for`와 `webapp/ledger_design.py`의 이용일·지출내용 복사가 이를 읽도록 연결하는 최소 변경을 제안한다. 이번에는 채울 이용기간이 0건이므로 저장·표시 연결을 구현하지 않는다.
