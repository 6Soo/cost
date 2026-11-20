# Traveloka 이식 독립 검수 (2026-11-20)

- 검수자: Claude Code 자식 세션 `c1930a9e` (opencode / deepseek-v4.1-flash-free, high, 읽기 전용 plan 모드)
- 1차 검수자 `ebe9380f`(altare glm-5.3)는 제공자 크레딧 부족(402)으로 결과 없이 종료 → 교체
- 대상: `747329bb`(이식), `65de53b1`(Unicode 숫자), `f52eafc7`(중복 예약 ID), `d11a4b8b`(Nd 블록 테이블), `ddb937f6`(Nd 전수 가드)
- 구현자와 다른 모델·다른 세션. 수정·커밋·테스트 실행 없음(문서만).

## 1차 판정: REQUEST_CHANGES — 차단 3건

### B1. 예약 ID 중복을 집합이 아니라 등장 횟수로 셌다 (차단)

- 위치: Python `app/traveloka_mail.py:15`는 `set(...)`으로 중복을 합치고 `:24`의 `len(refs) != 1`로 판정한다. Rust `traveloka.rs`의 `booking_ids`는 매치마다 push해 중복을 남겼고, 게이트가 `references.len() != 1`이었다.
- 차이: 두 파서 모두 "제목 + 개행 + 본문"을 검색하므로, 같은 ID가 제목과 본문에 한 번씩 나오면 Python은 원소 1개, Rust는 2개를 본다.
- 재현 1(결제): subject `[Traveloka] 결제 완료, 항공권 발권 중 - 예약 ID 1234567890`, body `예약 ID: 1234567890 … 123,000원`. Python은 charge 123000 fact를 만든다. Rust는 fact가 None이 되어 **결제가 통째로 사라진다**.
- 재현 2(예약): 예약 ID가 제목·본문에 함께 있는 항공권 안내. Python은 period 2026-11-09 fact, Rust는 None.
- 차단 이유: ID를 제목과 본문에 함께 쓰는 것이 이 공급자 메일의 기본 형태이고 기존 Python 테스트가 그 형태를 고정한다. 배선되면 결제 누락으로 이어진다.
- 수정: `f52eafc7` — first-seen 순서로 중복 제거.

### B2. 숫자 변환이 ASCII 전용이라 유니코드 숫자 계약과 모순 (차단)

- 위치: `is_nd`가 `char::is_digit(10)`, `int_amount`/`read_digits`가 `to_digit(10)` 사용. 둘 다 ASCII만 인정한다.
- 재현 A(금액): `１２３４원`(전각) → Python charge 1234, Rust fact None(결제 소실).
- 재현 B(기간): `출발 항공편 20２６년 6월 1일` → Python 2026-06-01, Rust 연도 20으로 **0020-06-01**(조용한 오답).
- 차단 이유: 정규식은 Nd로 넓히고 변환만 ASCII로 남겨 계약을 어긴다. 결과가 fact 소실 또는 연도 오답이다.
- 수정: `65de53b1` — `\p{Nd}` 판정 + Nd 값 변환.

### B3. Nd 블록 역산이 인접 런을 구분하지 못한다 (차단, 2차 검수)

- 수학 산세리프 등 5개 런(`U+1D7CE`–`U+1D7FF`)이 빈틈없이 붙어 있어 `𝟢`(U+1D7E2)→20, `𝟫`(U+1D7EB)→29, `U+1D7D8`→10이 나왔다(실측).
- 재현: `𝟣𝟤𝟥원` → Python charge 123, Rust 2343. `𝟢원` → Python fact None, Rust charge 20.
- 수정: `d11a4b8b` — Python `unicodedata`에서 `digit()==0`인 Nd 코드포인트 76개를 뽑아 블록 시작 테이블로 두고 `code - block_start`.
- 재검증: Rust 테이블 76개가 Python Nd 시작 76개와 **완전 일치**를 별도로 대조했다. 테이블이 모든 Nd를 덮고 블록 내부 오염이 없음도 확인.

## 최종 판정: APPROVE (차단 0)

| 항목 | 결과 |
| --- | --- |
| B1 해결 | `booking_ids` first-seen 중복 제거. 골든 `id-in-subject-and-body`(charge 123000)·`reservation-id-in-subject-and-body`(reservation, 2026-11-09)와 Rust 손추적 일치 |
| B2 해결 | `to_digit` 제거. `fullwidth-amount` 1234, `mixed-width-year` 2026-06-01 일치 |
| B3 해결 | `ND_BLOCK_STARTS` + `iter().rev().find(|s| *s <= code)`. 수학 산세리프 사례가 Python 값(123 / None)과 일치 |
| 골든 | 28건, 모두 변경 없는 Python 파서에서 생성. 운영·고객 원문 0 |
| 추가 전용성 | 유지 — 스위치·Python 삭제·운영 경로·`extract_sources.py`·`commands.py`·CLI 무변경 |

## 비차단(기록만)

1. `is_python_word`가 `is_alphanumeric`이라 Other_Alphabetic 결합 표기(U+0345 등)를 Python `\w`보다 과수용할 수 있다. Python 표본(U+0345·U+05BF·U+093E)은 모두 `\w`가 아니고 `isalnum`도 아니므로 이 슬라이스에서는 발현 사례가 확인되지 않았다.
2. `is_nd`가 문자마다 `to_string()`+Regex 매치라 `int_amount`·`read_digits`·`starts_inside_number`에서 할당이 남는다. 성능만 해당.
3. `outbound_period`의 날짜 형식 폴백, i64 초과 금액의 조용한 거부, float·대정수 digest 미검증 — 조사 문서 §9의 잔여 항목이며 이 단위 범위 밖.
4. **유니코드 버전 일치 확인:** Python 3.14.7 `unicodedata` 16.0.0, `regex` 1.13.1 / regex-syntax 0.8.11도 Unicode 16.0.0. 따라서 테이블 누락 위험은 현재 없다. `ddb937f6`의 전수 가드가 크레이트 갱신 시 이를 잡는다.

## 확인하지 못한 것 (모른다)

- 운영 배선 단계의 공급자 혼합 해소 방식(브리지 내 공급자별 스위치 vs 조립 계층 이식).
- 실고객 메일 코퍼스에서의 재현율 — 검수는 합성 사례와 보호 기준의 사건 17건(금액 0건)만 확인했다.
