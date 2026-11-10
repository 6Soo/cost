# 과거 원장 도구와 일정 도메인

현재 운영 장부의 정본은 `D:/WebLedgerHost/data/board.sqlite`의 `board_rows`다. 이 폴더의 CSV 원장과 워크북 연결 도구는 과거 분석·이관·대조 경로이며 별도 운영 쓰기 경로가 아니다. `classified_v14.csv`와 `master_ledger.csv`를 현재 장부로 덮어쓰지 않는다.

## 과거 도구

- `ingest.py`: 과거 카드 원본의 증분 적재·대조 도구다.
- `link_workbook.py`: 과거 워크북의 기록 여부를 대조한다.
- `domain/ledger_db.py`: 분리된 도메인 자료의 검증과 검토 보고서를 만든다.
- `domain/direct_trip_schedule_authority.py`: 명시 연도·기간·근거 digest를 가진 일정 계약을 정의한다. 현재 카드 흐름에서도 이 일정 검증을 사용한다.

과거 도구를 실행하면 로컬 산출물이 바뀔 수 있으므로 대상과 복구 사본을 확인한다. 기존 CSV 병합 규칙을 현재 거래의 중복 방지 규칙으로 일반화하지 않는다. 같은 원문 해시라도 실제 복수 거래는 보존하고, 결제·취소·환불을 합치지 않는다.

## 현재 기준

국민 국내·해외 매입 원본과 승인 보조 자료의 역할은 [카드 수집 문서](../docs/history/specs-20261110/finance.md#src-docs-card-downloads-md)를 따른다. 실제 비용 전기는 [현재 카드 파이프라인](../docs/history/specs-20261110/finance.md#src-docs-card-pipeline-md)의 미리보기·중복 방지 절차를 사용한다. 사용자 확정과 일정 근거는 [업무 규칙](../docs/history/specs-20261110/finance.md#src-docs-business-rules-md)을 따른다.

과거 48개 여행 목록과 2026-08-29 대사 보고서는 그 시점의 산출물이다. 현재 여행 40개와 권위 검증 상태, 장부 기록 수는 [운영 문서](../docs/operations.md)를 따른다. 과거 종료용 일정이나 카드 결제일을 새로운 OTA 이용기간으로 사용하지 않는다.
