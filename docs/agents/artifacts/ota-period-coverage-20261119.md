# 이용일 공백 분석 (2026-11-19)

대상: `board_rows` 3,378행 중 기간 없는 3,133행. 범위: **코드·설정·수집 경로 정적 분석만.** 운영 DB 읽기/쓰기 없음, 제품 코드 수정 없음. 운영 수치는 감독 제공만 인용.

## 결론

기간은 저장되는 사실이 아니라 **예약 증거에서 계산되는 값**이다. 카드 행은 `service_period=""`로 생성되고(`webapp/ledger_store.py:3340`,`:3694`), 값을 채우는 자동 경로는 사실상 하나다 — `card_flow.py:1304`가 `app/ota_mail.py:976 ledger_metadata`의 반환값을 payload에 넣는다.

`ledger_metadata`는 **booking_ref·service_period·ota_evidence를 한 번에** 돌려주고, 조건에 하나라도 어긋나면 셋 다 빈 값이다(`:978-1007`의 `return empty` 7지점). 따라서 "예약번호O·기간X = 0"과 "예약번호X·기간X = 635"(감독 실측, 숙박비 861)는 코드와 정확히 일치한다.

**즉 93%는 표시 문제도 백필 누락도 아니다. "어느 예약인지 시스템이 못 알아낸 카드 결제 635건" 하나다.**

## 코드로 확인된 결정적 단서

`config/ota-matching-defaults.json`의 `provider_merchant_aliases`는 9개 공급자(agoda·trip·klook·booking·gotogate·asiana·jeju·traveloka·skyticket)뿐이다. **airbnb·rakuten(라쿠텐)·forest(숲나들e)·mytrip이 없다.** 그런데 이 네 공급자의 **메일 파서는 이미 구현돼 있다**(`app/airbnb_mail.py`·`ota_rakuten_mail.py`·`forest_mail.py`·`mytrip_mail.py`). `_is_ota_row`(`card_flow.py:129-133`)가 `provider_for_merchant`로 게이트를 걸므로, 별칭에 없으면 `ledger_metadata`를 아예 호출하지 않는다. **기간 계산 능력은 있는데 명단 누락으로 게이트가 닫혀 있다.**

별칭 추가는 가맹점을 OTA로 인정하는 **소유자 정책 결정**이므로 규칙집 개정 절차가 필요하다.

## 감독 실측 정정 1건

"`ota_evidence_json` 있는 board_rows 0건" — `board_rows`에 **그 열이 없다.** `webapp/ledger_store_schema.py:9-15`의 열은 `row_id·row_kind·display_tab_id·revision·payload_json` 5개뿐이고 `ota_evidence`는 `payload_json` 안 키다. 정정 쿼리:

```sql
SELECT count(*) FROM board_rows WHERE json_extract(payload_json,'$.ota_evidence') IS NOT NULL;
```

## 사람이 기간을 입력할 수 있는가 — 아니오

- `CARD_EDITABLE = ("display_tab_id","item","description","operator_note")` (`webapp/ledger_store_change_validation.py:18`)에 `service_period` **없음**.
- `board_manual_overrides` INSERT 3곳(`ledger_store.py:792/3140/5368`)은 모두 `changes`의 필드 이름을 그대로 넣고, 그 `changes`는 `CARD_EDITABLE`로 검증되어 `service_period`가 거부된다(`:83`).
- **쓰는 곳 0곳.** 읽는 곳은 명시 6곳(`ai_classification.py:192`·`core_writer.py:86`·`ledger_design.py:913`·`ledger_stay_evidence.py:30`/`:1155`·`period_shadow.py:51`) + 일반 4곳 = 8곳 규모. 감독 지적과 일치.
- `read_period`(`ledger_stay_evidence.py:1158`)는 `row_id in manual`이면 빈 값도 "사람이 모른다고 함"으로 존중한다. 그 값을 만들 방법만 없다.

## 판정

| 판정 | 항목 | 근거 |
|---|---|---|
| **(가) 코드** | 별칭에 airbnb·rakuten·forest·mytrip 누락 | 파서 존재, 게이트 미개방. **정책 결정 필요** |
| (가) | `CARD_EDITABLE`에 `service_period` 없음 | 쓰기 0곳 |
| (가) | 라쿠텐 다중 기간 통째로 버림 | `ota_rakuten_mail.py:74` `len(periods)>1 → None` |
| (가) | 체크인/체크아웃 라벨 정확히 1개만 | `ota_mail.py:274` |
| (가) | 항공 형식 과좁음 | `ota_mail.py:196` `가는편:`/`오는편:`+`\|`+`YYYY년 M월 D일` |
| (가) | P2 모델명 하드코딩 `gpt-6.1-sol` | `ai_classification.py:203` |
| **(나) 자료** | 예약 메일 미수집 | `ota_mail.py:979-980` |
| (나) | 예약만 있고 결제 증빙 없음 | `ota_mail.py:1005-1007` digests |
| (나) | 렌터카 직접 예약증 | `ota_mail.py:210`,`:226` 두 형식만 |
| **(다) 원래 모름** | 분기 기타비용 525 | `period.rs:24` SERVICE_ITEMS 밖 |
| (다) | 식비·교통·주차 등 | `_is_ota_row` 거짓 |
| (다) | 사전승인·취소환불·현장결제 | `ledger_stay_evidence.py:1110` / `ledger_design.py:1018`,`:971` |

3,133 중 **약 2,000+는 (다)** — 고칠 필요 없는 행. 실제 문제는 **숙박 635 + 항공 87 + 렌터카 49**.

## 다음 단계 (모두 미확인, 운영 실측 필요)

1. **635건 가맹점 분포** — (가)/(나)/(다) 비율을 정하는 유일한 방법.
2. **22건(예약번호O·기간X) 정체** — 예약번호만 따로 쓰는 경로가 존재한다는 뜻. 기간만 채우는 해결책의 실마리.
3. 별칭 4개 추가 **검토** (정책 결정).
4. `CARD_EDITABLE`에 `service_period` 추가 (사람 안전망).

측정 SQL은 `.local-archive/ota-period-coverage-20261119/fixability.md` §R-A~R-E에 있다.

## 실행/미실행

**실행:** `app/`·`webapp/`·`tools/`·`core/crates/`·`config/` 정적 분석, `board_rows` 스키마 확인, `board_manual_overrides` 쓰기·읽기 전수 grep, 별칭-파서 교차 대조.
**미실행:** 운영 DB·`D:/WebLedgerHost` 접근 없음, 코드 수정 없음, 테스트 없음, 포트 미접촉, 실측 쿼리 실행 안 함.

전체 분석: `C:/AX/cost/.local-archive/ota-period-coverage-20261119/` (`write-paths.md`, `coverage-classes.md`, `fixability.md`, `RESULT.md`).
