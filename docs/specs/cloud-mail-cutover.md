# 비공개 클라우드 메일 수집 전환

> **2026-10-28 18:30 최신 구현 상태:** [구현현황 감사](implementation-status-audit-20261028.md). **PR #291 / main 9c3a88b 병합 완료**: 281MiB 규모 전체 원문에 대해 기존 100MiB/호출·16MiB/파일 제한을 완화하지 않고 1~100개 제한 배치/offset/전체 메타데이터 검증/불완전 apply 차단을 구현했고 기존 PR에 Supervisor51 passed가 기록돼 있다. 그러나 **실제 운영 원문 batch 적재, 기존 Gmail writer 해제·예약 전환, 운영 배포·실자료 수락은 미완료**다. 원래 본문의 배포 준비 시점 기술과 최신 코드 병합을 구분하며, 운영 변경 전에 백업·별도 복원·single-writer·보호13표를 검증해야 한다.


## 현재 상태와 영향

기존 Apps Script 프로젝트를 읽기 전용으로 내려받아 대조했다. 운영 프로젝트에는 `CloudMail`이 없고 기존 `GmailIngest.AUTO_DRAIN`은 false다. Windows Gmail 수집은 기존 예약 작업에서 계속 담당한다. 이번 코드는 클라우드 수집기, 별도 배포 패키지, Drive 원문을 COST에 가져오는 읽기/추가 경로를 준비한다. 후속 승인으로 새 전용 프로젝트의 실제 클라우드 수집을 활성화했다. 원문76건·초기전체탐색 미완료·트리거1을 확인했으며 호스트 원문 적재·기존 예약 작업 중지는 아직 하지 않았다.

기존 장부 Apps Script에 새 Drive 권한을 섞지 않도록 **새 전용 standalone 프로젝트**에 배포한다. 기존 `apps-script/CloudMail.gs` 사용자 초안은 원래 미추적 상태와 바이트를 보존하고, 별도 `cloud-mail/CloudMail.gs`에서 보완했다. 패키지에는 이 파일과 `cloud-mail/appsscript.json`만 들어간다. 장부 쓰기 함수·기존 시트 ID·인증 파일은 포함하지 않는다.

`CloudMail.gs`는 Gmail API `format=full` 응답의 헤더·MIME·internalDate를 비공개 Drive 폴더에 저장한다. 숲나들e·NICE·토요코인 제목 검색을 포함해 현재 로컬 수집 범위를 유지한다. 부분 페이지/시간 제한/실패에서 이어가며, 원문 ID·파일 digest·개별 공유 상태와 소유자를 검증한다. 조회 범위를 넓히면 최초 설정일부터 다시 탐색하고 이미 저장한 원문은 덮지 않는다.

`python -m app.cloud_mail`은 기본 미리보기다. Drive 페이지 전체·폴더 소유/비공개·파일 부모/이름·SHA-256·원문 형식을 검사하고 새 Gmail ID만 원자적으로 추가한다. 기존 로컬 ID는 최초 저장 원문을 유지한다. `--apply`는 기존 통합 원문 importer를 호출한다. importer는 예약 근거를 추출할 수 있으나 카드 판정·수동 여행/환불 결정·최종 Google 장부를 쓰지 않는다. import 실패 시 파일을 보존하며 재실행에서 DB 적재만 재시도한다.

## 실행 전 필요한 권한

새 프로젝트/원문 폴더·인증 전환은 저장소 AGENTS.md의 별도 운영/원본/인증·인프라 게이트를 적용한다. Google 권한 화면은 사용자가 승인해야 한다. 새 권한이 필요한 코드는 편집기에서 직접 한 번 실행해 승인해야 한다는 [Google 공식 안내](https://developers.google.com/apps-script/guides/services/authorization)를 따른다.

전용 manifest의 권한은 Gmail 읽기, Drive 접근, 외부 API 호출, 해당 프로젝트 트리거 관리다. **DriveApp 사용으로 Drive scope 자체는 전체 Drive 접근 권한이다.** 코드의 실제 쓰기 대상은 현재 계정 소유의 비공개 증거 폴더로 제한한다. 시트 scope나 Gmail 변경/발송 scope는 없다. 현재 Windows Drive ADC 읽기 probe는 `DefaultCredentialsError`였으므로 호스트의 Drive 읽기 인증도 필요하다. 토큰은 Git이나 CLI 보고서에 넣지 않는다.

## 검토 가능한 배포·전환 순서

1. 최신 main에서 새 빈 패키지 경로로 준비한다. 기존 출력 경로와 기존 장부 프로젝트 폴더를 재사용하지 않는다.

   ```powershell
   python tools/prepare_cloud_mail_release.py --output .local-archive/cloud-mail-release-NEW
   ```

2. 별도 승인을 받은 뒤 **그 패키지 디렉터리에서만** 새 프로젝트를 만든다. 기존 `apps-script/.clasp.json`은 복사하지 않는다.

   ```powershell
   clasp create-script --type standalone --title "COST private mail evidence"
   clasp push
   ```

   create 도구가 manifest를 생성/변경했다면 `cloud-mail/appsscript.json`의 검증된 내용을 복원하고 push한다. `.clasp.json`과 새 프로젝트 ID는 로컬 보호 기록에만 보존한다. 이 작업은 기존 장부 프로젝트를 변경하지 않는다.

3. 새 프로젝트 편집기에서 Google 계정을 확인하고 `initializeCostCloudMail`을 수동 실행해 권한을 승인한다. 기본 탐색 시작은 기존 수집 계약과 같은 2026-04-01이며 필요하면 실행 전에 `COST_CLOUD_MAIL_AFTER` 속성을 설정한다. 실행은 비공개 원문 폴더와 시간당 트리거 하나를 만든다. `costCloudMailStatus`의 stored/last_complete/trigger_count를 확인하고 초기 전체 탐색이 끝날 때까지 기존 Windows 수집을 유지한다.

4. Drive 읽기만 허용한 호스트 ADC를 사용자 인증으로 연결한다. 기존 Google 장부 자격 증명을 덮지 말고, 필요하면 이 작업 전용 ADC 파일을 예약 작업에만 지정한다. 새 계정·폴더 ID를 로컬 설정으로 전달하고 원문을 쓰지 않는 미리보기를 실행한다.

   ```powershell
   python -m app.cloud_mail --directory <EXISTING_OTA_MAIL_DIRECTORY> --folder-id <PRIVATE_FOLDER_ID> --account <OWNER_ACCOUNT>
   ```

5. `enumeration_complete=true` 및 `indexed=existing+new`를 확인한다. 운영 원문 적재 전에 기존 단일 작성자를 확보하고, 원문 폴더·통합 DB의 검증된 백업과 별도 복원 동등성을 확인한다. 기존 Windows 작업이 실행 중이면 완료를 기다리고 같은 원문/DB에 동시 작성하지 않는다. 보호된 금융·수동 결정 표의 내용/스키마 기준선을 확보한다. 해당 데이터 쓰기 게이트를 통과한 뒤에만 같은 명령에 `--apply`를 추가한다. 보호표 불변·원문/헤더 보존·재실행 appends0·COST 읽기 및 새 원문이 worker에 반영됨을 확인한다.

6. 클라우드 후속 예약 실행 1회와 Drive 가져오기/원문 적재 수락 후 기존 Windows Gmail 수집의 실행 파일·인자·state·작업 XML을 보관한다. 기존 Gmail 직접 수집 스케줄을 **Drive 가져오기 전용**으로 바꿔 비교하고, 성공한 뒤 Gmail 직접 수집만 중지한다. Board가 Windows에 있는 동안 Drive→로컬 원문/DB 전달은 여전히 필요하다. 이를 완전한 로컬 의존 제거라고 보고하지 않는다.

## 복구와 종료 기준

실패하면 새 프로젝트의 `pauseCostCloudMail`로 이 수집기 트리거만 중지하고 원문 폴더/파일은 보존한다. 기존 Gmail 수집 작업을 보관한 XML/명령으로 복원한다. 검증되지 않은 전체 DB 덮어쓰기나 원문 삭제는 하지 않는다. 부분 추가 파일은 재시도의 입력이며 새 importer가 기존 파일을 덮지 않는다.

완료는 코드/합성 검사와 구분한다. 새 프로젝트·Google 동의·초기 전체 탐색·실제 새 원문 적재·반복 불변·후속 예약 수집·Drive 전달·기존 로컬 Gmail 직접 수집 중지를 확인해야 `CUTOVER_COMPLETE`다. 현재는 `APPROVED / BACKFILL_RUNNING`이다. 사용자 전환 승인을 받았으며 전용 프로젝트와 Apps Script 동의는 완료했다. 최초 초기화의 Gmail API 403 accessNotConfigured를 확인해 Gmail 고급 서비스를 manifest에 추가하고 업로드/원격 일치를 확인했다. 초기화는 261.337초 정상 완료했고 원문76·last_complete=null·시간당 트리거1이다. 호스트 별도 Drive 읽기 동의 콜백을 정상 수신해 전용 ADC 저장·실제 Drive 읽기/소유자 검증을 완료했다. 초기 전체탐색·호스트 인증 이후 적재·후속 예약수집 수락을 진행하며 기존 Windows 수집을 유지한다.

## 2026-10-28 재시작 후 실행 기록

- 사용자 승인 범위: 전용 프로젝트/비공개 원문 폴더 생성, Gmail 읽기/Drive 접근, 별도 호스트 Drive 읽기 인증, 백업·별도 복원 검증, 원문 적재와 수집 스케줄 전환. 최종 Google 장부·금융/여행 수동 결정 쓰기는 제외한다.
- 기존 전용 프로젝트를 재사용한다. 최초 403 accessNotConfigured는 [공식 고급 서비스 활성화 절차](https://developers.google.com/apps-script/guides/services/advanced)에 따라 Gmail v1 manifest 의존성으로 수정했다. 명시 scope는 유지했다. 원격 소스/manifest 일치 근거는 Git 제외 로컬 cloud-live-source-verification-resumed.json이다.
- 호스트 인증 도우미: `python tools/authorize_cloud_mail_drive.py --client-file <기존 installed client> --destination <새 전용 ADC> --account <소유자> --request-file <새 로컬 요청 파일>` 실행 후 Aside에서 `http://127.0.0.1:8769/start`를 연다. Google 동의는 사용자가 직접 완료한다. state 검증·소유자/Drive readonly·offline refresh token을 확인한 뒤 새 파일만 생성하며 기존 자격 증명을 덮지 않는다. 거부·만료는 실제 차단으로 기록하고 같은 실패를 무한 재시도하지 않는다.
- 재시작 복구 검증: 수집기 20 passed, 별도 인증 14 passed(실제 loopback start/잘못된 콜백/동의 거부 포함), compile·원격 소스 비교 통과. 기존 importer32·browser3 검사는 변경이 없어 앞선 통과 근거를 재사용한다. Board 재시작·전체 회귀는 수행하지 않는다.
### 호스트 인증 수락과 백필 I/O 보완

호스트 인증의 최초20분 대기는 만료됐고 새 요청에서 사용자 직접 동의·콜백·새 전용 ADC 저장을 완료했다. 기존 인증 파일은 변경하지 않았다. 실제 Drive about200·소유자·비공개 폴더/목록 검증 통과, 최초76건 미리보기는 indexed76/existing76/new0/appended0/enumeration_complete=false다. 전체 Gmail 탐색 대상은3,704건이다. Windows 전달기는 고정SHA70f247e의980 Git blob을 검증해 준비하고 실제 preview를 수락했다. 운영 원문 적재/기존 수집 작업 전환은 전체 탐색 뒤의 백업/복원 게이트까지 대기한다.

실제 초기 처리량은76건/261.337초였다. 원문별 Drive 파일명 검색을 실행당 전체 목록 인덱스1회로 바꾸고, 원문을 먼저 설치한 뒤 체크포인트를10건·페이지/시간 종료·예외에서 저장한다. 재개 시 기존 원문/미완료 그룹의 orphan을 검증하고 새 원문을 덮지 않는다. digest·누락/중복·소유/비공개·전체탐색 watermark 보호를 유지한다. 수집기24 passed는50원문 전체 보존과 검색/저장 수 제한, 그룹 중간 실패/시간 종료의 복구, 중복 이름 차단을 포함한다. 실제 개선 처리량은 배포 후 별도 측정한다.
Gmail 원문 GET도 [UrlFetchApp.fetchAll 공식 API](https://developers.google.com/apps-script/reference/url-fetch/url-fetch-app)를 사용해 최대10개씩 미리 읽는다. 저장 전 각 응답의 ID·헤더·MIME를 따로 검증하며 기존 파일/기존 index 참조는 재다운로드하지 않는다. redirect를 허용하지 않고 HTTP 권한/할당량 오류는 제한된 오류로 중단한다. 묶음 네트워크 실패는 그 실행에서 한 번만 기존 순차 읽기로 전환한다. 응답 개수/ID 불일치·개별 HTTP 실패의 앞선 원문 보존을 포함한 Node27 passed다. 기존 scope/호스트·원문 설치·수동 결정 계약은 같다.


## 전체 원문이 100MiB를 넘는 경우의 배치 계약

초기 전체탐색3,704건의 Drive size 합계294,501,933B를 확인했다. 기존 단일16MiB/호출100MiB 안전 한도는 유지한다. 선택적 `--batch-size 1..100`과 읽기 전용 `--batch-offset`으로 전체 신규 원문을 작은 묶음으로 검증한다. 기본 모드는 정상 입력의 기존 반환 키/결과를 유지하며, 전체 메타데이터·로컬 충돌을 content 다운로드보다 먼저 검증하도록 강화했다.

배치 결과 `indexed=existing+new`에서 new는 전체 미존재 수다. selected는 이번에 내용 검증한 수, remaining_new는 현재 offset 이후 잔여 수이므로 한 배치 성공을 전체 원문 수락으로 보고하지 않는다. preview offset을 순회해 모든 신규 내용을 검증하고, apply는 offset0씩 반복한다. apply에 양수 offset을 허용하지 않으며 전체탐색 미완료 batch apply는 설치 전에 거부한다.

모든 파일·manifest의 소유/비공개·중복·ID/이름/digest 메타 검증은 선택 구간 밖까지 수행한다. 내용·digest·크기 검증이 끝난 선택분만 파일별 원자 설치하고 기존 통합 importer를 호출한다. 설치 경합이나 importer 실패에서 이미 설치된 원문은 삭제하지 않고 재실행에 사용한다. 묶음 전체에 대한 rollback/원자성을 주장하지 않는다.

이 코드는 실제 원문 적재/수집 전환 완료가 아니다. 백업/별도 복원·단일 작성자·보호13표·재실행 불변·후속 수집/전달 수락 게이트를 그대로 적용한다.
