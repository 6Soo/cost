# 2026-08-26 세션 인계 — reservation 일정 export와 cost 권위 import

> 상태: `PARTIAL_HANDOFF`
>
> 이번 세션은 2025년 결제연도와 행사연도를 분리하는 회계 draft 수정과
> reservation → cost 일정 export/import 경계를 재개했다. 회계 전기·외부 게시·배포는
> 수행하지 않았다. Production reservation export는 연결정보 형식 오류로 아직 생성되지
> 않았다.

## 다음 세션 시작 순서

1. 이 파일과 `AGENTS.md`, `LOG.md` 맨 아래를 읽는다.
2. `C:\AX\reservation\.env.local`의 `TURSO_DATABASE_URL`과 `TURSO_AUTH_TOKEN`을
   실제 Production 값으로 다시 동기화한다. 값은 채팅이나 문서에 기록하지 않는다.
3. reservation 저장소에서 아래 명령으로 export 파일을 만든다.

   ```powershell
   cd C:\AX\reservation
   npm.cmd run export:schedule -- --output outputs/reservation-trip-schedule-export-20260826.json
   ```

4. export 파일의 schema, record count, SHA-256을 확인한 뒤 cost의 격리 DB 복제본에
   다음처럼 두 번 import한다.

   ```powershell
   cd C:\AX\cost
   python tools/import_reservation_schedule.py `
     --input C:\AX\reservation\outputs\reservation-trip-schedule-export-20260826.json `
     --db outputs/cost-with-reservation-schedule-20260826.sqlite
   ```

   결과에서 첫 import는 실제 삽입, 두 번째 import는 `inserted=0`,
   `idempotent=true`, `posting_created=false`여야 한다.

5. import 후 `load_authoritative_trip_schedule`로 `authority_status=authoritative`,
   명시 `event_year/starts_on/ends_on`, `end_semantics`, source digest가 검증되는지
   확인한다. `window`, 월일 텍스트, 결제일 연도는 일정 생성에 사용하지 않는다.
6. 검증이 끝난 뒤에만 reservation export를 기준으로 필요한 Agoda draft를 별도
   산출한다. 기존 운영 DB나 과거 산출물은 덮어쓰지 않는다.

## 이번 세션에서 완료된 것

- `tools/build_agoda_accounting_draft_v3.py`에 `payment_year_terminal`을 추가했다.
  2025년 결제 중 2026년 서비스 기간이 명시된 2건만 2026 일정에 연결하고, 실제
  2025년 서비스 4건은 `2025년 결제`로 종결한다.
- `tools/build_agoda_journal_shadow_v3.py`가 같은 4건을
  `payment_year_terminal` shadow cohort로 보존한다.
- 관련 cost 회귀 35/35 PASS.
- draft/shadow 반복 생성의 DB·detail·audit SHA-256이 모두 일치했다.
- AGY smoke test는 `AGY_SMOKE: PASS`였고, 생성된 smoke agent는 archive했다.

## 최신 회계 산출물

- draft DB: `outputs/agoda-card-accounting-draft-v3-windowless-v3-20260826.sqlite`
  - SHA-256: `27b0aaf335630e6ae5271470f920c7b88687b7664df40371153d3f81eb044842`
- journal shadow DB: `outputs/agoda-card-journal-shadow-v3-windowless-v3-20260826.sqlite`
  - SHA-256: `5d404c4a93742a0cad4d31d2b76f91e124c086d6977c426be288b1f5195ceee3`
- 전체 77건, 2025 결제 6건, 그중 terminal 4건, 2026 명시 연결 2건,
  2026 권위 미확정 25건, 총액 20,546,481원, 실제 전기 0건.

## reservation export 현재 상태

- export 계약·함수: `C:\AX\reservation\src\lib\scheduleExport.ts`
- export 실행 스크립트: `C:\AX\reservation\scripts\export-schedule.ts`
- reservation 계약 테스트: `tests/scheduleExport.test.ts` 5/5 PASS.
- 2026-08-26 production export 실행은 `URL_INVALID`로 실패했다.
  `.env.local`에는 두 변수명이 있으나 현재 값이 유효한 `libsql://`/`https://` URL과
  token이 아니라 placeholder 형식이다.
- `outputs/quarantine-local-demo-20260825/reservation-trip-schedule-export-20260825.json`
  은 demo 격리 자료다. Production authority로 사용하지 않는다.

## cost import 경계 smoke 결과

demo 파일을 운영 자료로 사용하지 않는 별도 검증으로만
`outputs/reservation-schedule-import-smoke-20260826.sqlite`에 import했다.

- 첫 import: 3 records, authoritative 3, inserted 7
- 두 번째 import: inserted 0, `idempotent=true`
- `posting_created=false`
- `trip_schedule` source rows 3, `integrity_check=ok`, foreign-key 위반 0
- smoke DB SHA-256: `7f6a5f4c7303fcaa50c3b0e6a53588562c218636d49d07611504a515bab1a051`
- 이 수치는 demo 자료의 smoke 결과이며 Production 일정 수치가 아니다.

## 금지·보존 사항

- Vercel secret 값을 채팅·LOG·handoff에 복사하지 않는다.
- 기존 `windowless-v2`와 quarantine 파일은 audit/replay용으로 보존한다.
- reservation export가 검증되기 전에는 `trip_schedule` 권위로 승격하지 않는다.
- 권위 일정 import는 읽기·멱등 저장만 수행하며, posting이나 외부 전기를 만들지 않는다.
