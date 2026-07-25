# 저장소 구조와 브랜치 운영 기준

## 1. 두 실행 축

이 저장소에는 서로 다른 배포·검증 주기를 가진 두 실행 축이 있다.

| 축 | 위치 | 역할 | 현재 상태 |
|---|---|---|---|
| Apps Script | `apps-script/` | Google 계정 안에서 RAW 카드 시트를 읽고 장부 전기·상태 표시·메일 연동 | 운영 자동화 코드 |
| 비용분류 | `ledger/` | 카드·수기·OTA 원천을 분류·대사하고 분기 워크북을 생성 | v14/v76 레거시 정본 + v2 병렬 검증 |

운영 전환 승인이 있기 전까지 `classified_v14.csv`와 v76 워크북 계열이 정본이다.
`ledger/domain/`의 v2는 원천·결제·취소관계·예약·여행·판정·배분·전기를 분리한
병렬 경로이며, 전환 게이트가 통과했더라도 자동으로 운영 정본을 대체하지 않는다.

## 2. 디렉터리별 책임

### `apps-script/`

- `Code.gs`: 자동전기 엔진의 중심 진입점과 공통 규칙
- `GmailIngest.gs`: 이메일 기반 거래·예약 정보 수집
- `LeaderPaymentSync.gs`: 대장 결제 동기화
- `PinLinks.gs`: 예약 PIN 링크 처리
- `WeeklyReport.gs`: 주간 보고
- `appsscript.json`, `.clasp.json`: GAS 런타임·배포 설정

### `ledger/` 레거시 호환 경로

- `ingest.py`, `master_ledger.csv`: 카드 원천 정규화와 멱등 마스터
- `build_v13_trip.py`, `fix_v14.py`, `patch_v14.py`: `classified_v14.csv` 생성 계보
- `build_workbook_v64.py`~`build_workbook_v76.py`: 워크북 버전 이력. 새 버전을
  만들 때 기존 파일을 덮어쓰지 않는다.
- `gen_*`, `restructure_*`, `consolidate_2q.py`: 수기 장부와 매출확인자료 변환
- `integrity_check.py`: 행 단위 참조정합 감사
- `data/`: 커밋된 재현 입력·레거시 정본·워크북. 임의 정리나 재생성 결과의
  무검증 교체를 금지한다.

### `ledger/domain/` v2 경로

- `schema.sql`: 분리 도메인과 버전 관계의 SQLite 스키마
- `ledger_db.py`: 초기화·재생성·검증·검토 스냅샷 CLI
- `source_adapters.py`, `direct_sources.py`: 카드·수기·OTA 직접 적재
- `v2_workbook_adapter.py`: v2 결과의 병렬 워크북 projection
- `transition_gates.py`: 레거시 회귀와 전환 조건 검증
- `tests/`: 도메인 불변식, 어댑터, P6 전환 회귀 테스트
- `baselines/`: 재현 가능한 회귀 기준과 게이트 결과

## 3. 작업 시작과 검증 진입점

문서 읽기 순서는 루트 `AGENTS.md`를 따른다. 비용·장부를 수정할 때에는 최신 Drive
원장 재수취가 필요한지 먼저 확인하고, `docs/비용분류_지시사항_원장.md`의 불변식을
적용한다.

v2의 로컬 재현은 저장소 루트에서 다음 순서로 수행한다.

```bash
python3 -m unittest discover -s ledger/tests
python3 -m ledger.domain.ledger_db --db /tmp/cost-ledger.db rebuild
python3 -m ledger.domain.ledger_db --db /tmp/cost-ledger.db validate
python3 -m ledger.domain.ledger_db --db /tmp/cost-ledger.db import-direct-sources
python3 -m ledger.domain.transition_gates \
  --db /tmp/cost-ledger.db \
  --baseline ledger/baselines/p05_latest_20260725/regression_totals.json \
  --output /tmp/p6_transition_gate_report.json
```

`import-direct-sources`는 전환 게이트가 검사하는 카드·수기·OTA 직접 원천을 채운다.
이를 생략하면 새 DB의 `direct_source_records`가 비어 게이트 1이 실패한다. 정확한 재현
조건과 현재 검증값은 `docs/CODEX_CLOUD_HANDOFF.md`를 기준으로 한다.

## 4. 브랜치 정리 기준

1. 새 작업은 최신 기본 브랜치에서 목적이 드러나는 `feat/`, `fix/`, `docs/`,
   `chore/` 브랜치를 만든다. 임시 이름(`work`, `tmp`)은 PR 전 정리한다.
2. 서로 다른 계보의 장부 변경은 파일이 비슷하다는 이유만으로 병합하지 않는다.
   카드 이벤트 보존, 합계, 행 단위 정합성의 회귀 검증 후 필요한 커밋만 선별한다.
3. 병합된 로컬·원격 작업 브랜치는 삭제한다. 단, 미병합 PR은 고유 변경의 포함
   여부를 확인하기 전 닫거나 삭제하지 않는다.
4. 생성 DB, 검토 스냅샷 같은 gitignore 대상은 커밋하지 않는다. 기준선 변경은
   생성 명령과 검증 결과를 함께 남긴다.
5. 한 브랜치에는 한 목적만 두고, 커밋 후 PR 제목·본문에 정본 영향과 검증 명령을
   명시한다.

## 5. 2026-07-25 브랜치 감사 결과

GitHub 관리자 인증 후 열린 PR과 원격 브랜치를 전수 확인했다. 장기 draft였던 PR #5와
#7은 모두 최신 `main`과 충돌했고, 자동 병합하기에는 서로 다른 운영 축의 고유 변경과
레거시 생성 산출물이 섞여 있었다.

- PR #5의 마지막 커밋 `c3751a3`은 `archive/pr-5-pre-cleanup` 태그로 보존했다.
  Apps Script 중복 억제·메일 매칭·주간 보고 변경은 필요할 때 최신 `main`에 선별
  이식하고 GAS 스텁 테스트를 다시 수행한다.
- PR #7의 마지막 커밋 `47a1761`은 `archive/pr-7-pre-cleanup` 태그로 보존했다.
  17개 레거시 비용분류 커밋에는 최신 원장과 품질 게이트가 있지만, v2의 승인·취소
  이벤트 보존 원칙과 충돌할 수 있어 통째로 병합하지 않는다.
- 두 PR에는 감사 근거와 복구 태그를 댓글로 남긴 뒤 닫았고, 해당 원격 작업 브랜치를
  삭제했다. 따라서 고유 변경은 태그로 복구 가능하며, 기존 장기 draft PR과 그 원격
  브랜치는 남아 있지 않다. 이 감사 결과 자체는 별도 정리 PR로 반영한다.

태그 내용은 `git show archive/pr-5-pre-cleanup` 또는
`git show archive/pr-7-pre-cleanup`으로 확인한다. 태그를 삭제하거나 변경을 이식할
때에는 별도 검증 PR에서 근거를 남긴다.
