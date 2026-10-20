# 숲길여행 비용처리

## 현재 OTA 자료 연결

메일·포털·과거 조사 자료는 운영 `ota-sources.json`에 등록해 함께 조회한다. 자료 내용 변경을 감지하고 미연결 사유를 구분하는 수정까지 적용했다. 현재 연결 수와 남은 항목, 실제 검증 범위는 [OTA 문서](docs/ota_mail.md)의 최신 항목을 따른다.

카드 파일 업로드 → 자동 분류 → 원본·보류·중복·환불·OTA 보호를 통과한 거래는 **COST 내부 장부 자동 기록** → 예외만 사용자가 **지출 정리**에서 수정한다. Google 최종 장부에는 자동 쓰기하지 않고, 기존 7열 복사·사용자 붙여넣기 경계를 지킨다.

[운영 장부](https://ledger.foresttour.kr/)의 [지출 정리](https://ledger.foresttour.kr/import)는 카드 미기록 예외와 장부 미배정 지출을 통합 표시한다. 원본 거래·사용자 수정 이력을 보존한다. 현재 화면 및 로컬 AI의 미완성 부분은 [2026-10-20 세션 인계](docs/cost-session-handoff-20261020.md)를 따른다.

## 현재 상태

2026-10-20 최신 Git `main`과 운영 배포 이력은 [운영 상태](docs/operations.md) 최상단을 따른다. 2026-10-20 운영 문서상 릴리스는 `f5e27d3`이며, 예약 미연결 안내를 수정했다. 해당 안내의 **로그인된 운영 브라우저 실화면 확인은 PARTIAL**이다. 2026-10-18 운영에서는 지출 정리 카드형 화면(한 페이지 20건)과 자연어 규칙 제안 UI를 확인했다. 자연어 메시지 하나로 기존 규칙 수정·미래 규칙 활성화까지 완료하는 UX와 pstack–Paseo 무료 모델 통합은 아직 완료로 보지 않는다.

**과거 수치 주의**: README 구판의 2026-10-09 거래/장부 건수는 역사적 스냅샷이며 현재 운영 집계가 아니다. 현행 코드·권위 규칙·검증 결과는 [세션 인계](docs/cost-session-handoff-20261020.md), [업무 규칙](docs/business_rules.md) 및 [운영 상태](docs/operations.md)를 참조한다.

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

- [현재 운영 상태와 검증](docs/operations.md)
- [2026-10-20 최신 세션 인계와 구현/미구현 비교](docs/cost-session-handoff-20261020.md)
- [과거 미결 작업과 다음 세션 인계](docs/session_handoff.md)
- [업무 규칙](docs/business_rules.md)
- [구조와 정본](docs/architecture.md)
- [카드 처리와 API](docs/card_pipeline.md)
- [OTA 예약 근거](docs/ota_mail.md)
- [카드 수집과 원본 검증](docs/card_downloads.md)
- [웹 실행](webapp/README.md)
- [장부 화면 검증](webapp/DESIGN_REVIEW.md)
- [과거 원장 도구의 역할](ledger/README.md)

원본·운영 DB·비밀값·실행 증거는 로컬에 보존하고 Git에 추가하지 않는다. 과거 작업 수치와 현재 운영 수치는 구분한다.
