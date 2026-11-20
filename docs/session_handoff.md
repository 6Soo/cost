# COST 현재 상태 · 작업 인계

기준일 2026-11-21 KST. 확인한 main은 7d343bc4, 운영은 b29735e2다. 작업 직전에 PR head와 운영 릴리스를 다시 확인한다.


## 2026-11-21 · L1~L5 경량화 실행 경로 통합

- 소유자 결정에 따라 화면·메뉴와 내부 실행 경로의 통합, 저가치 편의 기능의 폐기 후보 조사를 기존 [L1~L5 계획](SPEC.md#l1l5--문서소프트웨어-경량화-2026-11-19-사용자-지시)에 편입했다. 기준 main은 380bdad0이다.
- 첫 구현은 Google 붙여넣기와 지출 대사의 검증 이용기간 해석을 DATE-109 공통 호출로 통합했다. 기존 행 선택·순서와 저장값·수동 공란 우선순위를 보존했다. Qwen4 Max 표적 89건과 감독자 재검사 19건이 통과했다.
- 도구 조사에서 품질 게이트·표적 검사·진입점 감사·비용 감사·합성 미리보기는 각자의 사용 근거가 확인됐다. 작업자별 근거와 다음 검사는 작업 브랜치의 로컬 체크포인트에 기록했다.
- 장부 상세의 숨은 행도 공통 금액·날짜 투영을 사용한다. 배분 상세, 수동 교정, 권한 밖 행 경계를 합성 자료로 확인했다. [PR #1081](https://github.com/6Soo/cost/pull/1081)
- 마감 기간·준비 비용 교정은 적용과 복원 트랜잭션을 공유한다. 도구별 판정·감사 종류·수정 열을 유지했으며 표적 회귀 109건, 최종 복원 표적 10건이 통과했다. [PR #1082](https://github.com/6Soo/cost/pull/1082)
- React 모바일 테마 전환을 상단 버튼으로 모았다. 390px 소유자·열람자, 1280px 소유자의 버튼과 메뉴 권한, 키보드 조작, 설정 저장을 합성 미리보기로 검증했다. 프런트 표적 검사 23건 통과.
- 정적 진입점 인벤토리는 모듈 285개, 라우트 후보 155개, 호출 가능 항목 4,091개를 수집했다. 호환 장부의 배분 편집과 기존 상세 직링크에는 사용 경로가 남아 있다. 전체 화면 퇴역에는 §11.2.1의 운영 읽기 대조와 교정 복귀 검증이 필요하다.

## 2026-11-21 · M6 Airbnb 파서 이식 단위

- 퇴역 계획 3단계 (b) 두 번째 단위. Airbnb는 `collect()`가 파싱·집계·사건 조립·ID를 한 번에 해 **슬라이스 전체**를 Rust로 옮겼고, 공용 헬퍼(인증·본문·`sent_day`)는 Python 경계 값으로 남겼다(`sent_day`는 RFC 2822+KST+수신 지연 규칙으로 호출처 10곳). 교차 파서 의존이 없어 배선 단계의 모듈 교체가 깨끗하다.
- **공용 `extract/pyre.rs` 신설.** Python `re`/`int()` 의미를 한 곳에 모았다: 확장 `\s`(`U+001C..U+001F`), 양방향 `\b`, Nd 블록 테이블. traveloka를 이 모듈로 전환했고 **골든 28건 바이트 동일이 회귀 가드**다.
- **단위 테스트가 실제 차이를 잡았다.** `char::is_alphanumeric`은 Other_Alphabetic 결합 표기(U+0345 등)를 Python `str.isalnum()`보다 과수용한다. 단어 범주를 Python `unicodedata`에서 뽑은 770범위 테이블(142,939자, 불일치 0 검증)로 바꿨다.
- **골든 26건**, 변경 없는 Python 파서 생성: 연도 추론 31일 경계·연말 넘김, 2월 29 양방향, `end_month` 0 폴백, 취소 sticky, 기간 충돌, `m2/m10` 정렬, 양방향 `\b`, 전각 월/일. 필드·canonical 바이트·SHA-256 일치.
- **검증:** lib 124건, airbnb 골든 26건, traveloka 4건, extract 2건, `fmt`·`clippy` 경고 0, Python airbnb+traveloka 11건 통과. **추가 전용**이며 스위치·Python 삭제·운영 경로 변경 없음.
- 조사 근거: [Airbnb 이식 조사](agents/artifacts/m6-airbnb-port-20261121.md) — 이식 가능·선행 차단 조건 없음.


## 2026-11-20 (3) · M6 Traveloka 파서 이식 단위

- 퇴역 계획 [3단계 (b)](playbooks/m6-extractor-retirement.md)의 첫 단위를 구현했다. Traveloka 메일 파서의 **판정·금액·항공일·fact digest를 Rust로** 옮겼고, 공용 메일 헬퍼(인증·본문·`Cf` 제거)는 Python 브리지에 남겼다. `extract_sources.forest_name_keys`가 Python 의미를 경계에서 넘기는 선례를 그대로 따른 것이라 `parseaddr`·`html.unescape` 동등성은 이 단위의 선행 조건이 아니다.
- **Python 정규식 의미를 명시적으로 재현했다.** `\s`에 `U+001C..U+001F` 추가, 말미 `\b` 2곳은 문자 후처리, `(?<![\d,])` 룩비하인드는 후처리(등가 논거는 모듈 주석). `$`는 `(?:\n?\z)`.
- **골든 28건**을 변경 없는 Python 파서로 생성했다(`tools/core_bridge/traveloka_golden.py` → `core/golden/synthetic/traveloka_mail.jsonl`). 사례는 예약/결제 구분, 취소 우선, 금액 모호·쉼표 표기 구분, 룩비하인드 적대, DKIM 정렬 대 `owner_collected`, 날짜 2형식·불가 날짜, 전각·아랍·수학 산세리프 숫자, 혼합 폭 연도, 제목+본문 중복 ID, 소프트하이픈, `U+001C` 공백이다.
- **독립 검수(다른 모델·다른 세션, 읽기 전용)가 차단 3건을 찾았고 모두 고쳤다.** ① Python `references()`는 집합이라 제목·본문에 같은 예약 ID가 두 번 나와도 1개인데 Rust는 등장 횟수로 세어 **결제 fact를 통째로 버렸다**(`f52eafc7`). ② `char::is_digit`/`to_digit`는 ASCII만 인정해 전각 금액은 결제 소실, 혼합 폭 연도는 **0020년** 오답이었다(`65de53b1`). ③ Nd 블록 역산이 인접한 수학 숫자 런을 구분하지 못해 `𝟢`→20이 나왔다(`d11a4b8b`, 블록 시작 테이블 + `v < 10` 안전망). 최종 판정 **APPROVE**. 기록 [검수](agents/artifacts/m6-traveloka-review-20261120.md).
- **유니코드 버전 일치를 확인했다.** Python 3.14.7 `unicodedata` 16.0.0, `regex-syntax` 0.8.11도 Unicode 16.0.0이며 Nd 760자 집합이 완전 일치한다. 크레이트 갱신 시 테이블 누락을 잡는 전수 가드를 넣었다(`ddb937f6`).
- **검증:** Rust 골든 대조 4건(필드·canonical 바이트·SHA-256), 라이브러리 단위 116건, `cost-core` 전체, `cargo fmt --check`·`clippy` 경고 0, Python 표적 41건 통과. CLI 시험의 stdin EPIPE 경합(`apply_t4`·`shadow_cli`·`shadow_links_cli`)도 무시하도록 고쳤다(`c1c8a70b`) — 단언은 그대로다. 이 단위는 **추가 전용**이며 스위치 신설·Python 삭제·운영 경로 변경이 없다. PR [#1076](https://github.com/6Soo/cost/pull/1076).
- 조사 근거: [Traveloka 이식 조사](agents/artifacts/m6-traveloka-port-20261120.md) — 조건부 이식 가능, 위험은 공용 헬퍼에 집중, `airline_payment_mail`이 traveloka를 직접 호출하므로 Python 모듈은 airline 이식까지 유지.

## 2026-11-20 · 운영 저장 판정 보완과 M6 기준 재설정

- 승인 범위 안에서 운영 decisions-only 보완 2,585건을 완료했다. 새 근거 874건, 저장 대상 누락 0, 재실행 0, 원장 및 기존 판정 91건 불변, 원천·투영·기간 불일치 0. 기존 판정과 다른 60건은 별도 정책 검토 대상이다. 3분기 동일 조회 22탭·256건에서 이용일 공란 56→52건을 확인했다.
- M6 새 기준 생산을 승인받았다. 기존 a26d4465… 기준은 이력에 보존한다. 새 보호 입력의 Python 2회와 Rust 산출물 7,965건·28,544,770바이트가 동일하며 SHA-256은 3c6c46f51fbaa03b6da34708c8891a940fe3f1b957138986860e5dd992b6bde1이다. 두 매니페스트를 검증했다. 보호 근거는 D:/WebLedgerHost/data/backups/m6-new-basis-20261120-212716-286978/baseline-proof.json이다.
- [#1072](https://github.com/6Soo/cost/pull/1072)에서 오프라인 Rust 추출 경로를 최신 main에 재적용했다. 다음 구현 단위는 Traveloka 파서다. 운영 추출은 기존 생산자를 사용한다.

## 2026-11-20 · 업로드 뒤 OTA 재판정 운영 반영

- PR #1071 병합·배포 완료. 업로드 후 검토 저장소의 선택 경로도 기존 OTA 스위치에 연결했다. 실제 호환 바이너리 Rust 모드 33건과 Python 모드 34건, 로컬 업로드 계약 1건 및 GitHub 영향 검사 263건이 통과했다.
- 현재 운영 바이너리와 새로 복제한 Board·Core, 이전 기간 근거로 저장 보완을 예행했다. 저장 2,585건, 재실행 추가 0건, 원장 쓰기 0건, 원장 논리 지문 동일. 화면 판정과 달라 별도 검토가 필요한 60건은 남아 있다. 근거 D:/WebLedgerHost/data/backups/ota-storage-readiness-20261120-210510-675279/storage-rehearsal/summary.json. 운영 저장 보완과 이용일 폴백 제거는 미수행이다.

## 2026-11-20 (2) · M6 새 추출 기준 확정

- **소유자 결정(2026-11-20):** "새 기준으로 진행." 기존 기준 `7,965건 / a26d4465…`는 원 입력 사본 소실로 재현 불가이므로 **이력으로만 보존**하고 비교 base로 쓰지 않는다. 현재 결정적 추출기로 새 보호 사본 기준을 생산한다.
- **새 기준:** `7,965건 · 28,544,770바이트 · SHA-256 3c6c46f51fbaa03b6da34708c8891a940fe3f1b957138986860e5dd992b6bde1`. 같은 보호 입력에서 Python 추출 2회와 오프라인 Rust 조립 결과의 바이트가 모두 일치했고, 두 Python 매니페스트도 검증했다.
- **코드:** [PR #1072](https://github.com/6Soo/cost/pull/1072) — 기존 M6 Rust 추출기 구현을 최신 main에 재적용(충돌 3건 해소, `extract-baseline-compare` 보존, `extract-sources` 추가 전용). `--stages` 입력은 파일을 읽기 전에 기본·지정 호스트의 Board·Core·OTA Evidence·OTA Review 경로와 파일 별칭을 거부한다(`DB_IS_LIVE`).
- **검증:** 합성 파이프라인 20건 + Rust 골든 2건 + 표적 Python 85건 통과. CI 3/3(impact-checks·rust-core·windows-p2-descendant-boundary) 통과. 독립 검수는 `4cb34308`에서 차단 1건(`--stages` 라이브 경로 미검사) 지적 → `2290b8a8`에서 해소, **APPROVE**.
- **다음:** 퇴역 계획 [3단계](playbooks/m6-extractor-retirement.md)의 단위별 이식(난이도 낮은 파서부터)과 1단계 결합 해소(`core_writer`의 `periods` 의존). 이번 PR은 오프라인 검증 CLI이며 운영 스위치·Python 삭제는 하지 않았다.

## 2026-11-20 (2) · M6 새 추출 기준 확정

- **소유자 결정(2026-11-20):** "새 기준으로 진행." 기존 기준 `7,965건 / a26d4465…`는 원 입력 사본 소실로 재현 불가이므로 **이력으로만 보존**하고 비교 base로 쓰지 않는다. 현재 결정적 추출기로 새 보호 사본 기준을 생산한다.
- **새 기준:** `7,965건 · 28,544,770바이트 · SHA-256 3c6c46f51fbaa03b6da34708c8891a940fe3f1b957138986860e5dd992b6bde1`. 같은 보호 입력에서 Python 추출 2회와 오프라인 Rust 조립 결과의 바이트가 모두 일치했고, 두 Python 매니페스트도 검증했다.
- **코드:** [PR #1072](https://github.com/6Soo/cost/pull/1072) — 기존 M6 Rust 추출기 구현을 최신 main에 재적용(충돌 3건 해소, `extract-baseline-compare` 보존, `extract-sources` 추가 전용). `--stages` 입력은 파일을 읽기 전에 기본·지정 호스트의 Board·Core·OTA Evidence·OTA Review 경로와 파일 별칭을 거부한다(`DB_IS_LIVE`).
- **검증:** 합성 파이프라인 20건 + Rust 골든 2건 + 표적 Python 85건 통과. CI 3/3(impact-checks·rust-core·windows-p2-descendant-boundary) 통과. 독립 검수는 `4cb34308`에서 차단 1건(`--stages` 라이브 경로 미검사) 지적 → `2290b8a8`에서 해소, **APPROVE**.
- **다음:** 퇴역 계획 [3단계](playbooks/m6-extractor-retirement.md)의 단위별 이식(난이도 낮은 파서부터)과 1단계 결합 해소(`core_writer`의 `periods` 의존). 이번 PR은 오프라인 검증 CLI이며 운영 스위치·Python 삭제는 하지 않았다.

## 2026-11-20 · OTA 배치 운영 반영

- PR #1070 병합과 ecbdb5c9 운영 배포를 완료했다. Board·Worker·호환 Rust 바이너리 적용과 보호 표 14개 불변을 확인했다. [운영 기록](operations.md#2026-11-20-2045-kst--ota-카드-후보-rust-배치-운영-전환)
- Linux 자격증명 시험에는 비공개 파일 모드를 적용했고 Windows 전용 M5 복구 시험은 Windows 러너에서 실행했다. 시험 파일과 검증 조건을 유지했다. 최종 CI 세 검사 통과.
- 다음 범위는 업로드 뒤 Python 재판정 경로, 저장 이용일 보완과 퇴역 절차다. 운영 DB 저장 보완은 별도다. 추출기 기준은 원 입력 사본 또는 소유자의 새 기준 결정이 필요하다.

## 2026-11-20 · OTA 규칙 압축과 Rust 후보 전환

- [#1070](https://github.com/6Soo/cost/pull/1070). 규칙·P2 호환성 5b9cfe7f, Rust 후보 배치 339b410f. 일반 외화의 전후 1일 허용과 결제대행사 표기의 당일 조건, 원문 결제일 공란, M:N과 표시용 공통기간을 보존했다. Rust CLI가 배치를 지원할 때만 후보 검색을 넘긴다. 구형 바이너리와 숲나들e·토요코인·라쿠텐 전용 조회는 Python 경로를 사용한다.
- 3분기 감사와 같은 시점의 Board·Core 사본 및 기간 근거로 카드 거래 7,349건을 감사했다. 저장 보완 대상 2,585건과 판정 변경 대상 60건을 구분했다. 격리 복원 후 decisions-only 보완에서 원장 행과 기존 저장 이용일 91건의 값이 그대로였고, 보완 2,585건·재실행 0건·미저장 0건을 확인했다. 새 이용일은 전체 검증 359건·추론 102건·미상 2,124건이며, 3분기 OTA 장부 후보와 겹치는 건 각각 149·40·47건이다. 판정 변경 대상 60건은 예행 뒤에도 남았다. 운영 화면 집계의 누락 867건·미판정 270건은 방문한 화면 범위의 별도 지표다.
- 같은 운영 사본의 이벤트 7,965건과 카드 원행 7,349건에서 운영 바이너리와 새 배치를 대조했다. 후보 진단 2,239건의 후보·탈락 사유를 포함해 결과 차이 0, 묶음 연결 결과 340건과 수동 연결 3건이 동일했다. 같은 사본에 고정 묶음은 0건이었으며 고정 묶음 경계는 합성 검사로 다뤘다. 같은 입력의 shadow-links는 OTA 7,965건과 환불 짝 486건에서 목록 밖 차이 0으로 통과했다. Python 최종 판정은 카드 업로드 뒤 갱신에도 호출된다. [Python 판정기 퇴역 절차](playbooks/core-cutover.md#ota-후보-배치와-python-연결-판정기-퇴역)를 따른다. 이용일 폴백 퇴역은 운영 저장 판정의 보완과 화면·내보내기 대조 뒤에 한다. 7,965건 고정 추출 기준은 원래 입력 재현 또는 소유자의 새 기준 결정이 필요하다.
- GitHub Rust·Windows P2 검사는 통과했다. [Linux 영향 검사](https://github.com/6Soo/cost/actions/runs/44725006671/job/136250069528)는 기준 브랜치와 같은 M5 테스트 파일에서 토큰 파일 권한 6건과 Windows 전용 taskkill 호출 1건이 실패해 #1070은 초안으로 남겼다. 운영 사본 대조와 격리 예행 집계는 D:/WebLedgerHost/data/backups/ota-rust-candidates-20261120-195941-089의 summary.json, solver-shadow-summary.json, storage-rehearsal/summary.json에 있다.
- 운영 장부는 Board·Worker가 실행 중인 2c442dbb다. 배포 증거의 릴리스 blob 불일치는 0이고 보호 표가 동일하다. 기존 브라우저 대조에서 기본 여행의 카드 지출 ID 89건과 별도 수입 탭의 Google 수입 35건을 확인했다. 참가자·보험, 항공권, 예약 연결 동선에는 차이가 남아 있다. 이번 OTA 운영 배포와 금융 적용은 미수행이다.

## 2026-11-20 · 장부 표시 기준과 Plush 화면

- 기준 `2fb41a74`. 기존 `/board`에서 레거시의 기본 여행과 분기 전환 선택지, 날짜·분류 순서, 거래처·내용 표시와 분기 지출 표시를 Plush 컴포넌트에 연결했다. 날짜 검색과 분기 지출 검색은 공통 서버 조회를 쓰며 검색 전 전체 합계를 유지한다.
- 카드 분류와 저장 스키마에는 변경이 없다. 운영 배포는 미수행이다. 참가자·보험, 항공권, 예약 연결을 장부 안에서 여는 동선은 미반영이다.
- 표적 확인 명령은 `python -B -m pytest -q -p no:cacheprovider webapp/tests/test_ledger_parity_spec_11_2_1.py webapp/tests/test_m4_parity_refund_total_scope.py`와 `npm --prefix frontend run test:run -- src/features/ledger`이다.

- 검증 결과는 장부 조회·환불·열람자 Python 검사 35건과 Plush 장부 검사 43건 통과다. 타입 검사와 빌드도 통과했다.

## 2026-11-20 (3) — 죽은 코드 퇴역과 기존 회귀 2건 수정

- **죽은 코드 퇴역:** 전수 조사로 참조 0을 확인한 13개 헬퍼·상수(−141줄)와 `ensure_ledger_schema` 래퍼. [#1064](https://github.com/6Soo/cost/pull/1064) `b8667cb9`, [#1065](https://github.com/6Soo/cost/pull/1065) `0920dc67`. #1065는 중복도 함께 정리(`COMPANY_CELL` 중복, `_esc` 사본 2개→`pages.esc`, `app`의 `replay()` 5개→`app.db.replay_scoped_request`)하고, #1062 검수 지적 O1(변환 후 저장소 쓰기→뷰 재생)을 검사로 입증했다.
- **기존 회귀 2건 수정** [#1066](https://github.com/6Soo/cost/pull/1066) `c01a5d98`:
  1. `/board` HTML이 수입 행 거래처 칸에 참가자 명부 이름(`customer_name`·`nickname`)을 실었다(`ledger_design._row_party_main`). SPEC §13 보호 경계·지연 로딩 계약 위반 → 경로 레이블로 대체.
  2. `test_ledger_apply` fixture가 `WEBLEDGER_UNIFIED_DB`를 정리하지 않아 다른 검사가 남긴 값이 `_embedded_audit` 분기를 바꿨다 → 스토어 생성 전 정리·복원.
  - 드러난 이유: `origin/main`의 impact 검사가 **PR 증거 재사용(skip)** 이라 실제 실행된 적이 없었다.
- **CI 재사용 실측(첫 사례):** main push `53204c7e`가 PR 증거를 재사용해 **1분 53초**에 종료(단계 로그에서 테스트·준비 전부 skipped, `44633965930`). 실제 실행 1회는 1분 58초 중 테스트 70초·준비 48초.
- **#1062 독립 검수 APPROVE**(차단 0). O2(apply 사이드카 재검증이 `-wal` 크기만)는 비차단 잔여.
- **남은 일:** `test_trip_ledger_presentation::test_browser_expense_table_keeps_long_party_and_service_dates_reachable`는 지출 행 기하 검사로 이번 변경 없이도 로컬 실패(15px 여유) — 브라우저 환경 의존 별건. M6 §11.1-3 고정 추출 기준 재설정은 2026-11-20 (2)에서 소유자 결정으로 해소됐다. 열린 PR은 [#1008](https://github.com/6Soo/cost/pull/1008)(draft)만. 운영 배포는 하지 않았다.

## 이번 연속 작업에서 병합한 것

- **열람자 금액 위조(차단 결함) 수정** [PR #1060](https://github.com/6Soo/cost/pull/1060) `19518d4e`. 독립 검수(SHA `e7ee3859`)의 차단 지적: `/access/rows` viewer 분기가 `int(display_amount_krw, amount_krw, 0)`로 금액을 강제 변환해, 금액 미확인 Google 수입 행(`amount_krw=None`, `amount_missing=True`)을 **0원으로 위조**했다. 같은 payload의 `confirmed`는 미확인이라 한 응답이 자기모순이었고 SPEC §11.2.1 계약 1·4 / GGL-014를 위반했다. 수정: 미확인이면 `None` 유지, `VIEWER_ROW_FIELDS`에 `amount_missing` 추가, 회귀 검사 1건(수정 없이는 `0 is None`으로 실패 확인). viewer 10 + 인접 128 passed, CI 3/3.
- **CI 증거 재사용 도구의 토큰 누출 수정** [PR #1061](https://github.com/6Soo/cost/pull/1061) `53204c7e`. artifact 다운로드의 302 redirect(서명 storage URL)로 `Authorization`이 따라가던 것을 `add_unredirected_header` + API URL 검증으로 막았다. `test_quality_checks` 60 passed(신규 검사는 수정 전 `io` import 누락으로 실패했다가 통과).
- **세 번째 저널 통합** [PR #1062](https://github.com/6Soo/cost/pull/1062) `62263509`. `source_fact_applies`를 `ledger_operation_requests`로 이동(3값 shape `legacy`/`unified`/`unified_source_facts`, `--include-source-facts` 오프라인 병합 CLI, 별도 백업 `.pre-source-facts-merge-backup`). `reserve_link_saves`는 AccessStore 계약(SPEC 16.4)이라 제외. 저널 32 + 스키마 5 = 37 passed(rebase 후 재확인), CI 3/3. 운영 DB·스키마 미접촉.
- **CI 재사용 첫 성공 실측:** main push `53204c7e`가 PR 증거를 재사용해 **1분 53초**에 끝났다(같은 PR 실행은 2~3분). 이전 main 실행 4건은 모두 재실행이었다.
- **남은 차단(소유자 결정):** M6 §11.1-3 고정 추출 기준(`7,965건 / a26d4465…`)은 입력 사본 소실로 재현 불가다. 기준 재설정은 소유자 결정 사항이라 그 전에는 M6 퇴역을 시작할 수 없다. → **해소(2026-11-20 (2)):** 소유자 "새 기준으로 진행" 결정으로 새 기준을 생산했다.
- **열린 PR:** [#1008](https://github.com/6Soo/cost/pull/1008) 정책 초안(draft, 소유자 결정 없이 병합하지 않음). 이번 작업에서 운영 배포는 하지 않았다.

## 진행 상태

| 범위 | 확인된 상태와 다음 근거 |
| --- | --- |
| 운영 | Board·Worker 실행 SHA `9fd2d4c2`. [17:55 KST 배포 증거](operations.md#2026-11-19-1755--9fd2d4c2-운영-배포). 인증 수집의 실사이트 확인은 별도다. |
| M2·P2 | M2는 [SPEC §10](SPEC.md#10-로드맵) 기준 종료. OTA와 이용기간 대상 보완 [#1036](https://github.com/6Soo/cost/pull/1036)·[#1034](https://github.com/6Soo/cost/pull/1034)·[#1042](https://github.com/6Soo/cost/pull/1042)·[#1044](https://github.com/6Soo/cost/pull/1044), 선택형 패킷 [#1012](https://github.com/6Soo/cost/pull/1012)·[#1043](https://github.com/6Soo/cost/pull/1043)은 main 병합. [#1022](https://github.com/6Soo/cost/pull/1022)의 규칙 통합도 병합됐다. 미연결 496건 중 실제 회수 수와 토큰 절감은 미측정. 기본 패킷은 전체 정책이다. |
| M3 Rust | P1 작성과 OTA·환불 연결의 Rust 운영 전환 기록이 있다. 이후 저장 판정 보완 및 고정 추출 기준 재현은 [SPEC §11.1](SPEC.md#111-rust-새-코어-m3-m6)의 종료 조건을 따른다. |
| L2·M4 장부 조회 | [#1026](https://github.com/6Soo/cost/pull/1026) 병합(`cde4077c`). 공통 조회의 운영 수락과 기존 HTML 상세·교정 퇴역은 [§11.2.1](SPEC.md#1121-장부-조회-통합)의 행·금액·권한·복귀 대조 뒤 진행한다. |
| L3·M6 장부 이관 | [#1013](https://github.com/6Soo/cost/pull/1013) 병합(`9a953e27`). 새 장부 테이블 추가의 소유자 승인과 이관 도구가 기록돼 있다. 운영 이관 및 대조 완료 근거는 확인되지 않았다. [#1030](https://github.com/6Soo/cost/pull/1030) revision 보정은 main 병합(`326d6afd`)으로 반영됐다. 원본 보존·백업 복원·행/금액/revision 대조는 [이관 계약](design/m6-ledger-merge-contract.md)과 [#1013](https://github.com/6Soo/cost/pull/1013)을 함께 본다. |
| L3·M6 추출기 | 새 기준 확정(`7,965건·28,544,770바이트·SHA-256 3c6c46f5…`) — 소유자 결정 2026-11-20. Python 2회 + Rust 바이트 일치, 매니페스트 검증. [PR #1072](https://github.com/6Soo/cost/pull/1072) 독립 검수 APPROVE(2290b8a8), CI 3/3. 구 기준 `a26d4465…`는 이력 보존·비교 제외. 남은 일: 단위별 파서 이식과 `core_writer`의 `periods` 결합 해소. [추출기 퇴역 계획](playbooks/m6-extractor-retirement.md) |
| L5·M5 운영 이전 | 합성 큐·보조 노드 예행 근거가 있다. 운영 요청량·저장/복원 비용과 제공자·과금·고객 원문 이전 결정이 남았다. [§11.3](SPEC.md#113-서버와-보조-노드-m5) |
| L4 CI·검수 | [기준 main CI](https://github.com/6Soo/cost/actions/runs/44549038076). 검증 증거 재사용과 실행 시간 계측을 우선한다. Windows·금융·보호 게이트는 [AGENTS](../AGENTS.md) 기준을 적용한다. |

## 문서 정리와 다음 검토

- L1 문서 통합 후보는 [#1041](https://github.com/6Soo/cost/pull/1041). 절차·정책·운영 기록의 역할은 [문서 지도](README.md)에서 확인한다. 이전 인계·작업판의 최신 원문은 아래 고정 링크에 있다.
- 다음 조회 작업은 #1026 병합본에서 장부 수락 조건과 남은 호환 경로를 대조한다. 장부 저장 이관은 신선 백업을 복원한 사본에서 대조한다. OTA 근거 DB는 사본 예행에서 압축할 중복과 절감량을 먼저 확인한다. [OTA 근거 압축 절차](playbooks/ota-evidence-compaction.md)
- 새 인계는 현재 진행·차단·다음 행동과 근거 링크만 갱신한다. 기존 승인 범위는 [SPEC §11.5](SPEC.md#115-m3m4m5-보완-명세)와 해당 PR의 소유자 결정에서 확인한다.

[통합 직전의 전체 인계](https://github.com/6Soo/cost/blob/a9c739e72a0f8ef806700253b48bc455e9d41dbb/docs/session_handoff.md) · [통합 직전 작업판과 승인 근거](https://github.com/6Soo/cost/blob/a9c739e72a0f8ef806700253b48bc455e9d41dbb/docs/agents/BOARD.md)
