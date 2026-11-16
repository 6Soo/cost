# 서버 밖 P2 제안

실행 기준은 [통합 명세](../../docs/SPEC.md) §6과 [규칙집](../../docs/DECISION_POLICY.md)이다. 운영 Board 내장 P2는 비활성 상태로 유지한다. 아래 기존 도구는 제안·미리보기 전용이며, 후속 승인된 증분 진입점은 기존 인증 API로 반영·규칙 등록을 수행한다. 배포 기능은 없다.

## 카드 수입 뒤 증분 1층

[운영 절차서](../../docs/playbooks/p2-incremental.md). 아래의 개발 범위·후속 계획은 구현 당시 기록이다. 이후 첫 실제 실행은 `--propose-only`로 모델 1회 성공·제안 4건·반영 0이었고, 인증 페이지를 확보하지 못해 apply를 실행하지 않았다([운영 기록](../../docs/history/operations-through-20261113.md#2026-11-13-2200-창--db848712-배포booking-132건증분-p2-첫-실행)). 최신 실행 상태는 [현재 상태](../../docs/session_handoff.md)와 [운영 기록](../../docs/operations.md)을 따른다. 이 문서를 읽는 것만으로 실제 호출·반영·예약 등록을 시작하지 않는다.

자동 실행 연결 비교(등록 스크립트만 포함, 등록은 헤드가 한다):
- 별도 Windows 예약 작업: 서버 배포 없이 하루 1회 실행하고 대상 0이면 모델·API 없이 즉시 종료하지만, 로그인된 Windows 세션·ego·Codex 구독이 필요하고 수입 시점과 최대 24시간 차이가 난다.
- Worker 주기 작업: 카드 수입 직후라 실행 순서가 정확하지만 서버 코드 변경·배포와 운영 검증 부담이 늘어난다.
- 이번에는 서버 변경 없이 예약 작업 방식만 제안하며 `register_incremental_task.ps1`은 실행하지 않았다. Codex 한도 오류는 실패로 기록되고 다음 예약 실행에서 이어진다.

```powershell
python -m tools.p2_batch.run_incremental --dry-run
python -m tools.p2_batch.run_incremental --propose-only --max-merchants 30 --max-calls 1
python -m tools.p2_batch.run_incremental --api-config D:/WebLedgerHost/data/p2-api.json --max-merchants 30 --max-calls 1
python -m tools.p2_batch.run_incremental --api-config D:/WebLedgerHost/data/p2-api.json --max-merchants 30 --max-calls 1 --register-rules
```

`scope.select`의 열린 분기·PROC-072·수동·금융·투영 보호를 그대로 사용한다. 이전 제안(유지·낮은 확신 포함)과 **그 가맹점 이름을 명시적으로 지정한 무조건 규칙이 구체 항목을 정한** 묶음만 신규에서 제외한다. `*` 전체 가맹점 규칙·패턴(가맹점 가족)·국가/기간/원본 결속 조건 규칙은 가맹점 전체를 덮지 못하므로 제외 사유가 아니며, 포괄 항목(기타경비·현지경비·여행경비)을 정한 명시 규칙도 제외하지 않는다 — 포괄 항목으로 남은 행을 AI가 다시 보게 하는 것이 목적이다. 도시·국가를 지운 별칭으로 범위를 넓히지 않는다. 대상 0이면 모델·인증 API를 호출하지 않는다. 기본 최대30묶음·모델1회, 묶음 크기30(30~50), 한 호출240초다. 실패 호출도 상한에 포함하며 혼잡·한도 오류는 실패 기록 후 다음 회차에 재시도한다. Claude 자동 전환은 없다.

저널은 `D:/WebLedgerHost/data/p2-incremental.json` 하나다. 원문 입력·변경 전 값·검증된 제안·요청 지문·사용량·API 요청과 결과 진행 상태·실행별 성공/실패 집계를 포함한다. 원자 교체와 별도 배타 lock으로 중복 실행을 막는다. 잠금 파일에는 작성 PID·시작 시각을 적으며, PID가 살아 있지 않거나 2시간을 넘은 잠금은 `STALE_LOCK_RECOVERED` 실패 기록 후 자동 인수한다. 살아 있는 최근 잠금과 확인 불가한 최근 파일은 거부한다. 상태를 지워 재실행하지 않는다. API 요청은 미리보기 digest와 고정 request_id를 보내기 전에 저장하고, 응답 유실 시 그대로 재전송한다. 새로 들어온 동명 거래를 이전 제안으로 자동 확장하지 않는다.

제안 전용 결과는 다음 실제 실행에서 모델 호출 없이 반영을 재개한다. 수동·금융·revision·원문·규칙이 바뀐 미준비 대상은 중단한다. 각 교정 요청은 최대50행이며 서버의 신선도·보호 가드를 통과해야 한다. **항목 교정과 규칙 등록은 따로 승인한다.** 규칙 등록은 기본 꺼짐이며 `--register-rules`를 명시한 실행에서만 반복2행 이상·높은 확신·단일 정확 가맹점·충돌 없음인 비포괄 항목을 `app.rules.normalize_rule`로 정리해 `/api/imports/rules`에 등록한다. 효과는 item 하나, 구매 조건, P2 실행 출처를 유지한다. 예약·상품 혼합은 기존 1층의 유지 판정을 따르며 단건은 승격하지 않는다. 교정만 완료한 묶음은 소급 등록하지 않으며, 이미 초안이 남은 묶음은 다음 `--register-rules` 실행에서 등록을 마친다.

초기 저널은 기존 `proposals.jsonl`로 `python -m tools.p2_batch.initialize_history --proposals <비공개경로>`를 실행해 만든다. 현재는 이전 원문이 삭제되어, 보존된 실행 전 백업과 당시 선택 코드 `d2a0c4428c7e0e56a320e7c0f15c639490c6d47c`로 585묶음/1,258행/13회 완료 집계와 대조해 초기화했다. 이는 원제안 파일의 직접 복원이 아닌 대상 재현임을 저널에 명시한다. 기본 이력 누락·집계 불일치는 실행을 거부한다.

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m tools.p2_batch.layer1 --db D:/WebLedgerHost/data/board.sqlite --output .local-archive/p2-batch-20261111
```

`--scope-only`는 집계와 보호 경로의 가맹점 입력/변경 전 값 생성까지만 수행한다. 기본 묶음은 45곳이며 `--batch-size`는 30~50이다. 운영 SQLite는 짧은 일관 읽기 후 닫고, 외부 서버나 포트에 연결하지 않는다. 환불 원결제·충돌·중복·수동 결정·제외·보류 보호를 메모리에서 검사한다. 빈 수동 결정 이력만으로 미배정을 사용자 선택이라고 해석하지 않는다.

실제 모델은 기존 도구 없는 실행기의 `gpt-6.1-sol`이며, 빈 cwd·read-only·never·도구 차단 설정과 소유 프로세스 시간 제한을 사용한다. 출력 스키마와 요청 지문, 모든 가맹점의 정확한 1회 출현, 항목·확신·근거를 검증한다. 용량·형식 오류는 최대 3회, 30/60초 간격으로 재시도한다. 인증·도구 실행 오류는 즉시 중단한다. 완료 묶음은 요청 지문이 같을 때만 재사용한다.

보호 출력 폴더에는 `scope-summary.json`, `merchant-inputs.json`, `before-state.json`, `batch-*.json`, `proposals.jsonl`, `summary.json`, `sample-30.json`을 남긴다. 거래 식별값·변경 전 값·가맹점 표본은 Git·PR·보고에 복제하지 않는다. 저장된 표시행의 이용일 경고는 실제 화면 함수로 집계하지만, 서버 메모리에만 있는 OTA 파생 근거는 읽지 않으므로 실시간 화면 경고 수의 상한이다.

P1 등록은 후속 승인 때 `app.rules.normalize_rule`과 `save_rule`로 한다. 조건은 정확한 `merchant_normalized`와 구매 방향, 효과는 `item`만 두고, `origin`에는 P2 실행 식별자를 적는다. 기존 규칙과 충돌 여부를 확인하고 `save_rule`의 버전·규칙 해시·변경 이력을 보존한다. 국가·이용기간·상품 종류 등 거래별 조건이 필요한 결과를 무조건 가맹점 전체 규칙으로 넓히지 않는다. 현재는 제안만이며 등록하지 않는다.

## 단계 2 정리·미리보기

대상 선정과 미리보기는 거래와 기존 장부 행의 `trip_id` 또는 `display_tab_id`가 서로 다른 건을 `PROJECTION_ATTRIBUTION_DISAGREEMENT`로 제외한다. 열린 분기 전체의 불일치 건수는 `projection_attribution_disagreements`로 집계한다. 이 건들은 귀속을 자동 수정하지 않고 분기 검수 목록에 해시만 남긴다. 장부 행이 없는 거래는 이 조건으로 제외하지 않는다.

완료된 `proposals.jsonl`은 모델을 다시 호출하지 않고 정리한다.

```powershell
python -m tools.p2_batch.normalize --archive .local-archive/p2-batch-20261111 --db D:/WebLedgerHost/data/board.sqlite
python -m tools.p2_batch.preview --archive .local-archive/p2-batch-20261111 --db D:/WebLedgerHost/data/board.sqlite
```

정리는 2026-04 이후 운영 장부에 실제 사용된 항목만 허용한다. `대중교통`은 `교통비`, 시설 이용이 확인되는 `이용료`는 `입장료`로 맞추고, 편의점·시설 이용이 아닌 이용료·알 수 없는 항목은 기존 항목 유지로 둔다. 동일 가맹점의 공백·도시·국가 표기 변형은 묶어 다수결을 적용하며 동률은 유지한다. `preview`는 `mode=ro`로 기존 교정 경로를 호출하고 보호 사유별 제외 수만 기록한다. 기록된 장부·화면 행을 AI 교정이 덮어쓰도록 서버 보호를 바꾸지 않는다.
