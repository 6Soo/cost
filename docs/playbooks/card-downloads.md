# 카드 원본 수집 — ego-browser 실행 안내

## 하나·IBK 수집기 상태 (U3, 2026-11-13)

`tools/hana_card_collection/collect.mjs`와 `tools/ibk_card_collection/collect.mjs`는 공통 경계 `tools/site_card_collection.mjs`를 사용한다. 현재 두 사이트의 조회 화면 선택자와 다운로드 동작은 `NOT_VERIFIED`라 수집 단계에서 멈춘다.

이미 저장된 합성 또는 사용자 승인 원본은 국민 수집기와 같은 `cost.kb-card-collection-manifest.v1` 계약으로 `manifest.json`과 함께 실행 폴더에 둔다. `tools/import_kb_card_download.py`는 하나의 `hana_usage` 및 IBK의 기존 `statement` 파서를 그대로 호출하고, 발급사·채널·파일 경로·SHA·바이트·화면 건수·파싱 이슈를 다시 검증한 뒤 미리보기 사본에서 기존 `Pipeline.receive`를 리허설한다. `--apply`는 그 도구의 단일 작성자·신선 백업/복원·원복 경계를 그대로 적용한다. 수집 화면 선택자를 확인하지 않은 상태에서 자동 다운로드를 수행하지 않는다.

```powershell
# 합성 또는 보호 폴더의 실행 폴더에 대해 기존 경계로 미리보기
python tools/import_kb_card_download.py --run-dir <run-folder> --db <target-board.sqlite>
```

합성 파이프라인 검증은 `tests/test_hana_ibk_card_import.py`, 기존 국민 동작 회귀는 `tests/test_import_kb_card_download.py`에서 확인한다.

다음 라이브 확인을 완료한 뒤 어댑터를 활성화해야 한다.

- 기업 로그인 후 세션 생존 판정과 미등록 자격 증명의 무시 동작
- 카드 이용내역 메뉴, 날짜 조회 입력, 허용 기간 하한·상한, 실제 조회 축
- 조회 실행 뒤 화면의 기간·발급사 echo 및 건수 요약
- 다운로드 제어, 저장 파일 형식·열·파서 인식 건수
- 중복 후보·취소·환불 행을 기존 `Pipeline.receive` 경계로 전달하는 미리보기 결과
- U2의 `collection-runs/<source>.json` 계약에 로그인 필요 상태를 기록하는 동작

현재 구현된 합성 경계 검증은 `tests/test_site_card_collection.py`다. 고정 합성 파일은 `tests/fixtures/hana-card-synthetic.csv`이며 실제 고객 데이터는 포함하지 않는다.

현재 브라우저 실행 기준은 **ego-browser**다. 아래 과거 실행 기록의 도구·인증 대기는 당시 증거이며 현재 실행 명령이나 새 수집 승인으로 사용하지 않는다.

사용자가 지정한 카드사·자료 종류·기간만 수집한다. 이번 확정 범위는 **국민 기업카드 국내 매입과 해외 매입을 이용일 기준2026-10-01부터 수집하고, 중복 검증 후 운영 DB에 가져오기까지**다. 승인 내역을 관성적으로 추가하지 않는다. 원본 다운로드·기간/건수 검증과 운영 DB 입력은 별도 완료 단계로 기록한다. 상세 금융 해석은 [금융 명세](../history/specs-20261110/finance.md#src-docs-card-downloads-md)를 따른다.

## 반복 실행의 기준

수집 도구는 [`tools/collect_kb_card.mjs`](../../tools/collect_kb_card.mjs), 설정·실행법은 [국민 스크립트 사용법](kb-script-usage.md)이다. 기본 Page 연결과 실제 XLS 파서 호출 코드는 제공되며 사용자가 새 진입점을 작성할 필요는 없다. 수집은 가져오기와 별도 단계이며 `importBoundary=NOT_RUN`으로 기록한다. 저장 파일의 형식·건수 검증 → 중복 리허설 → 기존 가져오기 경로 호출은 [`tools/import_kb_card_download.py`](../../tools/import_kb_card_download.py)가 담당하며, 사용법은 아래 [가져오기 스크립트 사용법](#가져오기-스크립트-사용법) 절을 따른다.

## 실제 화면 확인 필요

아래 **6항목**은 사용자 로그인 세션에서 한 번 관측하고 비공개 JSON(`KB_CARD_SELECTORS`의 절대 경로)에 넣는다. 이번 구현 검증은 합성 자료만 사용했다.

1. 같은 TaskSpace의 `p1`이 국민 기업 로그인 후 화면인지 확인하고 `space`와 `roles.session`에 인증 후에만 존재하는 요약 요소의 `css=` 선택자를 넣는다. 로그인·인증서·OTP는 자동화하지 않는다.
2. 국내·해외 화면의 실제 최소/최대 허용일 요소를 보고 `dateFloor`, `dateCeiling`을 설정한다. 값은 ISO 날짜여야 하며 실행일로 추측하지 않는다. 국내/해외 선택자가 다르면 `sources`의 정식 소스명 아래 역할을 덮어쓴다.
3. 매입일 조회축·사업자 전체·전표 전체가 선택됐는지 보고 `dateStartInput`, `dateEndInput`, `searchControl`을 설정한다. 이 범위 선택은 실행 전 화면에서 맞춘다. 시작일은 읽기 전용 DB 집계의 마지막 이용일을 `--last-use-date`로 전달한다.
4. 조회 후 실제 적용 기간과 자료 종류를 보여 주는 요소를 보고 `periodEchoStart`, `periodEchoEnd`, `periodEchoSource`를 설정한다. 기간 요약은 `YYYY-MM-DD` 형식, 종류 요약은 비어 있지 않아야 한다. 다른 형식이면 실행을 멈추며 화면 형식 관측 후 연결 코드를 조정한다.
5. 화면 총건수/0건 요소를 `summaryResults`에 넣는다. 숫자·쉼표·`총 N건`을 읽으며 파서 행수와 대조한다. 요약에 다른 문구가 섞이면 성공으로 단정하지 않고 형식 확인이 필요하다.
6. `XLS 파일저장`과 주의사항 창의 실제 `엑셀파일저장`을 확인한다. 중간 창이 있으면 `exportOpenControl`, 최종 버튼은 `downloadControl`에 설정한다. 실제 다운로드 파일의 확장자·국내/해외 파서 채널·정상/취소 포함 건수를 대조한다. DB 중복 리허설과 가져오기는 위 보호 절차로 별도 수행하며 이 도구의 파일 SHA 대조로 대신하지 않는다.

하나·기업의 기존 조사 결과와 미확인 사항은 [조사 결과·미확인 사항](card-login-research-20261111.md)에 보존한다. 해당 카드사 수집 스크립트가 완성됐다는 뜻은 아니다.

1. 운영 DB를 `mode=ro`로 열어 국민카드의 마지막 이용일(`approval_date`)과 매입일(`posting_date`)을 국내·해외별로 집계한다. 원문 행을 출력하지 않는다. 이번 사용자 지시의 기본값은 **전체 국민카드의 마지막 이용일 당일부터** 조회하는 것이다. 하루 겹침은 마지막 이용일을 하루 더 빼는 뜻이 아니다. 두 날짜와 자료별 마지막 날짜가 다르면 인터뷰에서 차이를 설명한다.
2. `ego-browser` 스킬과 `ego-browser skill`로 현재 설치 버전의 기능을 확인한다. Windows에서는 UTF-8 `.mjs` 파일에 스크립트를 작성하고 `ego-browser nodejs -e "await import('file:///C:/절대/경로/script.mjs')"`로 실행한다. 기본 프로필과 보안 설정을 바꾸지 않는다.
3. 로그인→국내→해외→다운로드 완료 확인은 **같은 TaskSpace**에서 순차 실행한다. 후속 스크립트는 기록한 `spaceId`와 Page 라벨로 재개한다. 실제로 새 로그인에 성공한 사실이 없으면 무인 재로그인 성공으로 기록하지 않는다.
4. `task.tabs()`로 해당 작업의 관련 탭을 확인하고, 기존 관리 Page를 재사용한다. 사용자 탭은 스킬의 소유권·제어권 절차를 따른다. 비관련 업무 탭을 닫거나 공유 인증 세션을 초기화하지 않는다. 프로필 선택은 사용자가 명시한 경우에만 수행한다.
5. `page.snapshot()`을 주 읽기 경로로 사용하고, 각 동작 뒤 새 snapshot으로 결과를 확인한다. ref는 새 snapshot 기준으로만 사용하며 저장해 둔 ref/좌표를 다음 실행에 재사용하지 않는다. 조회 결과 원문 표는 채팅/보고서/외부 모델에 출력하지 않는다. 확인할 폼·버튼·요약 영역을 좁혀 읽는다.

## 로그인

- 기업 홈페이지: `https://biz.kbcard.com/CXERCZZC0001.cms`.
- 세션이 유효하면 그대로 이용한다. 만료됐으면 **공동인증서 → 로그인 → 로컬디스크 → 실제 회사 기업 인증서 확인** 순으로 진행한다. 인증서 암호·개인키·원문 식별자를 읽거나 출력하지 않는다.
- 사용할 수 있는 브라우저 공식 저장 암호 자동입력 경로를 우선한다. ego-browser가 실제 지원하는 UI/API만 사용하며 자동입력 경로가 없으면 성공으로 꾸미지 않는다. 다른 도구의 저장 암호 API나 세션을 ego-browser에 있다고 가정하지 않는다.
- 공식 **키보드 입력전환** 버튼은 필요할 때 한 번 확인할 수 있다. 보안 입력 속성 변경·저장 암호 원문 조회·보안 프로그램 우회·반복 인증 제출은 하지 않는다. 암호를 채팅으로 받지 않는다.
- 로그인·인증 코드·CAPTCHA 등 사용자만 완료할 수 있는 단계가 실제로 남으면 `task.handOff()`로 같은 화면을 넘기고 필요한 행동을 구체적으로 알린다. 같은 인증 요청을 반복하지 않으며 암호·OTP·개인키·저장 암호 원문을 조회하거나 출력하지 않는다. 사용자 확인 후 동일 TaskSpace의 제어권을 정식으로 되찾는다.
- 인증 제한을 세션 플래그·설치 코드 변경이나 권한 검사 우회로 대체하지 않는다. 브라우저 전환은 새 모델 호출·과금·자격 증명 이전을 승인하지 않는다.
- 로그인 이후 기업 세션과 조회 화면 진입을 확인해야 인증 완료다. 인증서 선택이나 암호 입력란의 존재만으로 로그인 성공을 선언하지 않는다.

## 국민카드 필수 자료와 기간

| 자료 | 확인된 공식 경로 | 조회 축 | 범위 |
| --- | --- | --- | --- |
| 국내 매입 | `https://biz.kbcard.com/CXERCMLSD0002.cms` | 매입일 | 사업자 전체·전표 전체 |
| 해외 매입 | `https://biz.kbcard.com/CXERCMLS0008.cms` | 매입일 | 사업자 전체·해외 매입 전체 |

시작일은 마지막 국민카드 이용일 당일로 두되, **화면의 조회 축은 매입일**임을 함께 기록한다. 이번 인터뷰에서 사용자는 매입일2026-10-02 대신 **이용일 기준2026-10-01**을 명시적으로 선택했다. 국내/해외에 같은 시작일을 적용한다. 이후 반복 수집도 최신 사용자 지시가 달라지지 않으면 이 기준을 적용하고 매 실행의 DB 날짜를 다시 집계한다.

종료일은 실행일과 해당 화면이 허용하는 마지막 날짜 중 이른 날짜다. 과거 확인에서 국내 매입은 전날까지 가능했지만 실행 때마다 화면에서 재확인한다. 국내와 해외의 실제 종료일이 다르면 각각 기록한다. 과거 승인일의 지연 매입·취소도 원본에 포함되면 보존한다. 날짜가 조회 시작일보다 오래됐다는 이유만으로 파일 행을 버리지 않는다.

`XLS 파일저장`은 파일 주의사항 확인 창을 거칠 수 있다. 첫 버튼 뒤 새 snapshot에서 **엑셀파일저장**을 확인하고, 실제 다운로드를 일으키는 버튼과 다운로드 이벤트 대기를 묶는다. 이벤트 시간 초과만으로 같은 다운로드 버튼을 반복해서 누르지 않는다.

```javascript
// 저장 버튼의 ref는 직전 snapshot에서 확인한 실제 값으로 지정한다.
const pendingDownload = page.waitForEvent('download');
await page.click(actualSaveButtonRef);
const downloaded = await pendingDownload;
const outputPath = 'C:/AX/cost/.local-archive/card-downloads/' + uniqueOutputName;
await downloaded.saveAs(outputPath);
const fs = await import('node:fs/promises');
const completedSize = (await fs.stat(outputPath)).size;
console.log({filename: downloaded.suggestedFilename(), bytes: completedSize});
```

완료 파일의 보존과 확인은 다운로드 이벤트를 받은 같은 스크립트 실행 안에서 끝낸다. 원본은 실행별 새 보호 폴더에 복사해 보존하고 덮어쓰지 않는다. 원래 파일명, 실제 보존 절대 경로, 크기·SHA256을 확인한 뒤 원본 수집 완료로 기록한다. 파일명 예시는 `kb-domestic-acquired-시작일-종료일.xls`, `kb-overseas-acquired-시작일-종료일.xls`다.

## 다운로드 이후의 읽기 전용 검증

- 각 파일이 실제 XLS/XLSX/CSV인지 확인한다. 로그인 HTML·오류 응답·빈 파일은 실패다. 실제 XLS 파서로 시트/열과 건수를 읽고 화면의 총 건수와 대조한다. 다운로드 버튼이 눌렸다는 사실만으로 성공 처리하지 않는다.
- 자료별 조회 기간·조회 기준·국내/해외·회사 전체·전표 전체·정상/취소 건수·파일 해시를 manifest에 기록한다. 0건은 실제 조회 화면의 요약 근거와 `no_data` 상태가 필요하다. 고객 거래 원문은 manifest/문서에 넣지 않는다.
- 국내 취소번호/원승인번호를 구분한다. 해외 원본의 승인번호 부재는 정상이며 번호를 만들지 않는다. 해외 `총결제금액=결제원금+수수료`를 검사하고 수수료를 이중 합산하지 않는다. 취소매출 부호·현금서비스/리버설·동일 값의 복수 실제 행은 원본대로 보존한다.
- 기존 DB와의 중복 대조는 읽기 전용으로 수행할 수 있다. 사용자 승인 범위가 다운로드/검증까지이면 운영 DB·장부·환불 링크·Google에 쓰지 않는다. DB 입력까지 지시받은 경우에만 기존 가져오기 경로와 필요한 데이터 보호 절차를 별도로 수행한다.

## 가져오기 스크립트 사용법

[`tools/import_kb_card_download.py`](../../tools/import_kb_card_download.py)는 수집 실행 폴더(`manifest.json` + 보존 원본)를 받아 형식·건수 검증 → 기존 중복 검사 → 기존 가져오기 경로(`app.Pipeline.receive`) 호출까지 수행한다. 새 가져오기 로직은 없으며 운영 화면 업로드와 같은 사전검사(`app.card_preflight.validate_upload`)·파서·중복/충돌 보호를 그대로 쓴다. 분류·장부 기록·Google 쓰기를 직접 수행하지는 않으며, 분류는 웹 업로드와 동일하게 P1 대기열에 적재만 한다(아래 참조). **이번 검증은 합성 파일·합성 DB만 사용했고 실제 카드사 화면·운영 DB 반영은 하지 않았다.**

- 미리보기(기본): 대상 DB를 읽기 전용으로 열고 사본에서 리허설한다. 대상 DB에는 쓰지 않는다.
- `--apply` 단일 작성자 게이트(실제 검사): 운영자 플래그가 아니라 도구가 직접 확인한다. `--host-root`(기본 `D:/WebLedgerHost`)의 `config/ledger-route.json`에서 Board 포트(8751 또는 8752)를 읽고, `tools/complete_card_classification.py`의 `require_writers_offline`과 같은 PowerShell 검사로 `WebLedger-Board`·`WebLedger-SourceRefresh` 작업이 둘 다 존재하며 Running이 아니고 해당 포트에 리스너가 없을 때만 진행한다. 어기면 `WRITERS_NOT_OFFLINE`/`ROUTE_REQUIRED`/`ROUTE_PORT_INVALID`로 멈추며 백업도 만들지 않는다.
- `--apply` 신선 백업 증거: 쓰기 전에 새 백업을 만들고(`BACKUP_EXISTS`로 덮어쓰기 거부) 별도 파일로 복원 검증한다. 이어서 `require_offline_backup`과 같은 기준으로 백업이 1시간 이내이며 원본 DB의 전체 테이블 상태(`database_state`)와 일치하는지 확인한다(`BACKUP_NOT_FRESH`/`BACKUP_SOURCE_CHANGED`). 리허설은 이 신선 백업 사본에서 수행하고, 안전하지 않으면 `REHEARSAL_HOLD`로 멈춘다.
- 수집이 이미 검증한 항목(파일 SHA·화면 건수 대조 `countCheck=MATCHED`·파서 성공)을 매니페스트에서 요구하고, 도구 자신이 바이트·형식·채널·건수를 다시 검증한다. 하나라도 실패하면 멈추며 DB에 쓰지 않는다.
- 쓰기 뒤 검증과 자동 복원: `receive`는 파일마다 내부 트랜잭션을 커밋하므로 앱 코드 변경 없이 쓰기 전체를 하나의 외부 트랜잭션으로 묶을 수 없다. 그래서 **백업 자동 복원 방식**을 쓴다. 쓰기 직전 상태 비교는 `BEGIN IMMEDIATE` 쓰기 잠금 안에서 수행하고, 이 잠금은 비교 직후 `ROLLBACK`으로 풀리며 receive까지 유지되지 않는다(다른 작성자 차단은 잠금이 아니라 위 단일 작성자 게이트가 담당하고, receive는 파일별 자체 트랜잭션을 쓴다). 쓰기 뒤 결과 계획 비교(`PLAN_CHANGED`)·보호 검사·재수신 무변경 검사 중 하나라도 실패하면 자동 복원을 시도한다. **복원 직전에 단일 작성자 게이트(`require_writers_offline`)를 다시 확인**해서 서버가 다시 켜졌으면 복원하지 않고 `WRITERS_ONLINE_RESTORE_BLOCKED`로 멈춘다(라이브 작성자 커밋과 충돌 방지). 서버가 꺼져 있으면 신선 백업을 SQLite backup API로 대상에 자동 복원한 뒤 상태 일치를 검증하고 원래 오류로 끝낸다. 보고서 `apply.restored`가 복원·검증 결과다. **자동 복원 자체가 실패하면(`restored=false` 또는 `verified=false`) `RESTORE_FAILED_DO_NOT_START_SERVER` 전용 오류로 멈추며, 서버를 시작하지 말고 아래 수동 복원으로 되돌린다.**
- 분류 대기열: 가져온 각 배치를 웹 업로드(`/api/imports`)와 똑같이 `webapp.card_completion_worker.queue_batch`로 P1 분류 대기열(`requests` 테이블, `card_completion_job`)에 넣는다. 대기열은 DB에 영속하므로 서버가 멈춘 상태에서도 적재할 수 있고, Board 서버가 다시 시작되면 `CardCompletionWorker`가 이어서 처리한다. 장부 자동 기록은 이 후속 처리의 일부이며 가져오기 도구가 직접 하지 않는다.
- 보고서에는 집계만 남으며 거래 원문은 출력하지 않는다. `kb_last_dates`는 다음 수집의 `--last-use-date`를 위한 읽기 전용 집계 참고값이다(조회 기간 계산 자체는 아래 절차 1번의 집계로 수집 단계에서 수행).

수집 원본은 보호 폴더 `D:/WebLedgerHost/data/backups/card-downloads/<날짜>/`에 보존하고, 가져오기 백업은 별도 보호 폴더에 둔다. 도구는 실행 폴더·백업을 덮어쓰지 않으며 충돌을 거부한다.

```powershell
# 미리보기 — 대상 DB 읽기 전용, 사본 리허설
python tools/import_kb_card_download.py --run-dir D:/WebLedgerHost/data/backups/card-downloads/2026-11-13 --db D:/WebLedgerHost/data/board.sqlite

# 반영 — 실제 단일 작성자 게이트·신선 백업/복원 검증 뒤 기존 receive 경로 + 분류 대기열 적재
python tools/import_kb_card_download.py --run-dir D:/WebLedgerHost/data/backups/card-downloads/2026-11-13 --db D:/WebLedgerHost/data/board.sqlite --apply --backup-dir D:/WebLedgerHost/data/backups/card-import-2026-11-13 --host-root D:/WebLedgerHost
```

### 반영 뒤 분류 대기열 재개

`--apply`는 서버가 멈춘 상태에서도 대기열을 DB에 넣는다. 처리를 재개하려면 Board 서버를 다시 시작한다(호스트의 기존 재시작 절차와 같은 작업 이름). 대기열 처리는 호스트 설정 `config/card-flow.json`의 `automatic_card_completion=true`일 때 활성화된다.

```powershell
# Board 재시작 — CardCompletionWorker가 시작되며 적재된 대기열을 이어서 처리한다
Start-ScheduledTask -TaskName WebLedger-Board
# SourceRefresh도 멈춰 있었다면 함께 재개
Start-ScheduledTask -TaskName WebLedger-SourceRefresh
```

자동 복원이 실패했을 때의 수동 복원 최후 수단(`RESTORE_FAILED_DO_NOT_START_SERVER`): **대상이 불완전 상태일 수 있으므로 복원·검증이 끝날 때까지 서버를 시작하지 않는다.** 먼저 `WebLedger-Board`·`WebLedger-SourceRefresh`가 멈춰 있는지 확인하고(`WRITERS_ONLINE_RESTORE_BLOCKED`로 멈췄다면 반드시 정지시킨 뒤), 보고서 `apply.backup`에 기록된 백업 경로를 대상에 덮어쓴다. 백업은 자기완결 SQLite 사본이며 서버가 정상 종료되면 WAL 곁파일이 없으므로 그대로 복사할 수 있다. 복사 뒤 미리보기를 다시 실행해 무결성·상태 일치를 확인한 다음에야 서버를 시작한다.

```powershell
Copy-Item D:/WebLedgerHost/data/backups/card-import-2026-11-13/board-kb-import-<stamp>.sqlite D:/WebLedgerHost/data/board.sqlite -Force
```

합성 검증 항목: 파일 SHA/크기 대조, 로그인 HTML·형식 오류·파싱 이슈 거부, 국내/해외 채널 대조(해외 XLS·CSV 동일 거래 대조 포함), 화면 건수 대조, 내용 멱등·identity 중복·승인번호 없는 해외 행 다중집합·충돌 시 기존 행 보존, 미리보기 무쓰기, 단일 작성자 게이트(작업/포트·라우트 파일)와 신선 백업 증거, `REHEARSAL_HOLD`·쓰기 전 `PLAN_CHANGED` 무쓰기, 쓰기 뒤 `PLAN_CHANGED`/보호 실패 시 백업 자동 복원·상태 일치, `BACKUP_EXISTS`·`FILE_OUTSIDE_RUN_DIR` 거부, 분류 대기열 적재(웹 업로드와 동일), apply 백업/복원·재수신 무변경·수동 결정/장부 보존, 스키마 차이 거부. 실행은 `python -m pytest tests/test_import_kb_card_download.py -q`.

## 중복 검증 후 운영 DB 가져오기

이번 인터뷰에서 이 단계까지 승인됐다. 파일을 받기 전에는 원본 검증·중복 해소·DB 입력을 완료했다고 쓰지 않는다. 이 절의 사본 리허설·신선 백업/별도 복원·단일 작성자·재수신 무변경 절차는 위 가져오기 스크립트에 구현돼 있으며, 아래 보호 조건은 그대로 적용된다.

1. 원본 둘을 각 채널로 파싱하고, 운영 DB의 읽기 전용 사본에서 기존 `app.Pipeline.receive`/해당 카드 입력 경로로 리허설한다. 기존 화면의 가져오기/구형 CSV 입력기와 기능을 혼동하지 않는다. 실제 XLS 파서는 `app/import_card.py`에 있으며 최신 배포 SHA의 코드를 기준으로 한다.
2. 파일 해시 재수신·파일 간 동일 승인·매입과 승인의 동일 거래·승인번호 없는 해외 원행의 다중성까지 검사한다. 원승인일/매입일·부호·원금/수수료/총청구액을 구분한다. 과거에 변환 CSV로 넣은 행과 새 XLS 원행의 포맷 차이만으로 신규 거래를 만들지 않는다. 불명확한 중복 후보는 기록·삭제·강제 합치기로 넘기지 않는다.
3. 파일 수신과 파싱·분류·내부 장부 자동 기록을 구분한다. `CardFlow.classify`는 자동 기록 경로도 호출하므로, 단순 원본 가져오기 승인을 신규 장부/Google 기록 승인으로 확대하지 않는다. 새 금융 링크나 실제 환급을 자료 수신만으로 확정하지 않는다.
4. 실제 원본/금융 DB 쓰기 전에는 위험에 맞는 신선 백업·별도 복원·단일 작성자·같은 입력/DB 상태 리허설·원자성·재수신 무변경 검증을 적용한다. 현재 수동 교정·기존 원문/금액/ID·환불/중복 보호·기존 장부·분류를 보존하고 실제 신규/연결/충돌 건수를 별도로 보고한다. 필요한 보호가 실패하면 쓰기 전에 중단한다.
5. 최종 기록은 국내/해외의 다운로드·파싱·중복 검증·DB 입력 상태를 각각 표시한다. 새 DB 건수가 파일 행수와 같다고 가정하지 않는다. 문서만 바뀐 후속 단계에서 데이터 재처리나 재배포를 반복하지 않는다.

## 과거 인터뷰와 실행 상태 — 2026-10-29

이 절은 당시 도구·실행 상태의 보존 기록이다. 현재 브라우저 실행은 위 ego-browser 절차를 따르며, 아래 REPL/Vault 재개 조건을 현재 작업의 선행 조건으로 사용하지 않는다.

- 최신 사용자 범위: 국민 국내/해외 매입, DB 마지막 이용일과 하루 중복, 화면의 최신 허용일까지 수집, 불분명한 부분은 인터뷰로 구체화.
- readonly DB 확인: 국민3,675건. 국내 마지막 이용일2026-10-01/매입일2026-10-02, 해외 마지막 이용일2026-09-30/매입일2026-10-02. DB 쓰기0.
- 인터뷰 확답: **이용일 기준10월1일부터**, **중복 검증 후 운영 DB 가져오기까지**, **Aside Vault 저장 암호 사용 및 방법 기록**. 앞선 “ㄱ” 시점의 다운로드/검증까지라는 임시 범위는 이 명시 답변으로 대체됐다.
- 확인: 일반 모드, 만료된 기업 로그인, 로컬디스크의 기업 인증서 선택. REPL의 `passwordManager` 전역 없음, CLI 공개 스킬 목록에 password-manager 없음, 암호 입력란 집중과 공식 키보드 입력전환 후 저장 입력 제안 없음.
- **WAIT_SUPPORTED_VAULT_REPL**: 사용자 지적에 따라 크레딧을 Vault의 필수 조건으로 보던 앞선 판단을 정정했다. CLI1.26.1023.1115·데몬1.26.1029.43의 설치 코드에서 CLI REPL의 비공개 세션 고정과 Vault 전역 제외를 확인했다. 이는 설치 코드의 정적 확인이며 Vault 호출 성공을 관찰한 것은 아니다. 실제 REPL에서도 `passwordManager`가 없고 저장 설정을 켠 별도 REPL도 같았다. 일반 agent는 HTTP402로 도구 실행 전에 실패했지만 Vault 자체의 크레딧 요구는 확인되지 않았다.
- 자동입력 API·로그인·조회 기간 상한·국내/해외 다운로드·원본 파싱·중복 검증·DB 입력은 아직 미실행/미확인이다. 기본 계정/모델/Vault 정책 변경·신규 과금·운영 DB 쓰기0이며 임시 CLI 세션 표시 설정은 원래false로 복구했다. 조회 종료일을 오늘/전날로 추정해 완료 처리하지 않는다.
- 재개 조건: 지원되는 일반 세션의 직접 REPL/Vault 연결 또는 기존 승인 범위의 실행 가능한 agent 경로를 실제 확인한다. 이후 공식 자동입력→같은 지속 REPL에서 로그인 결과 확인→국내/해외 원본 다운로드→중복 검증→단일 작성자 조율과 보호된 DB 입력 순서다. 수동 암호 입력을 사용자에게 다시 요구하거나 새 유료 자원을 만들지 않는다. 운영 배포를 진행하는 별도 작성자와는 DB 입력 직전에 다시 조율한다.

작업 완료 후 스킬에 따라 `task.finish()`를 실행한다.

이 문서는 다운로드 실행 안내다. 상태가 대기인 항목을 완료라고 쓰지 않으며, 문서 변경 때문에 코드 검사·배포·서버 재시작을 하지 않는다.
