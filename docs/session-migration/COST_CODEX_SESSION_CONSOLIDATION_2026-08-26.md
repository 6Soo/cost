# COST Codex 세션 통합 정본 — 2026-08-26

이 문서는 `C:\AX\cost`에 묶인 폐쇄 대상 Codex 세션 89개의 작업 지식만 정제해 남기는 정본이다. 원문 전사본은 삭제 전 검증용 임시 증거이며 영구 보관물이 아니다. 예약번호·정책·실패 원인·미해결 작업은 보존하되, 개인식별정보와 인증정보는 재기록하지 않았다.

## Scope and preservation proof

- 고정 대상: 정확히 89개 Codex 세션, 합계 1,373,158바이트의 전사본.
- 고정 manifest SHA-256: `7630dd029b44d8f37d12427fd1377f8f41ea11a330d3e1c7fbc0668abc9c5876`.
- 전사본 추출 오류: 0건.
- 주제별 검토: 각 세션은 아래 8개 그룹 중 정확히 하나에 배정되었다.

| 그룹 | 세션 | 바이트 | 정본 절 |
| --- | ---: | ---: | --- |
| agoda-c-matrix-a | 13 | 136,983 | Agoda C-matrix A |
| agoda-c-matrix-b | 14 | 137,336 | Agoda C-matrix B |
| agoda-dom-canary | 25 | 154,500 | Agoda DOM and canary |
| agoda-retry-p1-p2 | 3 | 278,005 | Agoda retry pages 1-2 |
| agoda-retry-p3-p6 | 6 | 222,574 | Agoda retry pages 3-6 |
| agoda-detail-recovery | 17 | 267,315 | Agoda detail recovery |
| agoda-accounting-policy | 3 | 94,241 | Agoda accounting and policy |
| pipeline-webapp | 8 | 82,204 | Pipeline and web application |

- 기계적 식별자 보존 검사:
  - 문맥상 예약·작업 키로 판정된 식별자 193개 중 정본/영속 산출물 누락 0개.
  - 일반 10자리 식별자 277개 중 정본/영속 산출물 누락 0개.
  - 9자리처럼 보였던 `661557247`, `663245499`, `663246399`, `663906767`, `663907375`도 모두 영속 산출물에서 확인되었다.
- 기존 영속 산출물:
  - `outputs/agoda-paseo-page3-C03-20260822.json` — 37건.
  - `outputs/agoda-paseo-page4-C04-20260822.json` — 13건.
  - `outputs/agoda-paseo-session-recovery-20260826.json` — 복구 성공 6건, 미해결 4건. SHA-256 `a0c9503347819acd5e53adc69d0566b6191e6ae43cbbac65a9ac7b35ae17fa23`.
- 세션별 원문 SHA-256과 이 문서 절의 SHA-256 연결은 별도 `approval.json`에 남기며, 삭제 결과는 축약 JSONL 원장에 남긴다.
- 원문 전사본 두 벌과 임시 manifest/assignment 파일은 삭제 완료 및 부재 검증 후 영구 제거한다.

## Agoda C-matrix A

- 13개 세션을 모두 검토했다.
- 12개 세션은 브라우저를 이용할 수 없어 실제 수집으로 진입하지 못했다.
- 세션 `d2899ae4…`는 C05 S1에서 약 200개를 스캔·캡처한 정황이 있으나, 중단 조건을 지키지 않았고 최종 JSON을 남기지 않아 완료 산출물로 인정하지 않는다.
- 관련 예약·작업 식별자는 영속 산출물에서 보존됨을 확인했다.
- 후속 수집기는 다음을 필수로 유지한다: 브라우저 사전검사, 강제 취소 경로, 수정 제어, 지원 패널 실패 시 fail-closed.

## Agoda C-matrix B

- 14개 세션을 모두 검토했다.
- 세션 `0364c711…`은 C03 S1에서 1~3페이지 약 33개를 처리한 정황이 있으나 최종 JSON이 없어 완료로 인정하지 않는다.
- 세션 `f24f76f…`은 C07 S1에서 탐색 상태가 불명확해 결과를 채택하지 않는다.
- 나머지 12개 세션은 브라우저를 이용할 수 없었다.
- 관련 식별자는 영속 산출물에 보존되어 있다.

## Agoda DOM and canary

> 통합 워커 최종 보고 대기 중. 이 표시는 삭제 승인 전에 제거되어야 한다.

## Agoda retry pages 1-2

- U01 1페이지 시도는 39/40으로 부분 처리됐고 예약 `1759828442`가 불일치 대상으로 남았다.
- C01 1페이지 시도는 탐색 상태가 불명확했다.
- C02 2페이지 시도는 40건 중 33건을 캡처했고 7건은 실패했다.
- 부분 수치는 검증된 최종 산출물로 승격하지 않으며, 재개 시 페이지·행 키를 다시 대조한다.

## Agoda retry pages 3-6

- 3페이지: 37건 캡처, 상세 읽기 실패 3건.
- 4페이지: 13건 캡처 후 브라우저 연결이 끊겼으며 27건이 남았다.
- 5·6페이지: 실제 수집이 시작되지 않았다. 6페이지 40건이라는 수치는 주장만 있고 관측 근거가 없다.
- 관찰된 실패 분류: `NAVIGATION_STATE_UNKNOWN`, `PASEO_BROWSER_UNAVAILABLE`, `RETRY_EXHAUSTED`, `DETAIL_READ_FAILED`.
- 재개 시 페이지별 독립 체크포인트와 상세 패널 성공 증거가 없는 행의 승격을 금지한다.

## Agoda detail recovery

- 세션 정제 과정에서 다음 6건을 영속 복구 산출물에 기록했다: `1712295886`, `1714977171`, `1703632767`, `1709847157`, `1997544406`, `1679438284`.
- 미해결 4건:
  - `1698426325`, `1698427046`, `1698427296` — `DETAIL_READ_FAILED`.
  - `1625180324` — `PASEO_BROWSER_UNAVAILABLE`.
- 7페이지에서 추가로 미해결인 예약: `1679438347`, `1679438402`, `1679438822`, `1679438919`, `1709841661`.
- 단일 레인 시도에서 상세 정보가 확보되지 않은 예약: `1683778910`, `1687621609`, `1681854306`, `1685346271`, `1685346874`, `1968385259`, `1678503785`, `1681853186`.
- `1755579869`는 앞선 호텔 목록 주장과 달리 항공 항목으로 관측되었다. 유형을 재검증해야 한다.
- `1679438221`의 성공 주장은 독립 검증되지 않아 미확정으로 유지한다.
- 한 작업 세션이 Agoda 화면의 “삭제하기”를 두 번 눌렀다는 기록이 있다. 외부 상태 영향은 확인되지 않았으므로 후속 점검 항목으로 유지한다.

## Agoda accounting and policy

- 3개 세션, 94,241바이트를 모두 검토했다.

| 원본 세션 | 전사본 SHA-256 | 핵심 범위 |
| --- | --- | --- |
| `5a57fd5d-971c-4934-b3b9-2b0f171ad441` | `8f0446ff0a9f7440dd0a3d64f7ed185f574b5d0ffd65783bc1242212ac950b47` | `1578065492` 성공 후 브라우저 불가; 나머지 실패 이력 |
| `8beba886-9ce3-4d3b-83a4-75d1afe6929c` | `3b3e6f59f9f194a5ef2ea702110c79bade155e748908bff92c08b4144165fb23` | 여러 최종 수집 레인, 성공 8건과 반복 소진 2건 |
| `d2c17baf-a05d-4320-9b3c-dbe82d29d324` | `047e1780f7120edad02852d0b18e234a1ad16611613b2b1335ff514e4364b7ff` | `1694037597`, `1611368172` 성공 |

### 수집·회계 불변식

- Agoda 수집은 Paseo 인앱 브라우저 전용 단일 세션으로 수행하고, 다른 브라우저·지원·도움말·고객센터 경로를 사용하지 않는다.
- 상세 진입 전 정확한 예약 ID 카드의 존재를 증명한다. 상세 선택자는 해당 카드 안의 `[data-element-name="blp-booking-item-button-edit"]` 하나만 허용하며 성공 레코드는 `selector_count=1`이어야 한다.
- 검색은 React native input setter와 `input`, `change`, Enter 이벤트 및 bounded polling을 사용한다. 과거 페이지 fallback은 사전에 지정한 인접 페이지만 허용한다.
- 화면에 지원 버튼이 보이는 것만으로 차단하지 않는다. visible dialog/root와 정확한 고객센터 문구가 동시에 보일 때만 fail-closed한다. 아래 성공 레코드는 모두 `panel_visible=false`였다.
- `price_components`는 관측값만 `{kind,currency,decimal_text}` 배열로 기록한다. 계산으로 유추한 총액이나 참조 코드를 덧붙이지 않는다.
- 성공은 정확한 observed booking ID, `failure_code:null`, selector 1개를 요구한다. 소진된 조회도 삭제하지 않고 명시적 실패 레코드로 남긴다.

### 예약별 정제 결과

| 예약 ID | 결과 | 관측 회계 구성 |
| --- | --- | --- |
| `1578065492` | 성공, 2025-04-03~04 | base KRW `114324`; taxes/fees `24019`; gross `138343`; 카드 suffix 비공개; `reference_code:null` |
| `1681896384` | 성공, 2026-01-10~11 | `paid_full`, `prepaid`; base KRW `188672`; taxes/fees `29246`; paid/gross `217918` |
| `1681883010` | 성공, 2026-01-07~08 | `paid_full`, `prepaid`; base KRW `365328`; taxes/fees `56614`; paid/gross `421942` |
| `1563734768` | 성공, 2025-03-29~31 | `paid_full`, `prepaid`; base KRW `182539`; taxes/fees `38307`; paid/gross `220846` |
| `1557975496` | 성공, 2025-03-05~06 | `paid_full`, `prepaid`; base KRW `50985`; taxes/fees `10706`; paid/gross `61691` |
| `1537473252` | 성공, 2025-02-25~26 | `paid_full`, `prepaid`; base KRW `44771`; taxes/fees `9395`; paid/gross `54166` |
| `1537476504` | 성공, 2025-02-25~26 | `paid_full`, `prepaid`; base KRW `182628`; taxes/fees `38370`; paid/gross `220998` |
| `1537477488` | 성공, 2025-02-25~26 | `paid_full`, `prepaid`; base KRW `42970`; taxes/fees `9029`; paid/gross `51999` |
| `1694389493` | 성공, 2026-03-08~09 | `paid_full`, `prepaid`; base JPY `16011`; taxes/fees `3364`; paid/gross `18406` |
| `1694037597` | 성공, 2026-02-09~10 | `pay_at_property`; room JPY `11273`; tax/service `1127`; property collection/total `12400`; 참조 코드 비공개 |
| `1611368172` | 성공, 2025-05-31~06-01 | `prepaid`; room KRW `303495`; tax/service `61047`; additional `4320`; paid/total `368862`; 참조 코드 비공개 |
| `1520497128` | 소진 | 12페이지 초기 시도와 12/13/11 재시도 모두 exact card 없음; `RETRY_EXHAUSTED` |
| `1520504164` | 소진 | exact 검색 및 12/13/11 페이지에서 exact card 없음; `RETRY_EXHAUSTED` |

### 실패·모순·승계 판단

- `5a57…`은 `1578065492` 성공 후 전용 브라우저가 사라졌다. `1563734768`은 당시 `PASEO_BROWSER_UNAVAILABLE`와 `RETRY_EXHAUSTED`, 다른 9개 대상은 `PASEO_BROWSER_UNAVAILABLE`였으나 후속 세션에서 일부가 성공했다.
- `8beba…`의 초기 fill/type/keypress는 React 검색 필드에 반영되지 않았고 webview가 응답하지 않았다. 사용자 승인 하 동일 workspace reset 후 수집을 복구했다.
- `1537473252` 추출 중 정규식 escape 오류가 있었으나 다시 클릭하지 않고 추출식만 고쳐 성공했다.
- `1578065492` 화면에는 KRW `1473`의 별도 reference amount가 보였지만 정본 재출력은 이를 `price_components`에서 제외하고 `reference_code:null`로 남겼다. 숙박비로 임의 합산하지 않는다.
- `1520497128`은 초기 소진 레코드의 `selector_count=1`, 후속 재시도의 `selector_count=0`이 공존한다. 서로 다른 조회 단계의 이력으로 함께 보존한다.
- `d2c17…`은 상세 화면에서 `history.back()`으로 돌아왔다. 현행 정책의 “정확한 예약 목록/뒤로가기 제어를 browser evaluation으로 사용”과 어긋나므로 정책 수용 여부를 후속 결정한다. 회계 결과와 이탈 사실이 이 절로 완전히 승계됐으므로 원본 세션 자체는 별도 보존하지 않는다.
- 세 세션 모두 정본 병합 후 삭제 대상으로 승인한다.

## Pipeline and web application

- 파이프라인 운영 원칙:
  - manifest 기반 실행과 입력·출력 digest를 키로 하는 DAG 캐시.
  - 증분 projection 후 전역 불변식 검증.
  - Paseo 인앱 브라우저 수집기는 단일 순차 레인으로 운용.
  - 산출물은 불변 파일로 게시하고 read pointer 전환으로 롤백.
- 핵심 미해결 결함: 정상적인 여행 일정 수정만으로 중복 권위 행이 생겨 `trip_schedule_authority_duplicate_target`가 발생할 수 있다. 해결책은 append-only revision과 정확히 하나의 active pointer이며, “가장 최근 timestamp”를 권위 판정에 사용하지 않는다.
- 검토 UI는 DB를 기준으로 하고, Sheets는 호환 뷰로 제한한다. Apps Script 동기화는 얇고 멱등적으로 유지한다.
- SQLite와 PostgreSQL 간 전환 시점은 아직 결정되지 않았다.
- 응답이 전혀 없던 요청성 전사본 3건은 결과를 창작하지 않는다: synthetic N:N verdict, Sol feasibility review, Terra infrastructure review. 요청 프롬프트의 존재와 미응답 사실만 보존한다.

## Failure taxonomy

| 코드/범주 | 의미 | 재개 규칙 |
| --- | --- | --- |
| `PASEO_BROWSER_UNAVAILABLE` | 지정 브라우저 런타임 또는 세션을 사용할 수 없음 | 사전검사를 통과하기 전 수집 시작 금지 |
| `NAVIGATION_STATE_UNKNOWN` | 페이지·필터·현재 행 상태가 증명되지 않음 | 페이지 키와 화면 상태를 다시 고정 |
| `DETAIL_READ_FAILED` | 예약 상세 패널에서 필요한 값을 읽지 못함 | 상세 성공 증거 전까지 행 승격 금지 |
| `RETRY_EXHAUSTED` | 정해진 재시도 한도 소진 | 실패 원인 제거 후 새 체크포인트에서 재개 |
| 브라우저 분리/중단 | 실행 중 브라우저 연결이 끊김 | 마지막 검증 체크포인트 이후를 다시 대조 |
| 최종 JSON 부재 | 작업 정황은 있으나 완료 산출물이 없음 | 완료로 간주하지 않고 영속 결과와 재검증 |
| 요청만 있고 응답 없음 | 계획·검토 요청이 실행되지 않음 | 결과를 추정하거나 창작하지 않음 |

## Remaining work

1. DOM·canary 25개 세션의 최종 통합 보고를 반영한다.
2. 상세 복구 미해결 예약과 3~6페이지 잔여분을 단일 순차 브라우저 레인에서 재처리한다.
3. `1755579869`, `1679438221`, Agoda 화면 삭제 클릭 2회의 실제 영향을 재검증한다.
4. `d2c17…`의 `history.back()` 사용을 정책 예외로 인정할지 결정하고 향후 수집기는 정확한 예약 목록/뒤로가기 제어만 사용하도록 고정한다.
5. 일정 권위 모델을 append-only revision + 단일 active pointer로 고정한다.
6. SQLite/PostgreSQL 전환 기준과 DB 검토 UI 범위를 확정한다.

## Deletion decision

- 삭제 대상은 고정 manifest의 정확한 89개 `C:\AX\cost` Codex 세션뿐이다.
- 이 문서가 모든 주제 절에서 완결되고, 세션별 전사본 해시가 이 문서의 대응 절 해시에 연결되며, 두 독립 고추론 검토와 비파괴 dry-run이 통과한 뒤에만 영구 삭제한다.
- 영구 삭제는 세션별 순차 실행한다. 각 세션 직전에 provider=`codex`, cwd=`C:\AX\cost`, status=`closed`, childless, 원문 해시 일치를 다시 확인한다.
- 각 삭제 뒤에는 authoritative inspect의 명시적 not-found와 새 전역 목록 부재를 모두 확인한다. 예외·시간초과·파싱 실패는 부재 증거로 인정하지 않는다.
- 결과 원장은 삭제 의도와 확정 결과를 각각 fsync한 축약 기록으로 남긴다.
- 89개 부재가 모두 검증되면 임시 전사본·manifest·assignment 디렉터리와 이 작업을 위한 임시 워커·검토 세션을 영구 제거한다.
- 보존물은 이 정본, `outputs/agoda-paseo-session-recovery-20260826.json`, 그리고 축약 삭제 원장뿐이다.
