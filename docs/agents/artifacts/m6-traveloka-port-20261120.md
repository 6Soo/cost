# M6 Traveloka 메일 파서 Rust 이식 조사 (2026-11-20)

- 위임: Cost Codex V4 읽기 전용 조사. 코드 수정·커밋·push·테스트 실행 없음. 이 문서가 유일한 산출물이다.
- 방법: `graphify query` 우선 탐색(graphify-out/graph.json 존재) 후 결과 위치의 원본만 판독. 줄 번호는 grep으로 확정.
- 기준: 브랜치 `work/m6-extractor-reapply`, 조사 시점 HEAD `7b6c418b`. 퇴역 계획 [m6-extractor-retirement.md](../../playbooks/m6-extractor-retirement.md) 3단계 (b) 첫 단위.
- 현재 상태: 새 추출 기준 `7,965건 · SHA-256 3c6c46f5…` 소유자 결정 확정, PR #1072 재적용 완료, 다음 단위가 Traveloka ([session_handoff.md](../../session_handoff.md) 2026-11-20 (2)).

## 0. 판정

**조건부 이식 가능.** 파서 본문(`app/traveloka_mail.py`, 52줄)은 Rust로 완전히 옮길 수 있다. 다만 난이도는 파서가 아니라 함께 옮겨야 하는 헬퍼 3종(`authenticated_headers`·`body_text`·Cf 제거)에 집중되며, `parseaddr`·`html.unescape`의 Rust 동등성 검증이 선행 조건이다. 정규식 동등성은 기존 `regex` 크레이트 + 후처리 헬퍼로 새 의존 없이 달성 가능하다(룩비하인드·룩어헤드·역참조는 후처리/분리로 등가 변환). `source_sha256`은 기존 `digest.rs`를 재사용한다. `airline_payment_mail`이 traveloka를 직접 호출하므로 Python 모듈은 airline 이식까지 유지해야 하며, 이 단위는 추가 전용(additive) PR이어야 한다.

## 1. 파서 계약 (app/traveloka_mail.py)

### references() — traveloka_mail.py:10-15
- 입력: message dict(Gmail 저장 형식). 출력: `set[str]` — 예약 ID(숫자 6~20자리) 집합.
- `ota_mail.authenticated_headers(message, ('traveloka.com',))` 통과 못 하면 빈 집합 (L11-13).
- 검색 텍스트 = `subject + '\n' + ota_mail.message_text(message)` (L14). **Cf 제거 없음 — 원문 그대로.**
- 정규식 L15: `(?:예약\s*ID|Booking\s*ID)\s*[:：]?\s*(\d{6,20})\b`, `re.I`.

### extract() — traveloka_mail.py:18-52
- 입력: message dict. 출력: fact dict 또는 `None`.
- 인증 게이트 L19-21 → subject 원문 L22 → **본문만** Cf 제거 L23: `message_text(message).translate(ota_mail._format_char_table())`.
- L24-26: `refs = references(message)`; `len(refs) != 1`이거나 subject에 `항공권|e-ticket|flight`(re.I, L25) 없으면 None.
- L28 cancelled: subject `취소|환불|cancel|refund`(re.I). L29 completed: subject `결제\s*완료|payment\s*(?:complete|successful)`(re.I). **둘 다 원문 subject 대상.**
- L30 amounts: Cf 제거 본문에서 `(?<![\d,])((?:\d+|[1-9]\d{0,2}(?:,\d{3})+))\s*원\b` findall의 **문자열 집합**.
- L31: `completed and not cancelled and len(amounts)==1`일 때만 `int(next(iter(amounts)).replace(',',''))`. uniqueness는 정수가 아니라 캡처 문자열 기준("1,230"과 "1230"은 다른 원소).
- L32-33: `amount <= 0`이면 fact 전체 None(예약 fact도 아님).
- L35-45 period: `출발\s*항공편(.+?)(?:귀국\s*항공편|오는편|승객|$)`(re.S) 구간에서 `20\d{2}년…월…일`(L37) 또는 역순 `(\d{1,2})\s+(\d{1,2})월\s+(20\d{2})`(L38, 튜플 reverse) → `date(*map(int,parts))` 검증, ValueError면 period None.
- L46-52 fact 필드: `provider='traveloka'`, `booking_ref=next(iter(refs))`, `item='항공료'`, `paid_amount_krw=amount`, `paid_on=None`, `paid_on_semantics='missing'`, `period`, `reserved_dates=[]`, `reservation_status='observed'`, `evidence_status` = cancelled→`evidence_conflict` / amount→`paid_verified` / else→`reservation_observed`, `event_type` = amount→`charge` else→`reservation`, `source_sha256`.
- **source_sha256 (L51-52):** `sha256(json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode())` — message 전체의 canonical compact JSON. `default=str` 없음(ota_payments._digest L42-44와 다름).
- 결정성: `next(iter(set))`은 len==1 보장 하에서만 호출(L31, L46) → 해시 무작위화 영향 없음.
- 비대칭 요약: **Cf 제거는 extract의 본문(L23)에만 적용. references(L14)과 subject 정규식(L25·28·29)은 원문 대상.** 이식이 이 비대칭을 보존해야 한다.
- `reserved_dates`는 fact에만 있고 사건 조립층이 복사하지 않는다(ota_payments.py:165-208 event dict에 없음).

## 2. 헬퍼 분류표

| 헬퍼 | 위치 | 판정 | 근거·리스크 |
| --- | --- | --- | --- |
| `authenticated_headers` | ota_mail.py:177-193 | **이식 가능(중)** | L178 헤더 키 소문자화, L179 `email.utils.parseaddr`로 From 도메인 추출, L181 정확 일치 또는 `.endswith('.'+base)` 경계(traveloka.com.example 거부), L185 `owner_collected is True`(엄격 항등, truthy 아님)면 DKIM 면제, L187 `dkim=pass\s+([^;]+)`(re.I), L189 `header\.(?:i=@|d=)([a-z0-9.-]+)(?=\s|$)`(re.I, **룩어헤드**). 리스크: parseaddr의 기형 주소 엣지 동등성(모른다, §9), 룩어헤드는 후처리 변환 필요. 8종 파서 공용이므로 한 번 이식하면 후속 단위가 재사용. |
| `message_text` | ota_mail.py:41-46 | **이식 가능(하)** | `_BODY_TEXT` 메모는 로드 시 최적화일 뿐 값은 항상 `body_text(payload)`와 동일: 로드 경로가 `text=body_text(payload)`로 계산해 저장(ota_mail.py:148, 161, 168), 메모 미적재 시 폴백도 `body_text`(L46). Rust는 payload에서 직접 계산하면 등가. |
| `body_text` | ota_mail.py:349-359 | **이식 가능(중)** | L352-354 base64url 디코드(`+'='*(-len%4)` 패딩) + `utf-8','replace'`(손실 디코드), L356 HTML 주석 제거(re.S), L357 `<(script|style)\b[^>]*>.*?</\1>`(re.I\|re.S, **역참조** → script/style 별도 정규식 2개로 분리하면 등가), L358 태그→`\n` + `html.unescape`, L359 parts 재귀 + `'\n'` 결합(출력은 항상 `\n'`으로 끝남). 리스크: `html.unescape`는 HTML5 엔티티 테이블(세미콜론 없는 레거시 엔티티 포함) — Rust 동등 크레이트 미확인(모른다, §9). |
| `_format_char_table` | ota_mail.py:391-396 | **이식 가능(하)** | L395 `range(0x110000)` 중 `unicodedata.category == 'Cf'` 제거 테이블. Rust는 `\p{Cf}` 전체 치환으로 등가(regex 크레이트가 general category 지원). 리스크: Python unicodedata의 Unicode 버전(빌드 의존)과 regex-syntax 테이블 버전 간 Cf 집합 드리프트(모른다, §9) — Cf 문자 포함 차등 골든으로 고정. |
| `_extract_signed_payment_message` | **ota_payments.py:286-427** | **보류 — traveloka 의존 아님** | 위임 문구는 ota_mail 헬퍼로 적었으나 실제 소속은 `ota_payments.py`다. traveloka_mail.py는 이 함수를 호출하지 않는다(파일 전체 판독: ota_mail 헬퍼 3종만 사용). 호출자는 `extract_payment_fact`(ota_payments.py:216-229)의 richer/fallback 경로. `decimal_amount`·`service_period`·`sent_day`·`scheduled_charge_day`·`payment_failed` 등 대형 의존 트리를 가져 퇴역 계획 3단계 (e) 메일 핵심 단위 소속이다. |

## 3. Rust 현재 구조와 mail_events 생산 경로

**파서는 Python 브리지에 남는 구조가 맞다.** 생산 사슬(전부 file:line 확인):

1. `costcore extract --ota-evidence …` → core/crates/cli/src/main.rs:188 디스패치 → cli/src/extract.rs:9 `run()`.
2. cli/src/extract.rs:39 `python_bridge(&flags).extract_sources(...)` → core/crates/core/src/bridge.rs:88-90이 Python 브리지 명령 `"extract-sources"` 호출.
3. tools/core_bridge/commands.py:289 `'extract-sources': extract_sources` 매핑 → tools/core_bridge/extract_sources.py:65 `capture()`(OTA_EVIDENCE_REQUIRED·DB_IS_LIVE 보호) → :24 `collect()`.
4. extract_sources.py:53 `'mail_events': op._mail_events(...)` → app/ota_payments.py:57-72 `_mail_events`(메모+deepcopy) → :109 `_parse_mail_events`.
5. `_parse_mail_events` 내부: :123 `payment_facts()`가 메시지별로 jeju_payment_facts(:126) 우선, 없으면 `extract_payment_fact`(:128) → :216-229 `extract_payment_fact`가 `ota_mail.extract_mail` → richer → **`airline_payment_mail.extract` fallback** → airline_payment_mail.py:75-78이 **`traveloka_mail.extract`에 먼저 위임**.
6. fact→사건 조립은 별도 계층: ota_payments.py:165-208(event dict, source_lineage_ids :199, observation_ids :200, ota_event_id :204, `ota_mail_reservation_identity.attest` :208). **이식 단위인 traveloka 파서는 fact 계층까지이고, 조립 계층은 이번 단위의 대상이 아니다.**
7. 완성된 사건 배열이 `SourceStages`로 Rust에 전달: core/crates/core/src/extract.rs:55-64(`mail_events: Vec<Value>` — 이미 완성된 사건), :66 `build_ota_payment_events`는 산림 기간 보강·병합·정렬만 수행. 하위 모듈: extract/forest.rs(130줄, attach_periods), extract/merge.rs(203줄, conflict/combine/merge), extract/decimal.rs(62줄, 문자열 계수 Decimal — f64 없음). canonical 바이트: extract.rs:141 `baseline_bytes`, 쓰기 :189 `write_baseline`(배타 생성, 건수·해시만 반환).
8. 경계에서 Python 의미를 미리 계산해 넘기는 선례가 이미 있다: extract_sources.py:15-21 `forest_name_keys` — 주석 "Keep Python's exact Unicode word/casefold semantics while source parsing is bridged"(:16).

## 4. 정규식 동등성 — 8개 (위임 문구의 "6개" 정정)

traveloka_mail.py의 정규식은 **8개**다: L15, L25, L28, L29, L30, L35, L37, L38. Rust는 `regex` 1.13.1(core/Cargo.lock:321-323, core/Cargo.toml `regex = "1"`). 기존 사용례: `LazyLock<Regex>` 패턴(core/crates/core/src/links/ota/rule_scope.rs:36-37).

| # | 위치 | 패턴(요약) | flags | 동등성 쟁점과 변환 |
| --- | --- | --- | --- | --- |
| 1 | L15 | 예약/Booking ID `(\d{6,20})\b` | re.I | `\d` 유니코드 Nd, `\s` 확장 집합, 말미 `\b` 후처리(아래) |
| 2 | L25 | `항공권\|e-ticket\|flight` | re.I | ASCII 리터럴 + 한글(대소문자 없음) → `(?i)` |
| 3 | L28 | `취소\|환불\|cancel\|refund` | re.I | 동일 |
| 4 | L29 | `결제\s*완료\|payment\s*(?:complete\|successful)` | re.I | `\s` 확장 집합 |
| 5 | L30 | `(?<![\d,])((?:\d+\|[1-9]\d{0,2}(?:,\d{3})+))\s*원\b` | 없음 | **룩비하인드 후처리** + 말미 `\b` 후처리 + `\s` 확장 |
| 6 | L35 | `출발\s*항공편(.+?)(?:귀국\s*항공편\|오는편\|승객\|$)` | re.S | `$` 의미 차이 → `(?:\n?\z)` 에뮬레이션, 게으른 `.+?` 지원 |
| 7 | L37 | `(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일` | 없음 | `\d` Nd, `\s` 확장 |
| 8 | L38 | `(\d{1,2})\s+(\d{1,2})월\s+(20\d{2})` | 없음 | 동일 |

헬퍼 정규식(함께 이식 시): ota_mail.py:187 `dkim=pass\s+([^;]+)`(re.I), :189 `header\.(?:i=@|d=)([a-z0-9.-]+)(?=\s|$)`(re.I, **룩어헤드** → 캡처 뒤 문자가 Python `\s`이거나 문자열 끝/말미 `\n` 직전인지 후처리), :356 `<!--.*?-->`(re.S), :357 script/style **역참조** → `(?i)(?s)` 별도 정규식 2개(역참조는 같은 대안 반복이므로 등가), :358 `<[^>]*>`.

### 4.1 의미 차이와 변환 규칙

- **`\d` — 위임 전제 수정:** Rust `regex` 크레이트의 기본은 ASCII가 아니라 **유니코드 모드**다. 기본 `\d` = `\p{Nd}`로 Python과 동일하다. ASCII-only는 `(?-u)` 또는 `RegexBuilder::unicode(false)`일 때뿐이다. (확신: 크레이트 문서 기준 높음. 이 호스트 cargo registry에 regex-syntax 소스가 없어 파일 근거는 없음 — §9. 차등 테스트로 확정한다.)
- **`\s`:** Python `\s` = `str.isspace()` 집합 = Unicode White_Space **＋ `\x1c-\x1f`**(파일/그룹/레코드/유닛 구분자). Rust `\s` = `\p{White_Space}`로 `\x1c-\x1f` 미포함. 변환: 모든 `\s`를 `[\s\x{1C}-\x{1F}]`로 치환하면 정확.
- **`\b`/`\w`:** Python `\w` = `L*+Nd+Nl+No+_`(str.isalnum + 밑줄). Rust `\w` = `Alphabetic+M+Nd+Pc+Join_Control`. 차이: Nl/No(예: Ⅳ, ①)는 Python만 단어 문자, 결합 표기(Mn/Mc)·Join_Control은 Rust만 단어 문자. **이 슬라이스의 `\b`는 말미 2곳뿐**(L15 숫자 뒤, L30 원 뒤)이므로 후처리로 등가: 매치 끝 위치의 문자를 단일 문자 정규식 `^[\p{L}\p{Nd}\p{Nl}\p{No}_]$`로 판정해 단어 문자면 기각. 등가 논거: (a) L15 — 숫자 run 내부에서는 어떤 인접 위치도 경계가 성립하지 않으므로 `{6,20}` 그리디 백트래킹은 run 길이 >20이면 전부 실패하고, 프리픽스(예약 ID)가 앵커라 시작 위치 재시도도 없다. (b) L30 — 매치 끝은 리터럴 `원` 직후로 고정(백트래킹 상호작용 없음).
- **`(?<![\d,])` 룩비하인드 (L30):** regex 크레이트는 룩어라운드 미지원. **후처리 등가 증명:** 룩비하인드 없는 패턴으로 findall 후, 매치 시작 직전 문자가 숫자/쉼표면 기각한다. 기각된 나이브 매치의 금액 구간 내부의 모든 위치는 선행 문자가 항상 숫자/쉼표이므로 Python이 허용할 매치가 그 안에 숨을 수 없고, `\s*원` 부분은 숫자로 시작할 수 없다. 좌→우 비겹침 스캔의 귀납으로 양쪽 결과 집합이 동일하다. 대안: `fancy-regex`(룩어라운드 지원, 새 의존). 고정할 적대 사례: `"1234,567원"`→매치 없음, `"1123,456원"`→없음, `"1,234원"`→`1,234`, `"000123원"`→`\d+`로 `000123`.
- **`re.I` (L15·25·28·29):** 리터럴은 ASCII 영문+한글뿐. 비ASCII 입력이 ASCII로 폴딩되는 경우는 ſ(U+017F)→s, K(U+212A)→k이며 양 엔진 모두 유니코드 단순 폴딩으로 처리한다(동등 추정, 미실측 — §9). ß/İ 같은 전체 폴딩은 이 패턴들에 해당 사항 없음. `(?i)` 유니코드 모드로 변환.
- **`$` (L35, re.M 없음):** Python `$` = 문자열 끝 **또는 말미 `\n` 직전**. Rust `$` = haystack 끝만. 변환: `(?:\n?\z)`. body_text 출력은 항상 `\n`으로 끝나므로(ota_mail.py:359) Python `$`는 실제로 그 말미 개행 직전에서 성립한다. group(1) 말미 개행 한 칸 차이는 날짜 검색(L37-38) 결과에 영향 없지만 충실히 에뮬레이션한다.
- **`re.S` (L35):** `(?s)` — 양쪽 모두 `.`이 `\n` 포함 전체 매치. 등가.
- **날짜 검증 (L42):** `date(*map(int,parts))`의 ValueError → `time::Date::from_calendar_date` 오류로 등가(time 크레이트 기존 의존, forest.rs가 `dates::parse_iso` 사용).
- **`int()` (L31):** Python `int()`는 유니코드 Nd 전체(전각 ０-９, 아랍 숫자 ٠-٩ 등)를 받는다. Rust `str::parse::<i64>`는 ASCII만 → 문자별 `char::to_digit(10)` 변환 필요. **길이 무제한:** `\d+` 대안은 길이 캡이 없어 Python은 임의 정밀도 정수를 낸다. u64 초과 금액은 `serde_json::Value`로 표현 불가(arbitrary_precision 피처 없이는) → 설계 결정 필요(§9).
- **Cf 제거 (L23):** `\p{Cf}` 전체 치환. 버전 드리프트 §9.

**권고:** 새 의존 없이 `regex` 크레이트 + 소형 `python_re` 헬퍼 계층(확장 `\s` 클래스, 말미 `\b` 후처리, 룩비하인드/룩어헤드 후처리, `$` 에뮬레이션)으로 이식한다. 근거: 이 슬라이스의 룩어라운드는 전부 고정 폭 1 또는 말미 경계라 후처리 등가가 증명 가능하고, 역참조는 정규식 분리로 등가다. `fancy-regex`는 차등 테스트에서 후처리 발산이 발견될 경우의 대안으로만 둔다(새 의존 추가는 퇴역 계획 §4 위험 목록의 의존 결정 절차를 따름).

## 5. source_sha256 — 기존 digest.rs 재사용 가능

- traveloka L51-52의 레시피 `json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(',',':'))`는 **`core/crates/core/src/digest.rs:16 `python_json_compact`와 정확히 같은 레시피**다. 키 순서는 `serde_json::Map`(BTreeMap) = 코드포인트 순(digest.rs:1-2 주석), 이스케이프는 `write_string`(digest.rs:63-81)이 `"`·`\`·`\n`·`\r`·`\t`·`\b`·`\f`·기타 U+0000-U+001F를 `\u00xx`(소문자 hex)로 — Python과 동일. 해시는 `sha256_hex`(digest.rs:22).
- 재사용 시 주의: (a) 숫자 직렬화 — Python float repr과 serde_json의 지수 표기(예: `1e+22` vs `1e22`) 차이 가능(미실측, §9), (b) u64 초과 정수(§4.1), (c) IPC JSON 왕복의 타입 보존(int/float). 사실 수준 골든의 입력이 message dict 자체이므로 차등 대조가 이 차이를 잡는다.
- 사건 ID 계열(`_digest` ota_payments.py:42-44, `_event_id` :47-50)도 같은 compact 레시피(`default=str` 포함)이며 Rust extract.rs의 `digest`/`event_id`가 이미 이를 에뮬레이션한다 — 조립 계층 이식 시 재사용.

## 6. 테스트·골든 현황

- **tests/card_pipeline/test_traveloka_mail.py: 테스트 6개**(L12, L28, L42, L54, L64, L74) — traveloka 관련 5 + jeju 1(L74, 이 파일에 공존). 특성: 합성 `owner_collected` 메시지(`mail_collect.owner_record` mail_collect.py:290-302 — base64url 본문, Date 헤더에서 internal_date, owner_collected=True), 인증 거부(도메인 경계 `traveloka.com.example`, owner_collected 제거), refs 충돌(본문 다른 ID), 금액 모호(2개 금액), 외화 USD, 취소→evidence_conflict, 반복 티켓+결제 공유 identity, flight_evidence 연동.
- **core/golden/synthetic/extract.jsonl: 51건, Traveloka 0건**(grep 0매치). 형식: 줄당 `{case_id, input=stages(사건 수준), expected={events}, sha256, bytes}`. 생성기 `tools/core_bridge/extract_golden.py`(event() L16, stages() L27, inputs() L33, expected() L106, records() L115, `'x'` 모드 — 기존 골든 덮어쓰기 금지). 소비: `core/crates/core/tests/extract_golden.rs`(필드+sha256+bytes 대조, count>=50).
- **함의:** 기존 골든은 사건 조립 이후 계층만 덮으므로 traveloka 파서 단위에는 **새 사실 수준 골든**(input=message dict, expected=references/extract 출력)이 필요하다. 선례: `core/crates/core/tests/trips_golden.rs`("Python 함수 직접 호출 출력" 패턴).
- 골든 생성은 합성 전용이어야 한다(extract_golden.py:1-4 주석 — 고객 원문·운영 위치 금지). 보호 입력(D:/WebLedgerHost) 대조는 이 조사의 범위 밖이며 후속 단계에서 운영 담당이 수행한다.

## 7. airline 의존과 이식 순서 영향

- **airline_payment_mail.py:11-14** `cancellation_references`: traveloka 인증 + subject 취소 정규식 후 `traveloka_mail.references(message)` 호출.
- **airline_payment_mail.py:75-78** `extract`: `traveloka_mail.extract(message)`에 **먼저 위임**, 결과 있으면 그대로 반환.
- 함의: 퇴역 계획 순서(traveloka→airbnb→mytrip→rakuten→airline→…)에서 traveloka가 airline보다 먼저지만, **airline이 Python에 남아 있는 동안 Python traveloka 모듈은 삭제 불가**. 따라서 traveloka 단위는 Rust 구현 + 골든 검증의 추가 전용 PR이고, Python 삭제는 계획 5단계(airline 이식 후)다. 계획 §4 "한 실행 안에서 생산자를 섞지 않는다" 제약상 fact 수준 운영 배선(브리지 내 공급자별 스위치 vs 조립 계층 이식)은 후속 단위의 설계 결정이다(§9).
- 부수 의존(소비자, 파서 아님): `app/flight_evidence.py:18, 303, 319`가 traveloka 도메인/분기를 사용 — 삭제 단계에서 함께 검토하되 이식 단위에는 포함하지 않는다.

## 8. 파일별 구현 단계 초안 + 검증 명령

전제: 오프라인 골든 대조 단위이며 **운영 경로 전환·스위치 신설·Python 삭제가 아니다.**

| 단계 | 파일 | 내용 |
| --- | --- | --- |
| 1 | `tools/core_bridge/traveloka_golden.py` (신규) | 합성 message → `references()`/`extract()` 출력 JSONL 생성기. extract_golden.py 패턴(`'x'` 모드, 합성 전용). 사례: 기존 테스트 6종의 메시지 + 적대 사례(룩비하인드 4종, `\b` 결합표기/Nl/No, Cf 소프트하이픈·ZWJ, 전각/아랍 숫자, ſ/K subject, 말미 `\n` `$`, u64 초과 금액(결정 후), float 필드, DKIM 정렬 vs owner_collected, 도메인 경위) |
| 2 | `core/golden/synthetic/traveloka_mail.jsonl` (신규) | 단계 1 생성물. 줄당 `{case_id, input=message, expected={references, fact}, sha256, bytes}` |
| 3 | `core/crates/core/src/extract/python_re.rs` (신규) | 확장 `\s` 클래스, 말미 `\b` 후처리, 룩비하인드/룩어헤드 후처리, `$` 에뮬레이션 헬퍼 + 단위 테스트(§4.1 적대 사례 고정) |
| 4 | `core/crates/core/src/extract/mail.rs` (신규) | `body_text`(base64url+패딩, utf-8 손실 디코드, 주석 제거, script/style 2정규식, 태그→개행, 엔티티 unescape, parts 재귀), `authenticated_headers`(parseaddr 등가, 도메인 경계, owner_collected 엄격 true, DKIM 2정규식+후처리), `\p{Cf}` 제거 |
| 5 | `core/crates/core/src/extract/traveloka.rs` (신규) | `references`/`extract` — `serde_json::Value` message 입력, `digest.rs` 재사용, `time` 날짜 검증. §1 비대칭 보존 |
| 6 | `core/crates/core/src/extract.rs` | mod 선언 추가만(L5-7 구역). **운영 배선 변경 없음** |
| 7 | `core/crates/core/tests/traveloka_golden.rs` (신규) | 사례별 필드 동일 + canonical 바이트·sha256·bytes 대조, 건수 가드 |
| 8 | (후속 단위, 이 PR 아님) | fact 수준 운영 배선 설계: 브리지 내 공급자별 스위치 vs 조립 계층 이식. 계획 §4 생산자 혼합 금지 제약 충족 방안 |

검증 명령(구현 단위에서 실행):
```
python -X utf8 -m tools.core_bridge.traveloka_golden        # 골든 생성('x' 모드, 기존 파일 덮어쓰기 불가)
cargo fmt --check && cargo clippy --workspace               # core/ 에서
cargo test -p cost-core traveloka                           # 신규 골든·헬퍼 테스트
cargo test -p cost-core extract_golden                      # 기존 골든 무변동 확인
python -B -m pytest -q tests/card_pipeline/test_traveloka_mail.py   # Python 동작 무변동
python tools/run_quality_checks.py --base origin/main --run # 영향 기반 검사
```
수락 기준: 신규 골든 전 사례 필드+바이트 동일, 기존 extract.jsonl 무변동, Python 테스트 무변동. 보호 경로 새 기준 대조는 배선 단계에서 운영 담당이 수행(이 단위에서는 합성 골든만).

## 9. 확신 없는 지점 (모른다)

1. **Cf 버전 드리프트:** Python unicodedata(빌드 의존 Unicode 버전)와 regex-syntax 0.8(regex 1.13.1) 테이블의 Cf 집합 동일성 — **모른다**. Cf 포함 차등 골든으로 고정해야 한다.
2. **html.unescape 동등성:** 세미콜론 없는 레거시 엔티티 포함 HTML5 테이블을 바이트 동일하게 처리하는 Rust 크레이트 — **모른다**(html-escape 등 미검증, 이 호스트 registry 소스 부재). CPython `html.entities` 테이블 이식도 대안.
3. **parseaddr 동등성:** 기형 From 주소에서 `email.utils.parseaddr`와 같은 결과를 내는 Rust 구현 — **모른다**. CPython `_parseaddr` 알고리즘 이식 또는 크레이트+차등 테스트.
4. **regex 크레이트 `\d`=Nd 파일 근거:** 문서 기준 확신은 높으나 이 호스트에 registry 소스가 없어 실측 근거 없음 — 차등 테스트로 확정.
5. **re.I 폴딩 엣지(ſ/K):** 단순 폴딩 동등 추정 — 미실측.
6. **float 직렬화:** Python repr vs serde_json 지수 표기(`1e+22` 등) — 미실측. message에 float 필드가 있는 차등 사례 필요.
7. **u64 초과 금액:** `\d+` 무제한 길이 → 임의 정밀도 정수의 JSON 표현 — 설계 결정 필요(arbitrary_precision 피처 vs 수동 직렬화). 거부로 처리하면 동작이 바뀌므로 불가.
8. **fact 수준 운영 배선:** 브리지 내 공급자별 스위치와 조립 계층 이식 중 어느 쪽이 계획의 생산자 혼합 금지와 양립하는지 — **모른다**(후속 단위 설계 결정).
9. **Python `\s` 전체 코드포인트 집합:** `\x1c-\x1f` 차이는 확신 높음(CPython 문서화된 거동)이나 전체 집합 차등 검증은 미수행.

## 10. 조사 범위 준수

- 읽기 전용: 파일 수정 없음(이 문서 제외), 커밋·push 없음, 테스트 실행 없음, 운영 DB·D:/WebLedgerHost 접근 없음.
- graphify 우선: 헬퍼 위치·mail_events 사슬을 graphify query로 찾은 뒤 해당 줄만 판독.
- 위임 문구 정정 2건: 정규식 6개→**8개**, `_extract_signed_payment_message` 소속 ota_mail→**ota_payments.py:286**(traveloka 의존 아님).