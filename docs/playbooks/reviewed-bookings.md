# 보관 원문 검수와 미기장 예약 복구

공급자 파서가 읽지 못한 보관 원문은 AI가 직접 검수한다. 공급자별 패치를 추가하거나 카드 원문을 바꾸지 않는다. 검수 결과는 Git 밖 보호 저장소의 `data/reviewed-bookings/manifest.json`과 같은 디렉터리의 원본 파일로 보존한다. 이 파일은 사용자 결정이나 자동 매칭 결과가 아니라 신뢰된 로컬 AI 검수 자료다.

manifest v1은 `reviewer`(kind=`ai_review`, 실제 provider/model/run_id), `groups`를 가진다. 각 그룹에는 id, 실제 trip_id, item, service_period(starts_on/ends_on), basis, cards(transaction_id/source_hash/amount_krw/approval_date), originals(path/sha256/status/service_period/payments)가 필요하다. 원문별 payments에는 실제 paid_on과 amount_krw를 기록한다. 파일 경로는 보호 디렉터리 안에 있어야 한다.

`app/reviewed_booking_evidence.py`는 원본 바이트 해시, 카드 원천 해시·결제일·금액, 원문과 카드의 날짜/금액 다중집합, 동일 가맹점·날짜·금액의 카드 전체, 실제 여행의 이용기간 포함 여부를 매번 검사한다. 중앙 확정 근거와 기간 또는 여행이 다르면 중단한다. 같은 금액 여러 건은 묶음의 귀속만 증명하며 개별 예약번호나 금융 연결을 생성하지 않는다. 실제 수동 결정·원본 충돌·중복·환불·기완료 장부 보호를 유지한다.

먼저 보호 사본에서 현재 운영 Rust writer와 표준 기장 경로를 예행한다. 운영 적용 전에는 단일 작성자를 조율하고 신선 scoped 백업·복원 및 원본 불변을 검증한다. 검증한 보호 파일을 설치한 다음 기존 `card_completion_worker.queue_batch`에 정확한 batch/transaction 범위만 등록한다. 운영 worker가 원문 검수의 여행과 다른 미기장 자동 배정을 다시 분류하고 표준 preview/commit으로 기록한다. 별도 도구가 transactions나 ledger를 직접 수정하지 않는다.

완료 조건은 코드 배포가 아니라 대상 거래의 ledger와 board가 각각 정확히 한 번 존재하고, 귀속·금액·이용기간·검수 원본 해시가 일치하는 것이다. 원문·금액·날짜·ID·수동 결정과 대상 밖 금융 상태의 전후 불변을 검증한다. Google 최종 장부에는 쓰지 않는다.
