# 비공개 클라우드 메일 수집 전환

## 현재 상태와 영향

기존 Apps Script 프로젝트를 읽기 전용으로 내려받아 대조했다. 운영 프로젝트에는 `CloudMail`이 없고 기존 `GmailIngest.AUTO_DRAIN`은 false다. Windows Gmail 수집은 기존 예약 작업에서 계속 담당한다. 이번 코드는 클라우드 수집기, 별도 배포 패키지, Drive 원문을 COST에 가져오는 읽기/추가 경로를 준비한다. 실제 클라우드 활성화·운영 원문 적재·기존 예약 작업 중지는 아직 하지 않았다.

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

완료는 코드/합성 검사와 구분한다. 새 프로젝트·Google 동의·초기 전체 탐색·실제 새 원문 적재·반복 불변·후속 예약 수집·Drive 전달·기존 로컬 Gmail 직접 수집 중지를 확인해야 `CUTOVER_COMPLETE`다. 현재는 `IMPLEMENTED_TARGETED_TESTED / BLOCKED_AUTH_AND_INFRA_APPROVAL`이다.
