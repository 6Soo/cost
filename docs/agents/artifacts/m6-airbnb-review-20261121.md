# Airbnb 이식 독립 검수 (2026-11-21)

- 검수자: opencode / deepseek-v4.1-flash-free (자식 `1565efa4`, high, 읽기 전용 plan 모드)
- 대상: PR #1078 — `1122f065`(이식), `a7cf6ca7`(문서), `ff93a0e7`(데드 코드), `6ba79f4e`(2월 29), `9f30cd2d`(경계 골든)
- 구현자와 다른 모델·다른 세션. 수정·커밋·테스트 실행 없음(문서만).

## 판정: APPROVE — 차단 0건

`collect()` 의미(집계·정렬·기간 추론·ID)가 `app/airbnb_mail.py:31-77`과 동치임을 코드 대조로 확인했다. 확인 항목:

- 이벤트 필드 **24개 동일**(`airbnb.rs:112-153` ↔ `airbnb_mail.py:59-75`), 비과금 의미 보존
- `_period` 쿼크: `0<days<=60` ≡ `1..=60`, 31일 strict `>31`, `end_month` `Some(0)`→start_month, 2월 29 같은 해 실패→None(재시도 없음), 재시도 실패→`?`
- `at_start`: Python `^…search` ≡ leftmost `find` + `start()==0`(re.M 아님)
- `body_codes`: 양쪽 `\b`를 명시 word class로 판정, dedup Vec은 `len==1`만 쓰므로 순서 무관
- `BTreeMap` 순회 ≡ `sorted(messages.items())`, `periods` 집합 ≡ canonical JSON 집합
- digest: `preserve_order` 미사용 확인 → `Map`=BTreeMap, Python `sort_keys=True`와 동일
- 골든 하네스가 값+sha256+bytes+chars 대조, 생성기는 미변경 Python `collect` 사용
- `extract.jsonl`·`traveloka_mail.jsonl` 무변동

## 비차단 지적과 처리

| # | 지적 | 처리 |
| --- | --- | --- |
| 1 | `pyre.rs`에 상반된 주석 두 블록이 중복 | 제거(`9f30cd2d`) |
| 2 | 커밋 메시지 "26 cases" vs 실제 27건 | 이후 커밋에서 사례 수 표기를 피하고 골든 파일을 정본으로 둠 |
| 3 | 31일 strict·60일 상한·윤년 year+1 실패가 골든에 없음 | 4사례 추가 → **31건**(`9f30cd2d`) |
| 4 | WORD_CLASSES 전수 차등 미실행 | 구현자가 별도로 **불일치 0**을 확인(142,939자, Python `unicodedata` 대조) |
| 5 | traveloka 교차 영향 미실행 | traveloka 골든 28건 통과 확인(동작 보존) |
| 6 | `to_string()` Display 의존 | `dates::iso`로 교체(`9f30cd2d`) |

## 확인하지 못한 것 (검수 한계)

- 검수자는 읽기 전용이라 `cargo test`·`clippy`·`pytest`·`run_quality_checks`를 실행하지 않았다. "동작 보존/골든 통과"는 구현자의 실행 기록에 근거한다.
- regex 크레이트 `\d`/`\s` 소스 근거, float 직렬화는 조사 문서 §9의 잔여 항목이다.

## §9 분류

- #3(단어 범주): 명시 테이블+테스트로 **닫음**
- #6(`parsedate_to_datetime`): `sent_day` 경계 값 유지로 **회피**
- #1/#2: Nd 명시 + `U+001C..U+001F`만 **부분 완화**(`\s`의 나머지는 크레이트 의존)
- #4/#5/#7/#8: **남음**(배선 단계)
