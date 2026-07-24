# 카드거래 정본 마스터 (AI-Native 파이프라인)

주식회사 숲길여행 전 카드(국민·하나·기업) 거래를 단일 정본으로 관리.

## 파일
- `master_ledger.csv` — 정본 거래원장(거래키로 멱등 중복제거). 열: 거래키·카드사·카드4·구분·승인일·매입일·가맹점·원화금액·현지금액·통화·승인번호·취소여부·출처·적재일·**기록여부(워크북반영Y/N)**·워크북참조·비고
- `ingest.py` — 증분 적재기. 6종 원본형식 자동판별→정규화→병합.
- `link_workbook.py` — 워크북(classified) 대조해 기록여부 갱신.

## 표준 소스(2026-07-20 확정)
- 국민: 국내매입 + 해외매입 (승인내역은 해외 승인금액 0원이라 금액용 불가)
- 하나: **승인내역만** (비-승인내역은 거부, 교차검증만)
- 기업: 승인내역

## 사용
```
# 원본이 .xls면 먼저 변환
libreoffice --headless --convert-to xlsx --outdir conv <파일.xls>
python3 ingest.py conv/<파일>.xlsx        # 없으면추가/있으면병합/같으면버림
python3 link_workbook.py                   # 기록여부 갱신
```

## 병합 규칙
- 없는 건(신규 거래키) → 추가
- 있는 건(같은 거래키, 새 필드 있음) → 병합(빈 필드 보강, 기록여부 보존)
- 같은 건(변화 없음) → 버림
일자가 겹쳐 재업로드해도 중복 자동 제외(멱등).

## 도메인 분리형 원장 v2

기존 `classified_v14.csv`는 호환용 산출 정본으로 유지하되, 결제 원천과
예약·여행귀속·분류판정·장부전기를 분리한 SQLite 모델을 병렬 구축 중이다.

```bash
python3 domain/ledger_db.py import-legacy
python3 domain/ledger_db.py validate
python3 domain/ledger_db.py review-report
python3 domain/ledger_db.py review-snapshot \
  --output data/review-snapshots/baseline
```

`review-snapshot`은 집계값에 대응하는 8개 상세 검토 큐 CSV, 입력 원천 해시,
요약 지표와 배분대상·여행·계정별 회귀 합계를 생성한다. 이전 스냅샷과 비교하면
큐별 추가·해소·잔존 거래를 `diff.json`으로 확인할 수 있다.

```bash
python3 domain/ledger_db.py review-snapshot \
  --output data/review-snapshots/after-p1 \
  --compare-to data/review-snapshots/baseline
```

산출 구조:

```text
data/review-snapshots/baseline/
├── manifest.json
├── summary.json
├── regression_totals.json
└── queues/
    ├── unassigned.csv
    ├── unresolved_transaction_relations.csv
    └── ...
```

스키마는 `domain/schema.sql`, 설계와 전환 게이트는
`../docs/비용분류_도메인모델_v2.md`를 참고한다.
