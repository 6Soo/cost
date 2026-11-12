# 수집 상태 점검 — 2026-11-13 (읽기 전용)

지시: 헤드 세션(Cost V182)의 운영 점검 배정. 운영 호스트 `D:\WebLedgerHost`의 예약 작업
`WebLedger-MailCollect`·`WebLedger-GoogleAuthority`·`WebLedger-SourceRefresh`가 Disabled인 것이
의도된 Worker 이관인지, 일부 수집이 멈춘 것인지 판정한다.

- 점검 시각: 2026-11-13 01:12~01:15 KST (상태 조회 01:12:26 KST 기준).
- 방법: 문서·git 이력·예약 작업 조회(`Get-ScheduledTask`/`Get-ScheduledTaskInfo`)·호스트 설정/로그 파일 읽기만 수행.
  예약 작업 활성화·실행·중지, 프로세스 종료, 운영 설정 변경, 운영 DB 쓰기, 운영 포트(8751/8752/8790) 요청은 하지 않았다.
- 고객 원문은 이 보고서에 옮기지 않았다. 로그에서 인용하는 것은 시각·상태 코드·집계 수치뿐이다.

## 1. 결론 요약

| 원천 | 판정 | 마지막 성공 시각 (KST) | 근거 |
| --- | --- | --- | --- |
| Gmail 수집(OTA·항공 메일) | **(가) Worker가 정상 수행 중** | 2026-11-13 00:21:48 (exit 0, 428.3초) | `logs/webledger-worker.log` mail-collect exit 이벤트 |
| Google 수입·여행 탭 동기화 | **(가) Worker가 정상 수행 중** | 2026-11-13 00:15:32 (exit 0, 52.1초) | `logs/webledger-worker.log` google-authority exit 이벤트 + `logs/worker-google-authority.log` 마지막 줄 |
| 기타 원천 새로고침(review-source) | **(가) Worker가 정상 수행 중** | 2026-11-13 01:11:17 (`REFRESH_NO_CHANGE`) | `config/real-review.json.refresh-status.json` |
| 보험 명단(participant-roster) | **(가) Worker가 정상 수행 중** | 2026-11-13 01:12:59 (checked_at, 201명) | `logs/webledger-worker.log` roster 출력 |

**멈춘 수집은 없다. 복구는 불필요하다.** 세 작업의 Disabled는 2026-11-09 백엔드 프로세스 정리에 따른
의도된 이관 상태이며, 같은 일이 `WebLedger-Worker` 안에서 계속 돌고 있다. Gmail OAuth 토큰은
2026-11-10 재인증·프로덕션 게시 이후 유효하다(만료 오류 없음).

## 2. Disabled의 근거 — 의도된 Worker 이관

1. **명세**: [백엔드 프로세스 정리 (2026-11-09)](../../history/specs-20261110/backend-process-consolidation-20261109.md)
   "유지한 것과 이유" 절 — "기존 네 작업(COST-InsuranceRosterSync, WebLedger-SourceRefresh,
   WebLedger-MailCollect, WebLedger-GoogleAuthority)은 삭제하지 않고 비활성화한다."
   `tools/webledger_worker.py` + `WebLedger-Worker` 작업이 보험 명단(60초)·원본 갱신(300초)은 스레드로,
   메일 수집·Google 권한 동기화(매시간)는 자식 프로세스로 실행한다.
2. **커밋/PR**: 구현 `0f5ea6635990ddaef4cd2974b87fbcf4ee7a7d9f`(2026-11-09),
   [PR #767](https://github.com/6Soo/cost/pull/767) 병합 `3dd0750e`.
   [운영 기록](../../operations.md) "2026-11-10 장부 이용일·성능 코드 배포 연속 기록" 표 0행:
   `3dd0750e…` #767(백엔드 작업 Worker 통합) PASS 2026-11-09T08:55Z.
   같은 절 공통 항목: #767 시점에는 Worker 전환 도구 결함으로 `worker_switched=false`였고,
   #769 이후 배포는 모두 `true`.
3. **설치 증거(호스트)**: `D:\WebLedgerHost\logs\worker-install-20261109T175705\`에
   여섯 작업 XML(Board·Gateway·MailCollect·GoogleAuthority·SourceRefresh·InsuranceRosterSync)이
   2026-11-09 17:57:05 KST에 보존돼 있다. `install_webledger_worker.ps1 -Apply`가 기존 작업을
   비활성화하며 남긴 증거 폴더다. 이 시각이 세 작업의 실제 비활성화 시점이다.
4. **현재 명세와의 일치**: [통합 명세](../../SPEC.md) §3("운영은 … 예약 작업 `WebLedger-Board`(8751/8752),
   `WebLedger-Gateway`(8790), `WebLedger-Worker`로 돈다", 94행)는 Worker 체제를 반영한다.
   §7의 Gmail·Google "예약 실행 유지"는 Worker의 매시간 자식 실행으로 이행되고 있다.

## 3. 예약 작업 실측 (2026-11-13 01:12:26 KST)

| 작업 | 상태 | 마지막 실행 | 결과 코드 | 비고 |
| --- | --- | --- | --- | --- |
| WebLedger-MailCollect | Disabled | 2026-11-09 16:09:25 | 0 | Missed=81 |
| WebLedger-GoogleAuthority | Disabled | 2026-11-09 17:00:00 | 0 | Missed=80 |
| WebLedger-SourceRefresh | Disabled | 2026-11-09 16:02:43 | 1 | 이관 전 마지막 실행 실패(명세의 재부팅 후 미재시작 관측과 같은 시기) |
| COST-InsuranceRosterSync | Disabled | 2026-11-09 16:02:43 | 267014 (0x41306 종료됨) | |
| WebLedger-Worker | **Running** | 2026-11-12 23:14:40 | 267009 (0x41301 실행 중) | |

- Missed=81/80은 비활성화 동안 지나간 예약 횟수이며 장애 신호가 아니다. Disabled 작업의 NextRun 표시는 실행을 의미하지 않는다.
- Worker 작업 실행 경로: `pythonw.exe` →
  `D:\WebLedgerHost\releases\335b9eda56b73fd65e201f39a1ffdefd82c955f3\tools\webledger_worker.py --config D:\WebLedgerHost\config\worker.json`.
  릴리스 `335b9eda`는 현재 `origin/main` HEAD(#815 병합)와 같다.
- `worker.json`의 주기 작업 4개:
  | 이름 | 방식 | 주기 | 실행 대상 |
  | --- | --- | --- | --- |
  | participant-roster | watch(스레드) | 60초 | `tools.ingest_participant_roster` |
  | review-source | watch(스레드) | 300초 | `tools.refresh_review_source` |
  | mail-collect | process(자식) | 3600초, timeout 1800초 | `app.mail_collect` (토큰 `secrets\gmail-collector-token.json`) |
  | google-authority | process(자식) | 3600초, timeout 900초 | `tools/google_authority_sync.py --google-auth public` |

## 4. 원천별 증거

### 4.1 Gmail 수집 — (가)

- 감독 로그 `logs/webledger-worker.log`의 이벤트(시각은 KST로 환산):
  - mail-collect start 22:47:23 → exit 0 (22:50:36, 193.3초), start 23:14:41 → exit 0 (23:18:49, 248.9초),
    start 2026-11-13 00:14:40 → **exit 0 (00:21:48, 428.3초)**. 이상 2026-11-12.
  - 직전 로그 `logs/webledger-worker.previous.log`(2026-11-12 05:20:27~22:47 KST 구간)에서
    mail-collect·google-authority의 error/timeout/비정상 종료 이벤트 **0건**.
- 자식 로그 `logs/worker-mail-collect.log`(총 705줄, 타임스탬프 없음). 과거 실패는 세 구간으로, 모두 종료됐다:
  - 1~380줄: DNS 실패 `getaddrinfo failed` 5회(릴리스 `3dd0750e` = 11-09 이관 직후 네트워크 장애).
  - 381~478줄: `OTA_MESSAGE_CONTENT_CONFLICT` 3회(399·418·436줄, 같은 릴리스). 원본 충돌 보호가
    통합 저장소 동기화를 중단시킨 사례로, 사이사이 정상 수집 출력도 섞여 있다. #768/#769(메일 재시도·동일 원본 비교)에서 보강된 경로다.
  - 479~583줄: 토큰 만료 시기 `HTTP Error 400` 3회(513·548·583줄, 릴리스 `998dd461` = 11-10).
  - **584~705줄은 전부 `matched N fetched M` 정상 출력이며 오류 라인이 0건이다.**
    마지막 실행은 신규 0건(증분 정상, 예: `matched 188 fetched 0`, `history matched 9438 fetched 0`).
- 주기 참고: 자식 실행은 Worker 시작 시각에 닻을 내려 매시 :14분에 시작한다(과거 인계의 "매시 30분"은 당시 Worker 시작 시각 기준).

### 4.2 Google 수입·여행 탭 — (가)

- 감독 로그: google-authority exit 0 — 22:48:13(51.0초), 23:15:36(56.4초), **2026-11-13 00:15:32(52.1초)**.
- 자식 로그 `logs/worker-google-authority.log`(총 105줄):
  - 1~3줄: `SOURCE_UNREACHABLE`·stale=true (11-09 이관 직후 네트워크 장애 시기),
    4~5줄: `BACKOFF_WAIT` next_attempt 2026-11-09T19:31:07 KST.
  - 6줄부터 마지막(105줄)까지 전부 `status ok·error_code null·stale false`:
    main 45탭·archive 22탭·andre_main 5탭, trips 71.
- 이 작업은 `--google-auth public`(공개 XLSX 내보내기 읽기) 모드라 Gmail OAuth 토큰과 무관하다.
  Google 원본·공유 권한 변경은 없었다(로그상 읽기 동기화만).

### 4.3 기타 원천 새로고침(review-source) — (가)

- watch 스레드가 2026-11-12 23:14:40 KST 시작 이후 exit/error 없이 실행 중(감독 로그).
- 상태 파일 `config/real-review.json.refresh-status.json`:
  `{"code": "REFRESH_NO_CHANGE", "collected_at": "2026-11-12T16:11:17Z"}` = **2026-11-13 01:11:17 KST**.
  `REFRESH_NO_CHANGE`는 성공이며 디스크를 바꾸지 않는 성공이다(`tools/refresh_review_source.py` run_once).
- 실제 번들 갱신(원천 변경 시) 마지막: `review\refreshed\8285af1d70f48c13-…\` 2026-11-12 20:12:27 KST.
  이후 300초 주기 수집은 계속 성공하며 변경 없음으로 지나가고 있다.
- participant-roster: 감독 로그의 마지막 roster 출력 `checked_at 2026-11-12T16:12:59Z`
  = **2026-11-13 01:12:59 KST**, participant_count 201. 60초 주기 감시 정상.

## 5. Gmail OAuth 토큰 상태

- [운영 기록](../../operations.md) 말미 절차 항목: "2026-11-10 17:06 KST Gmail 수집 토큰 만료(테스트 상태 OAuth 앱 7일)
  → 재인증·프로덕션 게시로 복구."
- 호스트 토큰 파일 `secrets\gmail-collector-token.json` 메타데이터: 207 bytes,
  LastWrite **2026-11-10 18:17:48 KST** — 재인증 시각과 일치(내용은 읽지 않았다).
- 재인증 이후 자식 로그에 HTTP 400/invalid_grant 계열 오류 0건, 매시간 수집 exit 0 지속 → **토큰 유효**.
- OAuth 앱이 프로덕션으로 게시됐으므로 테스트 상태의 7일 refresh token 만료는 더 이상 적용되지 않는다.
  통합 명세 §7의 "OAuth 앱 프로덕션 전환은 완료 여부 확인 필요" 문구는 위 운영 기록(11-10)으로 해소된 상태다.
  이 보고서는 명세를 수정하지 않는다.

## 6. 복구 방법 (이번에 실행하지 않음)

멈춘 것이 없으므로 복구는 불필요하다. 아래는 향후 장애 시 참고 절차다.

1. **Gmail 토큰 재만료(HTTP 400/invalid_grant) 시** — 운영 릴리스 디렉터리에서 venv Python으로 재인증:
   ```powershell
   Set-Location D:\WebLedgerHost\releases\<운영 SHA>
   D:\WebLedgerHost\venv\Scripts\python.exe -m app.mail_collect --authorize `
     --token-file D:\WebLedgerHost\secrets\gmail-collector-token.json `
     --client-file D:\WebLedgerHost\secrets\google-oauth-desktop-mail.json
   ```
   사용자 행동: 브라우저에서 Google 로그인·동의가 필요하다(로컬 포트 8765 리다이렉트, 600초 대기).
   재인증 후 다음 매시간 자식 실행이 새 토큰을 자동 사용한다. Worker 재시작은 불필요.
2. **Worker 작업 자체가 중지된 경우** — `Start-ScheduledTask -TaskName 'WebLedger-Worker'`.
   단일 인스턴스 mutex(`Local\AX.WebLedger.Worker`)가 중복 실행을 거부하므로 이중 수집은 생기지 않는다.
3. **구 작업 체제로 되돌리기(롤백)** — 설치 증거 폴더를 지정해야 한다:
   ```powershell
   powershell -File D:\WebLedgerHost\releases\<SHA>\tools\install_webledger_worker.ps1 `
     -Rollback -Evidence D:\WebLedgerHost\logs\worker-install-20261109T175705
   ```
   저장된 XML로 다섯 작업을 복원하고 Worker 작업을 지운다.
4. **주의**: Worker가 도는 동안 구 예약 작업(MailCollect·GoogleAuthority·SourceRefresh·InsuranceRosterSync)을
   다시 활성화하지 않는다. 같은 수집이 이중 실행될 수 있다. Disabled는 의도된 상태다.

## 7. 검증 경계와 미확인

- 감독 로그 보존은 4MB 회전 1회뿐이라 `webledger-worker.previous.log`는 2026-11-12 05:20 KST부터만 커버한다.
  **11-09~11-12 05:20 구간의 감독 타임스탬프는 보존되지 않았다.** 그 구간은 자식 로그(오류 부재)와
  운영 기록으로 판단했으며, 특히 재인증(11-10 18:17) 직후 첫 성공의 정확한 시각은 특정하지 못했다.
- 자식 로그(mail-collect·google-authority)에는 타임스탬프가 없다. 시각 근거는 감독 로그와 파일 메타데이터다.
- 디렉터리 목록의 LastWriteTime은 열린 파일에서 지연 갱신될 수 있다(실측: webledger-worker.log 목록은
  11-12 22:57:33으로 표시됐으나 내용에는 11-13 01:12:59 KST 기록이 있음). 내용 타임스탬프를 기준으로 삼았다.
- 운영 포트 요청·실제 수집 실행·화면 수락은 하지 않았다. 본 판정은 로그·파일·예약 작업 조회 근거다.
- Google 여행 탭의 내용 정합성(탭 수 71의 정확성 등)은 검증하지 않았다. 동기화 실행 성공까지만 확인했다.

## 8. 근거 파일 목록

| 근거 | 위치 |
| --- | --- |
| 이관 명세 | `docs/history/specs-20261110/backend-process-consolidation-20261109.md` |
| 배포 기록(#767 표 0행, worker_switched) | `docs/operations.md` "2026-11-10 … 연속 기록" 절 |
| OAuth 만료·복구 기록 | `docs/operations.md` 말미(422행) |
| 구현 커밋 | `0f5ea663` / 병합 `3dd0750e`(PR #767) |
| 비활성화 증거 | `D:\WebLedgerHost\logs\worker-install-20261109T175705\` (XML 6개) |
| Worker 설정 | `D:\WebLedgerHost\config\worker.json` |
| 감독 로그 | `D:\WebLedgerHost\logs\webledger-worker.log`, `webledger-worker.previous.log` |
| 자식 로그 | `D:\WebLedgerHost\logs\worker-mail-collect.log`(705줄), `worker-google-authority.log`(105줄) |
| refresh 상태 | `D:\WebLedgerHost\config\real-review.json.refresh-status.json` |
| 토큰 메타데이터 | `D:\WebLedgerHost\secrets\gmail-collector-token.json` (LastWrite만, 내용 미열람) |
| 워커 코드 | `tools/webledger_worker.py`, `tools/refresh_review_source.py`, `webapp/real_review.py`, `app/mail_collect.py` |
