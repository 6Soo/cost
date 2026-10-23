# 구조

## 현재 OTA 자료 연결

메일·포털·과거 조사 자료는 운영 `ota-sources.json`에 등록해 함께 조회한다. 자료 내용 변경을 감지하고 미연결 사유를 구분하는 수정까지 적용했다. 현재 연결 수와 남은 항목, 실제 검증 범위는 [OTA 문서](ota_mail.md)의 최신 항목을 따른다.

Import → Normalize → Classify → Review unresolved → Preview → Commit ledger.

app/의 여덟 Python 파일이 카드 처리의 핵심이며 OTA 메일, 여행 수집과 보류 처리는 같은 패키지의 별도 모듈이 담당한다.

```text
app/
  __init__.py       처리 흐름 연결
  import_card.py    실제 카드 양식과 원본 보존
  normalize.py      날짜와 금액 정규화
  classify.py       규칙과 명확한 업종 적용
  rules.py          재사용 규칙 관리
  review.py         답변과 수정 충돌 검사
  ledger.py         미리보기와 중복 없는 기록
  db.py             저장과 변경 이력
  ota_mail.py       예약 메일 분류와 카드 대조
  ota_portal.py     보존 Agoda 포털 근거의 읽기 전용 대조
  reserve_trips.py  출발 예정 여행 수집
  review_holds.py   취소·환불과 확인 대기 보호
webapp/
  card_flow.py      기존 로그인과 연결한 카드 처리 화면
  ledger_design.py  거래 테이블·모바일 목록·편집 패널
  ledger_board.py   기존 장부 API·수입·배분·출력
  ledger_store.py   장부 정본과 저장 충돌·중복 방지
tests/card_pipeline/
```

운영 DB는 D:/WebLedgerHost/data/board.sqlite 하나다. board_rows가 현재 장부이며 ledger_entries는 최초 기록 영수증이다. 장부 수정은 현재 장부와 수정 이력에 저장한다. 영수증을 별도 수정 가능한 장부로 사용하지 않는다.

카드 처리의 기본 테이블은 import_batches, import_batch_rows, transactions, cost_classification_rules, review_decisions, ledger_entries, change_log, requests다. transaction_review_holds는 취소·환불과 확인 대기를 보호한다. 원본 파일과 거래 내용, 분류 결과와 사용자 답변을 구분한다. 거래와 감사 이력과 장부 반영은 같은 DB 트랜잭션에서 처리한다.

기존 여행 관리, 입금, 로그인, 권한, 출력 기능의 호환 테이블은 유지한다. 운영 DB 전체가 네 테이블로 줄었다고 주장하지 않는다. 과거 검토 답변과 감사 이력은 이 DB에 이관했다. 이전 DB 파일은 복구용으로 보존하며 현재 쓰기 경로로 사용하지 않는다.

파일 fingerprint, stable transaction key, source hash와 기록 여부가 중복 방지의 핵심이다. 별도 shadow, baseline, 전환 gate 없이 처리한다. 명시 일정과 원본 hash 검증은 잘못된 여행 배정을 막기 때문에 유지한다.

AI 호출은 새 카드 처리 흐름에 없다. 규칙과 이전 사용자 결정, 명확한 업종으로 분류하고 나머지를 사람에게 질문한다.

## 현재 실행과 중복 방지

2026-10-08 기준으로 운영 카드 흐름은 기존 단일 DB를 사용한다. `app.ledger.recordable_rows()`는 blocked·already_booked를 제외한 고유 거래를 반환하며 미리보기 ready와 홈 집계가 함께 사용한다. 출력 화면과 작업 조회는 읽기 전용 SELECT를 사용한다. 장부 projection은 거래 ID를 먼저 검사하고 거래 ID가 없는 과거 행에만 카드사·카드·승인번호·일자·부호 있는 금액·거래 종류를 함께 비교한다. 승인과 취소를 같은 거래로 합치지 않는다.

명시 일정의 원본과 최신 근거가 맞지 않으면 기록을 차단한다. 서버 정상 여부와 모든 여행 일정의 검증 완료 여부는 별개다. 최신 운영 수치와 미결 항목은 [운영 문서](../../../docs/operations.md)를 따른다.
