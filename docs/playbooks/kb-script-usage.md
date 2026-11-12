# 국민 기업카드 매입 수집 스크립트 사용

제공된 `tools/collect_kb_card.mjs`와 기본 진입점 `tools/kb_card_collection/entry_kb.mjs`를 쓴다. 사용자가 새 브라우저 모듈을 작성할 필요는 없다. 로그인·인증서·OTP는 사람이 완료하며 세션이 만료되면 `LOGIN_REQUIRED`로 멈춘다. 이번 검증은 합성 Page와 합성 XLS만 사용했다.

## 설정과 실행

[카드 절차서의 실제 화면 확인 필요 6항목](card-downloads.md#실제-화면-확인-필요)을 관측한다. 비공개 UTF-8 JSON에 `space`와 `roles`를 둔다. 읽기 역할은 `css=#실제요소` 또는 `loc=css:#실제요소` 형태로 지정한다. 모호한 다중 요소는 존재로 인정하지 않는다. 행동 역할에도 고정 CSS 선택자를 쓰고 snapshot ref를 저장하지 않는다.

역할: `session`, `dateFloor`, `dateCeiling`, `dateStartInput`, `dateEndInput`, `searchControl`, `periodEchoSource`, `periodEchoStart`, `periodEchoEnd`, `summaryResults`, `downloadControl`. 주의사항 창을 먼저 열어야 하면 `exportOpenControl`을 추가한다. 날짜 읽기 값은 ISO 날짜여야 한다. 선택자만으로 실제 화면의 날짜 형식을 표현할 수 없으면 CAPTURE_REQUIRED로 중단하고 관측한 형태에 맞춰 연결 코드를 수정해야 한다.

국내/해외 선택자가 다르면 JSON의 `sources` 아래 `국민 기업카드 국내 매입` / `국민 기업카드 해외 매입` 객체에 해당 역할을 넣어 공통 `roles`를 덮어쓴다. 화면은 실행 전에 매입일·사업자 전체·전표 전체로 설정한다. 이 조건 선택 자체의 자동화는 미구현이다.

PowerShell에서 레포 루트를 현재 폴더로 두고 실행한다. 아래 경로·날짜·TaskSpace 이름은 실제 관측한 값으로 바꾼다. 수집 원본 보존 폴더는 보호 경로 규칙 `D:/WebLedgerHost/data/backups/card-downloads/<날짜>/`를 따른다(실행마다 새 폴더; 비어 있지 않으면 거부).

```powershell
$env:KB_CARD_SELECTORS = 'C:/private/kb-selectors.json'
node tools/collect_kb_card.mjs --ego-entry tools/kb_card_collection/entry_kb.mjs --space-name kb-collection --source both --last-use-date 2026-10-01 --execution-date 2026-11-11 --out-dir D:/WebLedgerHost/data/backups/card-downloads/2026-11-11 --python python --parser-module tools/kb_card_collection/verify_xls.py
```

CLI는 UTF-8 `.mjs`를 만들고 `ego-browser nodejs -e`로 실행한다. 브라우저 프로세스가 셸 환경을 상속한다고 가정하지 않고 선택자 파일의 절대 경로를 launcher에 전달한다. 같은 TaskSpace·p1을 재사용하며 인증 자동화는 없다. 프로그램 API의 기존 stdin runner는 호환용이며 CLI는 파일 실행 경로를 사용한다.

## 끝까지 도는 범위와 가져오기 경계

1. 호출자가 읽기 전용 DB 집계로 제공한 마지막 이용일 당일부터 시작하고, 종료일은 실행일/화면 허용일 중 이른 날짜로 계산한다. 도구가 운영 DB를 읽지는 않는다.
2. 국내·해외 조회 입력 → 조회 후 실제 기간 확인 → 주의사항 창(설정 시) → 다운로드 대기 설치 → 최종 저장 버튼 → 같은 라운드 `saveAs`를 수행한다. 타임아웃 때 버튼을 다시 누르지 않는다.
3. 새 보호 폴더에 파일을 보존하고 바이트·형식·SHA256을 확인한다. 기존 Python 카드 파서가 XLS의 시트/열을 해석하며 화면 총건수와 파서 행수를 대조한다. 불일치/파싱 이슈는 실패다. `countCheck=MATCHED`와 파서 성공을 확인하며, 파서 옵션을 생략하면 건수 검증 완료가 아니다.
4. 화면 0건 근거가 있으면 파일 없이 `no_data`로 기록한다. 원문 행을 manifest/로그에 쓰지 않는다.
5. 같은 실행 파일과 `--previous-manifest <이전 manifest>`의 SHA256을 대조해 `DUPLICATE_FILE` / `NO_FILE_MATCH`를 남긴다. 같은 파일이라도 지우거나 합치지 않는다. 이는 파일 단위 검사이며 DB 거래 중복·포맷 간 동일 거래·환불 짝 검증은 아니다.
6. `importBoundary=NOT_RUN`, `databaseRows=NOT_RUN`을 기록하고 종료한다. 운영 DB 가져오기는 별도 도구 [`tools/import_kb_card_download.py`](../../tools/import_kb_card_download.py)가 담당한다: 미리보기는 읽기 전용 사본 리허설, `--apply`는 실제 단일 작성자 게이트(라우트 포트의 작성자 정지 검사)·신선 백업/별도 복원 뒤 기존 `Pipeline.receive` 경로로 쓰고 웹 업로드처럼 분류 대기열에 적재한다([가져오기 스크립트 사용법](card-downloads.md#가져오기-스크립트-사용법)). 이 수집 도구는 DB·장부·Google에 쓰지 않는다.

`manifest.json`은 원문 없이 기간·자료 종류·파일 지문·화면 건수·파서 건수·파일 중복·미실행 경계를 담는다. 폴더가 비어 있지 않으면 덮어쓰지 않고 거부한다. CLI의 실패/manifest 쓰기 실패는 exit 2다. 전체 결과 `ok`는 수집 경로의 결과이며 `countCheck` 미확인이나 가져오기 완료를 대신하지 않는다.

## 검증

`python -m pytest tests/test_kb_card_collection_script.py -q`는 Node 합성 묶음을 실행한다. 합성 Page에서 조회·파일 저장·실제 합성 XLS Python 파싱·건수 불일치·이전 파일 중복·0건을 검증한다. 실제 로그인·사이트·고객 자료·운영 DB 접근은 하지 않는다. 실제 다운로드 파일 채널·취소 건수·원금/수수료 검증과 운영 가져오기는 이번 검증 범위 밖이다.
