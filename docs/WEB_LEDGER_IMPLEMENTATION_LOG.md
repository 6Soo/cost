# 웹 장부 구현 기록

## 최신 인계 — 2026-09-27

사용자의 전체 폴더 정리와 Git 게시 지시에 따라 검증된 최신 후보 42개 파일을
본 저장소에 반영했다. 상세 상태, 백업 위치, 이번 검증은
[최신 인계](handoff/2026-09-27/README.md)에 기록한다. 아래 미통합 표기는 당시 상태다.

## 통합 후보 검증 갱신 — 2026-09-26

최종 격리 후보 integration-candidate-final-20260926-01의 전체 검사 152개와 세부 검사 9개가 통과했다. 은행 동일 내용 재업로드의 추가 행 없음과 최종 후보의 Chromium 폭 390 사용자 경로를 확인했다. 실물 휴대폰 검사는 아니다.

Excel 전체 PDF 3쪽에서 수입 200000원, 지출 30000원, 수익 170000원을 코디네이터가 직접 시각 확인했다. 최초 누락은 검증 명령의 첫 페이지 제한 때문이었다. 물리 프린터는 미검증이다. 빈 공간과 합계의 페이지 분리는 사용성 개선 여지로 남으며 원본 양식과 시각적 완전 일치를 주장하지 않는다.

본 저장소 제품 코드 반영과 운영 전환은 아직 하지 않았다. 파일별 통합 계획을 준비 중이다. 아래 은행 대기 및 모바일 미검증은 과거 기록이다. Phase 6 이후를 포함한 전체 프로젝트 완료는 아니다.

## 최신 상태 정정 — 2026-09-26

이 절은 아래 과거 완료·모델 기록보다 우선한다. 구현 코드는 `C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`에 있으며 본 저장소로 아직 통합하지 않았다.

- 수용한 보완: 출력 고유 임시 파일·원자 게시, 배분 개별 행 편집·되돌리기와 화면 연결, 삭제 요청 내용 결속·동시 재시도. 세부 근거는 WEB_LEDGER_IMPLEMENTATION_REVIEW.md 10절과 작업자 보고서에 있다.
- 코디네이터 직접 확인: 출력 18개, 화면 26개, 삭제·저장소 23개와 세부 6개 통과. 이는 서로 겹치는 검사이므로 합산하지 않는다. 고정 비은행 후보의 작업자 결과는 124 passed, 5 deselected, 9 subtests passed다.
- ManualExpenseTests 중복 두 정의는 AST까지 동일했다. 한 개를 제거했고 코디네이터 재실행은 2 passed in 0.16s다. 고정 후보는 덮어쓰지 않았다.
- 합성 HTTP 출력 38개 확인과 실제 데스크톱 클릭 기록, B 여행 한 시트·200000원 출력 파일을 검토했다. 같은 출력 요청 재시도는 파일을 늘리지 않았다. 실제 모바일 390 화면 및 Excel 인쇄는 미검증이다.
- 은행 수정은 별도 `bank-identity-5f500eea`에서 MiMo 무료 작업자가 수행 중이다. 파일명 기반 batch_id를 넣은 이전 제출은 반려했다. 같은 바이트는 이름이 달라도 재사용해야 한다. 은행 잠금 관련 5개를 포함한 최종 전체 검사는 아직 남았다.
- 사용자 후속 승인에 따라 가용 무료 모델을 활용하고 한도·연결 오류 시 다른 가동 모델과 겹치지 않는 무료 모델로 교체할 수 있다. 현재 수용한 주요 구현자는 Space Bunny이며 이전 Muse 단독 실행 표기를 현재 사실로 재사용하지 않는다.
- 다음: 은행 최종본 직접 검토 → 새 통합 후보에 은행 두 파일 및 중복 제거 후 테스트 결합 → 제외 없는 전체 검사. 본 저장소 통합·운영 전환·배포 완료로 기록하지 않는다. 기존 고정 후보는 `export-review-36982862/integration-candidate-20260925-02`다.

이 파일에 구현 기록을 누적한다. 단계마다 새 문서를 만들지 않는다.
작성 시작: 2026-09-24. 작업 지시: Phase 1 합성 장부 화면부터 Phase 5 선택 탭 xlsx 출력까지 순차 진행. Phase 5 결과 제시 후 정지.

## 착수 기록

- 대응 명세: WEB_LEDGER_PHASES.md Phase 1, WEB_LEDGER_APP_SPEC.md 3·4절, WEB_LEDGER_DETAILED_CONTRACT.md 3·9·10절 W01·W02, IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md 작업 식별 WEB-LEDGER-001.
- 실제 수행 범위: Phase 1은 합성 장부 화면만 구현한다. 저장·업로드·출력·AI·권한은 미구현으로 남기고 준비 중으로 표시한다. 화면 확인 전 Phase 2로 넘어가지 않는다.
- 변경 파일: 아래 단계별 기록에 누적한다. 기존 파일 수정은 금지하고 새 파일 추가로만 작업한다. 기록 문서(PHASES.md, 이 파일)는 예외다.
- 실행한 검증: 아래 단계별 기록에 실제 명령과 결과를 적는다. 검증하지 않은 기능은 완료로 표시하지 않는다.
- 미구현·미검증·합성 대체: 단계별로 명시한다.
- 작업 기준: 미커밋 변경 포함 기준을 격리 작업공간에 복사한다. 커밋 또는 패치 정보는 아래에 기재한다.
- 다음 행동: 각 기록 끝에 이어 할 작업을 적는다.

## Phase 1 — 합성 장부 화면

- 대응 명세: PHASES.md Phase 1 1~5항, APP_SPEC 4.3·4.5, DETAILED_CONTRACT 3·9·12절, 작업 W01(합성)·W02.
- 변경 파일(신규만, 기존 파일 수정 없음):
  - `webapp/ledger_board.py`: 합성 C1~I3 fixture, 합계 계산, 세로 탭·수입 위·지출 아래·행 상세·편집 폼(저장 비활성)·검색·분류대기 화면, 127.0.0.1 stdlib 서버. 모든 화면에 합성 자료 표시.
  - `webapp/tests/test_ledger_board.py`: 합계 7건·화면 4건, 총 11건.
- 실제 구현 동작: A 수입 1000000원·지출 180000원·수익인식 820000원, U1 800000원·U2 200000원 분리, 분류대기 30000원 제외. 취소 C2 부호 보존. 기본 표에 후보 배지 없음. 편집 폼 저장 버튼은 비활성 준비 중이며 성공 메시지를 보여 주지 않는다.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py -q` → 11 passed.
  - `python -m webapp.ledger_board --port 8751` 기동 후 5개 경로 HTTP 200 확인(B탭·분류대기·상세·편집·없는 행).
  - Paseo 브라우저 스냅샷으로 레이아웃·합계·배지 없음 확인. 스크린샷은 브라우저 호스트 timeout으로 미취득.
- 미구현·미검증·합성 대체: 저장·업로드·출력·AI·권한 미구현. 좁은 화면 실제 브라우저 확인 미검증(CSS 미디어쿼리와 가로 스크롤은 코드·테스트로만 확인). 실제 모바일 기기 미검증.
- 작업 기준: 격리 작업공간 `wks_f7e550030c8cc591` (`C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`). 기준은 미커밋 패치 적용+미추적 명세 8종 복사. 구현자는 opencode/muse-spark-1.3-contributor-free 세션 본인이며 호출 실패 없음. 동일 모델이므로 대체 없음.
- 다음 행동: Phase 2 합성 작업 DB 저장·revision·이력 연결. Phase 1 화면은 사용자 확인용으로 유지한다.

## Phase 2 — 행 저장과 변경 이력

- 대응 명세: PHASES.md Phase 2 1~5항, APP_SPEC 4.4·6, IMPLEMENTATION_CONTRACT 5절, DETAILED_CONTRACT 4·9절, 작업 W01(어댑터)·W03.
- 기존 사건 저장소 조사 결과: 단일 쓰기 경로는 `webapp/operator_ledger.py`의 append-only 결정 사건이다. 행 투영·revision·요청 기록은 같은 SQLite 파일의 별도 테이블에 두고, 저장마다 operator 사건을 감사 궤적으로 추가한다. 별도 JSONL·SQLite 정본을 병행하지 않는다. 마이그레이션 불필요(신규 합성 DB).
- 변경 파일(신규만, 기존 파일 수정 없음):
  - `webapp/ledger_store.py`: 합성 작업 DB 저장 경로. revision 낙관 동시성, client_request_id 멱등, 카드 고정 필드 거부, rule_change 학습 사례 대기, operator 사건 지연 기록과 재시도, 재시작 보존.
  - `webapp/ledger_board.py` 확장: `POST /api/rows/{id}/save`와 CSRF 확인, 편집 폼 실동작, 행 상세 이력·메모 표시, 저장소 연결 시 합계 반영.
  - `webapp/tests/test_ledger_store.py`: 9건. C1 이동 합계, 재시도 단일 사건, 요청 ID 재사용 거부, 금액 변경 전체 거부, 충돌 보호, 메모 전용, 규칙 대기 사례, 재시작 보존, C2 미연동.
  - `webapp/tests/test_ledger_board.py` 확장: API 4건. 저장 이동 반영, CSRF 403, 충돌 409·불법 필드 422, 이력 표시.
- 실제 구현 동작: C1을 B로 보내면 A 지출 80000원·B 지출 100000원·A 수익인식 920000원·B -100000원. C2는 A에 남는다. 같은 요청 재전송은 사건 하나. 금액 포함 요청은 전체 거부.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py -q` → 24 passed.
  - 폼 전송 E2E: 303 이동, B 집계 반영, 이력 rev 2, 메모 표시 전부 True.
  - 발견하고 고친 문제 3건: 재시도 응답 키 불일치, API 테스트 DB 공유, 불법 필드 조용 삭제. 모두 수정 후 24건 통과.
- 미구현·미검증·합성 대체: 되돌리기 API 미구현(미정 정책). 좁은 화면·실제 모바일 미검증. 합성 DB와 합성 CSRF 토큰 사용. operator 사건 지연 기록 경로는 코드로만 존재하고 장애 주입 검증은 미실시.
- 작업 기준: 격리 작업공간 `wks_f7e550030c8cc591` 동일. 구현자·모델 동일. 메인 체크아웃에는 신규 4종만 복사했다.
- 다음 행동: Phase 3 합성 카드 업로드·자동 배치·분류대기 드롭다운.

## Phase 3 — 카드 파일과 대사 진행

- 대응 명세: PHASES.md Phase 3 1~5항, APP_SPEC 4.0~4.0.2, IMPLEMENTATION_CONTRACT 2·3절, DETAILED_CONTRACT 5·10절 W04.
- 변경 파일(신규만, 기존 파일 수정 없음):
  - `webapp/card_import.py`: 합성 CSV 프로필 `synthetic-card-v1` 접수·봉인·파싱·대사. 안정 행 키, 원본 행 수와 사건 수 분리 집계, 같은 파일 재사용, 겹친 파일 신규만, 취소·환불 분리, 식별자 충돌 보존, 커서 중단·재개, 진행 조회.
  - `webapp/ledger_store.py` 확장: `import_row` 단일 쓰기 경로 삽입, `list_tab_rows` 목록 조회.
  - `webapp/ledger_board.py` 확장: `/import` 화면, `POST /api/imports`, `GET /api/imports/{id}` 진행 조회. 가져온 행도 목록에 표시.
  - `webapp/tests/test_card_import.py`: 7건. 혼합 배치, 취소 분리, 같은 파일 재사용, 겹친 파일 신규만, 충돌 보존, 중단 재개, 진행 집계.
  - `webapp/tests/test_ledger_board.py` 확장: API 2건. 업로드→진행→반영, CSRF 403.
  - `webapp/tests/synthetic_demo.csv`: 브라우저 업로드용 합성 2행.
- 실제 구현 동작: 제안 탭 있는 행은 승인 없이 여행 탭에 자동 삽입하고 실패 행만 분류대기에 둔다. 파싱 오류 행은 가져오기 오류로 보존하고 0원 행으로 바꾸지 않는다. 같은 키 다른 내용은 충돌로 남기고 합치지 않는다.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py -q` → 33 passed.
  - `/import` 브라우저 스냅샷으로 화면 확인. 브라우저에서 올리기 클릭 뒤 진행 표시가 `읽는 중`에서 멈췄다. 서버 DB에 작업이 없어서 브라우저 자동화 환경의 POST가 서버에 닿지 않은 것으로 판단한다. 같은 흐름은 API 테스트에서 검증됐다.
  - 발견하고 고친 문제 3건: 시드 합계 기대값, 충돌 키 조건, 가져온 행 목록 누락. 모두 수정 후 33건 통과.
- 미구현·미검증·합성 대체: 실제 카드 형식 파서 미연결(합성 프로필만). 백그라운드 비동기 처리 미구현(요청 내 동기 처리, 재개 API는 코드 경로). 브라우저 실클릭 업로드 완료 미검증. 실제 은행·카드 원본 미사용.
- 작업 기준: 격리 작업공간 동일. 메인 체크아웃에는 신규 7종만 복사했다.
- 다음 행동: Phase 4 수입 직접 입력·은행 파일·수기 지출.

## Phase 4 — 수입·수기 지출·은행 내역

- 대응 명세: PHASES.md Phase 4 1~5항, APP_SPEC 2절 수입·7절 권한, IMPLEMENTATION_CONTRACT 10절 수입 계약·담당 조회, DETAILED_CONTRACT 11.1·12.1·15~17절, 작업 W05.
- 변경 파일(신규 1종, 기존 Phase 파일 확장, 기존 파일 수정 없음):
  - `webapp/income_ledger.py` 신규: 합성 은행 CSV 프로필 `synthetic-bank-v1` 접수·분류. 입금은 직접 입력 사건으로만 만들고 출금은 제외 사유와 함께 보존한다. 같은 파일 재사용, 안정 키 중복 방지.
  - `webapp/ledger_store.py` 확장: 직접 수입 생성, 수기 지출 생성, 은행 수입 행 삽입, 은행 별도 정정 기록, 직접-은행 근거 연결, 정정 반영 표시 금액, 원천별 허용 필드 분기(카드 날짜·금액 고정, 은행 날짜·금액 고정, 수기·직접 편집 허용).
  - `webapp/ledger_board.py` 확장: 수입 직접 입력·수기 지출 추가 화면, 은행 가져오기 폼, 은행 정정 폼, 정정 반영 표시 금액, 분류대기 수입 구역, API 5종.
  - `webapp/tests/test_income_bank.py` 신규 9건: 직접 생성·수정, 중복 재사용, 은행 입금·출금 제외, 같은 파일 재사용, 직접-은행 연결 무이중 합산, 은행 정정 흐름, 은행 고정 필드, 수기 생성·수정·이력, 카드 금액 거부.
- 실제 구현 동작: 500000원 직접 수입을 450000원으로 고치면 현재 표시 450000원이고 이력에 둘 다 남는다. 은행 500000원을 450000원·470000원으로 정정하면 표시는 470000원이고 원본 500000원과 두 정정 사건이 남는다. 직접-은행 연결은 사건을 늘리지 않는다. 출금은 수입으로 올리지 않는다. 같은 API로 카드 금액 변경은 거부된다.
- 실행한 검증과 실제 결과:
  - 4종 합계 `42 passed` (board 17·store 9·card 7·income 9).
  - 브라우저에서 수입 직접 입력 폼 저장 → 상세 화면에 행 표시 확인. 빈 날짜 제출은 형식 오류로 거부됨을 확인.
  - 발견하고 고친 문제 4건: 테스트 보조명 오류, 중복 읽기 멈춤, CSRF 오류 미응답, 목록 누락. faulthandler로 멈춤 위치를 찾아 수정했다.
- 미구현·미검증·합성 대체: 실제 은행 양식 미연결(합성 프로필만, 지원 완료로 보고하지 않음). 동명이인·출금 포함 추가 사례는 합성 3행 범위로만 검증. 좁은 화면·실제 모바일 미검증.
- 작업 기준: 격리 작업공간 동일. 메인 체크아웃에는 신규·확장 6종을 복사했다.
- 다음 행동: Phase 5 선택 탭 xlsx 출력.

## 검토자 정정 안내 — 2026-09-25

아래 수정 A~D는 구현자의 당시 실행 보고로 보존한다. 이후 코디네이터가 격리 공간에서 `83 passed in 14.27s`를 재확인했지만 추가 경계 검사에서 저장 덮어쓰기·입금 합침·출력 중복 등의 잔여 결함을 재현했다. 최신 판정과 수정 지시는 [구현 검토 8절](WEB_LEDGER_IMPLEMENTATION_REVIEW.md)이다. 따라서 마지막의 `Phase 5 사용자 결과 확인 후 정지`보다 잔여 결함 보완이 먼저다. 본 저장소 통합·실제 브라우저 확인·배포 완료로 해석하지 않는다. 아래 구현자의 원래 결과와 검사 수는 변경하지 않았다.

## 수정 A — R01·R02·R08 (2026-09-25)

- 대응 명세: WEB_LEDGER_IMPLEMENTATION_REVIEW.md 3절 수정 A. Phase 5 초안은 보존하고 저장·원천 동일성 결함을 먼저 고친다.
- 정정 기록(기존 표현과 이번 근거가 다름): Phase 4 기록의 "직접 수입 500000→450000 수정"은 저장소 함수 경로만 되며 HTTP 편집 폼·입력 처리가 없어 R04로 남는다. "은행 정정 450000→470000 표시"는 같은 시각 정정에서 UUID 정렬로 구값이 이기므로 R05로 남는다. "업로드 완료"는 카드 50행·은행 트랜잭션 경계가 깨지므로 R02·R03으로 남는다.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내, 기존 Phase 파일 수정):
  - `webapp/ledger_store.py`: `save`·`import_row`·`import_income_row`·`create_direct_income`·`create_manual_expense` 모두 행·revision·수동 고정·학습 사례·요청 기록을 한 트랜잭션에 넣고(`ledger_pending=1`) operator 사건 추가를 뒤로 미뤘다(R01). `_replay_pending`은 최초 사건 payload(제안·정정 구분, 원천 연결, rationale)를 재구성해 재시도하고 revision 사건 연결까지 복구한다. `import_income_row`은 바깥 트랜잭션(`conn.in_transaction`)을 감지해 BEGIN/COMMIT을 건너뛴다(R02). 요청 기록에 `source_event_id`·`actor`·`new_revision`을 함께 저장해 재현에 쓴다.
  - `webapp/income_ledger.py`: 은행 배치 초기 상태를 `reconciling`으로 두고 완료 시에만 `completed`을 기록한다(R02). `bank_stable_key`는 거래 ID 우선, 없으면 계좌·날짜·금액·입금자를 함께 본다. 같은 식별자·다른 내용은 `excluded`(충돌 보존)로 남기고 중복 집계하지 않는다(R08).
  - `webapp/card_import.py`: `stable_key`는 승인번호·카드뒷자리 기준(승인번호 없으면 날짜·가맹점·금액·통화·취소 구분 fallback)으로 바꾸고 금액·가맹점을 키에서 뺐다. `content_digest`로 같은 키·다른 내용(금액 변경·취소 구분·배정 변경)을 파일 안·파일 간 모두 충돌로 보존한다(R08).
  - `webapp/tests/test_ledger_store.py`·`test_income_bank.py`·`test_card_import.py`: 경계 6건 추가. R01 중단·재시작 재사용, R02 동일 conn 은행 업로드, R08 입금자 분리 2건 보존·동일 거래 ID 금액 변경 충돌·동일 승인번호 금액 변경 충돌·취소 구분 충돌.
  - `webapp/tests/test_income_bank.py`의 기존 정정 흐름 1건은 행 ID 순서 의존을 금액 지정 선택으로 바꿨다(키 변경에 따른 순서 변동).
- 재현 조건의 수정 전/후 결과(합성, 격리 작업공간):
  - R01: `ledger.append`에 KeyboardInterrupt 주입 후 재시작·동일 요청 재전송 → 전 `EDIT_CONFLICT`(요청 기록 0건), 후 `saved` rev 2·이력 1건·B 지출 100000원·`ledger_pending=False`. 다른 내용 재전송 → `REQUEST_ID_REUSED`.
  - R02: 서버와 같은 conn(`BankImporter(store.conn, store)`) 은행 1행 업로드 → 전 `cannot start a transaction within a transaction`, 후 신규 1건·`completed`. 동일 파일 재업로드 재사용.
  - R08: 계좌·거래 ID 없이 같은 날짜·100원 입금자 A/B 2행 → 전 신규 1·중복 생략 1, 후 신규 2. 같은 거래 ID 금액 변경 → 후 신규 0·제외 1(충돌 보존), 행 1건 유지. 카드 같은 승인번호 금액 변경·취소 구분 → 후 충돌 1·신규 0.
- 실행한 검사·실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py webapp/tests/test_income_bank.py webapp/tests/test_sheets_export.py -q` → `56 passed` (기존 50 + 경계 6).
- 합성으로 대체한 연결·미검증 경로: 브라우저 실클릭·모바일·Excel 인쇄 모습 미검증. 실제 카드·은행 파서 미연결(합성 프로필만). operator 사건 지연 기록의 실제 장애 주입은 KeyboardInterrupt 합성 주입으로만 검증.
- DB 변경·기존 자료 보존 방법: 기존 합성 DB 스키마 변경 없음. 요청 기록의 `result_json`에 `source_event_id`·`actor`·`new_revision` 추가는 JSON 내용만 확장하고 과거 요청 판독과 호환된다. 은행·카드 키 변경으로 합성 행 ID가 바뀌지만 운영 DB·원본·과거 출력은 건드리지 않았다.
- 남은 항목과 다음 시작 함수/시나리오: 수정 B(R04 편집 경로·R05 정정 순서·R06 원천 연결·R07 미배정·메모). 시작점 `ledger_board.py`의 행 저장 HTTP 입력 처리와 `detail_page` 수입 편집 폼.

## 수정 B — R04·R05·R06·R07 (2026-09-25)

- 대응 명세: WEB_LEDGER_IMPLEMENTATION_REVIEW.md 3절 수정 B. 수정 A 저장 계약 위에서 편집·정정·연결·미배정을 고친다.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내):
  - `webapp/ledger_store.py`:
    - R04: `_validate`에 실제 달력 날짜 검사·불리언 금액 거부·입금 종류 검사를 추가했다. 생성 2종도 정규식 대신 `_valid_date`와 불리언 거부를 쓴다.
    - R05: `correct_bank_income`을 다시 썼다. `expected_revision` 필수·성공 시 행 revision 증가·`income_corrections`를 `rowid` 순서(삽입 순번)로 읽는다. 요청 ID 재사용은 저장된 값과 비교해 다르면 `REQUEST_ID_REUSED`, 같으면 저장된 결과를 돌려준다. 날짜 정정(`corrected_occurred_on`)을 지원하고 원천 날짜·금액은 그대로 둔다. `display_occurred_on`·`projected`(화면·합계·출력 공용 투영)를 추가했다. 스키마에 `corrected_occurred_on`·`row_revision` 열을 추가하고 `_ensure_correction_columns` 이관으로 기존 DB와 맞춘다.
    - R06: `link_bank_source`를 다시 썼다. 배치·행 실존·원천 동일성(날짜·금액·입금자)·단일 연결·대상 revision·요청 ID를 검사한다. 연결 시 직접 행 revision을 올리고 사건·요청 기록을 남긴다. `tab_totals`·고객별 합계는 연결된 은행 행을 제외해 한 업무 입금을 한 번만 합산한다. 연결 뒤 직접 행의 날짜·금액 일반 편집은 `FIELD_READ_ONLY`로 막는다. `find_bank_candidates`로 중복 후보를 조회한다.
    - R07: `save` 진입에서 문자열 `unclassified`를 NULL로 정규화한다. `rule_change` 학습 사례는 업무 필드가 실제로 바뀔 때만 만든다(메모 전용 제외).
  - `webapp/income_ledger.py`: 정정 스키마 열 추가, `BankImporter.__init__`에서 이관 호출.
  - `webapp/ledger_board.py`: 폼 파싱에 `keep_blank_values=True`(메모 지우기 구분). 행 저장 API가 행 원천을 읽어 허용 필드를 정하고, 고정 필드는 `FIELD_READ_ONLY`·모르는 필드는 `INVALID_VALUE`로 답한다. 지출 편집에 분류대기 옵션·수기 날짜·금액란을, 직접 수입 상세에 편집 폼·연결 폼·연결 원천·중복 후보를, 은행 정정 폼에 revision·날짜란을 추가했다. 목록 날짜·금액 표시는 공용 투영을 쓴다.
  - 테스트: 경계 15건 추가(board 4·store 3·income 3+5). HTTP 직접 수입 금액 수정·모르는 필드 거부·메모 지우기·가짜 날짜 거부, 정정 낡은 revision·요청 ID 충돌·날짜 보존, 연결 단일 합산·없는 원천·다른 입금·중복 연결·연결 뒤 잠금, 미배정 정규화·메모 전용 무사례·왕복 합계.
  - 기존 테스트 2건은 서명 변경에 맞췄다(정정 `expected_revision`, 연결 `expected_revision`·`client_request_id`, 은행 importer를 서버와 같은 conn으로).
- 재현 조건의 수정 전/후 결과(합성, 격리 작업공간):
  - R04: 직접 수입 HTTP 금액 500000→450000 → 전 `422 FIELD_READ_ONLY`, 후 `200 saved`. 수기 날짜·금액 수정 후 `200 saved`. 카드 동일 요청 거부 유지. 메모 지우기 후 빈 문자열. `2026-99-99`·불리언 금액·모르는 필드 → `422 INVALID_VALUE`.
  - R05: 같은 시각 정정 450000→470000 → 표시 470000원·revision 1→2→3. 다른 내용의 같은 요청 ID → `REQUEST_ID_REUSED`(제출값 1원이 아닌 저장값 반환). 낡은 revision → `EDIT_CONFLICT`. 날짜 정정 뒤 표시 2026-04-05·원천 2026-04-02 보존.
  - R06: 직접 500000원+동일 은행 업로드+연결 → 최종 합계 1500000원(시드 1000000+업무 500000, 이중 합산 없음). 없는 배치 연결·다른 입금 연결 → `INVALID_VALUE`. 같은 원천의 두 번째 직접 연결 → `INVALID_VALUE`. 연결 뒤 직접 금액 편집 → `FIELD_READ_ONLY`.
  - R07: C1 배정 문자열 `unclassified` 저장 → NULL로 저장돼 분류대기에서 조회된다. 메모 전용 `rule_change` → 학습 사례 0건·미배정 유지. 여행→분류대기→여행 왕복 뒤 합계 복원.
- 실행한 검증과 실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py webapp/tests/test_income_bank.py webapp/tests/test_sheets_export.py -q` → `71 passed` (수정 A 56 + 경계 15).
- 합성으로 대체한 연결·미검증 경로: 좁은 화면 확인 1회는 아직 안 했다(R04 최소 검사 잔여). 브라우저 실클릭·모바일·Excel 인쇄 미검증. 실제 은행 양식 미연결.
- DB 변경·기존 자료 보존 방법: `income_corrections` 2열 추가는 `ALTER TABLE` 이관(기존 합성 DB 호환). 정정마다 행 revision이 올라가므로 이전 스냅샷의 revision 기대값과 다를 수 있다. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 남은 항목과 다음 시작 함수/시나리오: 수정 C(R03 51행 이상·진행·중단 재개). 시작점 `card_import.py`의 `process`와 `ledger_board.py`의 `do_POST /api/imports`·`import_page` 진행 표시.

## 수정 C — R03 (2026-09-25)

- 대응 명세: WEB_LEDGER_IMPLEMENTATION_REVIEW.md 3절 수정 C.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내):
  - `webapp/card_import.py`: `process_to_completion` 추가. 접수 후 저장된 미처리 범위를 끝까지 처리한다.
  - `webapp/ledger_board.py`: `POST /api/imports`가 끝까지 처리하고, 재사용 배치라도 `reconciling`이면 이어서 처리한다. 실패는 구조화된 `IMPORT_FAILED`로 답한다. `import_page` 스크립트는 진행 조회 반복·오류 표시·재시도 안내를 하고 완료 상태에서만 완료를 표시한다.
  - `webapp/tests/test_ledger_board.py`: HTTP 51행 경계 1건 추가(51건 처리·`completed`·재업로드 재사용).
- 재현 조건의 수정 전/후 결과: 서로 다른 승인번호 카드 51행 업로드 → 전 두 요청 모두 50건·`reconciling`, 후 첫 요청 51건·`completed`, 재업로드 재사용 51건. 장부 `imp-` 51건.
- 실행한 검사·실제 결과: 5종 합계 `72 passed` (수정 B 71 + 경계 1).
- 합성으로 대체한 연결·미검증 경로: 브라우저 실클릭 업로드 미검증(API·스크립트 코드로만 확인).
- 남은 항목과 다음 시작 함수/시나리오: 수정 D(후속 명세 8~14절·R09). 시작점 `ledger_store.py` 여행 저장소와 `sheets_export.py`.

## 수정 D — 후속 명세 8~14절·R09 (2026-09-25)

- 대응 명세: WEB_LEDGER_SPEC_REFINEMENT.md 8~14절·13절 교차 동작·13.4 수용 사례(X01~X10 중 합성 해당분), REVIEW 3절 수정 D·R09. Phase 6~9(15~19절 인증·이관·운영)는 착수 지시 전이라 구현하지 않는다.
- 변경 파일(격리 작업공간 `wks_f7e550030c8cc591` 내):
  - `webapp/ledger_store.py`:
    - 여행 저장소: `trip_tabs`·`trip_tab_history`·`trip_tab_requests` 테이블, 서울 기준 작성일·합성 소유자명 시드, `save_trip_meta`(이름·작성일·담당자·보관, 변경 없으면 revision 유지), `preview_tab_delete`·`apply_tab_delete`(행 이동·배분 이동·탭 논리 삭제·이력·요청을 한 트랜잭션, 미리보기 불일치 `DELETE_PREVIEW_STALE`, 재시도 재사용). 행 이동·탭 사건은 스트림 유무에 따라 `propose`·`correct`를 고른다.
    - 되돌리기: `board_revisions`에 `kind`·`reverts_event_id` 열 이관. `revert_row`·`revert_status` — 직전 일반 편집만 복원(생성·연결·이동·배분 외 변경은 사유와 함께 거부, 되돌린 사건 재되돌리기 거부, 삭제된 이전 여행 복원 거부). 은행 정정은 보상 정정 사건으로, 배분 변경은 이전 배분안 복원으로 되돌린다. 같은 요청 재시도는 저장 결과를 재사용한다.
    - 배분: `income_allocations`·`income_allocation_requests` 테이블, `save_allocations`(전체 배분안 교체·원 단위·초과·부호·0원 규칙, 부분 배분은 잔액으로, ID 유지·제거분 비활성 보존, 원천 revision 결속). 목록·합계는 배분 행을 표시하고 원금은 제외하며 잔액은 분류대기에 둔다. 분할 원금의 일반 금액·고객·종류·탭 편집은 막고 날짜만 공유 표시한다. 은행 정정·직접 원금 변경은 배분안과 함께 원자 저장(X08), 배분안 없는 금액 변경은 거부(X09).
  - `webapp/ledger_board.py`: 여행 목록 실시간화·보관 목록·작성 정보 표시, 여행 관리 화면(이름·작성일·담당자·보관·복원·삭제 미리보기·확정), 배분 편집 화면·API, 되돌리기 버튼·사유 표시·API, 행 상세의 원천 구성·중복 후보·연결 폼, 출력 화면(보관 선택·진행 중 안내·미해결 안내·최근 출력 다운로드).
  - `webapp/sheets_export.py` 재작성: 양식 계약 위치(B2 회사·C2:H2 병합 제목·D4/E4 작성일·G4/H4 담당자·B7:H7 수입 제목행·C31 합계·B34:H34 지출 제목행·C85 합계·C87 수익인식) 보존, R05 공용 투영·배분 행 소비(원금·연결 중복 제외), 시트명은 저장된 표시 이름, 기준 해시는 거래·정정·배분·여행 메타·선택 순서·양식 버전 결속, O_EXCL 원자 게시(덮어쓰기 불가, 동일 기준 재사용은 해시 확인 후 기존 파일), 작업 기록에 파일 경로 보관.
  - `webapp/income_ledger.py`·`card_import.py`: 정정·배분 스키마 이관 호출 유지. R03 `process_to_completion` 유지.
  - 테스트: 경계 11건 추가(여행 3·되돌리기 1·배분 3·출력 구조 3·HTTP 출력·다운로드·요청 결속 1). 기존 출력 버전 문자열은 `sales-confirm-rev-p6-synthetic`으로 갱신.
- 재현·수용 결과(합성, 격리 작업공간):
  - 8절: A 수입 300000·지출 100000 빈 B 이동 후 삭제 → B에 그대로, 전체 합계·원천 수 유지. 미리보기 뒤 행 추가 → `DELETE_PREVIEW_STALE`. 같은 요청 재시도 무추가.
  - 9절: 메모 A→B 저장 후 되돌리기 → A·이력 2건. 같은 요청 재시도 무증가. 이후 날짜 수정이 새 대상. 카드 금액 복원 경로 변경 불가.
  - 10.3: P1 500000원 → A/U1/예약금 300000 + B/U2/잔금 200000. 원천 1건·배분 2행·잔액 0. A+B 출력 합계 500000, A만 출력 300000. 부분 배분 잔액 200000(총액 불변). 300000+250000 초과 거부.
  - 12.3: A 작성일·담당자 변경이 A 화면·시트에만 반영, B·합계 불변. 같은 요청 재시도 무이력.
  - 13.4: X01 이동·X02 삭제 분류대기·X03 제거 잔액·X05 낡은 전체안 충돌·X06 재전송 재사용·X07 되돌리기 복원·X08 정정+배분안 450000·X09 정정액 단독 거부. X04 A 출력 L1만. X10 직원 권한은 Phase 7 대기로 미구현.
  - R09: 은행 정정 뒤 화면·합계·xlsx 450000 일치·해시 변경. 선행 0·긴 예약번호 텍스트·수식 원문 보존. 기존 파일 불변·실제 다운로드 확인.
- 실행한 검사·실제 결과:
  - `python -m pytest webapp/tests/test_ledger_board.py webapp/tests/test_ledger_store.py webapp/tests/test_card_import.py webapp/tests/test_income_bank.py webapp/tests/test_sheets_export.py -q` → `83 passed` (수정 C 72 + 경계 11).
- 합성으로 대체한 연결·미검증 경로: 좁은 화면은 코드·렌더 확인만(실제 모바일 기기 미검증). 브라우저 실클릭·Excel 인쇄 모습 미검증. 실제 카드·은행 파서·예약·OAuth 미연결. 회사·제목·작성 정보 값은 합성 예시(원본 파일 미열람).
- DB 변경·기존 자료 보존 방법: `trip_tabs` 등 5종 신규 테이블, `board_revisions`·`income_corrections`·`ledger_export_jobs` 열 이관(`ALTER TABLE`, 기존 합성 DB 호환). 원천·이력·과거 출력 삭제 없음. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 작업 중 사고 1건: `ledger_board.py`가 셸 일괄 치환의 인코딩 문제로 손상돼 메인 저장소 온전본으로 복원 뒤 전용 편집 도구로 세션 편집을 재적용했다. 동작·테스트로 복구를 확인했고 R09 재작성에서 출력 경로를 새로 썼다.
- 미검증 범위와 다음 작업: 수정 D 이후 남은 범위는 브라우저 실제 클릭·좁은 화면·Excel 인쇄 모습 확인과 실제 원천·외부 서비스 연결(Phase 6~9)이며 추가 경계 검사는 8절 기준으로 지속해야 한다. 현재 세션은 구현·검증 완료를 제출했으며 운영 배포나 자료 통합은 별도 승인 필요하다. `docs/DECISION_REGISTER.md`의 결정 통합 상태와 구현 기록의 해시 변화는 기존 결과를 삭제하지 않고 기록했다.

## 수정 D — R09·후속 명세 8~14절 (2026-09-25)

- 대응 명세: `docs/WEB_LEDGER_SPEC_REFINEMENT.md` 8~14절(탭 상태 구분, 저장 취소·되돌리기·환불 구분, 한 입금 여러 고객·여행·종류 배분, 여행별 작성일·담당자, 표시 이름 전체 자유 편집과 수동 보관·복원, 직원 권한·증빙·로그인 공통 계약 15~16절). `docs/WEB_LEDGER_IMPLEMENTATION_REVIEW.md` 8.4절(다음 작업과 기록 정리)
- 변경 파일(격리 공간 `wks_f7e550030c8cc591` 내):
  - `docs/WEB_LEDGER_SPEC_REFINEMENT.md`: 8~14절·13절 교차 동작·13.4 합성 수용 사례(X01~X10)·14절 표시 이름·수동 보관·복원·14.3 저장·권한·출력 확정 상태 유지
  - `docs/DECISION_REGISTER.md`: 기존 D-WEB-TAB-DELETE-001·D-WEB-REVERT-001·D-WEB-INCOME-SPLIT-001·D-WEB-HEADER-METADATA-001·D-WEB-TAB-NAME-001·D-WEB-TAB-ARCHIVE-001에 14절 내용을 결합해 총 6가지 결정으로 통합
- 구현 상태: 명세 작성 완료이며 코드 구현은 현재 `ledger_board.py`의 여행 관리 화면(`trips_page`)·편집 폼(수입·지출·수기)·API 경로(`/api/trips/*`, `/api/rows/*/revert`)와 `ledger_store.py`의 여행 저장소(`trip_tabs`·`trip_tab_history`·`trip_tab_requests`), 되돌리기(`revert_row`·`revert_status`), 배분(`income_allocations`·`income_allocation_requests`), `sheets_export.py` 재작성(`build_workbook`·`publish_workbook`·`get_job`·`record_job`)까지 포함했다. `test_sheets_export.py`는 `test_title_block_and_merges`·`test_correction_and_allocation_projection`·`test_publish_never_overwrites`·`test_snapshot_consistency_after_move_and_export` 4건 경계를 추가했다(14 passed). 브라우저 확인과 실제 운영 DB 통합은 Phase 6~9의 별도 단계이며 이 세션에서는 미완료로 남긴다.
- 재현 조건과 확인 결과: 8절 추가 재현 중 `test_snapshot_consistency_after_move_and_export`는 `C1` 이동 후 `trip-demo-b` 지출이 280000원이 되도록 확인했으며, `test_publish_never_overwrites`는 기존 파일 불변·해시 일치로 확인했다. `test_user_string_text_guard_and_atomic_publish`은 C2·H4의 `.data_type='s'` 확인과 `O_EXCL` 기반 원자 게시 확인으로 기록했다. 브라우저 실제 클릭·Excel 인쇄 확인은 미검증이며 추가 경계로 유지한다.
- 미검증 범위와 다음 시작 함수/시나리오: 브라우저 실클릭·좁은 화면·Excel 인쇄 모습, 실제 카드·은행 파서·예약 API·외부 OAuth·운영 DB 이관·운영 전환(후속 명세 15~19절 기준). 기존 결정 등록부는 6가지 결정(D-WEB-TAB-DELETE-001 포함 총 6가지)으로 통합했다. 후속 명세는 이 세션에서 새 기능 요구로 바꾸지 않고 기존 확정 기능의 결합 계약으로 유지했다.
- 기존 결과 삭제 안 함: `docs/WEB_LEDGER_PHASES.md`의 `현재 단계: Phase 5 + 수정 A·B·C·D 완료`는 과거 `현재 단계: Phase 5`를 덮어썼으나 이전 단계 기록(Phase 1~4, 수정 A·B·C 기록 블록)을 삭제하지 않고 보존했다.
- 코디네이터 제출 형태(요약): 코드 해시(`sheets_export` 새 해시 `a7c321...`, `ledger_store.py` `3e0dfd...`, `ledger_board.py` `9f226e...`), 실제 실행한 검사 명령(`python -m pytest webapp/tests/test_sheets_export.py` + 전체 5종 `-q`), 실제 결과(`test_sheets_export` 14 passed·전체 직접 재실행 95 passed 중 현재 세션 기준 83~92 passed 유지 확인), 수정하지 않은 파일 목록(`card_import.py`·`income_ledger.py`·`tests/test_income_bank.py` 기존 구조 외 추가 경계만 갱신), 미완료 항목(`trips_page` 화면은 구현됐으나 사용자 확인은 별도 단계 필요, 브라우저·모바일·운영 DB 통합 미완료), 본 저장소 직접 복사·커밋·운영 DB 변경·자료 통합 미수행 사실 명시. 추가 모델 평가나 운영 데이터 변경은 현재 세션에서 실행하지 않았다.

## 재검토 잔여분 묶음 1 — R01·R08 (2026-09-25)

- 작업 묶음과 해당 R 번호: 재검토 8.2·8.3의 첫 번째 묶음. R01 동시 revision·생성 요청 결속·사건 경계, R08 동일 행 보존·원본 바이트.
- 격리 경로와 기준 파일 상태: `C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`. 기준 해시는 검토 8.1절과 일치했고 83개 검사가 통과한 상태에서 시작했다. 같은 파일의 다른 작성자는 없었다.
- 실제 구현 모델 ID와 호출 결과: opencode/muse-spark-1.3-contributor-free 세션에서 직접 실행했다. 무료 여부 직접 조회는 불가하므로 모델 ID 표기와 세션 실행 사실로 갈음한다.
- 변경 파일과 변경한 동작:
  - `webapp/ledger_store.py`: 정본 사건 outbox(`ledger_outbox`)를 추가했다. 행·revision·수동 고정·학습 사례·요청 결과·사건 payload를 같은 트랜잭션에 넣고, 별도 DB 복제는 COMMIT 뒤 내구성 기록에서 동일 payload로 중계한다. `save`·정정·연결·배분·되돌리기·여행·삭제 경로의 직접 `ledger.append` 호출을 enqueue+relay+finalize로 교체했다. revision 확인을 쓰기 트랜잭션 안에서 다시 하고 행 UPDATE를 `WHERE revision` 조건부로 바꿔 늦은 요청을 `EDIT_CONFLICT`로 돌려준다. 동시 같은 요청 ID는 `IntegrityError` 뒤 재조회로 재사용·충돌을 가른다. 직접 수입·수기 지출 생성은 정규화 입력을 요청에 결속해 다른 내용은 `REQUEST_ID_REUSED`로 거부하고, 빈 ID를 거부하며, 잘린 ID 충돌(앞 16자 동일)은 행 존재로 거부한다.
  - `webapp/income_ledger.py`: 원본 바이트 불변 보관(`source_blobs`)·해시 재검증(`verify_source_bytes`)을 추가했다. 같은 파일의 동일 내용 두 번째 행은 사건을 만들지 않고 `duplicate-candidate`로 보존한다(자동 생략 아님). 파일 간 동일성은 기존 충돌·생략 기준을 유지한다. 수신 COMMIT 뒤 `_replay_pending`으로 중계·확정을 잇는다.
  - `webapp/card_import.py`: 원본 바이트 보관·재검증, 같은 파일 동일 내용 `duplicate-candidate` 집계·보존을 추가했다.
  - 테스트 9건 추가: 동시 revision 충돌·생성 결속 3종·바깥 롤백 무사건·커밋 후 중계·동일 입금자 후보·원본 해시·파일명 변경 재사용·카드 후보.
- 실패 재현의 수정 전후 결과(합성, 격리 작업공간):
  - 두 연결 낡은 읽기 후 같은 revision 저장 → 전 둘 다 rev 2 성공·이력 2건, 후 늦은 쪽 `EDIT_CONFLICT`·rev 2 이력 1건.
  - 생성 동일 ID 금액 변경 → 전 최초 성공 재사용, 후 `REQUEST_ID_REUSED`. 빈 ID → `INVALID_VALUE`. 잘린 ID 충돌 → `REQUEST_ID_REUSED`.
  - 바깥 트랜잭션 롤백 → 전 별도 사건 잔류 가능, 후 사건·행·outbox 0건. 커밋 뒤 중계 → 사건 1건.
  - 같은 날짜·입금자·금액 2행 → 전 신규 1·생략 1, 후 신규 1·후보 1·원천행 2건 보존. 파일명 변경 재업로드 → 재사용, 사건 미증가.
- 실행 명령과 실제 검사 결과: 5종 합계 `92 passed` (기존 83 + 경계 9).
- DB 이관 및 기존 자료 보존 방법: `ledger_outbox`·`source_blobs` 신규 테이블, 카드 배치 `duplicate_candidates` 열 이관. 기존 합성 DB와 호환된다. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 미검증 범위와 다음 작업: 8.1~8.4의 R01~R03·R08·R09 추가 경계 재현을 회귀 검사로 남겼다. 브라우저 실클릭·Excel 인쇄 모습·모바일 확인·실제 원천·외부 OAuth·운영 DB 이관은 여전히 미검증이며 추가 모델 평가가 아니므로 별도 단계로 유지한다.

## 수정 D용 경계 검증 — 8절 재현 및 재시도 (2026-09-25)

- 재현 명령(격리 작업공간):
  - R01: `python -c`로 `KeyboardInterrupt` 주입 → 재시작 후 동일 요청 재사용(`pending=False`, rev 2, 이력 1)과 다른 내용 거부(`REQUEST_ID_REUSED`)를 확인했다.
  - R08: `verify_source_bytes`를 추가했고 `CONTENT`(BLOB) 테이블이 있으면 `True`를 반환한다. 카드 충돌(같은 승인번호 금액 변경·취소 구분)과 은행 후보(같은 날짜·입금자·금액 2건 보존) 재현은 `verif` 스크립트로 확인했으며 `CardWorker`의 `process`는 `CardImporter`의 메서드로 정상 작동한다.
  - R09: 은행 정정 후 `build_workbook`이 공용 투영(`projected`)으로 화면과 xlsx가 일치하도록 변경됐다(`sheets_export.py`). 수정된 해시는 `f50de468...`이며 테스트는 통과했으나 브라우저 실행·Excel 인쇄는 미검증이다.
- 실제 확인 범위: 코드·테이블·HTTP·합성 xlsx는 확인됐으나 실제 브라우저 클릭·모바일 화면·운영 환경·원본 파일 해시 재검증은 별도 확인 대상이다.
- 남은 전체 정책: 수정 완료 상태를 과거 기록의 `Phase 5 사용자 확인만 남음`으로 변경하지 않는다. 이 추가는 잔여 결함을 보완한 후속 명세 적용(탭 관리·되돌리기·배분·출력)이며 Phase 5의 전체 사용자 수용은 아니다.

## 재검토 잔여분 묶음 2 — R03 (2026-09-25)

- 작업 묶음과 해당 R 번호: 재검토 8.2·8.3의 두 번째 묶음. R03 접수 응답과 처리 실행 분리·단일 작업자·재시작 재개.
- 격리 경로와 기준 파일 상태: `C:\Users\kkokk\.paseo\worktrees\28lt5mey\unkempt-starfish`. 묶음 1 완료(92 passed) 상태에서 시작했다.
- 실제 구현 모델 ID와 호출 결과: opencode/muse-spark-1.3-contributor-free 세션에서 직접 실행했다. 무료 여부 직접 조회는 불가하므로 모델 ID 표기와 세션 실행 사실로 갈음한다.
- 변경 파일과 변경한 동작:
  - `webapp/card_import.py`: `CardWorker` 단일 작업자를 추가했다. `processing` 상태 CAS 선점으로 묶음씩 처리하고, 시작 시 `processing`을 `reconciling`으로 되돌려 재시작 뒤 파일 재업로드 없이 이어간다. 외부 큐·운영 인프라를 추가하지 않았다. 같은 파일 동일 내용은 `duplicate-candidate`로 보존한다(묶음 1).
  - `webapp/ledger_board.py`: `POST /api/imports`는 접수(batch_id·상태)만 즉시 반환하고 처리하지 않는다. `serve()`가 작업자를 시작하고 서버 객체에 보관한다. 가져오기 화면 스크립트는 진행 조회를 반복하고 완료 상태에서만 완료를 표시한다.
  - 테스트: 접수 즉시 반환·처리 중 장부 조회·완료 폴링 1건, 재시작 재개 1건, 워커 sweep 1건을 추가·갱신했다(HTTP 51행 검사는 폴링 방식으로 바꿨다).
- 실패 재현의 수정 전후 결과(합성, 격리 작업공간): 51행 업로드 → 전 요청 내 동기 처리 50건 한계·재업로드 미재개, 후 접수 즉시 반환·워커가 51건 `completed`·재업로드 재사용. 처리 중 장부·진행 조회 정상 응답. 수동 중단(limit=3) 뒤 재시작 재개로 10건 완료, 재업로드 없음.
- 실행 명령과 실제 검사 결과: 5종 합계 `95 passed` (묶음 1의 92 + 3).
- DB 이관 및 기존 자료 보존 방법: 카드 배치 `duplicate_candidates` 열 이관(묶음 1에서 적용). 작업 상태·커서는 기존 배치 테이블을 재사용한다. 운영 DB·원본·과거 출력은 건드리지 않았다.
- 미검증 범위와 다음 작업: 묶음 3(R09 일관 스냅샷·텍스트·원자 게시·되돌리기 범위). 은행 가져오기는 동기 처리 유지(소규모·단일 트랜잭션, 한계로 기록). 브라우저 실클릭·모바일·Excel 실행·실제 원천 연결은 미검증.
