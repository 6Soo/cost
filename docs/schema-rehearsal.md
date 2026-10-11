# COST 운영 SQLite 스키마 리허설 (비운영 복사본 전용)

> 개발 검증 가이드. 이 문서와 도구는 운영 DB 마이그레이션·배포·운영 재시작 승인이나 완료 증거가 아니다.

## 위험 및 목적

통합 PR #85에서는 app.db.Store의 생성 과정(ensure_schema)에서 transaction_company_exclusions를 비롯한 미존재 테이블을 생성할 수 있다. 웹 요청 중 첫 CardFlow 생성도 이 DDL의 실행 시점일 수 있다. 따라서 운영 DB에 새 코드를 연결하는 것만으로 변경이 발생할 수 있다. 메인 병합·운영 연결 전에 격리 복구본에서 마이그레이션을 시험한다.

tools/rehearse_cost_schema.py는 명시적으로 제공된 **정지 상태의 백업/복구 SQLite 사본만 입력**받는다. 원본 DB를 SQLite로 열지 않고 파일 해시를 계산한 뒤 임시 폴더에 바이트 복제한다. 임시 복제본에만 Store의 실제 생성 코드를 호출한다.

검사 항목:

- 정상 SQLite 파일 헤더 및 board_rows/board_requests 존재 확인
- 입력 파일 SHA-256 및 선택적인 사전 승인 해시 일치
- WAL/SHM/저널 파일이 남아 있는 불완전 복사본 차단
- SQLite integrity_check (전후)
- 기존 스키마의 테이블·인덱스·트리거·뷰 정의 불변
- 기존 테이블의 행 수와 행별 해시 지문 불변
- transaction_company_exclusions 존재 확인
- 입력 복사본 SHA-256 불변 및 임시 시험 DB 자동 폐기

출력에는 고객 행·거래금액·파일 경로를 담지 않는다. 실패하면 종료 코드 2와 오류 종류만 표시한다.

## 실행 전 조건

1. 운영 PC의 기존 쓰기 프로세스를 임의로 중지하지 않는다. 백업·복구 운영 절차는 별도 승인 후 수행한다.
2. 기존 tools/verify_operational_backup_restore.py 등으로 **검증된 복구 사본**을 준비한다. 원본 D:\WebLedgerHost\data\board.sqlite를 직접 넘기지 않는다.
3. 입력 경로와 해시를 검토하고 복구 사본 안에 -wal, -shm, -journal 부속 파일이 없음을 확인한다.
4. 이 도구가 검사하는 대상은 **COST Store DDL**뿐이다. 전체 호스트 DB 전환, Google 권한, 실제 사용자 로그인, 카드·환불·OTA 보존, rollback/restart 과정까지 검증한 것이 아니다.

격리 복구본이 준비된 비운영 환경에서만 실행한다.

~~~powershell
python tools/rehearse_cost_schema.py --source-copy "C:\isolated-restore\board.sqlite" --expected-sha256 "<이미 검증한 백업 SHA-256>" --confirm-isolated-copy
~~~

결과의 status=PASS는 해당 입력 복사본의 스키마 리허설이 통과했다는 제한적인 뜻이다. 운영 DB 변경이나 실제 배포 허가가 아니다. 실데이터 복구본을 사용하면 출력은 집계 메타만 저장하고 원본 자체는 외부로 전송하지 않는다.

## 검증 범위

- 새 합성 검사: tests/card_pipeline/test_schema_rehearsal.py (보존, 해시 불일치, WAL 차단, DDL 실패, 빈 파일/잘못된 DB 거부, CLI 승인 플래그).
- 작성 세션은 격리한 합성 스키마 하네스에서 7개 테스트 통과. **실제 저장소의 전체 의존성을 사용한 pytest 실행은 별도 필요**하므로 통과했다고 단정하지 않는다.
- 기존 PR #85의 전체 회귀 3035 passed / 3 skipped / 2452 subtests는 이전 코드 시점의 근거이며 본 신규 도구에 대한 근거로 합산하지 않는다.

운영 승인 전 필수 게이트: 실제 복구 사본의 별도 리허설, 실제 운영 프로세스/DB 접근 경로 확인, 복원 리허설, 거래·환불·확정·OTA 불변 검증, 필요 권한/개인정보 검증. 승인 없이 main 병합, 운영 스키마 자동 생성, 스케줄러 활성화, Google 원본 수정, 배포를 하지 않는다.
