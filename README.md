# 숲길여행 비용처리

## 현재 OTA 자료 연결

메일·포털·과거 조사 자료는 운영 `ota-sources.json`에 등록해 함께 조회한다. 자료 내용 변경을 감지하고 미연결 사유를 구분하는 수정까지 적용했다. 현재 연결 수와 남은 항목, 실제 검증 범위는 [OTA 문서](docs/ota_mail.md)의 최신 항목을 따른다.

카드 파일 업로드 → 자동 분류 → 미확정 거래 확인 → 미리보기 → 장부 기록.

[운영 장부](https://ledger.foresttour.kr/)는 카드 자료와 기록된 장부를 구분한다. [카드 검토](https://ledger.foresttour.kr/import)에서 파일·거래·질문을 확인하고 미리보기 뒤 기록한다. 사용자 답변과 원본을 보존하며 XLSX는 출력 자료로 사용한다.

## 현재 상태

2026-10-09 확인 기준으로 운영 정본은 `D:/WebLedgerHost/data/board.sqlite`다. 원본 거래 6,037건 중 완료 기간 3,653건은 내부 보존하고, 2026-04-01 이후 2,384건을 검토한다. 이 중 국민 국내·해외 매입에서 새로 가져온 709건은 분류 331건, 사용자 검토 377건, 보존 1건이며 장부에 기록하지 않았다. 장부에는 734건, 취소를 포함한 순액 73,702,707원이 기록됐다. 여행 탭에 496건, 분류대기 장부에 238건이 있다. 일정 검증 차단 926건과 기존 보류 16건은 남아 있다.

승인번호가 같은 결제와 취소를 서로 다른 거래로 보존하는 수정과 ready 집계·읽기 전용 출력 조회·여행 목록의 수입 안내를 운영 코드에 적용했다. OTA 예약번호와 이용기간은 미리보기 digest를 거쳐 장부 행에 전달한다. 최신 실행 결과와 미결 사유는 아래 문서에 기록한다.

## 개발 실행

운영과 다른 절대 경로를 사용한다. 합성 로그인은 개발 환경에서만 사용한다.

```powershell
$env:WEBLEDGER_CARD_FLOW='1'
$env:WEBLEDGER_UNIFIED_DB='1'
python run_candidate.py --data-root C:\AX\cost-dev-data --port 8765 --environment local-synthetic --synthetic-sessions
```

운영 서버는 별도 실행기와 설정으로 시작한다. 개발 명령에 운영 DB나 운영 자료 경로를 넣지 않는다.

## 개발·검증 원칙

[AGENTS.md](AGENTS.md)의 **검증 최소화·재검증 금지** 정책을 따른다. 변경된 기능과 직접 영향을 받는 범위만 한 번 검증하고, 기존 유효한 테스트·브라우저·운영 결과를 관성적으로 반복하지 않는다. 장부·거래·환불·사용자 확정 등 실제 영향을 받는 회계 불변조건은 필요한 만큼 보호한다.

## 목표 업무 구조 (현재 운영과 구분)

[Google 최종정본 / COST 카드·영수증 지출 작성 보조 — 목표 명세](docs/target-workflow-google-authority.md)를 따른다. 수입과 은행 이체 지출은 사용자가 Google에 직접 입력하며 COST는 읽기 전용으로 가져온다. 법인카드·현지 영수증 지출은 COST에서 검토·분류한 후 사용자가 Google에 직접 복사·붙여넣는다. 이 구조는 **후속 개편 목표**이며 현재 SQLite 운영 정본이 이미 전환되었다는 뜻이 아니다. 구현 전 미확정 사항은 목표 명세 9절에서 확인한다.

## 문서 안내

- [보험가입 명단 기반 참가자 확정·수입 대조 계획과 명세](docs/participant-income-reconciliation-spec.md)와 [해당 기능 작업 인덱스](docs/participant-income-task-index.md): 계획 작성 완료이며 제품 구현·운영 적용은 미실행이다.
- [현재 운영 상태와 검증](docs/operations.md)
- [미결 작업과 다음 세션 인계](docs/session_handoff.md)
- [업무 규칙](docs/business_rules.md)
- [구조와 정본](docs/architecture.md)
- [카드 처리와 API](docs/card_pipeline.md)
- [OTA 예약 근거](docs/ota_mail.md)
- [카드 수집과 원본 검증](docs/card_downloads.md)
- [웹 실행](webapp/README.md)
- [장부 화면 검증](webapp/DESIGN_REVIEW.md)
- [과거 원장 도구의 역할](ledger/README.md)

원본·운영 DB·비밀값·실행 증거는 로컬에 보존하고 Git에 추가하지 않는다. 과거 작업 수치와 현재 운영 수치는 구분한다.
