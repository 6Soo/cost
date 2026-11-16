# AI 분기 검수 교정 반영

- 목적: 분기 검수에서 AI 검수자가 확정한 교정 목록(manifest)을 운영 장부에 반영한다. 반영 뒤 거래·장부·화면의 귀속·항목·출처·근거가 일치하고, 변경 전 값과 감사 이력이 남아 원복할 수 있다.
- 실행 주체: 스크립트(`tools/apply_ai_quarter_review.py`). 승인된 배포 담당이 실행한다.
- 주기: 분기 검수 확정 후 1회. 같은 요청 재실행은 변경 없이 `REPLAYED`로 끝난다.
- 개정 이력: 2026-11-13 · 최초 작성 · AI 분기 검수 교정 환류(통합 명세 §6.4·§8) 도구 착수. 합성 검증 완료, 운영 반영·사본 예행은 미실행.

정책 근거는 [통합 명세](../SPEC.md) §6.4(제안과 반영)·§8(분기 검수와 교정 환류)·§13(보호 경계)다. 구조는 [일반 준비기간 추론 귀속 정리](preparation-cost-grouping.md)와 같은 미리보기/digest/신선 백업/감사 원복 구조이며 요청·감사 이름공간은 분리한다(`ai_quarter_review`, `card.ai_review_corrected`, `card.ai_review_restored`).

## 입력

- 비공개 manifest JSON 파일. **레포 작업 폴더 안에 있으면 거부한다**(`MANIFEST_IN_REPOSITORY`). 고객 식별값이 Git에 들어가지 않게 운영 데이터 폴더 등 레포 밖 보호 경로에 둔다(예: `D:/WebLedgerHost/data/review-private/`).
- manifest 형식(합성 예시):

```json
{"review_id": "ai-quarter-review-2026Q3",
 "reviewer": {"provider": "claude", "model": "claude-fable-5-2", "effort": "high"},
 "corrections": [
   {"transaction_id": "<거래 ID>", "source_hash": "<원본 해시>", "revision": 3,
    "display_tab_id": "<여행 tab_id 또는 quarter:YYYY:Q>", "item": "<항목>",
    "basis": "식별값 없는 근거 문장(규칙 ID 포함)"}
 ]}
```

- `transaction_id`·`source_hash`·`revision`은 검수 시점의 행 상태와 일치해야 한다(다르면 `STALE` 제외). 같은 `transaction_id`가 두 번 있으면 전체 실패(`DUPLICATE_CORRECTION`).
- 신선 백업·복원 검증 증거(`tools/verify_operational_backup_restore.py` 산출물, 1시간 이내).
- Board·SourceRefresh writer 정지 상태(반영 시). Gateway는 유지한다.

## 단계

1. **백업 검증.** 신선 백업과 복원 동등을 확인한다. 실패하면 멈춘다(`BACKUP_RESTORE_FAILED`).
2. **미리보기.** 읽기 전용으로 대상·제외 사유·여행별 행 수 변화·분기별 증가 수를 집계한다. 쓰기는 없다. 보고서에 식별값·금액은 없다.
3. **반영.** 미리보기 digest와 백업 증거를 제시해야만 쓴다(`--apply --expected-digest --backup-evidence`). writer 정지 게이트를 통과해야 한다. 기존 장부 행·화면 행만 동기화하고 새 행은 만들지 않는다.
4. **재실행 확인.** 같은 요청을 다시 실행해 `REPLAYED`(변경 0)를 확인한다.
5. 필요하면 **원복.** 다시 신선 백업을 만든 뒤 `--restore` 미리보기 digest로 실행한다.

운영 반영은 호출 세션과 분리된 프로세스로 실행하고 `finally`에서 Board 시작·route resume·Worker 시작을 수행한다. 승인된 배포 담당이 신선 백업·복원 검증 후 검증된 릴리스의 Python으로 실행한다.

```powershell
$reviewEvidence = 'D:/WebLedgerHost/data/backups/ai-quarter-review-2026Q3'
$reviewManifest = 'D:/WebLedgerHost/data/review-private/ai-quarter-review-2026Q3.json'
New-Item -ItemType Directory -Path $reviewEvidence -Force | Out-Null
python tools/verify_operational_backup_restore.py --evidence-out "$reviewEvidence/backup-restore.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/apply_ai_quarter_review.py --host-root D:/WebLedgerHost --manifest $reviewManifest --request-id ai-quarter-review-2026Q3 --report "$reviewEvidence/preview.json"
if ($LASTEXITCODE -ne 0) { throw 'PREVIEW_FAILED' }
$reviewPlan = Get-Content -LiteralPath "$reviewEvidence/preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/apply_ai_quarter_review.py --host-root D:/WebLedgerHost --manifest $reviewManifest --request-id ai-quarter-review-2026Q3 --apply --expected-digest $reviewPlan.digest --backup-evidence "$reviewEvidence/backup-restore.json" --report "$reviewEvidence/applied.json"
if ($LASTEXITCODE -ne 0) { throw 'APPLY_FAILED' }
python tools/apply_ai_quarter_review.py --host-root D:/WebLedgerHost --manifest $reviewManifest --request-id ai-quarter-review-2026Q3 --report "$reviewEvidence/replay.json"
```

원복은 다시 신선 백업을 만든 후 `--restore` 미리보기의 digest로 실행한다. 이후 사용자 편집·금융 보호 변경·다른 수정이 있으면 원복을 거부한다(`AI_REVIEW_RESTORE_STALE`·`AI_REVIEW_RESTORE_FINANCIAL_STALE`). 감사 이력과 revision은 남기고 귀속·항목·출처·근거·투영은 변경 전으로 복원한다.

```powershell
python tools/verify_operational_backup_restore.py --evidence-out "$reviewEvidence/restore-backup.json"
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_RESTORE_FAILED' }
python tools/apply_ai_quarter_review.py --host-root D:/WebLedgerHost --request-id ai-quarter-review-2026Q3 --restore --report "$reviewEvidence/restore-preview.json"
$reviewRestore = Get-Content -LiteralPath "$reviewEvidence/restore-preview.json" -Encoding UTF8 | ConvertFrom-Json
python tools/apply_ai_quarter_review.py --host-root D:/WebLedgerHost --request-id ai-quarter-review-2026Q3 --restore --apply --expected-digest $reviewRestore.digest --backup-evidence "$reviewEvidence/restore-backup.json" --report "$reviewEvidence/restored.json"
```

사본은 `--isolated-copy`로만 writer 정지 확인을 생략할 수 있다. 신선 백업·복원 동등·파일 분리 확인은 그대로 필요하며 운영 DB·동일 파일·하드링크는 거부한다.

## 판단 기준

반영 값은 `item`, `display_tab_id`, `trip_id`(여행이면 같은 tab_id, 분기이면 빈 값), `classification_source='ai_inference'`, `classification_state='classified'`, 근거는 `AI_REVIEW · {model·provider·effort·review_id} · 근거 문장`이다. 사용자 결정 표기(`user_decision` 등)와 `decided_at`은 쓰지 않는다.

- 여행 목적지는 열린 여행(시작일 2026-06-30 이후, 삭제·보관 아님)이어야 한다.
- 분기 목적지는 `quarter:YYYY:Q` 형식이고 2026년 3분기 이후이며 그 거래의 결제일 분기와 같아야 한다. 항목은 `분기 기타비용`으로 강제한다.
- 현재 귀속도 열린 분기(열린 여행 또는 2026년 3분기 이후 분기 목적지)여야 한다. 닫힌 분기 여행에서 꺼내거나 넣지 않는다. 같은 여행 안의 항목만 바꾸는 교정도 허용한다.
- **PROC-073 원문 재대조 예외:** 사용자가 지시한 과거 Q2 자동 귀속의 명시적 재검수는 manifest의 `scope="q2_source_recheck"`와 `--source-review <보호 폴더>`를 함께 사용한다. `source_recheck.load`가 보호 폴더의 `manifest.json`에 나열한 원본 해시·원본 카드 파일 재파싱·카드 필드·이전 여행을 검증하고 공통 판정 규칙으로 목적지를 재계산한다. 교정 manifest의 목적지·항목·근거가 재계산 결과와 다르면 제외한다. 근거 문서의 `version=1`, `review_id`, `reviews` 및 각 행의 `transaction_id`, `card`, `before_tab`, `kind`, `basis`, `originals`는 필수다. `originals`는 보호 폴더 내부 상대 `path`, `sha256`, `role`을 가진다. 원본 역할은 `card_original`, `payment_confirmation`, `cancellation_confirmation`, `counter_evidence`, `manual_ledger`다.
  - `payment_outside_trip`: 카드 이용일이 7월 이후이면서 기존 Q2 여행 종료 뒤인 자동 추론만 공통 날짜·지역 규칙으로 재판정한다. 실제 서비스 기간을 생성하지 않는다.
  - `manual_ledger_attribution`: `manual_ledger` 역할의 보관 XLSX 두 개에 `ledger_source=archive/main`과 해당 정식 `spreadsheet_id`를 지정한다. 전체 Q1/Q2 원문에서 금액+(결제일 또는 업체 일부)로 일치하는 행이 없고, 열린 Q3/Q4 수기 원문에 유일한 카드·원장 행이 있으며 명시된 이용기간이 해당 실제 여행 안에 있는 경우 그 여행과 원문 항목으로 교정한다. 원문 2자리 연도는 명시된 원장 연도와 같아야 한다. 최초 owner 수입은 빈 여행·빈 이전 값·정식 최초 요청·카드 원본 지문·이후 사용자 수정 없음까지 검증할 때만 허용한다. 실제 사용자 교정은 계속 보호한다. 원문 기간은 근거에 보존하며 실제 예약·결제 연결이나 이용 완료를 생성하지 않는다.
  - `cancelled_booking_payment`: 실제 결제 원문과 취소 완료 원문, 같은 `booking_ref`/`cancelled_booking_ref`, `reservation_status="cancelled"`가 필요하다. 기존 공통 메일 판독기로 인증·예약번호·결제일/금액·실제 취소 완료를 원문에서 다시 읽고 대조하며 역할명/해시 선언만으로 통과시키지 않는다. 양수 결제 원액을 결제일 분기 기타비용으로 분류한다. Q2 목적지는 이 취소 사례에서만 허용된다. 메일 환불 안내를 실제 환불 원행으로 만들지 않는다.
  - 원행 최초 생성의 자동 확인 표기와 이후 실제 사용자 수정 부재까지 확인한다. `actor=owner`와 `confirmed_by=owner`인 기장은 제외한다. 닫힌 Q1·실제 수동·P2·환불·원본·투영 보호 및 동일한 백업/복원/감사/재실행 게이트는 유지한다. 원본 지문은 교정 감사 이력에 포함된다.
- 행별 제외 사유(미리보기 요약에 사유별 건수, 식별값·금액 없음):
  - `STALE` — source_hash·revision 불일치(검수 뒤 행이 바뀜).
  - `MANUAL_OR_USER_EXCEPTION` — 수동 결정·수동 출처·활성 검수 결정·화면 수동 덮어쓰기.
  - `CLOSED_CARD_PERIOD` — 결제일이 닫힌 카드 기간(2025년·2026년 1분기)이거나 현재 귀속이 열린 분기가 아님(닫힌 여행·닫힌 분기·미분류).
  - `SOURCE_PROTECTED` — 중복·원본 충돌·파서 오류.
  - `REVIEW_HOLD` / `COMPANY_EXCLUDED` — 검수 보류·회사 제외.
  - `PROJECTION_ATTRIBUTION_DISAGREEMENT` — 거래/장부/화면 귀속 불일치 또는 화면 수동 확인 표기.
  - `INVALID_TARGET` — 잘못된 목적지(닫힌 여행·미존재 여행·경계 이전 분기·결제일 분기 불일치·빈 항목/근거).
  - `NO_CHANGE` — 이미 같은 값.
  - `REFUND_*` — 환불 보호. 정식 환불 묶음은 **모든 구성원이 manifest에 같은 목적지로 들어 있을 때만** 함께 옮긴다. 일부만 포함(`REFUND_INELIGIBLE_MEMBER`), 목적지 불일치(`REFUND_DESTINATION_DISAGREEMENT`), 초과 환불·추론 연결·미검증 연결(`REFUND_UNVERIFIED_OR_EXCESS`), 불완전 묶음(`REFUND_INCOMPLETE_GROUP`), 짝 없는 환불 보호(`REFUND_UNPAIRED`)는 묶음 전체를 제외한다.
- 미리보기는 쓰지 않는다. digest는 대상·여행·manifest·금융 상태를 묶는다.
- 금액·부호·원문·ID·금융 연결은 불변이며 반영 전후 금융 상태 동일을 검사한다(다르면 `AI_REVIEW_FINANCIAL_CHANGED`로 롤백).

## 출력

- `--report` 파일과 stdout JSON: `status`(PREVIEW/APPLIED/REPLAYED/FAILED), `digest`, `manifest_rows`(manifest 건수), `to_apply`(반영 대상 수), `kinds`(여행→여행·여행→분기·분기→여행·항목만, 해당 시 분기→분기), `excluded`(사유별 건수), `refund_move_rows`·`refund_move_groups`, `open_trip_row_delta`(열린 여행 표시 이름과 행 수 변화), `quarter_increases`(분기별 순증가), `applied_this_run`.
- 감사 이력: `change_log`의 `card.ai_review_corrected`(변경 전/후 전체 상태·금융 지문)·`card.ai_review_restored`, 요청 기록 `requests`의 `ai_quarter_review` 범위.
- 검증 방법: 재실행 `REPLAYED`·변경 0, 반영 전후 금융 지문 동일, 원복 후 변경 전 값 일치(revision·감사 이력은 증가·보존).

## 실패했을 때

- `MANIFEST_IN_REPOSITORY`·`MANIFEST_REQUIRED`·`MANIFEST_INVALID`·`DUPLICATE_CORRECTION` — manifest를 레포 밖 보호 경로로 옮기거나 형식·중복을 고친 뒤 다시 미리보기한다. 운영 쓰기는 없었다.
- `PREVIEW_AND_BACKUP_REQUIRED`·`BACKUP_RESTORE_NOT_VERIFIED`·`BACKUP_NOT_FRESH`·`BACKUP_SOURCE_CHANGED`·`WRITERS_NOT_OFFLINE` — 반영 게이트 미충족. 백업을 다시 만들고 writer를 멈춘 뒤 재시도한다. 쓰기는 없었다.
- `AI_REVIEW_PREVIEW_STALE` — 미리보기 뒤 행·여행·금융 상태가 바뀌었다. 다시 미리보기해 새 digest로 반영한다.
- `AI_REVIEW_REQUEST_CONFLICT` — 같은 요청 ID로 다른 내용이 이미 반영됐다. 요청 ID를 분리하거나 기존 반영을 확인한다.
- `AI_REVIEW_RESTORE_STALE`·`AI_REVIEW_RESTORE_FINANCIAL_STALE` — 반영 뒤 편집·금융 변경이 있어 원복을 거부한다. 이후 변경을 먼저 확인하고 필요하면 수동 교정 절차를 따른다. 강제 원복하지 않는다.
- `AI_REVIEW_FINANCIAL_CHANGED`·쓰기 중 오류 — 트랜잭션 전체가 롤백된다. 다시 미리보기부터 시작한다.
- 재시도 한도: 같은 실패 코드가 2회 반복되면 멈추고 헤드 담당에게 보고한다.

## 하지 않는 것

- 카드 원문·금액·부호·ID·금융 연결을 바꾸거나 지우지 않는다. 새 장부 행·금융 연결을 만들지 않는다.
- 사용자 결정 표기(`user_decision` 등)·`decided_at`을 쓰지 않는다. 수동 교정·보류·제외·닫힌 기간을 덮지 않는다.
- Google 최종 장부에 쓰지 않는다. 여행은 Google 시트 탭에서만 생긴다.
- 고객 원문·식별값·금액을 Git·PR·보고서·stdout에 넣지 않는다. manifest는 레포 밖에 둔다.
- 운영 포트 8751·8752·8790을 미리보기·테스트에 쓰지 않는다. 시작하지 않은 프로세스를 종료하지 않는다.
- 인증 우회·강제 push·운영 DB 삭제·승인 없는 과금을 하지 않는다. 병합·배포는 헤드 담당만 한다.
