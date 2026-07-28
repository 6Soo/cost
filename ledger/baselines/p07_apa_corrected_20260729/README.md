# p07 기준선 — APA 합산청구 정정 반영 (2026-07-29)

`ledger/domain/ledger_db.py`의 `write_review_snapshot(db, output_dir, compare_to=p05_latest_20260725)`
로 생성했다. 이전 기준선과의 차이는 같은 폴더 `diff.json`에 있다.

## 왜 새 기준선을 만들었나

구 기준선 `p05_latest_20260725`는 **APA 누락 상태를 정답으로 고정**하고 있었다.
그 `0424_알펜루트` 값 **49,990,557**은 사용자가 인계서 §9.10에서
"사본에 APA HOTEL 3건 / 1,715,886원이 빠졌다"고 지적한 **49,990,561**과 같은 상태다.

따라서 구 기준선에 면제 규칙을 덧대 `unexplained_differences`를 0으로 만드는 것은
잘못된 상태를 영구화하는 선택이다. 구 기준선은 이력 보존을 위해 **삭제하지 않고** 남겨 두고
(불변규칙 9: 같은 이름으로 덮어쓰지 않는다) 새 버전을 회귀 기준으로 삼는다.

## 구 기준선 대비 차이 6건 (전건 규명 완료)

| 항목 | 이전 | 이후 | 차이 | 원인 |
|---|---:|---:|---:|---|
| `0417_아오모리` | 36,624,313 | 34,336,465 | −2,287,848 | APA 합산청구 정정(탭 이동) |
| `0424_알펜루트` | 49,990,557 | 51,706,443 | +1,715,886 | APA 합산청구 정정(+2,287,848 −571,962) |
| `취소환불` | 0 | −59,975 | −59,975 | 하나카드 취소 2건 `HAN-9111` −52,954 + `HAN-9112` −7,021 |
| `숙박비`(계정) | 175,096,484 | 175,101,272 | +4,788 | `resolve_hana_split_cancellations` 보정 **+636,725** + 데이터 변경 **−631,937** |
| `0625_아키타` | 20,178,248 | 20,197,003 | +18,755 | 구 분류기도 `intended_improvement`로 인정하던 항목 |
| `여행_미배정` | 2,734,540 | 3,352,510 | +617,970 | 구 분류기도 `legacy_error_correction_and_intended_improvement`로 인정하던 항목 |

### 숙박비 +4,788의 분해 (혼동 주의)

CSV(`classified_v14.csv`) 기준 숙박비 변화는 **−631,937**이다
(하나 취소 −59,975 + APA 정정 −571,962). 그런데 어댑터 집계는 +4,788로 나온다.
단계별 실측 결과 차이는 전부 `resolve_hana_split_cancellations` 한 단계에서 발생하며,
그 단계에서 숙박비가 정확히 **+636,725** 오른다(다른 계정·다른 단계는 불변):

```
CSV            임포트직후      하나분리후      p1~p5후
174,464,547   174,464,547   175,101,272   175,101,272
```

이는 버그가 아니라 하나카드 동일 RAW 행의 승인·취소를 분리 보존하는 기존 보정이다.
`regression_report`도 `hana_legacy_correction`이라는 이름으로 이 보정을 알고 있으나,
**보정분과 실제 데이터 변경이 섞인 차이**는 단순 등식 비교로 분류하지 못해 `v2_error`로
떨어뜨린다. 분류기의 한계이지 데이터 오류가 아니다.

## 재생성 방법

```python
from ledger.domain.ledger_db import (connect, initialize, import_legacy, LEDGER_DIR,
    DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS, apply_p1_confidence_rules,
    apply_p3_unassigned_review, apply_p4_provider_rules, apply_p5_quality_audit,
    resolve_hana_split_cancellations, write_review_snapshot)
from ledger.domain.direct_sources import import_all
# connect → initialize → import_legacy → resolve_hana_split_cancellations
# → apply_p1/p3/p4/p5 → import_all(manual_v4, ota_mail_index) → write_review_snapshot
```

새 기준선을 또 만들 때는 **반드시 새 디렉터리명**을 쓰고 `compare_to`로 직전 기준선을 지정해
`diff.json`을 남긴다. 차이가 하나라도 설명되지 않으면 기준선을 갱신하지 말고 원인을 먼저 밝힌다.
