# WebLedgerHost 상시 HDD I/O 경량화 및 운영 안전성 명세 (2026-11-05)

**2026-11-05 실행 판정: PARTIAL · 명세 #644 및 구현 #646 병합. 현재 Board는 PR #658 포함 SHA `b3b1bb90`으로 공식 운영 배포됐다.** 최신 호스트 evidence는 1,383 files·blob mismatch0·runtime SHA 확인·단일 listener·8752·health/ready 200·보호 API 401·보호13표 불변을 기록한다. HDD 실측은 실제 D: HDD에서 했으나, 물리 디스크 전체 수치는 다른 운영 작업을 포함하므로 Gateway status 파일 횟수와 혼동하지 않는다. **목표는 WebLedgerHost 24시간 운영 기능을 없애는 것이 아니라 유휴 시 불필요한 HDD 접근을 줄이는 것**이다.

## 12시경 문서 재점검: 검증된 절감 범위와 남은 계측

- #646의 Gateway status 이벤트/30초 heartbeat 및 route cache 코드, #652 후속 최적화, #658 운영 릴리스는 이미 병합·적용된 범위다. 완료된 gateway 경량화를 다시 구현하거나 문서 PR #659~#661만을 이유로 재배포하지 않는다.
- **확정 가능한 수치:** 격리 60초 status 파일 mtime 변경 `58→2회`(-96.6%), 격리 15분 원자 교체 `886→31회`(-96.5%). #661의 소스 점검에 따르면 OTA·항공권 스냅샷은 동일 입력 지문에서 불필요한 재발행을 건너뛴다. 이는 **파일 접근 횟수와 코드 계약**의 증거다.
- **확정할 수 없는 수치:** 기존 두 구간의 Windows process `IOWriteBytes=0` 카운터는 실제 쓰기 바이트를 설명하지 못한다. D: 물리 전체는 132.9→221.0MB로 증가해 사용자가 체감하는 HDD 전체 소음·활성 시간 감소를 입증하지 못했다. **성능 개선 완료**가 아닌 **Gateway 부분 개선 완료/HDD 전체 효과 미입증**으로 표기한다.
- **다음 수락:** 실제 운영과 동등한 유휴 상태에서 process/file별 출처를 신뢰할 수 있는 Windows 계측으로 분리하고, 다른 에이전트 pytest/개발 SSD 작업·SourceRefresh·OTA 색인·로그·WAL을 구분한다. 원인으로 확인된 쓰기만 최소 변경하고, 새 배포가 필요할 때에만 기존 drain/13표 보호/고정 SHA 게이트를 적용한다. [통합 실행계획](autonomy-io-unified-followup-20261105.md#현재-판단과-실제-남은-작업-2026-11-05-12시경-문서-대조) 참조.

## 2026-11-05 구현·운영·실측 결과

- PR #646은 `40ea7f9d`로 병합됐다. Gateway status 이벤트 게시/30초 heartbeat, route stat cache 250ms, OTA/항공 check-only 로그 억제·시간별 heartbeat·5MiB 순환이 main에 포함됐다. 서비스의 기존 `ota_snapshot.json`은 동일한 입력 키와 역할에서 `_publish_if_active()`가 재쓰기하지 않으며, 변경 입력·역할 복귀 때 재게시한다. 관련 OTA 스냅샷 테스트와 #646 영향 CI를 재사용했다.
- 실행 중 `WebLedger-Gateway`는 기존 PID를 유지했다. 실행 중인 스크립트와 병합본 `tools/ledger_gateway.py`의 SHA-256은 동일했고, 예약 작업의 다음 실행 파일을 공식 릴리스 `f7ff4ec4` 경로로 갱신했다. task principal·trigger·settings·interpreter·working directory·실행 PID는 변경되지 않았고 재시작은 없었다.
- 실제 D: HDD (`ST1000DM003`)에서 운영 포트와 별도인 loopback Gateway를 각각 구형/신형 코드로 15분간 무연결 실행했다. NTFS USN 기준 `gateway-status.json` 원자 교체/임시파일 생성은 **886→31회(-96.5%)**, 관련 USN 기록은 **6,202→216건**이었다. 이 격리 경로에서는 정기 status 파일 쓰기가 크게 줄었다.
- 같은 구간의 물리 D: 전체 카운터는 구형 **132.9 MB / 약 7,061 write ops / busy 0.672%**, 신형 **221.0 MB / 약 6,671 write ops / busy 0.945%**였다(각 90개 수집 구간 중 유효 89개). 전체 쓰기 바이트와 busy 비율은 감소하지 않았고 오히려 증가했다. 카운터에는 다른 호스트 작업이 섞이므로 이 증가는 Gateway 원인으로 단정하지 않으며, **전체 HDD 활동 감소는 입증되지 않았다.** 소음 측정도 하지 않았다.
- 운영 Gateway의 같은 15분 관측 구간에는 status 교체 885회, 자율정리 상태 49회, 카드완료 상태 30회, OTA 스냅샷 1회, OTA/항공 로그 append 각 44회가 있었다. 이벤트 트래픽이 있는 운영 관측이며 변경 전 대조군이 아니므로 개선 전후율로 해석하지 않는다.
- 후속 동일 길이 D: USN 비교에서 `gateway-status.json` 6,202→216, `ota-snapshot.log` 82→44, `flight-search.log` 90→44, `autonomous-cleanup-status.json` 222→147 records로 관찰됐다. 이는 파일 변경 저널의 레코드 수이지 물리 write bytes가 아니다. 물리 D: 전체 카운터는 여전히 132.9→221.0 MB, busy 0.672→0.945%로 증가했으므로 process별 write-byte 절감 및 전체 HDD 개선은 수락하지 않는다. 원시 자료는 `C:/AX/cost/.local-archive/autonomy-io-20261105-acceptance/controlled-before-usn.csv`, `controlled-after-usn.csv`, `controlled-before.csv`, `controlled-after.csv`다.
- 추가 격리 재현 `D:/WebLedgerHost/scratch-io-ab-20261105-0105/status-count-ab.json`: 운영 listener를 건드리지 않고 D: scratch 경로·별도 loopback port에서 구형 1초 heartbeat와 신형 30초 heartbeat를 각 60초 유휴 측정했다. status 파일 mtime 교체는 58→2회(-96.6%)였다. Windows process `IOWriteBytes`는 75초 양쪽 실행에서 0→0으로 보고됐다. 이 카운터 결과는 계측 불능으로 보고하며, mtime 횟수는 status 파일 업데이트 빈도만 증명한다. 기존 실제 D: 전체 쓰기량 비교는 증가했으므로 HDD 전체 개선은 여전히 미입증이다.
- 소스 검토: OTA 및 항공권 snapshot worker는 입력 키가 현재 snapshot과 같으면 `held`로 계산·재발행을 건너뛴다. 입력 키는 원본 파일의 SHA-256 content stamp를 사용하므로 mtime만으로 변경을 판정하지 않는다. 새 입력 결과나 deployment writer role 변경 때만 public snapshot/passenger index를 발행한다. PR #646의 OTA 변경은 unchanged/failed check 로그를 상태 변경 시 또는 최대 시간 heartbeat로 제한하고 5 MiB에서 rotate한다. 해당 경로는 중복 snapshot 재기록 방지를 구현하고 있으나, 이 코드 검토는 물리 HDD write-byte 감소 실측을 대신하지 않는다.
- PR #653 측정 당시 Board는 `79a3c57340cfadeb227e3748966a4baf0fd6ca63`/route8751이었다. 이후 PR #658 배포로 현재 Board는 `b3b1bb9098b2c88d23ba5653bcd7e90afd684135`/route8752에서 실행한다. Gateway8790 유지, 단일 listener·health/ready200·비인증 보호 API401·13표 불변은 최신 공식 evidence에서 확인했다.
- 320px·390px 화면 구조 수락에서 가로 넘침은 없었으나 브라우저 세션에 인증 지출정리 화면이 없어 로그인 화면/검토 목록은 **UNVERIFIED**다. 외부 로그인·인증 우회는 하지 않았다.

## 후속 PR #646 구현 대조 및 남은 수락

- [PR #646](https://github.com/6Soo/cost/pull/646)은 `40ea7f9d`로 병합됐다: 상태파일 event publish + 30초 heartbeat, route stat cache(250ms), `tools/gateway_route.py` status freshness 정합화, `webapp/ota_snapshot.py` check 로그 change-only·시간별 heartbeat·5MiB rotation 및 관련 테스트. 현재 Gateway 코드 SHA-256은 검증 릴리스 코드와 같다. 작업의 다음 실행 경로도 공식 `f7ff4ec4` 릴리스로 갱신했으며 현재 프로세스를 재시작하지 않았다.
- 기존 1초 대비 30초 **정기 상태 publish 빈도**의 이론적 감소는 약 96.7%다. 실제 D: A/B에서 격리 무연결 경로의 status 교체는 886→31회(-96.5%)였다. 물리 디스크 전체 바이트는 132.9→221.0 MB로 증가했고 busy 평균도 0.672→0.945%로 증가해, **전체 HDD 쓰기 감소나 소음 개선을 수락하지 않는다.**
- **남은 수락:** 현재 Board task/process SHA `b3b1bb90`/route8752, Gateway8790이다. 워커와 Gateway를 합성 실패·재시도·성공 시나리오로 함께 검증했고 배포 보호13표도 통과했다. OTA/항공 로그 및 status USN 활동은 비교 구간에서 감소했지만 물리 디스크 전체 쓰기와 busy는 증가했고 process별 write bytes를 대조하지 못해 전체 HDD 감소는 미검증이다. 인증 지출정리 UI도 미검증이다. OTA 스냅샷은 동일 입력 key·동일 writer role에서는 persist를 생략하고, 변경 입력이나 role 재취득 때 게시한다. 운영 항공권·예약 데이터는 테스트에 쓰지 않았다.
- 기존 서술의 '현행 코드 1초 기록'은 **명세 작성 당시 main 기준 baseline**이다. 실측 결과는 위의 현재 운영 상태와 별도로 해석한다.

## 1. 조사 사실 및 검증할 가설

- 운영 호스트: 물리 HDD `D:\WebLedgerHost` (Seagate ST1000DM003), 개발/테스트 SSD `C:` (NVMe). 카드/장부 원본·백업·WAL은 운영 보호 자료이며 성능 최적화를 이유로 옮기거나 삭제하지 않는다.
- `tools/ledger_gateway.py`: `Gateway.service_actions()`는 요청이 없어도 주기마다 `ledger-route.json`을 읽고, 배포 generation 변화 또는 `last_publish >= 1s`이면 `atomic_json(ledger-gateway-status.json)`을 호출한다. 연결 시작·종료 시에도 같은 파일을 갱신한다. `atomic_json`은 임시 파일 생성→기록→`os.replace`다. **추정 기준 하루 86,400회 정기 쓰기**이며 추가 연결 이벤트 수는 미포함. 동시에 route 읽기/메타데이터 I/O도 측정 대상이다.
- `ota-snapshot.json` 약 7.68MB, `ota-catalog-index.json` 약 2.64MB, `board.sqlite-wal` 약 4.65MB, `ota-snapshot.log` 약 3.8MB, `flight-search.log` 약 497KB는 사용자 진단 당시 관찰값이다. 크기 자체로 비정상 또는 매분 전체 재생성이라고 단정하지 않는다.
- SSD의 pytest 임시 SQLite, Git worktree, PostgreSQL WAL, 에이전트·Paseo·OneDrive 쓰기는 **별도 개발 부하**이며 D: WebLedgerHost의 운영 유휴 HDD 쓰기와 분리한다.
- 비대상: 웹서버/Cloudflare/Gateway 삭제, SQLite WAL 비활성화, 비용/지출·원본·Google 장부 처리 규칙 변경, 불필요한 Rust 도입, 성능 개선을 위한 감사 로그 삭제.

## 2. 성공 조건과 측정 설계 (변경 전 baseline 필수)

1. **동일 조건 비교:** 서비스 운영 정상·테스트/배포/자료 갱신 없음·접속 요청이 거의 없는 **15분 유휴 구간** 및 의도적으로 ①정상 요청②긴 HTTP 업로드/다운로드③배포 전환④OTA/항공 색인 갱신을 유발하는 구간을 분리해 측정한다. 운영 데이터를 변경하는 시나리오는 별도 합성 호스트·복구 사본에서 실행한다. Windows Task Scheduler 실행 이력과 해당 시점 프로세스 PID·배포 SHA·USN/ProcMon(사용 가능 시)·리소스 모니터/성능 카운터를 시간 동기화해 결과에 남긴다.
2. **측정 지표:** 파일별 실제 write/rename/create/remove 횟수, 읽기/metadata 접근 횟수, 바이트, D: Disk Transfers/sec·Avg Disk sec/Transfer·활성 시간(가능하면 소음/절전 진입 관측), C: 개발 쓰기 별도, OTA 스냅샷 생성 횟수·원본 변화 여부·로그 append 횟수, 웹 응답 지연 p50/p95, 자원 사용량. `board.sqlite-wal`의 파일 크기만으로 무한 쓰기 판정하지 않는다.
3. **우선 개선 목표:** 유휴 상태 게이트웨이의 **정기 상태 파일 갱신 횟수 ≥90% 감소**(연결·배포 이벤트에 따른 필수 쓰기는 제외). Gateway+상태·로그의 D: 유휴 파일 메타데이터 변경을 감소시키고, 운영 전환 안전성/장애 감지를 **기존 대비 악화시키지 않을 것**. 디스크 전체 소음 또는 모든 I/O에 동일한 감소율을 약속하지 않는다. 목표 미달은 수치와 한계로 보고한다.
4. 자료 변화가 없는 OTA/항공권 색인의 **불필요한 재계산/재쓰기 건수가 0 또는 정당화 가능한 수준**인지 입증한다. 실측 근거가 없으면 함부로 워커를 수정하지 않는다.

## 3. P0: Gateway 상태 파일과 배포 핸드셰이크

### 3.1 안전성 불변 조건
- `8790` 고정 loopback Gateway→활성 `8751/8752` 및 Cloudflare 외부 접속을 유지한다. 게이트웨이는 TCP 바이트만 전달하며 금융 POST 재시도/본문 기록을 하지 않는다.
- 배포 시 **현재 활성 연결 수를 정확히 판정**하고, 기존 요청/업로드가 drain될 때까지 기존 백엔드에 고정한다. 새 연결은 기존 route pause 계약에 따라 대기한다. drain 타임아웃이면 이전 경로로 복구하며 구 버전을 임의 종료하지 않는다. single-writer, SHA/task/process, 보호 API·13표 불변 게이트 유지.
- `status.json`은 단순 로그가 아니라 배포 안전장치의 일부다. **주기만 1→30초로 바꾸는 단독 패치는 금지.** 현재 status를 읽는 전환 스크립트/배포 전제/검사를 실제 코드 검색해 전부 확인하고, 새 이벤트·heartbeat·신선도 의미에 맞춰 함께 수정한다.

### 3.2 개선 구현 요구
- 상태 변경(연결 수, generation, pause/route 전환/복귀, 프로세스 시작·종료) 시 **즉시** 원자적 publish. 변화가 없으면 redundant publish를 줄이되 **감시자가 프로세스 생존과 상태 최신성을 구별할 수 있는 보증**을 제공한다.
- 우선안은 **이벤트 기반 업데이트 + 길어진 bounded heartbeat**다. heartbeat 최장 주기는 소비자의 stale timeout/배포 확인 지연과 함께 설계하고 실제 전환 코드에서 증명한다. 더 나은 구조라면 OS 내 로컬 IPC/명시적 ack 또는 durable status + in-memory active를 사용할 수 있으나, 새 IPC 도입의 복잡성 대비 이득을 검증한다.
- 모든 소비자가 `updated_at`와 generation/PID/active를 어떻게 검증하는지 조사한다. 상태 파일 오래됨·부분 손상·락 충돌·generation 불일치·Gateway 다운이면 배포가 **실패 폐쇄(fail closed)** 하되 일반 사용자 요청은 현재 검증된 경로에서 가능한 한 유지한다.
- `ledger-route.json`을 서버 유휴 상태에서 반복 읽는 비용도 계측한다. route 캐시/메타데이터 감시를 도입할 경우 **pause/active 전환 감지 상한**, 초기화, 실패 시 동작, 경합 상황, 라우트 원자 교체와 클라이언트 연결 도착 순서를 시뮬레이션하여 누락/잘못된 연결이 없음을 입증한다. 단순 캐시로 stale routing이 생기면 하지 않는다.
- event publish 실패·`os.replace` PermissionError·읽기 오류 시 서비스 계속 가능 범위와 배포 차단을 분리한다. 상태를 메모리에만 두고 배포 도구가 볼 수 없게 만들지 않는다. 무제한 예외 무시나 busy-loop 금지.
- **선택적 2차안:** 파일 쓰기가 남아 HDD spin-down을 방해한다면 게이트웨이의 **재생성 가능한 상태/heartbeat만** C: SSD의 명시적 runtime 디렉터리로 이전하는 방안을 시험한다. 현재 D: 고정 경로, 배포 스크립트, scheduled task, lock, 복구 도구, ACL/권한/백업 경계를 함께 갱신해야 하며 경로만 덜렁 옮기지 않는다. 실제 고객 DB/백업/영수증/OTA 원본 이전은 승인 없이는 금지.

## 4. P1: OTA/항공권/Google 읽기 캐시와 로그

- `SourceRefresh`, OTA 스냅샷·catalog 색인, 항공 검색/메일, Google **읽기 스냅샷**의 트리거와 의존성을 추적한다. 각 작업을 실행함으로써 저장되는 파일과 임시 파일·로그를 inventory로 만든다. 원본·규칙·여행 세대·코드 SHA 등 필요한 갱신 조건과 수동 강제 refresh 의미를 분리한다.
- **내용이 바뀌지 않았다면 재저장하지 않는다.** 기존 generation/digest/mtime 검증을 우선 사용하되 실제 내용 변경 누락이 없어야 한다. `mtime` 단독으로 바이트 동일/변경을 보증하지 말고 원본 digest/신뢰 가능한 버전 표식을 활용한다. 동일 입력이어도 계산 결과의 생성 시각·비결정적 순서로 매번 다른 JSON이 되는지 분석하고 안정적 직렬화를 고려한다. 예약 취소·환불·지연 도착·수동 변경을 갱신 누락하지 않는다.
- 재계산 필요와 디스크 영속화 필요를 구분한다. 결과가 같다면 원자 교체·파일 타임스탬프 변경을 피할 수 있는지 확인하되, freshness 확인용 생존 표시는 별도 가벼운 메타데이터/실행 상태로 제공한다. 캐시 적중을 stale 성공으로 오인하지 않는다. startup/deploy 뒤 검증된 색인을 재사용하되 새 원본이 있으면 재생성한다.
- `ota-snapshot.log`/`flight-search.log` 등의 **변화 없는 정상 heartbeat**는 정보 가치·오류 진단 필요성을 확인해 축소하거나 상위 집계/Windows Event Log 등 적절한 로깅으로 전환한다. 처리 시작·완료·실패·backoff·데이터 세대 교체·금융/접근 감사 이벤트는 절대로 없애지 않는다. 로그 순환/보존 크기를 설정하고, 비밀·원본/개인정보가 로그로 유출되지 않도록 한다.
- SQLite `board.sqlite-wal`은 운영 저장 정합성과 동시성에 필요하다. **WAL 강제 삭제·journal_mode 변경·임의 체크포인트/백업/DB 이동 금지.** 유휴 시간에도 불필요한 앱 트랜잭션이 발생한다면 원인 쿼리/작성자를 계측하고 **그 트랜잭션만** 제거한다.

## 5. 운영 적용 절차와 위험 관리

1. **읽기 전용 baseline** 수집 → 프로세스/경로·구독자 의존성 확인 → CPU/I/O 병목 분리 → 영향도별 우선순위. 다른 에이전트의 개발 테스트 C: I/O와 D: 운영 I/O를 구분한다.
2. 독립 영역(Gateway / snapshot / logging)은 병렬 조사할 수 있으나 공통 배포·상태파일 계약은 한 담당자가 통합한다. 검증된 동작을 위해 최소 파일만 수정하고 서비스 추가·전체 재작성·새 대시보드 도입은 피한다.
3. 각 변경은 **기준 테스트 red/green·성능 동일 조건 비교**를 포함한다. Gateway에 대해서는 합성 Windows 환경에서 연결 고정, 요청 중 전환, 대기/재개, 업로드 진행, 오래된/손상 status, Gateway 종료, 강제 write 실패, 다중 연결, 롤백, 신규 POST 재전송 금지 및 health/ready 응답을 검증한다.
4. API/GUI·카드/OTA·환불/Google 읽기와 구분하여 금융 원본·수동 교정·승인번호·여행/금액/환불 링크·보호 13표의 사전/사후 불변을 확인한다. 고객 금융 업무를 성능 테스트 때문에 자동 처리·재분류하거나 Google Sheets에 쓰지 않는다.
5. GitHub PR과 영향 QA/CI 통과 후 **현재 운영 SHA와 배포 single-writer**를 확인한다. 공식 `deploy_verified_release.ps1` 등 승인된 무중단 배포 경로만 사용하고, 준비된 후보 검증→전환→health/ready·보호 API·13표·task/process SHA·연결 drain을 확인한다. 실패하면 구버전 유지/복구한다. 변경이 게이트웨이 **프로세스 자체**에 영향을 준다면 앱 배포만으로 바뀌지 않을 수 있으므로 안전한 게이트웨이 업데이트/교체 절차를 별도로 계획·검증하며 사용자 요청 중 무작정 restart 금지.
6. 운영 **유휴 15분 이상 재측정**, 스냅샷이 실제 갱신될 때의 시간·내용 정확성 확인, 배포 전환 중 서비스 지속성과 무인 상태 최신성 비교. 작업자/에이전트 중복 실행이 없는지 확인하고 결과·한계·운영 SHA·되돌리기 경로를 [인계](../session_handoff.md)·[운영 기록](../operations.md)에 요약한다.
7. 테스트/운영 도구 권한이 차단되거나 오디오 소음 자체가 계량 불가라면 우회하지 않는다. **코드 정적 근거, 합성 I/O 실측, 실제 D: 실측, 소음 체감**을 구분해 완료 상태를 기록한다. 문서만 작성하거나 테스트 수치 없이 `성능 개선 완료`로 보고하지 않는다.

## 6. 완료 수락 조건

| ID | 반드시 입증할 것 |
| --- | --- |
| IO-01 | 변경 전/후 동일 유휴 15분의 파일·프로세스·USN/성능 카운터 측정(가능한 환경); Gateway 정기 status write 수 **90% 이상 감소**, 다른 요인/전체 HDD 효과와 구분 |
| IO-02 | 연결 시작/종료, 빠른 연속 요청, active 0→N→0 때 정확한 최신 상태 publish, 오래된 status만으로 drain 성공 처리 금지 |
| IO-03 | 정상 배포·후보 실패·연결 중 drain timeout·Gateway status 기록 실패에서 업로드/기존 요청 보존, 실패 폐쇄/복구·POST 재전송 금지 |
| IO-04 | route generation·pause 전환/복귀와 읽기 캐시가 충돌하지 않음. gateway/배포 도구의 모든 status 소비자 계약 검사 |
| IO-05 | 원본 변화 없는 OTA/항공권/Google 읽기 갱신에서 불필요한 snapshot replace가 줄었고, 새 예약/취소/원문 변경은 정상 반영 |
| IO-06 | 정상 반복 로그 쓰기 감소와 실패·감사·복구 추적 가능성 유지. WAL·원본·금융 DB·보호 13표 불변 |
| IO-07 | PR/CI·Windows 통합 테스트 및 운영 고정 SHA/health/ready/보호 API·실제 주요 업무 읽기 수락. 게이트웨이 프로세스 교체가 필요한 경우 별도 안전 전환 증거 |
| IO-08 | 최종 보고에 기능별 변경 전/후 횟수·바이트·지연·I/O·운영 SHA·남은 병목과 미검증 항목을 명시; 개선되지 않은 값도 그대로 보고 |

## 7. 사용자에게 보고할 ELI10 요약 형식

- **왜 계속 드르륵했는지:** Gateway status/route 읽기, 스냅샷·로그, 개발 SSD 작업을 구분.
- **뭘 줄였는지:** 파일별 유휴 15분 변경 전/후 write/rename 횟수와 작업 의미.
- **서비스가 안전한지:** 연결 중 배포·원복, 게시 status 최신성, 건강 검사, 보호 13표/금융 불변.
- **소음이 얼마나 감소했는지:** 측정된 디스크 활동량만 보고하고 실제 청감·절전 진입 미측정이면 단정 금지.
