# M6 Airbnb 메일 파서 Rust 이식 조사 (2026-11-21)

- 위임: Cost Codex V4 읽기 전용 조사. 코드 수정·커밋·push·테스트 실행 없음. 이 문서가 유일한 산출물이다.
- 방법: `graphify query` 우선 탐색(graphify-out/graph.json 존재, 30,954 노드) 후 결과 위치의 원본만 판독. 줄 번호는 grep·read로 확정.
- 기준: detached HEAD `7d343bc456a2982d4238d4a72ec5bec666ce47d4`(PR #1076 Traveloka 이식 병합 직후). 작업트리 clean(`.qwen/`·`graphify-out/` 미추적만). 퇴역 계획 [m6-extractor-retirement.md](../../playbooks/m6-extractor-retirement.md) 3단계 (b) 두 번째 단위(순서 L66: traveloka→**airbnb**→mytrip→rakuten→airline→…).
- 선행 근거: [Traveloka 이식 조사](m6-traveloka-port-20261120.md), [session_handoff.md](../../session_handoff.md) L5-13(Traveloka 단위 완료·독립 검수 APPROVE·차단 3종 수정).

## 0. 판정

**이식 가능 — 추가 전용(additive) PR, 선행 차단 조건 없음.** Traveloka의 "조건부"를 건 선행 조건(`parseaddr`·`html.unescape` Rust 동등성 검증)이 이 단위에는 **없다**. 인증·본문·`sent_day` 공용 헬퍼가 Python 브리지에 남고 경계 값만 넘기므로, Rust는 정규식 3개·기간 추론·집계·사건 조립·digest만 소유한다. 구현 조건(합성 골든 신규, 공유 헬퍼 회귀 가드, 차등 사례 고정)은 §8 단계 안에서 해소한다. 기존 `extract.jsonl` 골든에 airbnb **0건**이라 새 사실 수준 골든이 필수다.

## 1. 파서 계약 (app/airbnb_mail.py, 77행)

Traveloka와 구조가 다르다: traveloka는 단건 `references()`/`extract()`(fact 계층)이고 사건 조립은 `ota_payments._parse_mail_events`가 한다. **airbnb는 `collect()` 하나가 파싱+집계+조립+ID 전부**다(fact/event 분리 없음).

### collect(messages, inventory=()) — L31-77
- L35 `sorted(messages.items())` — message_id **문자열** 오름차순으로 순회.
- L36-38 `ota_mail.authenticated_headers(message, ('airbnb.com',))` 게이트. 실패 시 skip.
- L40 `subject = str(headers.get('subject') or '')` — None/빈 값 → `''`.
- L41-43 `CONFIRMED.search(subject)`, `CANCELLED.search(subject)`. 둘 다 없으면 skip. **둘 다 있으면 withdrawn 우선**(L48).
- L44-46 `codes = set(CODE.findall(ota_mail.message_text(message)))` — **본문 전용**(subject 아님, Cf 제거 없음). `len(codes) != 1`(0개 또는 2개+)이면 skip.
- L48-50 withdrawn이면 `cancelled.add(code)` 후 continue — **sent/period 불필요**.
- L51-54 confirmed면 `sent = ota_mail.sent_day(message, headers)`; `period = _period(confirmed, sent) if sent else None`; period가 있을 때만 `observed[code].append((message_id, period, core._digest(message)))`. **period 무효 행은 digest·source_ids에 전혀 기여하지 않는다.**
- L56 `sorted(observed.items())` — code(ASCII) 오름차순으로 사건 생성.
- L57 `periods = {tuple(p.values()) for _, p, _ in rows}` — (starts_on, ends_on) 튜플 집합. `len != 1` → conflict.
- L58 `source_ids = ['mail:' + mid for mid, _, _ in rows]` — message_id 순서.
- L62-63 `service_period = rows[-1][1] if len(periods)==1 else None`; `service_period_conflict = len(periods)!=1`.
- L64 `reservation_status = 'cancelled' if code in cancelled else 'observed'` — **취소는 sticky**(재확인해도 취소 유지).
- L67 `source_digest = rows[-1][2]`(마지막 message_id의 digest); `source_digests = [d for _,_,d in rows]`(**리스트, 중복 허용·집합 아님**).
- L68 `identity_source_ids = source_ids`(같은 리스트).
- L69 `source_inventory = list(inventory)`(얕은 복사, 기본 `()`→`[]`); `paid_on_semantics='missing'`.
- L72-75 `identity = 'airbnb:'+code`; `source_lineage_ids=[identity]`(**mail digest 아님 — code 기반 identity**); `observation_ids = sorted('obs_'+core._digest([identity, source]) for source in source_ids)`(**digest hex 순 정렬, message 순 아님**); `ota_event_id = core._event_id([identity])`.
- 사건 키 집합(24개): provider, booking_ref, event_type='reservation', item='숙박비', paid_on/amount/currency/amount_krw/card_last4=None, service_period, service_period_conflict, reservation_status, payment_status='unknown', evidence_status='reservation_observed', evidence_kind='authenticated_reservation_mail', source_digest, source_digests, source_ids, identity_source_ids, source_inventory, paid_on_semantics, source_lineage_ids, observation_ids, ota_event_id. **source_binding_ids·refund_status·payment_id·card_issuer 없음**(결제 경로와 다른 모양).
- 취소만 있고 확인 관측이 없는 code → **사건 없음**. 사건은 observed에서만 생성.

### _period(match, sent) — L15-28
- L17 `start_month, start_day, end_month, end_day = (int(v) if v else None for v in match.groups())` — 캡처는 `\d{1,2}`라 빈 문자열 불가, None만 필터. **유니코드 Nd `int()`**(전각 ５→5).
- L19 `start = date(sent.year, start_month, start_day)` — ValueError(월 0/13, 일 0/32, 2월 30, 비윤년 2월 29) → None. **연도+1 재시도 없음**(첫 생성 실패가 곧 None).
- L20-21 `if start < sent - timedelta(days=31): start = date(sent.year+1, ...)` — **strict `<`**(31일 경계는当年 유지). 두 번째 생성도 ValueError 가능(윤년 2월 29가 다음 해 비윤년으로) → None.
- L22 `end_month = end_month or start_month` — **`0`은 falsy → start_month로 치환되는 쿼크**(`unwrap_or`가 아님).
- L23 `end = date(start.year + (end_month < start_month), end_month, end_day)` — bool 덧셈(연말 넘김), ValueError → None.
- L26 `if not 0 < (end - start).days <= 60: return None` — **0일(당일) 거부, 60일 포함 상한**.
- L28 `{'starts_on': start.isoformat(), 'ends_on': end.isoformat()}`.

## 2. 경계 제안

### Rust가 소유할 것 (collect 전체)
정규식 3개 매칭+후처리, `_period` 연도 추론·달력 검증, 메시지별 digest, observed/cancelled 집계, 정렬, 사건 조립(24개 키 전부), `source_lineage_ids`/`observation_ids`/`ota_event_id`, conflict 플래그. 입력은 다건 메시지 + inventory, 출력은 code 정렬된 사건 배열.

### Python 브리지에 남길 것 (경계 값)
| 헬퍼 | 위치 | 경계 값 | 근거 |
| --- | --- | --- | --- |
| `authenticated_headers` | ota_mail.py:177-193 | `subject: Option<String>`(None=미인증) | parseaddr·DKIM 정렬·owner_collected. 8종 파서 공용. traveloka 선례(TravelokaInput.subject, traveloka.rs:97-104). |
| `message_text` | ota_mail.py:41-46 | `raw_text: String`(본문 전용, **Cf 제거 없음**) | body_text(HTML·base64·unescape)가 Python에 남으므로 Rust 본문 파싱 불요. airbnb는 Cf 제거를 쓰지 않는다(traveloka와의 차이). |
| `sent_day` | ota_mail.py:371-385 | `sent_day: Option<String>`(KST ISO 날짜) | **공용 헬퍼로 남긴다.** RFC2822 `parsedate_to_datetime`+KST 변환+수신 지연(미래 발송 거부)은 메일 계층 의미. 호출처 10곳(airbnb·airline·forest×2·forest_payment·mytrip·ota_mail×2·ota_payments×2, grep 확인). Rust 재구현 시 parsedate 동등성 리스크 → 경계 값으로 제거. |
| 메시지 원본 | — | `message: Value`(전체 dict) | digest 입력. traveloka source_sha256 선례(traveloka.rs:155). |
| inventory | ota_mail.py:133-134 | `inventory: Vec<Value>`(pass-through) | `{'kind','path','messages','collection'}` — **운영 경로 포함 → 골든은 합성만**. |

입력 형태(제안): `AirbnbInput { messages: BTreeMap<String, AirbnbMessage>, inventory: Vec<Value> }`, `AirbnbMessage { message, subject, raw_text, sent_day }`, `deny_unknown_fields`. BTreeMap 순회 = Python `sorted(messages.items())`(UTF-8 바이트 순 = 코드포인트 순). **stripped_text 필드 불요**(airbnb는 Cf 제거 안 함).

### digest 대응 — 이미 Rust에 있다
- `core._digest`(ota_payments.py:42-44) = `sha256(json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False, default=str))`. **`digest.rs:16 python_json_compact` + `:22 sha256_hex`가 정확히 같은 레시피**(키 코드포인트 순, 이스케이프 동일). `default=str`은 에뮬레이션 안 하지만 **도달 불가**: 메시지는 `json.loads`(ota_mail.py:129) 또는 `owner_record`(mail_collect.py:290-302, 순수 dict) 출신이라 JSON 타입만. 경계 입력도 `serde_json::Value`(이미 JSON).
- `core._event_id`(ota_payments.py:47-50) = `'ota_'+_digest(sorted(set(ids)))`. `extract.rs:251 event_id`(private)가 BTreeSet 정렬·중복 제거로 이미 에뮬레이션. airbnb는 단일 identity라 `digest.rs`로 직접 계산 가능.
- `observation_ids` = `'obs_'+digest([identity, source])` — 문자열 2개 리스트, compact JSON. `digest.rs` 재사용.
- 사건 키 순서는 골든이 `sort_keys=True`로 비교하므로 삽입 순서 재현 불요(Value 객체 비교는 순서 무관). **리스트 순서**(events=code순, source_ids/source_digests=message_id순, observation_ids=digest순)는 정확히 재현해야 한다.

### 왜 traveloka와 경계가 다른가 (collect 전체 이식)
1. airbnb는 fact/조립 분리가 없어 `collect`이 곧 완성 사건 생산자다. 단건 fact만 옮기면 Python에 집계·정렬·ID가 남아 2단계 이식이 되고, 존재하지 않는 중간 계약을 발명하게 된다.
2. **교차 파서 의존이 없다**(grep: `airbnb_mail` import는 ota_payments.py:209와 테스트뿐). traveloka의 airline 의존 같은 삭제 차단이 없어 배선 단계에서 모듈 전체 교체가干净하다.
3. 퇴역 계획 L86 "한 실행 안에서 생산자를 섞지 않는다"는 **한 생산자를 Rust/Python으로 쪼개지 말 것**으로 읽힌다("Rust 다수·Python 소수 공존"은 허용). collect 전체 이식(생산자 하나 통째 Rust)이 단건 분할(한 생산자 반쪽씩)보다 이 제약에 부합한다. 배선 단계에서 재확인(§9).

## 3. 정규식 동등성표 — 3개

airbnb_mail.py 정규식은 **3개**(L10·11·12)뿐. 헬퍼 정규식(auth·body_text)은 Python에 남으므로 이식 대상 아님. Rust `regex` **1.13.1**(Cargo.lock:321-323, Cargo.toml `regex="1"`). 기존 헬퍼: traveloka.rs `PY_SPACE`:29, `word_boundary_after`:224, `is_python_word`:238, `is_nd`:247, `nd_value`:279, `read_digits`:319.

| # | 위치 | 패턴 | flags | 동등성 쟁점과 변환 |
| --- | --- | --- | --- | --- |
| 1 | L10 | `\bHM[A-Z0-9]{8}\b` | 없음 | **양방향 `\b` 후처리**(아래). 대소문자 구분(re.I 없음) → 소문자 hm 불매치. `[A-Z0-9]` ASCII 고정. |
| 2 | L11 | `^예약 확정(?: 안내)?\s*:\s*(\d{1,2})월\s*(\d{1,2})일\s*~\s*(?:(\d{1,2})월\s*)?(\d{1,2})일` | 없음 | `^`=텍스트 시작(re.M 없음 → Rust 기본 `^` 등가, `(?m)` 금지). `\s`→`PY_SPACE`. `\d`→`\p{Nd}`. 한글 리터럴(대소문자 없음). **`예약 확정`의 공백은 리터럴 U+0020**(\s* 아님). 선택 종료월 그룹. `$` 없음 → prefix 매치. 캡처 `int()`는 Nd. |
| 3 | L12 | `예약이 취소되었습니다` | 없음 | 순수 리터럴 부분문자열. `.search`→`.is_match`. 자명 등가. |

### 3.1 의미 차이와 변환 (traveloka 보고서 §4.1 준용)
- **`\d`**: regex 크레이트 기본 유니코드 모드 `\d`=`\p{Nd}`=Python `\d`. ASCII-only는 `(?-u)`일 때뿐. 명시적 `\p{Nd}` 사용(traveloka 선례).
- **`\s`**: Python `str.isspace()` = White_Space **+ U+001C..U+001F**. Rust `\s`는 후자 미포함 → `[\s\u{1C}-\u{1F}]`(PY_SPACE) 치환.
- **`\b`/`\w`**: Python `\w`=`L*+Nd+Nl+No+_`; Rust `\w`=`Alphabetic+M+Nd+Pc+Join_Control`. 차이: **Nl/No(Ⅳ·①)는 Python만 단어 문자, 결합 표기(U+0301)·Join_Control은 Rust만**. → 크레이트 `\b`를 쓰지 않고 `is_python_word`(`char::is_alphanumeric||'_'`, traveloka.rs:238)로 **양방향 후처리**.
- **`^`**: re.M 없으면 양쪽 모두 텍스트 시작만. 등가.
- **캡처 semantics**: regex 크레이트 leftmost-first는 Python 백트래킹과 캡처 결과 등가(문서화). 선택 그룹·그리디 `\d{1,2}` 백트래킹 차등 사례로 고정(§9).

### 3.2 CODE 양방향 후처리 등가 논거 (traveloka는 말미만, airbnb는 선도+말미)
`\b` 없는 `HM[A-Z0-9]{8}`로 findall 후, **선행 문자가 Python 단어 문자면 기각(선도 `\b`), 후행 문자가 Python 단어 문자면 기각(말미 `\b`)**.
- 후보 구간 = HM + 8개 ASCII 영숫자 = **전부 양쪽 의미에서 단어 문자**. 구간 내부 어떤 위치도 Python `\b`가 성립 불가(양 이웃 모두 단어 문자) → **기각된 후보 안에 유효 Python 매치가 숨을 수 없다**.
- 스캔 정렬: Python은 `\b` 실패 시 시작을 +1 전진하지만 후보 내부에서는 `\b` 불가라 후보 끝으로 점프; Rust `captures_iter`도 기각 후 후보 끝에서 재개 → 동일. 좌→우 비겹침 귀납으로 매치 집합 동일.
- `set` 중복 제거 + `len==1` 게이트라 순서 무관(traveloka references의 first-seen 순서 문제보다 단순).
- **적대 사례(골든 고정)**: `①HMABCDEFGH`(선도 No → 불매치), `HMABCDEFGHⅣ`(말미 No → 불매치), `HMABCDEFGH\u0301`(말미 결합표기 → **매치**, Rust naive `\b`는 불매치라 오답), `XHMABCDEFGH`·`_HMABCDEFGH`(선도 단어 → 불매치), `HMABCDEFGH_`·`HMABCDEFGHX`(말미 단어 → 불매치), `hmabcdefgh`(소문자 → 불매치), `HMABCDEFG`(7자 → 불매치), `HMABCDEFGHI`(9자 → 말미 I 단어 → 불매치), 본문 내 중복 코드(set→1), **subject에만 코드**(본문 전용 검색 → 불매치).

## 4. _period Rust 대응

- `sent_day` ISO 문자열 → `dates::calendar::parse_iso`(calendar.rs:27, strict YYYY-MM-DD, ValueError↔DateError). `isoformat()` 출력은 항상 이 형식.
- 날짜 생성: `time::Date::from_calendar_date`(traveloka.rs:326 calendar / calendar.rs:46과 같은 u8/i32 가드). 월 0/13·일 0/32·2월 30 → Err → None.
- 연도 추론: `start < sent - Duration::days(31)`(strict). 두 번째 생성 실패도 None.
- 일수 차: `(end - start).whole_days()`(closed_period.rs:260 선례). `0 < days <= 60`.
- **쿼크 재현 필수**: ① `end_month or start_month`의 **0-falsy 치환**(Rust `match em { None|Some(0) => sm, Some(v)=>v }`, `unwrap_or` 금지). ② 첫 생성 실패 시 연도+1 재시도 없음. ③ 윤년 2월 29 양방향(비윤년 sent.year→즉시 None; 윤년→다음 해 비윤년→None). ④ 31일 경계 strict `<`. ⑤ 당일(0일) 거부.
- Nd 캡처 `int()`: `read_digits`(traveloka.rs:319, nd_value 블록 테이블) 재사용 — 전각 월/일 지원. **traveloka 검수 차단 2종(ASCII digit 65de53b1, Nd 블록 d11a4b8b)이 airbnb 월/일 파싱에 그대로 적용된다.**

## 5. 테스트·골든 현황

- **tests/card_pipeline/test_airbnb_mail.py: 테스트 5개**(L12·23·32·37·44), `collect` 호출 8회. 형태: 합성 `owner_record`(mail_collect.py:290-302, base64url 본문·Date→internal_date·owner_collected=True). 사례: 확인→reservation+기간+무결제+NOT_CARD_CHARGE 연동(L12), 연도 추론·월/년 넘김(L23), 취소→cancelled(L32), 미인증 도메인 경계·코드 2개·비매치 subject 무시(L37), 기간 충돌(L44).
- **webapp/tests/test_ledger_stay_evidence.py: 표시 테스트 3개**(L323·343·350, L343은 2변형 parametrize). `airbnb_stay` 픽스처(L314-317)가 `test_airbnb_mail.confirmed`를 재사용해 `collect` 호출 → **파서 골든이 깨지면 표시 테스트도 깨진다**.
- **core/golden/synthetic/extract.jsonl: 51건, airbnb 0건**(findstr精确 `"provider": "airbnb"` 0 + 대소문자 무시 `airbnb` 0, exit 1). 사건 조립 이후 계층만 덮으므로 airbnb 파서 단위에는 **새 골든 필요**.
- 선례: `core/golden/synthetic/traveloka_mail.jsonl`(PR #1076, 합성 28건). 생성기 `tools/core_bridge/traveloka_golden.py`(`stages()`가 경계 값 계산, `case()`가 references/fact+sha256/bytes/chars, `build()`가 기존 파일 덮어쓰기 거부). 소비 `core/crates/core/tests/traveloka_golden.rs`(필드+canonical 바이트 대조, 건수 가드, 미인증/기형 입력 거부).
- airbnb 골든 생성기 제안: `tools/core_bridge/airbnb_golden.py` — `stages(record)` = `{message, subject: str(auth[0].get('subject') or '') if auth else None, raw_text: message_text(record), sent_day: sent_day(record,headers).isoformat() if sent else None}`; input = `{messages:{id:stages}, inventory}`; expected = `{events: collect(messages, inventory)}`; sha256/bytes/chars = compact canonical. **합성 전용**(고객 원문·운영 경로 금지).

## 6. 의존 소비자

- **생산 사슬**: `costcore extract` → bridge.rs `extract-sources` → tools/core_bridge/commands.py → extract_sources.py:53 `'mail_events': op._mail_events(...)` → ota_payments.py:57 `_mail_events`(메모+deepcopy) → :109 `_parse_mail_events` → **:209 import, :212 `airbnb_mail.collect(messages, inventory)`** 반환 배열에 concat. airbnb 사건은 `ota_booking_context.attach`·`attest`(결제 경로 :205-208)를 **거치지 않는다**.
- **사건 소비자**:
  - `webapp/ledger_stay_evidence.py:119` → `:849-895 _airbnb_code_periods`: provider=='airbnb'(:859), 카드 descriptor `airbnb\s*\*\s*(HM[A-Z0-9]{8})\b` re.I(:866, **소비자 측 정규식 — 이식 대상 아님**), 기간 0<days<=60 재검증, reservation_status=='observed'·conflict 없음·evidence_kind=='authenticated_reservation_mail'(:882)·source_digest 있음·단일 사건/단일 카드·purchase·환불/중복 플래그 없음 요구. **읽기 전용 표시**(숙박 기간).
  - `ota_payments.py:1988-1995 match_ota_payment_events`: airbnb reservation은 `_event_is_paid` false, provider가 RESERVATION_ONLY 목록('toyoko','forest','rakuten')에 없음 → **NOT_CARD_CHARGE**(자동 결제 매칭 안 함). 테스트 L12가 확인.
- **교차 파서 의존 없음**: `airbnb_mail` import는 ota_payments.py:209와 테스트 2곳뿐(grep). airline이 traveloka를 호출하던 것과 달리 **삭제 차단 의존이 없다**.
- 부수: app/rules.py:103 'AIRBNB' 분류 마커(파서 아님, 이식 무관).

## 7. 위험 — 조용한 오답 후보

1. **message_id 문자열 정렬**(`'m10' < 'm2'`)이 `rows[-1]` → source_digest·service_period 선택을 결정. Rust BTreeMap 바이트 순 ≡ Python 코드포인트 순이지만 골든으로 고정.
2. **observation_ids는 digest hex 순 정렬**(message 순 아님). 정렬 키를 틀리면 ID가 조용히 바뀐다.
3. **취소 sticky**: 취소 후 재확인 → cancelled 유지; 취소만 → 사건 없음; period 무효 취소도 cancelled; confirmed+withdrawn 동시 매치 → withdrawn 우선.
4. **period 무효 행 완전 제외**: 무효 행을 남기면 source_ids/digests가 늘고 conflict 플래그가 뒤집힌다.
5. **service_period_conflict**: (starts,ends) 튜플 집합 크기. 같은 기간 다른 메시지 → conflict 아님.
6. **end_month=0 falsy 쿼크**(L22): `unwrap_or`로 옮기면 `0월` 종료에서 다른 기간이 나온다.
7. **2월 29 이중 ValueError**: 첫 생성 실패→연도+1 재시도 없음; 연도+1 생성 실패→None. 윤년 양방향.
8. **31일 strict `<`, 60일 포함, 0일 거부** 경계.
9. **CODE 양방향 `\b` 후처리**: Nl/No(Ⅳ·①)와 결합표기(U+0301)에서 naive Rust `\b`가 오답(§3.2). 선도 후처리는 traveloka에 없던 신규.
10. **CODE 본문 전용**(subject 코드 불인정) — traveloka references(subject+body)와 반대.
11. **CONFIRMED `^`·리터럴 공백·prefix 매치**: `예약  확정`(공백 2개)·선행 공백 subject → 불매치. `\s` 확장 집합(U+001C). 전각 월/일.
12. **digest float 직렬화**: message에 float 필드가 있으면 Python repr vs serde_json 지수 표기 차이 가능(§9). 차등 사례 필요.
13. **source_digests 리스트 중복 허용**(집합 아님): 동일 메시지 두 키 → [d,d].
14. **사건 키 집합 정확**(24개, source_binding_ids 등 없음): 골든 전체 객체 비교가 누락/추가를 잡는다.
15. **Unicode 테이블 드리프트**: `char::is_alphanumeric`(Rust) vs `str.isalnum`(Python 빌드). traveloka PY_WORD 단위 가드준용 + airbnb 양방향 차등.
16. **소비자 영향**: 오답 기간은 ledger 숙박 표시를 조용히 바꾼다(결제 매칭은 NOT_CARD_CHARGE라 결제 위험 없음, 표시 위험). traveloka 검수 차단 3종(집합 중복 f52eafc7, ASCII digit 65de53b1, Nd 블록 d11a4b8b)이 airbnb에도 그대로 적용.

## 8. 구현 단계 초안 + 검증 명령

전제: 오프라인 골든 대조 단위. **운영 배선 전환·스위치 신설·Python 삭제 아님**(추가 전용).

| 단계 | 파일 | 내용 |
| --- | --- | --- |
| 1 | `tools/core_bridge/airbnb_golden.py`(신규) | 합성 메시지 → `collect()` 출력 JSONL 생성기. traveloka_golden.py 패턴(덮어쓰기 거부). 사례: 기존 테스트 5종 + 적대(연도 추론 31일 경계·2월 29 양방향·60일 상한·당일·end_month=0, m2/m10 정렬, 취소 후 재확인·취소만·무효 period 취소, 무효 행 제외, 코드 2개·subject 전용 코드·소문자 hm, Nl/No/결합표기 양방향, 전각 월/일, U+001C 공백·선행 공백 subject·리터럴 공백 2개, confirmed+cancelled 동시, 중복 digest 리스트, float 필드, inventory empty/합성 non-empty, sent=None) |
| 2 | `core/golden/synthetic/airbnb_mail.jsonl`(신규) | 단계 1 생성물. 줄당 `{case_id, input={messages,inventory}, expected={events}, sha256, bytes, chars}` |
| 3 | 공유 헬퍼 추출(권장) | traveloka.rs private 헬퍼(PY_SPACE:29·is_python_word:238·word_boundary_after:224·is_nd:247·nd_value:279·ND_BLOCK_STARTS:266·read_digits:319)를 `extract/pyre.rs`(가칭)로 이동 + **word_boundary_before 신규**. traveloka.rs는 import만. **동작 보존 리팩터 — traveloka 골든 28건 바이트 동일이 회귀 가드**. 대안: traveloka.rs 무변동을 원하면 airbnb.rs에 헬퍼 복제(후속 6종 파서 중복 비용). |
| 4 | `core/crates/core/src/extract/airbnb.rs`(신규) | `AirbnbInput`/`AirbnbMessage`(deny_unknown_fields), collect 등가(집계·정렬·조립·ID). `digest.rs` 재사용, `dates::calendar` parse_iso/iso, `time::Date` 연산. §1 쿼크·§3 후처리 보존 |
| 5 | `core/crates/core/src/extract.rs` | mod 선언 + pub use만(L5-10 구역). **운영 배선 변경 없음** |
| 6 | `core/crates/core/tests/airbnb_golden.rs`(신규) | 사례별 events 필드 + canonical 바이트·sha256·bytes·chars 대조, 건수 가드, 미인증/기형 입력 거부, 양방향 `\b`·기간 쿼크 단위 테스트 |
| 7 | (후속 단위, 이 PR 아님) | 사실 수준 운영 배선 설계(브리지 공급자 스위치 vs 조립 계층). 계획 L86 생산자 혼합 금지 충족 방안 |

검증 명령(구현 단위에서 실행):
```
python -X utf8 -m tools.core_bridge.airbnb_golden          # 골든 생성(덮어쓰기 거부)
cargo fmt --check && cargo clippy --workspace              # core/ 에서
cargo test -p cost-core airbnb                             # 신규 골든·헬퍼
cargo test -p cost-core traveloka                          # 공유 헬퍼 추출 회귀(28건 바이트 동일)
cargo test -p cost-core extract_golden                     # 기존 골든 무변동
python -B -m pytest -q tests/card_pipeline/test_airbnb_mail.py webapp/tests/test_ledger_stay_evidence.py
python tools/run_quality_checks.py --base origin/main --run
```
수락 기준: 신규 골든 전 사례 필드+바이트 동일, 기존 extract.jsonl·traveloka_mail.jsonl 무변동, Python 테스트 무변동. 보호 입력 새 기준(7,965건·3c6c46f5…) 대조는 배선 단계에서 운영 담당(이 단위는 합성 골든만).

## 9. 확신 없는 지점 (모른다)

1. **regex 크레이트 `\d`=Nd·`\s`=White_Space 파일 근거**: 문서 기준 확신 높으나 이 호스트 registry 소스 부재 — 차등 골든으로 확정(traveloka §9.4 준용).
2. **Python `\s` 전체 코드포인트 집합**: U+001C-001F 차이는 확신 높음, 전체 집합 차등 검증 미수행.
3. **`char::is_alphanumeric` vs `str.isalnum` Unicode 버전 드리프트**(Nl/No/Mn 경계): traveloka PY_WORD 가드준용하나 airbnb **선도** 경계 차등은 신규 — 미실측.
4. **float 직렬화**(Python repr vs serde_json 지수 표기): message digest에 float 필드가 있는 차등 사례 필요 — 미실측.
5. **CONFIRMED 캡처 semantics**(선택 종료월·그리디 `\d{1,2}` 백트래킹): regex 크레이트 leftmost-first 등가 문서화, 적대 차등 미수행.
6. **`parsedate_to_datetime` Rust 동등성**: 이 단위는 sent_day를 Python에 남겨 **회피**. 후속 메일 핵심(3(e)) 이식 시 필요 — 모른다.
7. **사실 수준 운영 배선**: 브리지 공급자 스위치 vs 조립 계층 이식이 계획 L86 생산자 혼합 금지와 양립하는지 — 후속 설계 결정(traveloka §9.8 준용). collect 전체 이식이 단건 분할보다 부합한다는 해석(§2)은 배선 단계 재확인.
8. **보호 입력 새 기준의 airbnb 사건 수**: 합성 extract.jsonl은 0건이나 운영 기준(7,965건)에 airbnb가 몇 건인지 미확인(보호 경로 D:/WebLedgerHost 이 조사 범위 밖). 배선 수락 대조에서 확인.

## 10. 조사 범위 준수

- 읽기 전용: 파일 수정 없음(이 문서 제외), 커밋·push 없음, 테스트·cargo 실행 없음, 운영 DB·D:/WebLedgerHost 접근 없음, 고객 원문 미접촉.
- graphify 우선: 소비자·헬퍼 위치를 graphify query로 찾은 뒤 해당 줄만 판독. 줄 번호 grep 확정.
- 골든 airbnb 0건은 findstr(대소문자 구분)精确 일치 + 대소문자 무시 재확인 둘 다 0(exit 1)으로 검증.
- 위임 질문 정정: airbnb 정규식은 3개(CODE·CONFIRMED·CANCELLED). `_digest`/`_event_id`는 digest.rs+extract.rs:247/251로 이미 대응. sent_day는 경계 값이 아니라 **공용 헬퍼로 Python에 남기고 결과만 경계 값으로** 넘기는 것을 권고.
