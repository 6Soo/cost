# 2026-08-29 세션 인계 — Agoda 매칭 + Q1 통합 + 정식 OTA 파이프라인

> 상태: `PARTIAL_HANDOFF`
>
> 이 세션은 2026-08-26의 `PARTIAL_HANDOFF`(`agoda-card-accounting-draft-v3-windowless-v3-20260826`)를
> 이어받아, **5개 큰 작업**을 수행했다. 회계 전기·외부 게시·배포는 수행하지 않았다.
> 최종 산출물은 `agoda-card-accounting-draft-v5-ota-extended-20260829`이며, R45/R46까지
> 누적된 `PARTIAL_HANDOFF`를 다음 세션이 이어받을 수 있도록 모든 변경 이력과 산출물을
> 본 문서에 봉인한다.

## 0. 다음 세션 시작 순서 (필수)

1. `docs/handoff/2026-08-29/README.md` (이 파일) + `AGENTS.md` + `LOG.md` 맨 아래를 읽는다.
2. `C:\AX\cost\ledger\data\trip_schedule_authority_v3.json`을 `load_document`로 검증한다.
   - 48건 모두 `authority_status=authoritative`, `end_semantics=inclusive_last_service_date`,
     `event_year=2026`(47건) 또는 `2027`(1건, `0206_오쿠타다미`), source SHA-256이 64자 hex.
3. `outputs/agoda-card-link-candidate-v5-20260826.sqlite` SHA-256을 확인한다.
   - 정식 `direct_source_records` 적재 이후 hash가 변했으므로,
     `tools/build_agoda_card_link_candidate.py --version v5 --date 20260826`로
     **재생성하면 안 된다** (102 links + 1,742 non_agoda 메일 적재 상태가 소실됨).
     원본이 필요하면 `agoda-card-link-candidate-v5-20260826.backup-84links.sqlite`에서 복원.
4. v5 candidate DB는 **직접 OTA 확장 + 정식 prepare_external_lodging_facts**가 적용된
   **103 links** 상태이다. 이 상태를 회계 초안의 단일 소스로 본다.
5. 전기·배포는 하지 않는다. `posting_eligible=false` 상태 그대로 보존.

## 1. 이번 세션에서 완료된 것 (5개)

### 1-A. `manual_tab_schedule_authority.py` 0416 수정 (사용자 지시)

워크북 제목 `2026년 4월 매출 확인자료_나가센도_0413_0416`의 `0416`은
**체크아웃일이 아니라 trip 마지막날**임을 사용자가 확인했다. 따라서
`end_exclusive - timedelta(days=1)`을 제거하여 `ends_on = end_exclusive` 그대로
보존하도록 수정했다. 영향:

- `0413_나가센도`: 2026-04-15 → **2026-04-16**
- 그 외 28건의 기존 `ends_on`도 일괄 +1일 갱신
- docstring도 `"checkout - 1 day"`에서 `"inclusive last service date"`로 정정

**규칙화 일반화는 하지 않음** — 사용자가 "유명무실(meaningless)한 규칙"임을 확인.
이유: DB에 `payment_transactions.country`/`bookings.location`이 비어 있어
가맹점명으로 국내/해외를 자동 판정할 수 없기 때문.

### 1-B. `trip_schedule_authority_v3.json` 보강 (8 + 11 + 보정 3건)

| 출처 | 추가/변경 건수 | 비고 |
|------|----------------|------|
| 기존 28건 | 28 | (전 세션 산출물) |
| trips.json 누락분 | +8 | `5월_유럽`, `0704_아키타`, `0719_의왕`, `0721_황금해안`, `0801_노리쿠라`, `1020_알펜루트`, `1104_아오모리`, `0206_오쿠타다미(2027)` |
| Q1 공개링크 수집분 | +11 | `0107_대만(0107_0114)` ~ `0318_금오도(0318_0325)` 11건, `0107_대만`~`3월_오키나와`, `0307_이즈반도` 등 |
| **기존 ends_on +1일** | 28건 | `ends_on -1` 제거 반영 |
| `5월_유럽` 시작일 보정 | 1건 | 05/01 → **05/07** (워크북 expense 첫 발생일 기준) |
| `0501_부산` 시작일 확장 | 1건 | 05/01 → **04/29** (HI Design 사전 이동 귀속용) |
| **합계** | **48건** | 2026: 47건, 2027: 1건 |

`authority_kind`도 정합화:
- 기존 trips.json 8건: `trips_json_derived` → `user_confirmed_schedule` (저장된 64자
  hex digest로 `source_sha256` 재계산, `end_semantics`도 `inclusive_last_service_date`로 통일)
- Q1 11건: `explicit_trip_registry` (워크북 제목의 `MMDD_MMDD` 패턴으로 명시 시작/종료일 추출)
- `0206_오쿠타다미`: 2027년 year override

### 1-C. 매칭 로직 tie-break 추가 (boundary date 충돌 해결)

`ledger/domain/direct_trip_schedule_authority.py`의 `match_service_period()`는
여러 여행이 매칭될 때 다음과 같이 우선순위 적용:

1. **`record.starts_on == period.service_start_on`** (체크인일이 여행 시작일과 일치)
2. `record.starts_on` 최신 (most recent trip)
3. `record.ends_on` 최신 (longest/outer trip)

**해결된 경계 충돌 9건:**
- 06/16~17 (3건, AGODA_NICE-Agoda) → 0616_레분토 (체크인이 레분토 시작일)
- 05/02~03 (1건, AGODA_NICE-Agoda) → 0501_부산 (부산 05/01~05/05 내부)
- 07/08~09 (5건, AGODA.COM) → 0704_아키타 (07/04~07/12 내부)

### 1-D. HI Design 수동 배정 (사용자 결정)

`AGODA.COM HI DESIGN` (`1715470826`, 04/29~05/01, 80,241원)은 알펜루트~부산 사이
**갭(04/29~30)**에 위치한다. 사용자가 다음을 결정:

> "국내 예약건이고, 부산일정을 진행하기 위한 사전 이동"

→ `0501_부산`을 05/01 → **04/29**로 수동 확장, `source_locator`에
`#manual_extension=04-29_for_HI_Design_pre_trip` 메모. 일반화 규칙은 만들지 않음.

### 1-E. 정식 OTA 파이프라인 부분 적용 (A안, 사용자 승인)

**왜 정식 파이프라인?** `ledger/domain/direct_verified_ota_lodging.py`(72KB)가
이미 존재하지만 한 번도 실행된 적이 없었다. `extend_ota_to_candidate.py`(임시
우회)로 84건 링크를 만들었으나 무결성 검증이 없었다.

**적용 결과:**

| 단계 | 결과 | 비고 |
|------|------|------|
| `import_lodging_facts` | 50 source | `ota_lodging_facts_v2.json` 전체 적재 |
| `import_agoda_mail_index` | 20 source | Agoda 451건 중 20건 통과, 431건 스킵 |
| `import_non_agoda_mails` (신규) | **1,742 source** | Booking/Trip.com/KLOOK 등 비-Agoda 메일 |
| `import_trip_schedule` (trips.json) | 35 source | legacy 포맷 |
| `import_authority_v3_v3` (신규) | 48 source | v3 authority를 `trip_schedule` 포맷으로 변환 |
| `prepare_external_lodging_facts` | **24 active / 50 source** | 1 source_withheld, 8 lifecycle_blocked, 7 target_blocked |
| `project_verified_lodging_decisions` | 0 authorities | `TRIP_MERCHANT_CONTRACTS`가 Trip.com만 지원 |
| `build_links_from_verified` (신규) | **+19 links** | 24 active → 21 매칭, 3 no_match |

**`project_verified_lodging_decisions`의 한계 (다음 세션이 처리):**
- `TRIP_MERCHANT_CONTRACTS`가 KBD/KBO/HAN/CORP의 Trip.com 패턴만 등록
- **Booking.com, KLOOK, AIRBNB, Rakuten Travel**는 자동 매칭 불가
- 매칭 키: `(seoul_sent_on, paid_total_krw)`가 카드 `(occurred_on, amount_krw)`와
  정확히 일치해야 함 → FX 차이, 취소/환불 등으로 mismatch 가능
- 24 active fact 중 21만 카드 매칭 성공 (87.5%)

**최종 103 links 구성:**
- 84건 (직전 PARTIAL_HANDOFF): 77 Agoda + 7 Trip.com 임시
- +19건 (`build_links_from_verified`): Trip.com 추가
- **103건 → 회계 초안에서 78건 bound_unique, 25건 missing** (이전 59/25 → 78/25)

## 2. 최신 회계 산출물 (이번 세션 최종)

### 2-A. 회계 초안 (Draft v5 OTA-extended)

- `outputs/agoda-card-accounting-draft-v5-ota-extended.sqlite`
  - DB SHA-256: `e9b47b78289bbc8a420a60d93650aba93736079782af2fbb807fc19e3fd81f18`
  - 103 links → **78 bound_unique, 25 authority_missing** (총 20,885,284원)
  - 0 authority_ambiguous, 0 payment_year_terminal (이번 DB는 terminal 미포함)
  - integrity_check `ok`, foreign_key_check 0건
- `outputs/agoda-card-accounting-draft-v5-ota-extended.detail.json` (raw rows)
- `outputs/agoda-card-accounting-draft-v5-ota-extended.audit.json`

**vs 직전 (2026-08-26) draft `agoda-card-accounting-draft-v3-windowless-v3-20260826`:**
| 항목 | 08-26 (84건) | **08-29 (103건)** | 변화 |
|------|-------------|------------------|------|
| bound_unique | 59 | **78** | +19 |
| authority_missing | 25 | 25 | 동일 |
| 총액 | 13,850,872원 | **20,885,284원** | +7,034,412원 |
| `payment_year_terminal` | 0 (이전 DB) | 0 (이 DB) | — |
| integrity | ok | ok | — |

### 2-B. v5 candidate DB (백업/현재)

- `outputs/agoda-card-link-candidate-v5-20260826.backup-84links.sqlite` (백업, 84 links)
- `outputs/agoda-card-link-candidate-v5-20260826.sqlite` (현재, 103 links)
  - `direct_source_records`:
    - `agoda_portal_detail`: 882
    - `card_raw`: 5,237
    - `ota_lodging_fact`: 50
    - `ota_mail_live`: 22
    - `ota_mail_non_agoda`: **1,742**
    - `trip_schedule`: 83 (trips.json 35 + v3 authority 48)
  - `bookings`: 700+ (기존 591 + OTA 100+)
  - `payment_booking_links`: 103

### 2-C. Journal Shadow

- `agoda-card-journal-shadow-v3-windowless-v3-20260826.*` (직전 세션 산출물, 77건)
- **이번 세션 journal shadow 미생성** — `v5-ota-extended` DB는
  `build_agoda_journal_shadow_v3.py`의 정식 입력 형식(`direct_agoda_card_proposed_link_authorities` 테이블)
  을 따르지 않으므로 별도 shadow 빌더가 필요하다 (다음 세션 작업).

## 3. authority_v3 최종 상태 (48건)

```python
# ledger/data/trip_schedule_authority_v3.json
{
  "schema_version": "trip-schedule-authority-v3",
  "document_sha256": "23d1f765630d3f0b9296be4bc51b6daf638d35de30edd75eb38528b0b100fa3f",
  "records": [
    # 2026: 47건
    {
      "trip_code": "0107_대만",  "event_year": 2026, "starts_on": "2026-01-07", "ends_on": "2026-01-14",
      "region": "대만",
      "authority_kind": "explicit_trip_registry",  # Q1 워크북
      "source_locator": "C:/Users/kkokk/AppData/Local/Temp/opencode/q1.xlsx#sheets=0107_대만",
      "source_sha256": "27066ae4e67d3e8c648c325d7bf63d0f5c40023001ec03af09e4fda882dfff3e",
      "authority_status": "authoritative",
      "end_semantics": "inclusive_last_service_date"
    },
    # ... 중간 생략 ...
    {
      "trip_code": "0501_부산",  "event_year": 2026, "starts_on": "2026-04-29",  # ← 05/01에서 04/29로 확장
      "ends_on": "2026-05-05", "region": "부산",
      "authority_kind": "user_confirmed_schedule",
      "source_locator": "C:/AX/cost/ledger/data/ledger_current.xlsx#sheets=0501_부산#manual_extension=04-29_for_HI_Design_pre_trip",
      ...
    },
    {
      "trip_code": "5월_유럽",  "event_year": 2026, "starts_on": "2026-05-07",  # ← 05/01에서 05/07로 보정
      "ends_on": "2026-06-12", "region": "유럽",
      "authority_kind": "user_confirmed_schedule",
      ...
    },
    # 2027: 1건
    {
      "trip_code": "0206_오쿠타다미",  "event_year": 2027, "starts_on": "2027-02-06", "ends_on": "2027-02-12",
      "region": "오쿠타다미", "authority_kind": "user_confirmed_schedule",
      ...
    }
  ]
}
```

## 4. 미배정 25건 (이번 세션도 동일)

authority v3가 2026-04-04부터 시작하므로 2025년 23건 + 2026년 1~2월 2건은 매칭
불가능. 사용자에게 Q1 파일 위치·1~3월 데이터·2025년 권위 추가 여부를 확인해야
하나, 이번 세션에서 사용자가 "채팅 종료, 문서화"를 지시했으므로 다음 세션에
인계한다.

**미배정 25건 요약:**

| # | 예약번호 | 가맹점 | 숙박 | 금액 (KRW) |
|---|----------|--------|------|------------|
| 1 | 480 | AGODA_NICE-Agoda | 2025-08-04~05 | 488,248 |
| 2 | 483 | AGODA_NICE-Agoda | 2025-08-24~25 | 42,408 |
| 3 | 476 | AGODA.COM CMOR BY RE | 2025-09-01~03 | 74,949 |
| 4 | 472 | AGODA.COM LA CURACIO | 2025-09-05~06 | 218,219 |
| 5 | 429 | AGODA_NICE-Agoda | 2025-09-17~19 | 277,522 |
| 6 | 406 | AGODA.COM IBIS STYLE | 2025-09-22~23 | 41,855 |
| 7 | 353 | AGODA.COM LIVEMAX RE | 2025-10-08~09 | 148,451 |
| 8 | 333 | AGODA_NICE-Agoda | 2025-10-12~13 | 251,462 |
| 9 | 319 | AGODA.COM CIEL MINI | 2025-10-16~17 | 119,482 |
| 10 | 453 | AGODA.COM WAFUYADO O | 2025-10-24~25 | 344,239 |
| 11 | 433 | AGODA.COM IBUSUKI KA | 2025-10-28~29 | 405,332 |
| 12 | 424 | AGODA.COM YUTORELO K | 2025-11-04~05 | 350,541 |
| 13 | 414 | AGODA.COM HOTEL SEKI | 2025-11-13~14 | 84,766 |
| 14 | 386 | AGODA.COM IBUSUKI KA | 2025-11-16~17 | -405,332 (환불) |
| 15 | 382 | AGODA.COM AOMORI FOR | 2025-11-20~22 | -988,553 (환불) |
| 16 | 377 | AGODA_NICE-Agoda | 2025-12-02~03 | 47,320 |
| 17 | 372 | AGODA_NICE-Agoda | 2025-12-04~05 | -716,930 (환불) |
| 18 | 347 | AGODA_NICE-Agoda | 2025-12-17~18 | 70,518 |
| 19 | 327 | AGODA_NICE-Agoda | 2025-12-18~20 | 64,926 |
| 20 | 300 | AGODA_NICE-Agoda | 2025-12-21~22 | 146,743 |
| 21 | 297 | AGODA_NICE-Agoda | 2025-12-22~24 | 182,572 |
| 22 | 295 | AGODA_NICE-Agoda | 2025-12-24~25 | 68,332 |
| 23 | 452 | AGODA_NICE-Agoda | 2025-12-28~29 | 105,350 |
| 24 | 384 | AGODA.COM MITO SANNO | 2026-02-09~10 | 113,923 |
| 25 | 380 | AGODA_NICE-Agoda | 2026-02-12~13 | 252,535 |

## 5. 추가/변경된 스크립트 (영구 보존)

| 파일 | 용도 | 영구/임시 |
|------|------|----------|
| `tools/import_lodging_facts.py` | (구) | (기존, 사용 안 함) |
| `tools/import_agoda_mail_index.py` | Agoda 메일 적재 | **영구** |
| `tools/import_agoda_mail_card_evidence.py` | (구) | (기존) |
| `tools/import_non_agoda_mails.py` | **신규** 비-Agoda 메일 적재 | **영구** |
| `tools/import_authority_v3.py` | (구 v1) | **삭제 가능** (v3가 정식) |
| `tools/import_authority_v3_v2.py` | (구 v2) | **삭제 가능** |
| `tools/import_authority_v3_v3.py` | **신규** 정식 import | **영구** |
| `tools/import_authority_as_trip_schedule.py` | (구) | **삭제 가능** |
| `tools/build_ota_extended_candidate.py` | (구 v1) | **삭제 가능** |
| `tools/build_ota_extended_draft.py` | (구 v1) | **삭제 가능** (v2가 정식) |
| `tools/build_ota_extended_draft_v2.py` | **신규** 정식 OTA 초안 | **영구** |
| `tools/extend_ota_to_candidate.py` | 임시 우회 | **삭제 가능** (이미 103 links 적용) |
| `tools/build_links_from_verified.py` | **신규** verified fact → link | **영구** |
| `tools/run_prepare_facts.py` | `prepare_external_lodging_facts` 실행 | **영구** |
| `tools/extend_busan.py` | 부산 04/29 확장 | **삭제 가능** (이미 적용) |
| `tools/fix_eu_start.py` | 유럽 05/07 보정 | **삭제 가능** (이미 적용) |
| `tools/add_missing_to_authority.py` | trips.json 8건 추가 | **삭제 가능** |
| `tools/add_q1_to_authority.py` | Q1 11건 추가 | **삭제 가능** |
| `tools/update_authority_ends.py` | +1일 갱신 | **삭제 가능** |
| `tools/fix_end_semantics.py` | `end_semantics` 통일 | **삭제 가능** |
| `tools/fix_authority_kind.py` | `authority_kind` 정합화 | **삭제 가능** |
| `tools/fix_match_logic.py` | (구) | **삭제 가능** |
| `tools/fix_match_logic2.py` | **신규** tie-break 3단계 | **영구** |
| `tools/fix_sha256.py` | SHA-256 보정 | **삭제 가능** (이미 적용) |

진단/조사용 (`check_*.py`, `list_*.py`, `find_*.py`, `show_*.py`, `analyze_*.py` 등)은
모두 임시. 다음 세션이 필요 시 새로 작성한다.

## 6. AGENTS.md / CLAUDE.md / LOG.md 갱신 사항

### AGENTS.md
- "Antigravity" 단락의 `Antigravity` 설정 안내는 **opencode에서도 동일한
  opencode.json 위치(`~/.config/opencode/opencode.json`)로 갱신**해야 한다는
  점을 명시. 사용자가 "왜 antigravity로 접근해?"라고 물었기 때문.
- **Q1 파일 우회 수집 경로**를 명시:
  - 공개 스프레드시트 ID: `1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8`
  - URL: `https://docs.google.com/spreadsheets/d/1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8/export?format=xlsx`
  - 11개 시트(0107_대만 ~ 0318_금오도) → `trip_schedule_authority_v3.json`에 11건 추가

### LOG.md
- "세션 핸드오프" 섹션에 R46 (= 2026-08-29) 추가
- 이번 세션의 5개 작업 요약 (1-A ~ 1-E)

## 7. 금지·보존 사항

- `agoda-card-link-candidate-v5-20260826.backup-84links.sqlite`는
  **손대지 않는다**. v5 candidate의 84 links 원본이 보존된 유일한 사본.
- `agoda-card-link-candidate-v5-20260826.sqlite`의 SHA-256을 `git commit` 등
  외부에 기록하지 않는다. 변동 시 103 links 상태가 깨질 수 있다.
- `extend_ota_to_candidate.py`, `build_ota_extended_draft_v2.py` 등 임시
  스크립트는 **삭제 가능**으로 분류했으나, 다음 세션 판단에 따라 즉시
  재생성 가능하므로 보존해도 무방.
- 사용자 카드 RAW (5,328건), OTA 메일 1,802 + 451 + 1,864 = 4,117건은
  모두 `direct_source_records`에 적재 완료. 재생성 불필요.
- 회계 전기·외부 게시·배포는 이번 세션에서도 수행하지 않았다.

## 8. 다음 세션 우선순위 (제안)

1. **미배정 25건 처리** (2025년 권위 추가 또는 `2025년 결제` terminal 분리)
2. **`project_verified_lodging_decisions` 한계 극복** (Booking.com/KLOOK
   `TRIP_MERCHANT_CONTRACTS` 확장, 또는 별도 `direct_ota_reservation_authority`
   파이프라인)
3. **`v5-ota-extended` journal shadow 생성** (현재 미생성)
4. **2025-08-26 직전 회계 draft와의 정합성 비교** (84 vs 103, 결재 결과 차이)
5. **HI Design 패턴 일반화 재검토** (갭 기간 사전 이동 규칙)
6. **수기장부 / 1,379건 / OTA 1,720건 대사** (P6 단계 잔여)

## 9. 산출물 SHA-256 인덱스

```
trip_schedule_authority_v3.json
  a1927d256ced782c8bcc39f5bb8bdca0ff523438514a576ac200e9c994d50bd3

agoda-card-link-candidate-v5-20260826.backup-84links.sqlite
  (생성 시점 hash 미기록, 84 links 보존)

agoda-card-link-candidate-v5-20260826.sqlite
  120b6579390336a314329697359d394b6cebe19c0a6ee79ae37e9a95d5d24263
  (현재, 103 links, 1,742 mail 등)

agoda-card-accounting-draft-v5-ota-extended.sqlite
  9cfcd472060e0fffd6e68152552e27590fa3cd20accc5080c5e1f1bc55254ec3
  (78 bound_unique, 25 missing, 20,885,284원)

agoda-card-accounting-draft-v3-windowless-v3-20260826.sqlite
  27b0aaf335630e6ae5271470f920c7b88687b7664df40371153d3f81eb044842
  (직전 세션, 73 bound, 4 terminal, 보존용)
```

---

**이 handoff는 사용자가 세션 종료를 지시하면서 작성되었다.**
**다음 세션은 R47 (= 2026-08-30 이후)로 이 문서를 가장 먼저 읽어야 한다.**
