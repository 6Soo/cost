# 몽골 항공료 실제 기장과 Google 수입 표시 검증

2026-11-17 02:31 KST. 코드 배포와 실제 금융 결과를 구분해 확인했다. 고객 이름·예약번호·카드 식별값·원문은 이 기록에 포함하지 않는다.

| 요구사항 | 상태 | 실제 근거 |
| --- | --- | --- |
| 항공료 복구 | COMPLETE | 운영 worker8건6500202원 표준 기장. 각 ledger/board 정확1회·여행/항공료/2026-07-12~16/원문·카드 해시 일치 |
| 몽골 보드 | COMPLETE | 실제 인증 API200·DOM14행·고유14행·항공료8행, 합6767151원. 보호 스크린샷 직접 확인 |
| Google 수입 조회 | COMPLETE | 실제 인증 API200·DOM14행. 금액13+합계빈1, 표시합17337200원. 미확인1·잠정 안내·verified=false. 390/1440px 가로넘침0 |
| 운영 코드 반영 | COMPLETE | 공식도구 exit0·actual9af20414/8751·1883파일 blob불일치0·코드배포 보호14표 불변·health/ready200·보호API401 |
| 원본/사용자/금융 보호 | COMPLETE | 카드 원문·금액·날짜·ID·수동결정 불변. 대상 밖 거래/기장/보드·다른 core 결정·나머지 보호표 불변 |
| 재처리 중복 보호 | COMPLETE | 같은8건 큐 실제 재등록 뒤 pending0. 모든 보호 금융표와 core 전체 상태 동일·recorded8/failures0 |

수입 합계가 빈 원장 행은 수정하지 않았다. 수입과 차액10570049원은 잠정이며 Google 최종 장부 쓰기0이다. 기존6건266949원에 항공료8건이 추가됐다. 라쿠텐·어드벤처의 기존 수동 보드 교정도 보존해 raw ledger16건7793532원과 유효보드14건6767151원은 구분한다.

## 배포와 데이터 안전

코드9af204148b1b6450f7bb9c6ec1185c5f2f3aa852, Previous8888230deb1a5bd09d826da7e66034e2091ba0a1. Rust 분류/연결 flags·기존888 바이너리·설정 해시 보존. 신선4DB 백업/복원 후 공식배포했다. 도구 fresh_backup_restore=false는 full-backup 옵션 미사용이며 별도 scoped 백업을 생략한 것이 아니다.

첫 설치는 프로세스 임대 기록 변경을 감지해 원문/큐 등록 전에 멈췄다. postdeploy board/core 백업/복원을 새로 통과했고 범위 밖 OTA/원본은 불변이었다. 독립 승인 설치 스크립트가 배타 lock 아래 신규 보호 디렉터리와 기존 큐만 등록했다. 실제 금융 행은 기존 운영 worker만 썼다. 첫 전체 OTA 대조 뒤1회 처리로8건 기장했다.

## 검사와 근거 위치

정확코드9af 공식 영향1101 passed+30subtests, skip0/failure0. 관련합성21·frontend79/typecheck/build PASS. 보호 사본 현재 Rust 예행도 PASS. 독립 gpt-6.1-sol medium이 코드9af와 실행 코드가 같은 docs-only46cbed24를 APPROVE했고, 설치 스크립트의 commit 후 보고 실패 시 원본 보존 수정도 APPROVE했다. 최종 PR SHA 판정은 PR980에 기록한다. CI 두 job은 실제 annotation의 결제 한도로 시작 전 차단됐다. 문서 추가 뒤 코드 검사·브라우저·배포를 반복하지 않는다.

보호 경로 `D:/WebLedgerHost/data/backups/reviewed-mongolia-20261117/`:

- `predeployment-4db-backup-restore.json`: 4DB scoped 백업/복원·원본/범위 밖 불변.
- `fresh-backup-restore.json`: postdeploy board/core scoped 백업/복원·범위 밖 OTA 등 불변.
- `queued.json`: 정확8건/한 배치 등록·설치 도구 직접 금융 행 쓰기0.
- `financial-verification.json`, `financial-verification-replay.json`: 정확 기장·원문/수동/대상 밖 보존·재처리 뒤 모든 보호 금융/core 상태 동일. 검증 스크립트 DB쓰기0.
- `browser-income-evidence.json`, `browser-income-responsive.json`, `browser-expense-evidence.json`: 실제 인증 API/DOM·금액·미확인 안내·반응형 결과. `browser-income.png`, `browser-expense.png` 보호 화면도 직접 확인.

배포 근거 `D:/WebLedgerHost/releases/deploy-evidence-9af204148b1b6450f7bb9c6ec1185c5f2f3aa852.json`. 코드 배포 단계 financial_apply=NOT_RUN과 그 뒤 worker 금융 기장 완료를 구분한다. 후속 문서 때문에 재배포하지 않는다.
