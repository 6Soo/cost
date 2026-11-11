# 서버 밖 P2 제안

실행 기준은 [통합 명세](../../docs/SPEC.md) §6과 [규칙집](../../docs/DECISION_POLICY.md)이다. 운영 Board 내장 P2는 비활성 상태로 유지한다. 이 도구에는 반영·배포·규칙 등록 기능이 없다.

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m tools.p2_batch.layer1 --db D:/WebLedgerHost/data/board.sqlite --output .local-archive/p2-batch-20261111
```

`--scope-only`는 집계와 보호 경로의 가맹점 입력/변경 전 값 생성까지만 수행한다. 기본 묶음은 45곳이며 `--batch-size`는 30~50이다. 운영 SQLite는 짧은 일관 읽기 후 닫고, 외부 서버나 포트에 연결하지 않는다. 환불 원결제·충돌·중복·수동 결정·제외·보류 보호를 메모리에서 검사한다. 빈 수동 결정 이력만으로 미배정을 사용자 선택이라고 해석하지 않는다.

실제 모델은 기존 도구 없는 실행기의 `gpt-6.1-sol`이며, 빈 cwd·read-only·never·도구 차단 설정과 소유 프로세스 시간 제한을 사용한다. 출력 스키마와 요청 지문, 모든 가맹점의 정확한 1회 출현, 항목·확신·근거를 검증한다. 용량·형식 오류는 최대 3회, 30/60초 간격으로 재시도한다. 인증·도구 실행 오류는 즉시 중단한다. 완료 묶음은 요청 지문이 같을 때만 재사용한다.

보호 출력 폴더에는 `scope-summary.json`, `merchant-inputs.json`, `before-state.json`, `batch-*.json`, `proposals.jsonl`, `summary.json`, `sample-30.json`을 남긴다. 거래 식별값·변경 전 값·가맹점 표본은 Git·PR·보고에 복제하지 않는다. 저장된 표시행의 이용일 경고는 실제 화면 함수로 집계하지만, 서버 메모리에만 있는 OTA 파생 근거는 읽지 않으므로 실시간 화면 경고 수의 상한이다.

P1 등록은 후속 승인 때 `app.rules.normalize_rule`과 `save_rule`로 한다. 조건은 정확한 `merchant_normalized`와 구매 방향, 효과는 `item`만 두고, `origin`에는 P2 실행 식별자를 적는다. 기존 규칙과 충돌 여부를 확인하고 `save_rule`의 버전·규칙 해시·변경 이력을 보존한다. 국가·이용기간·상품 종류 등 거래별 조건이 필요한 결과를 무조건 가맹점 전체 규칙으로 넓히지 않는다. 현재는 제안만이며 등록하지 않는다.

## 단계 2 정리·미리보기

완료된 `proposals.jsonl`은 모델을 다시 호출하지 않고 정리한다.

```powershell
python -m tools.p2_batch.normalize --archive .local-archive/p2-batch-20261111 --db D:/WebLedgerHost/data/board.sqlite
python -m tools.p2_batch.preview --archive .local-archive/p2-batch-20261111 --db D:/WebLedgerHost/data/board.sqlite
```

정리는 2026-04 이후 운영 장부에 실제 사용된 항목만 허용한다. `대중교통`은 `교통비`, 시설 이용이 확인되는 `이용료`는 `입장료`로 맞추고, 편의점·시설 이용이 아닌 이용료·알 수 없는 항목은 기존 항목 유지로 둔다. 동일 가맹점의 공백·도시·국가 표기 변형은 묶어 다수결을 적용하며 동률은 유지한다. `preview`는 `mode=ro`로 기존 교정 경로를 호출하고 보호 사유별 제외 수만 기록한다. 기록된 장부·화면 행을 AI 교정이 덮어쓰도록 서버 보호를 바꾸지 않는다.
