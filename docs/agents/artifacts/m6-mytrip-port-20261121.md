# M6 mytrip 메일 파서 Rust 이식 조사 (2026-11-21)

- 위임: Cost Codex V4 읽기 전용 조사. 코드 수정·커밋·push·테스트 실행 없음. 이 문서가 유일한 산출물이다.
- 방법: `graphify query` 우선 탐색(graphify-out/graph.json 존재, 30,954 노드) 후 결과 위치의 원본만 판독. 줄 번호는 grep·read로 확정.
- 기준: 브랜치 `work/m6-mytrip-20261121`, HEAD `304a42ae23854762f9726c9d8816d3032cf8e3df`(PR #1078 Airbnb 병합 직후). 작업트리 clean(`.qwen/`·`graphify-out/` 미추적만). 퇴역 계획 [m6-extractor-retirement.md](../../playbooks/m6-extractor-retirement.md) §1.2 L44(mytrip 81행·난이도 낮음), §2-3(b) L66 순서 traveloka→airbnb→**mytrip**→rakuten→airline→….
- 선행 근거: [Airbnb 이식 조사](m6-airbnb-port-20261121.md)(경계·골든 선례), [Traveloka 이식 조사](m6-traveloka-port-20261120.md)(정규식 의미·검수 차단 3종), [session_handoff.md](../../session_handoff.md)(Airbnb 단위 완료·pyre.rs 신설·골든 회귀 가드).

## 0. 판정

**이식 가능 — 추가 전용(additive) PR, 선행 차단 조건 없음.** airbnb와 같은 경계(collect 전체)가 가능하다. fact/조립 분리가 없고 교차 파서 의존이 없다(grep: `mytrip_mail` import는 ota_payments.py:209와 테스트 2곳뿐). 연도 추론이 없어(LEG가 연도를 명시) 기간 추론은 airbnb보다 단순하지만, mytrip 고유 쿼크(무효 날짜 1건 → 메시지 전체 기각, 연도 0000, totals **문자열** 집합, confirmed 우선)가 있다. 기존 `extract.jsonl` 골든에 gotogate/mytrip **0건**이라 새 사실 수준 골든이 필수다.

## 1. 파서 계약 (app/mytrip_mail.py, 81행)

**`collect(messages, inventory=())` 하나가 파싱+집계+조립+ID 전부**다(L35-81). airbnb와 같은 형태. `_facts`(L17-32)는 private 헬퍼로 collect L52에서만 호출된다 — 외부 fact 계약 없음.

### collect — L35-81
- L36 `from app import ota_payments as core` — 지연 import, `_digest`·`_event_id`만 사용.
- L38 `observed, withdrawn = {}, set()` — 주문별 행 목록 + 전역 취소 주문 집합.
- L39 `sorted(messages.items())` — message_id **문자열** 오름차순.
- L40-42 `ota_mail.authenticated_headers(message, DOMAINS)` 게이트. DOMAINS = `('mytrip.com', 'gotogate.com')`(L9). 실패 시 skip — **취소 기여도 없음**. `auth[1]`(canonical 도메인)은 쓰지 않는다.
- L44 `subject = str(headers.get('subject') or '')` — None/빈 값 → `''`.
- L45 `text = ota_mail.message_text(message)` — 본문 전용, **Cf 제거 없음**(airbnb와 동일).
- L46 `confirmed = CONFIRMED.match(subject.strip())` — **`.match`**(시작 고정) + `^…$` 완전 앵커. strip은 Python 공백 집합.
- L47-50 confirmed가 아니면: `WITHDRAWN.search(subject)`(L48, **subject 전용·strip 안 함**) 매치 시 `withdrawn.update(re.findall(ORDER, text))`(L49) — 본문 속 **모든** 주문 문자열을 취소 집합에 추가(관측 안 된 주문도, 복수 주문도). continue.
- L51-55 confirmed면: `order = confirmed[1]`, `facts = _facts(text, order)`, `sent = ota_mail.sent_day(message, headers)`. **`facts and sent`일 때만** `observed.setdefault(order, []).append((message_id, facts, sent, core._digest(message)))`. 무효 행은 digest·source_ids에 전혀 기여하지 않는다.
- L57 `sorted(observed.items())` — order 문자열 오름차순으로 사건 생성.
- L58 `distinct = {(tuple(f[0].values()), f[1]) for _, f, _, _ in rows}` — ((starts_on, ends_on), amount) 집합. dict `.values()`는 삽입 순서(starts_on, ends_on).
- L59 `source_ids = ['mail:' + mid …]` — message_id 순서.
- L60-61 `period, amount = rows[-1][1]`(**문자열 정렬 마지막 행**, 날짜 최신 아님); `conflict = len(distinct) != 1`.
- L62-75 사건 dict(**25키**): provider=**'gotogate'**(mytrip 아님), booking_ref=order, event_type='reservation', item=**'항공료'**, paid_on=None, paid_on_semantics='missing', card_last4=None, amount/amount_krw=conflict 시 None else 정수, currency=conflict 시 **None** else 'KRW', service_period=conflict 시 None else 기간 dict, service_period_conflict, reservation_status='cancelled' if order in withdrawn else 'observed'(L68, **sticky**), payment_status='unknown', evidence_status=**'reservation_only'**(airbnb 'reservation_observed'와 다름), evidence_kind='authenticated_reservation_mail', **reservation_observed_on=sorted({sent.isoformat()})**(L71,同日 재발송 중복 제거), source_digest=rows[-1][3], source_digests=리스트(중복 허용), source_ids, identity_source_ids=source_ids(같은 리스트), source_inventory=list(inventory).
- L76-79 `identity = 'gotogate:'+order`; `source_lineage_ids=[identity]`; `observation_ids = sorted('obs_'+core._digest([identity, source]) for source in source_ids)`(**digest hex 순 정렬**); `ota_event_id = core._event_id([identity])`.
- 취소만 있고 관측이 없는 주문 → **사건 없음**(L57은 observed에서만 생성).
- airbnb와의 구조 차이: ① 금액·통화가 있다(비conflict 시). ② `reservation_observed_on` 추가. ③ **confirmed 우선**(L46-50) — airbnb는 withdrawn 우선. 단 mytrip은 CONFIRMED가 완전 앵커라 매치 subject에 취소 단어가 들어갈 수 없어 **동시 매치는 구조적으로 불가**(§7.9). ④ 취소는 subject가 아니라 **본문 ORDER 전수**로 퍼진다.

### _facts(text, order) — L17-32
- L18 `set(re.findall(ORDER, text)) != {order}` → None. 본문에 subject 주문과 **같은 문자열**이 정확히 1종이어야 한다(0종·2종 기각). ORDER에 `\b`가 없어 긴 숫자런 내부도 매치(§3.4).
- L20-25 `legs = set()`; LEG.findall 3-튜플마다 `date(int(year), int(month), int(day))` — **ValueError면 그 자리에서 return None(메시지 전체 기각)**. 무효 날짜 1건이 유효한 다른 날짜까지 버린다. int()는 유니코드 Nd.
- L26 `totals = set(TOTAL.findall(text))` — **캡처 원본 문자열** 집합(정규화 전).
- L27 `not legs or len(totals) != 1 or (max(legs)-min(legs)).days > 366` → None. 단일 날짜(0일) 허용, **366일 허용·367일 기각**. 가는/오는 구분 없이 전체 leg의 min/max.
- L29-31 `amount = int(next(iter(totals)).replace(',', ''))` — 쉼표 **전부** 제거; `amount <= 0` → None(패턴상 음수 불가, 0만 도달).
- L32 `({'starts_on': min.isoformat(), 'ends_on': max.isoformat()}, amount)` — 삽입 순서 starts_on→ends_on.

## 2. 경계 제안

### Rust가 소유할 것 (collect 전체)
정규식 5종 매칭+후처리, `_facts`(ORDER 게이트·LEG 달력 검증·기간 상한·TOTAL 금액), 메시지별 digest, observed/withdrawn 집계, 정렬, 사건 조립(25키 전부), `source_lineage_ids`/`observation_ids`/`ota_event_id`, conflict 플래그. 입력은 다건 메시지 + inventory, 출력은 order 정렬된 사건 배열.

### Python 브리지에 남길 것 (경계 값) — airbnb 선례 그대로
| 헬퍼 | 위치 | 경계 값 | 근거 |
| --- | --- | --- | --- |
| `authenticated_headers` | ota_mail.py:177-193 | `subject: Option<String>`(None=미인증) | parseaddr·DKIM 정렬·owner_collected. DOMAINS 2개(mytrip.com·gotogate.com)는 브리지에 남는다. `auth[1]` 미사용이라 도메인 값 불요. airbnb.rs `AirbnbMessage.subject` 선례. |
| `message_text` | ota_mail.py:41-46 | `raw_text: String`(본문 전용, **Cf 제거 없음**) | body_text(ota_mail.py:349-360, HTML·base64·unescape)가 Python에 남으므로 Rust 본문 파싱 불요. |
| `sent_day` | ota_mail.py:371-385 | `sent_day: Option<String>`(KST ISO 날짜) | RFC2822 `parsedate_to_datetime`+KST+수신 지연(미래 발송 거부, mail_internal_date ota_mail.py:362-368). **호출처 10곳**(grep: airline_payment_mail:139·airbnb_mail:51·forest_mail:122,123·forest_payment_mail:68·mytrip_mail:53·ota_mail:447,905·ota_payments:243,391). 공용 헬퍼로 남기고 결과만 넘긴다. |
| 메시지 원본 | — | `message: Value`(전체 dict) | digest 입력. traveloka source_sha256·airbnb 선례. |
| inventory | ota_mail.py:133-134 | `inventory: Vec<Value>`(pass-through) | `{'kind','path','messages','collection'}` — **운영 경로 포함 → 골든은 합성만**. |

입력 형태(제안): `MytripInput { messages: BTreeMap<String, MytripMessage>, inventory: Vec<Value> }`, `MytripMessage { message, subject, raw_text, sent_day }`, `deny_unknown_fields`. BTreeMap 순회 = Python `sorted(messages.items())`(UTF-8 바이트 순 = 코드포인트 순). stripped_text 필드 불요.

### digest 대응 — 이미 Rust에 있다
- `core._digest`(ota_payments.py:42-44) = `sha256(json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False, default=str))`. **`digest.rs:16 python_json_compact` + `:22 sha256_hex`가 같은 레시피**. `default=str`은 도달 불가(메시지는 `json.loads` ota_mail.py:129 또는 `owner_record` mail_collect.py:290-302 출신, JSON 타입만).
- `core._event_id`(ota_payments.py:47-50) = `'ota_'+_digest(sorted(set(ids)))`. `extract.rs:254 event_id`(private)가 BTreeSet으로 에뮬레이션. mytrip은 단일 identity라 `digest.rs`로 직접 계산 가능(airbnb.rs 선례).
- `observation_ids` = `'obs_'+digest([identity, source])` — 문자열 2개 리스트 compact JSON. `digest.rs` 재사용.
- 사건 키 **순서**는 골든이 `sort_keys=True`로 비교하므로 재현 불요. **리스트 순서**(events=order순, source_ids/source_digests=message_id순, observation_ids=digest순, reservation_observed_on=ISO순)는 정확히 재현해야 한다.

### 왜 collect 전체인가 (airbnb §2와 같은 논거)
1. fact/조립 분리가 없어 collect이 곧 완성 사건 생산자다. 단건만 옮기면 존재하지 않는 중간 계약을 발명하게 된다.
2. **교차 파서 의존 없음**(grep `*.py` 13건: ota_payments.py:209,213 + test_mytrip_mail.py + test_ledger_stay_evidence.py:358-360). traveloka의 airline 의존 같은 삭제 차단이 없다.
3. 계획 L86 "한 실행 안에서 생산자를 섞지 않는다"는 한 생산자를 Rust/Python으로 쪼개지 말 것으로 읽힌다 — collect 전체 이식이 부합. 배선 단계 재확인(§9).

## 3. 정규식 동등성표 — 컴파일 4개 + ORDER 원자 패턴(실질 5종)

모듈 수준 컴파일: CONFIRMED(L11)·WITHDRAWN(L12)·LEG(L13)·TOTAL(L14). ORDER(L10)는 문자열 상수로 CONFIRMED에 내장되고 `re.findall(ORDER, …)`로 2곳(L18·L49)에서 단독 사용(암시 컴파일·캐시). 헬퍼 정규식(auth·body_text)은 Python에 남아 이식 대상 아님. Rust `regex` **1.13.1**(Cargo.lock:321-323). 공용 헬퍼: `pyre.rs` PY_SPACE:15, is_python_word:37, word_boundary_after:821, word_boundary_before:830, is_nd:837, nd_value:842, read_digits:857.

| # | 위치 | 패턴 | flags | 동등성 쟁점과 변환 |
| --- | --- | --- | --- | --- |
| 1 | L10 | `\d{4}-\d{3}-\d{3}` (ORDER) | 없음 | `\d`→`\p{Nd}`. **`\b` 없음** — 긴 숫자런 내부 매치 허용. 캡처를 **문자열 그대로** 사용(int 변환 없음) → 전각 주문은 전각 그대로 booking_ref·identity가 된다. findall 비겹침 좌→우 = 크레이트 `find_iter` 등가. |
| 2 | L11 | `^여행이\s*확정되었습니다\.\s*주문\s*번호\s*(ORDER)\s*$` (CONFIRMED) | 없음 | `.match(subject.strip())`(L46). `^`=텍스트 시작(re.M 없음, `(?m)` 금지). **`$`→`(?:\n?\z)`**(traveloka 선례, handoff 2026-11-20 (3)). `\s`→PY_SPACE. **리터럴 `\.` 필수**(마침표 없으면 불매치). 완전 앵커 — 선행/후행 잡음 기각. strip은 §3.3. |
| 3 | L12 | `취소\|환불\|cancel\|refund` (WITHDRAWN) | **re.I** | `.search(subject)`(L48) — **subject 전용·본문 아님**, confirmed 실패 시에만. `(?i)` 부분문자열(cancellation·refunded도 매치). 한글 리터럴은 대소문자 무관. 전각 라틴(ｃａｎｃｅｌ)은 ASCII로 폴딩되지 않아 양쪽 모두 불매치. |
| 4 | L13 | `(?:가는\|오는)\s*편\s*[•·]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일` (LEG) | 없음 | findall 3-캡처. `\d`→`\p{Nd}`, `int()`→`read_digits`. 불릿은 **U+2022(•)·U+00B7(·)만**(・U+30FB·‣ U+2023 불매치). 가는/오는 구분 없음. 달력 검증은 §4. |
| 5 | L14 | `합계\s*([0-9][0-9,]*)(?:\.00)?\s*KRW\b` (TOTAL) | 없음 | **`[0-9]` 명시적 ASCII**(Nd 아님 — ORDER·LEG와 반대). `(?:\.00)?`만 허용('.50'·'.000'은 불매치→집합 공집합→기각). **말미 `\b` 후처리**(§3.2). 캡처 원본 문자열 집합(§7.4). 대소문자 구분(krw 불매치). |

### 3.1 의미 차이와 변환 (traveloka·airbnb 보고서 준용)
- **`\d`**: 크레이트 기본 유니코드 `\d`=`\p{Nd}`=Python. 명시적 `\p{Nd}` 사용(선례). TOTAL의 `[0-9]`는 ASCII 그대로 유지.
- **`\s`**: Python = White_Space **+ U+001C..U+001F** → `PY_SPACE`(pyre.rs:15) 치환.
- **`\b`/`\w`**: Python `\w`=L*+Nd+Nl+No+`_`; 크레이트 `\w`=Alphabetic+M+Nd+Pc+Join_Control. TOTAL 말미 `\b`는 `word_boundary_after`(pyre.rs:821) 후처리. **선도 `\b`가 없어 word_boundary_before는 불요**.
- **`^`/`$`**: re.M 없으면 `^`=텍스트 시작 등가. `$`는 말미 개행 1개를 허용하므로 `(?:\n?\z)`로 변환(strip 후엔 도달 불가지만 충실 변환 유지).
- **re.I**: WITHDRAWN만. cancel/refund 글자(c,a,n,e,l,r,f,u,d)에는 특수 단순 폴딩 문자(ſ→s, K→k 등)가 해당 없어 `(?i)` 등가 확신 높음 — 차등 사례로 고정(§9).
- **캡처 semantics**: 크레이트 leftmost-first = Python 백트래킹 캡처 등가(문서화). LEG 그리디 `\d{1,2}` 차등 사례 고정.

### 3.2 TOTAL 말미 `\b` 후처리 등가 논거
`\b`를 뺀 `합계\s*([0-9][0-9,]*)(?:\.00)?\s*KRW`로 find_iter 후 **후행 문자가 Python 단어 문자면 기각**.
- 매치는 리터럴 'KRW'로 끝난다. 선행 문자 'W'는 양쪽 의미 모두 단어 문자 → 경계 판정은 **후행 문자 분류만** 차이(Nl/No는 Python만 단어, 결합표기·Join_Control은 크레이트만 단어).
- 엔드포인트 고정: 금액 뒤 `(?:\.00)?\s*` 다음 첫 'KRW'에서 끝나며, 백트래킹이 끝점을 다른 'KRW'로 옮길 수 없다(숫자·쉼표·공백 클래스에 'K'가 없음). 기각 후보 내부에 유효 매치가 숨을 수 없다 — 후보 내부는 공백·숫자·쉼표·점·KRW뿐이라 새 매치의 시작 리터럴 '합계'가 들어갈 수 없다. 크레이트가 후보 끝에서 재개해도 Python의 start+1 전진과 매치 집합 동일.
- `set` 중복 제거 + `len==1` 게이트라 순서 무관.
- **적대 사례(골든 고정)**: `KRWE`·`KRW1`·`KRW_`·`KRW원`(말미 단어 → 불매치), `KRWⅣ`(Nl → 불매치, naive 크레이트 `\b`는 매치라 오답), `KRW\u0301`(결합표기 → **매치**, naive 크레이트는 불매치라 오답), `krw`(소문자 → 불매치), `합계\u001C100 KRW`(확장 공백 → 매치).

### 3.3 subject.strip() — 새 헬퍼 필요
Python `str.strip()` 공백 집합 = `str.isspace()` = White_Space + U+001C..U+001F. Rust `str::trim()`은 `char::is_whitespace`(White_Space)만 → **U+001C-1F에서 차이**. pyre.rs에는 regex용 PY_SPACE만 있고 trim 헬퍼가 없다.
- 제안: pyre.rs에 소형 헬퍼 추가(예: `py_trim(s) = s.trim_matches(|c| c.is_whitespace() || ('\u{1C}'..='\u{1F}').contains(&c))`) + 단위 테스트. 후속 파서(rakuten·airline)도 재사용. 대안: mytrip.rs 인라인 클로저(pyre 무변동). **어느 쪽이든 traveloka 28건·airbnb 31건 골든 바이트 동일이 회귀 가드**.
- strip 후 subject는 말미 개행이 없어 `$`의 개행 허용은 도달 불가 — 그래도 `(?:\n?\z)` 변환을 유지해 의미론을 국소화한다.

### 3.4 ORDER 무경계·문자열 동일성
- `\b`가 없어 `11111-222-3333`에서 `1111-222-333`이 나온다(좌측 비겹침 스캔). 취소 메일 본문(L49)에서도 동일 — 긴 숫자런이 주문을 취소시킬 수 있다.
- L18 게이트는 **문자열 집합** 비교: 전각 `１１１１-２２２-３３３`과 ASCII `1111-222-333`은 다른 원소(혼재 → 2종 → 기각). subject·body가 모두 전각이면 통과하고 **booking_ref·identity가 전각 문자열 그대로**다(정규화 금지).

## 4. _facts Rust 대응

- 날짜 생성: `time::Date::from_calendar_date`(airbnb.rs `calendar` 선례 — u8/i32 가드). 월 0/13·일 0/32·2월 30·비윤년 2월 29 → Err → **메시지 전체 None**(행 단위 skip 아님, L21-25).
- **연도 가드 신규**: Python `date.MINYEAR=1` — LEG `\d{4}`가 `0000`을 캡처하면 ValueError → None. `time` 크레이트는 연도 0을 허용하는 것으로 알려져 있으나 이 호스트에서 소스 미확인 → **`year >= 1` 명시 가드**로 무력화(§9). MAXYEAR 9999는 `\d{4}` 상한과 같아 도달 불가. airbnb에는 없던 가드(연도가 sent에서 왔음).
- Nd 캡처 `int()`: `read_digits`(pyre.rs:857, nd_value 블록 테이블 pyre.rs:23·842) — 전각·아랍 숫자 연도/월/일. traveloka 검수 차단 2종(ASCII digit 65de53b1, Nd 블록 d11a4b8b)이 그대로 적용.
- 기간 상한: `(max-min).whole_days() > 366` 기각(L27). **0일(단일 leg)·366일 허용**. BTreeSet<time::Date>로 중복 제거·min/max.
- TOTAL 금액: 캡처는 ASCII `[0-9][0-9,]*` → 쉼표 제거 후 `str::parse::<i64>()`(Nd 변환 불요). 선행 숫자 보장으로 공백 문자열 불가. `amount <= 0` 기각. **Python int는 무한 자릿수** — i64 초과는 이론적 발산(§9.4, 골든 범위 내 + 문서화).
- 금액 집합: 캡처 **원본 문자열** BTreeSet<String>(정규화 전). `len != 1` 기각. 메시지 간 conflict는 ((starts, ends), amount) **정규화 후** 집합(L58) — 비대칭(§7.4).
- 기간 dict: `{"starts_on": iso(min), "ends_on": iso(max)}` — `dates::calendar::iso`(calendar.rs:50), sent_day 파싱은 `parse_iso`(calendar.rs:27, strict YYYY-MM-DD).

## 5. 테스트·골든 현황

- **tests/card_pipeline/test_mytrip_mail.py: 테스트 4개**(L14·L22·L28·L36), collect 호출 7회(L15·24·29·30·31·32·37). 헬퍼 `message`(L4, owner_record 합성·기본 sender no-reply@support.kr.mytrip.com·Date Wed, 19 Aug 2026 13:49:53 +0000), `confirmed`(L8, **legs를 2번 반복**해 집합 중복 제거를 암시 검증, 기본 total '224,682.00').
  - L14 확인 → reservation·기간 2026-09-18~21·224682원·paid_on None·observed·reservation_observed_on ['2026-08-19'] (KST 22:49, 같은 날).
  - L22 환불 subject('[No Reply] 환불 영수증') + 본문 주문 → cancelled.
  - L28 무시 4종: 위장 도메인(mytrip.com.example)·USD·leg 없음·주문 2종.
  - L36 총액 다른 확인 2건 → conflict(period None·amount None·conflict True).
- **webapp/tests/test_ledger_stay_evidence.py: 표시 테스트 3개**(L366·L391·L398). `gotogate_stay` 픽스처(L357-363)가 **test_mytrip_mail.confirmed를 import**(L359)해 collect 호출 → 파서 골든이 깨지면 표시 테스트도 깨진다. L391은 unsafe pairing 변형 **11종** parametrize(금액 1원 차·승인일 +3일·타 항공사 descriptor·카드 2장·환불·취소·conflict·중복 사건 3종·results 끼어들기).
- **tests/card_pipeline/test_ota_alias_four_providers.py: 별칭 테스트 3개**(L54 MYTRIP/MYTRIP KOREA/NICE_MYTRIP→gotogate, L59 **MYTRIP.COM→trip已知 결함 고정**, L70 GOTOGATE/이니시스(일반)-고투게이트코리아유→gotogate). 소비자 측 정책 — 이식 대상 아님.
- **core/golden/synthetic/extract.jsonl: 50건, gotogate/mytrip 0건**(실측: `find /c /v ""` 50 + `findstr case_id` 50; 대소문자 무시 grep `mytrip|gotogate` 0 — 부분집합이므로 0건 확정). **PR #1078은 이 파일을 건드리지 않았다**(`git diff --stat 7d343bc4 304a42ae -- core/golden/`: airbnb_mail.jsonl +31만). airbnb 보고서의 "51건"은 오기 — §9.9.
- 선례 골든: **airbnb_mail.jsonl 31건**(생성기 inputs() 31 yield와 일치; handoff·커밋 메시지의 "26건"은 갱신 전 기록 — §9.9), **traveloka_mail.jsonl 28건**. 생성기 `tools/core_bridge/airbnb_golden.py`(stages()가 경계 값 계산, case()가 collect 출력+sha256/bytes/chars, build()가 덮어쓰기 거부), 소비 `core/crates/core/tests/airbnb_golden.rs`(필드+canonical 바이트 대조, 건수 가드, 기형 입력 거부).
- **mytrip 골든 생성기 제안**: `tools/core_bridge/mytrip_golden.py` — stages(record) = `{message, subject: str(auth[0].get('subject') or '') if auth else None, raw_text: message_text(record), sent_day: sent_day(record,headers).isoformat() if sent else None}`(auth는 DOMAINS 2개); input = `{messages:{id:stages}, inventory}`; expected = `{events: collect(messages, inventory)}`. **합성 전용**(고객 원문·운영 경로 금지). 사례 목록은 §8 단계 1.

## 6. 의존·소비자

- **생산 사슬**: `costcore extract` → bridge.rs `extract-sources` → tools/core_bridge/commands.py → **extract_sources.py:53** `'mail_events': op._mail_events(...)` → ota_payments.py:57 `_mail_events`(메모+deepcopy) → :109 `_parse_mail_events` → **:209 import, :213 `mytrip_mail.collect(messages, inventory)`** 반환 배열 concat. mytrip 사건은 `ota_booking_context.attach`·`attest`(결제 경로 :205-208)를 **거치지 않는다**.
- **결제 매칭 — 영향 없음**: `_event_is_paid`(ota_payments.py:1019-1021)는 event_type 'reservation' → False. :1985 미결제 분기에서 provider 'gotogate'는 RESERVATION_ONLY 목록 `('toyoko','forest','rakuten')`(:1989-1991)에 없고 evidence_status 'reservation_only'는 'preauthorized'가 아니며 price_change도 없다 → **:1995 `NOT_CARD_CHARGE`**. 자동 결제 매칭을 하지 않는다.
- **표시 소비자 — 위험 지점**: `webapp/ledger_stay_evidence.py:117` → **:779-845 `_gotogate_exact_amount_periods`**. 게이트(:791-795): provider gotogate·reservation·**observed**·booking_ref·source_digest 있음·conflict 플래그 4종 없음·currency KRW. 금액>0·기간 0≤days≤366 재검증·**reservation_observed_on 정확히 1일**이어야 pairing 후보. 카드 측: `provider_for_merchant(merchant)=='gotogate'`(:811)·**정확한 KRW 총액 일치**·승인일이 발송일 **±1일**·일대일(양쪽 유일성, :825-830은 **취소 건 포함** 전체 gotogate reservation의 동일 총액 사건 수로 유일성 판정)·purchase·미점유·수동 교정 없음·중복/환불 플래그 없음. 산출: service_period 표시 + item 항공료 + `ota_evidence kind='reservation_period_inferred', payment_verified=False`. **읽기 전용 표시**(결제·여행·예약 관계 생성 없음). 오답 기간·금액·관측일은 게이트웨이 카드의 항공일 표시를 조용히 바꾼다.
- **별칭**: ota_matching_defaults.py:18 `gotogate: ['gotogate','고투게이트']`, :49 승인 레코드 '이니시스(일반)-고투게이트코리아유'(소유자 스크린샷 2026-10-30), :142 `provider_for_merchant`. 표시 테스트의 '이니시스(빌링)-…'은 기본 별칭 '고투게이트' 부분문자열로 해석된다(소비자 측, 이식 무관).
- **분류 마커(파서 아님)**: automatic_classification.py:116(항공료 regex에 gotogate|고투게이트)·:367(airfare_ota), rules.py:105·115 — 이식 무관.
- **교차 파서 의존 없음**: `mytrip_mail` import는 ota_payments.py:209와 테스트 2곳뿐(grep `*.py` 전체 13건). **삭제 차단 의존이 없다**(traveloka→airline과 반대).
- 부수: 테스트 간 결합 — test_ledger_stay_evidence.py:359가 test_mytrip_mail.confirmed를 재사용(§5).

## 7. 위험 — 조용한 오답 후보

1. **무효 날짜 1건 → 메시지 전체 기각**(L21-25): 월 0/13·일 0/32·2월 30·비윤년 2월 29·**연도 0000**. 행 단위 skip으로 옮기면 유효한 leg가 살아나 기간·금액이 조용히 생긴다.
2. **연도 0000 가드 신규**: Python MINYEAR=1. `time` 크레이트 연도 0 수용 여부와 무관하게 `year >= 1` 명시 가드(airbnb calendar 헬퍼에 없던 것).
3. **기간 상한 경계**: >366 기각·**366 허용**·단일 leg(0일) 허용. 가는/오는 구분 없는 min/max — 왕복이 역순이어도 그냥 swap.
4. **totals 문자열 집합 비대칭**(L26 vs L58): 한 본문에 '224,682.00'+'224682.00' → 2종 → **facts 기각**. 다른 메시지에서 같은 금액 다른 표기 → 정규화 후 동일 → **conflict 아님**. 집합을 정규화 금액으로 옮기면 양쪽 다 오답.
5. **쉼표 전수 제거**(L29): '1,,,' → 1. 선행 [0-9] 보장. amount 0 기각('0.00'·'000').
6. **`.00`만 허용**: '.50'·'.000'은 TOTAL 불매치 → 집합 공집합 → 기격. 소수점 일반화로 옮기면 오답.
7. **TOTAL 말미 `\b` 후처리**(§3.2): Nl/No(Ⅳ·①)·결합표기(U+0301)에서 naive 크레이트 `\b`가 오답. **ASCII [0-9]** — Nd 금액캡처로 바꾸면 전각 금액이 새로 매치돼 오답.
8. **ORDER 무경계·문자열 동일성**(§3.4): 긴 숫자런 내부 매치, 전각/ASCII 혼재 기각, 전각 booking_ref 보존.
9. **confirmed 우선**(L46-50) — airbnb(withdrawn 우선)와 반대 방향이지만 mytrip은 완전 앵커라 동시 매치 불가. **후행 잡음 subject**(예: '…주문 번호 1111-222-333 취소')는 CONFIRMED 실패 → WITHDRAWN 분기로 떨어져 본문을 취소시킨다.
10. **취소 전파·sticky**(L38·49·68): 인증된 비확인 WITHDRAWN subject 메일 1건이 본문 속 **모든** 주문(미관측 포함)을 취소; 재확인해도 cancelled 유지; 취소만 있으면 사건 없음; 미인증 메일은 취소 기여 없음.
11. **facts/sent 게이트**(L54): sent None(발송일 파싱 불가·미래 발송)이면 확인 행도 조용히 제외 — digest·source_ids에 흔적 없음.
12. **message_id 문자열 정렬**(L39·57): 'm10'<'m2'. rows[-1]이 period·amount·source_digest를 결정(L60·72) — 날짜 최신이 아님.
13. **conflict 시 null 범위**(L65-67): amount·amount_krw·**currency**·service_period가 None. currency None은 표시 게이트(:794 KRW)에서 탈락 — conflict 사건은 표시도 안 된다. source_digest·reservation_observed_on은 유지.
14. **reservation_observed_on 중복 제거·정렬**(L71): 同日 재발송 → 1일(표시 pairing 가능), 다른 날 재발송 → 2일(**표시 pairing 차단**, 파서는 유지). 표시 측 len(days)==1 게이트와 결합.
15. **observation_ids digest순 정렬**(L78)·source_digests 리스트 중복 허용(L72)·identity_source_ids 동일 리스트(L73).
16. **사건 키 집합 정확**(25키, evidence_status='reservation_only'·provider='gotogate'·item='항공료'): airbnb 템플릿을 복사하면 evidence_status·reservation_observed_on·금액 필드에서 오답. 골든 전체 객체 비교가 누락/추가를 잡는다.
17. **digest float 직렬화·무한 int 금액**: message에 float 필드가 있으면 Python repr vs serde_json 지수 표기 차이 가능; 금액 i64 초과는 이론적 발산(§9). 차등 사례·문서화 필요.
18. **Unicode 테이블 드리프트**: pyre 전수 가드(traveloka ddb937f6)가 Nd를 지킨다. strip 공백 집합(§3.3)은 신규 차등.
19. **소비자 영향**: 결제 매칭은 NOT_CARD_CHARGE라 결제 위험 없음. **표시 위험**(게이트웨이 카드 항공일). traveloka 검수 차단 3종(집합 중복 f52eafc7, ASCII digit 65de53b1, Nd 블록 d11a4b8b)이 mytrip에도 그대로 적용.

## 8. 구현 단계 초안 + 검증 명령

전제: 오프라인 골든 대조 단위. **운영 배선 전환·스위치 신설·Python 삭제 아님**(추가 전용).

| 단계 | 파일 | 내용 |
| --- | --- | --- |
| 1 | `tools/core_bridge/mytrip_golden.py`(신규) | 합성 메시지 → `collect()` 출력 JSONL 생성기. airbnb_golden.py 패턴(덮어쓰기 거부). 사례: 기존 테스트 4종 + 적대 — **leg**: 단일·중복 dedup·366일 허용/367일 기각·월 0/13·일 0/32·2월 29 윤년/비윤년·연도 0000·유효 leg 사이 무효 1건(전체 기각)·전각/아랍 Nd 연도월일·혼합 폭·불릿 ・(U+30FB) 불매치·U+00A0/U+001C 공백·오는 편만. **TOTAL**: '.50'/'.000' 기각·정수 금액·'0.00' 기각·'1,,,'→1·한 본문 '224,682'+'224682' 기각·메시지 간 동일 금액 다른 표기 conflict 아님·KRWE/KRW1/KRW_/KRW원 불매치·KRWⅣ 불매치·KRW+U+0301 매치·krw 불매치·USD 불매치. **ORDER**: 본문 주문 없음·2종·긴 숫자런 내부·전각 subject+body(문자열 보존)·전각+ASCII 혼재. **subject**: 선행/후행 잡음·마침표 없음·U+001C·말미 개행·빈 subject·미인증·후행 취소 단어(Withdrawn 분기). **취소**: 환불/취소 subject·복수 주문 전파·미관측 주문·취소만(사건 없음)·재확인 sticky·미인증 취소 무효. **집계**: m2/m10 정렬·同日 재발송 dedup·다른 날 재발송 2일·conflict null 범위+source_digest 유지·중복 digest·sent=None 행 제외·inventory empty/합성 non-empty·주문 2종 사건 정렬 |
| 2 | `core/golden/synthetic/mytrip_mail.jsonl`(신규) | 단계 1 생성물. 줄당 `{case_id, input={messages,inventory}, expected={events}, sha256, bytes, chars}` |
| 3 | `core/crates/core/src/extract/pyre.rs` | **Python 공백 strip 헬퍼 추가**(§3.3) + 단위 테스트. 동작 보존 추가 — **traveloka 28건·airbnb 31건 골든 바이트 동일이 회귀 가드**. 대안: mytrip.rs 인라인 클로저(pyre 무변동) |
| 4 | `core/crates/core/src/extract/mytrip.rs`(신규) | `MytripInput`/`MytripMessage`(deny_unknown_fields), 패턴 5종, `_facts` 등가(ORDER 게이트·LEG 달력+**year≥1 가드**·366 상한·TOTAL ASCII 집합+`\b` 후처리+쉼표 제거), collect 등가(집계·정렬·조립 25키·ID). `digest.rs`·`dates::calendar` 재사용. §7 쿼크 보존 |
| 5 | `core/crates/core/src/extract.rs` | mod 선언 + pub use만(L5-13 구역). **운영 배선 변경 없음** |
| 6 | `core/crates/core/tests/mytrip_golden.rs`(신규) | 사례별 events 필드 + canonical 바이트·sha256·bytes·chars 대조, 건수 가드, 미인증/기형 입력 거부, 쿼크 단위 테스트(전체 기각·연도 0000·문자열 집합·\b 후처리·strip) |
| 7 | (후속 단위, 이 PR 아님) | 사실 수준 운영 배선 설계(브리지 공급자 스위치 vs 조립 계층). 계획 L86 생산자 혼합 금지 충족 방안 |

검증 명령(구현 단위에서 실행):
```
python -X utf8 -m tools.core_bridge.mytrip_golden          # 골든 생성(덮어쓰기 거부)
cargo fmt --check && cargo clippy --workspace              # core/ 에서
cargo test -p cost-core mytrip                             # 신규 골든·헬퍼
cargo test -p cost-core airbnb                             # pyre 변경 회귀(31건)
cargo test -p cost-core traveloka                          # pyre 변경 회귀(28건)
cargo test -p cost-core extract_golden                     # 기존 골든 무변동
python -B -m pytest -q tests/card_pipeline/test_mytrip_mail.py tests/card_pipeline/test_ota_alias_four_providers.py webapp/tests/test_ledger_stay_evidence.py
python tools/run_quality_checks.py --base origin/main --run
```
수락 기준: 신규 골든 전 사례 필드+바이트 동일, 기존 extract.jsonl(50건)·airbnb_mail.jsonl(31건)·traveloka_mail.jsonl(28건) 무변동, Python 테스트 무변동. 보호 입력 새 기준(7,965건·3c6c46f5…) 대조는 배선 단계에서 운영 담당(이 단위는 합성 골든만).

## 9. 확신 없는 지점 (모른다)

1. **Python `\s`/`str.strip` 전체 코드포인트 집합**: U+001C-1F 차이는 pyre.rs:15 주석·단위 테스트로 확신 높음. 전체 집합 차등 검증은 미수행.
2. **re.I vs `(?i)` 폴딩 경계**: cancel/refund 글자에는 특수 단순 폴딩 문자가 해당 없어 등가 확신 높으나, 전각 라틴 불매치 등 차등 사례 미실측.
3. **`time` 크레이트 연도 0 수용 여부**: 이 호스트 registry 소스 미확인. `year >= 1` 가드로 무력화하므로 판정에 영향 없음 — 가드 전제만 기록.
4. **무한 자릿수 금액**(Python int vs serde_json i64/u64): 20자릿수 이상 금액에서 이론적 발산. 정책 결정(명시 상한+문서화 vs 임의 정밀도) 필요. 골든은 범위 내로 제한하고 발산을 문서화하는 것을 권고 — 미결.
5. **float 직렬화**(Python repr vs serde_json 지수 표기): message digest에 float 필드가 있는 차등 사례 필요 — 미실측(airbnb §9.4 동일).
6. **LEG 그리디 `\d{1,2}` 백트래킹 캡처 등가**: 크레이트 leftmost-first 문서화 기준 등가. '12월345일' 류 적대 차등 미수행.
7. **보호 입력 새 기준의 gotogate 사건 수**: 합성 extract.jsonl은 0건이나 운영 기준(7,965건)에 몇 건인지 미확인(보호 경로 D:/WebLedgerHost 이 조사 범위 밖). 배선 수락 대조에서 확인.
8. **사실 수준 운영 배선**: 브리지 공급자 스위치 vs 조립 계층 이식이 계획 L86과 양립하는지 — 후속 설계 결정(airbnb §9.7 준용).
9. **기록 불일치 2건(판정 무관, 기록 정정 대상)**: ① airbnb 보고서는 extract.jsonl "51건"이라 했으나 실측 50건(`find /c`·`findstr case_id` 일치, #1078에서 무변동 git 확인). ② handoff·커밋 메시지는 airbnb 골든 "26건"이라 했으나 파일·생성기 실측 31건. mytrip 단위에는 영향 없음 — 별도 기록 정정 단위에서 다룰 것을 권고.

## 10. 조사 범위 준수

- 읽기 전용: 파일 수정 없음(이 문서 제외), 커밋·push 없음, 테스트·cargo 실행 없음, 운영 DB·D:/WebLedgerHost 접근 없음, 고객 원문 미접촉.
- graphify 우선: 소비자·헬퍼 위치를 graphify query로 찾은 뒤 해당 줄만 판독. 줄 번호 grep 확정.
- 골든 0건은 대소문자 무시 grep(상위집합)으로 검증 — case-sensitive 0보다 강한 조건. 건수는 find /c + findstr 파이프 2방법 일치.
- 위임 질문 답변 위치: ① 계약 §1, ② 의존 §2·§6, ③ 정규식 §3, ④ 쿼크 §4·§7, ⑤ 테스트·골든 §5, ⑥ 소비자 §6.
