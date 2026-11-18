# COST 저장소 경량화 전수 점검 (정적 감사)

> 작성: 2026-11-18 (KST)  
> 기준: [main 00d4aac573470ac0ca80fd82d7674aa467bc091f](https://github.com/6Soo/cost/commit/00d4aac573470ac0ca80fd82d7674aa467bc091f) — PR #1005 병합 직후  
> 성격: **현황 측정·개선 후보·안전한 실행 순서**. 삭제·리팩터링·운영 배포를 승인하는 문서가 아니다.
> **마일스톤 우선:** [M3~M6 충돌 점검과 단계 연동 실행 순서](#3-m3m6-마일스톤-연동-실행-순서)에 따라 실제 변경 시점을 제한한다.

## 0. 결론

저장소를 더 경량화할 여지는 충분하다. 그러나 목표를 네 가지로 분리해야 한다.

1. **Git 추적 파일·체크아웃 부피:** 과거 산출물·데이터 스냅샷·검수 스크린샷의 보존 위치를 재검토한다.
2. **개발·AI 작업 문맥:** 최신 정책·실행 기준만 빠르게 읽고, 과거 로그와 일회성 절차를 기본 입력에서 제외한다.
3. **수정 비용·회귀 위험:** 대형 Python 클래스와 레거시/신규 경계의 책임을 기능 단위로 나눈다. 파일을 쪼개는 것만으로 실행 시간이나 총 코드 바이트가 감소하지는 않는다.
4. **웹 사용자 전송량·응답 시간:** 실제 로드되는 폰트·자산·프런트 번들을 측정한 뒤 최적화한다. Git 파일 크기를 웹 성능이라고 해석하지 않는다.

**최우선은 공개 저장소의 이력·산출물·원본 자료를 메타데이터만으로 조사하고 보존 책임을 확정하는 것**이다. 원본을 열어 개인정보를 노출하거나 무작정 Git에서 지워서는 안 된다.

## 1. 조사 방식과 한계

- GitHub의 main 재귀 트리(잘림 없음, blob 1,931개), 각 blob의 Git 크기와 SHA, 주요 코드·구성·절차서 본문을 확인했다.
- 원본 금융 파일, 고객 내역, 메일·세션 transcript의 **내용은 열거나 복사하지 않았다**. 민감도는 **미평가(UNASSESSED)** 상태다.
- 대형 Python 파일의 함수·클래스 경계와 길이, 프런트 진입점, 자산 URL, Rust/테스트 게이트의 실제 코드를 조사했다. 전체 호출 그래프·동적 import·실행 트래픽은 재현하지 않았다.
- 저장소를 로컬로 clone하지 못했으므로 테스트, 빌드, 실제 서버의 API·브라우저 성능 측정, 데이터 사용처 확인은 실행하지 않았다.
- 아래 크기는 **현재 Git 트리에 적힌 비압축 blob 크기 합계**다. Git pack/clone 크기, 브라우저 다운로드 크기, 운영 DB 크기 또는 절감 가능한 확정 용량이 아니다. 경로가 중첩된 표는 서로 합산하지 않는다.

### 1.1 저장소 크기

| 지표 | 측정값 |
| --- | ---: |
| 추적 blob 파일 | **1,931개** |
| 비압축 파일 크기 합계 | **49,235,374 bytes (49.24 MB)** |
| Python 파일 | **1,050개** |
| Markdown 파일 | **238개** |
| 테스트 디렉터리 전체 파일 | tests/ 아래 289개, webapp/tests/ 아래 366개 |
| 100 KB 이상 Python 모듈 | **13개, 합계 2,219,694 bytes** |
| 동일 Git blob SHA의 중복 경로 | 14그룹·31경로, 중복 체크아웃 분량 **1,987,439 bytes** |

### 1.2 상위 디렉터리

| 경로 | 파일 | 크기 |
| --- | ---: | ---: |
| webapp/ | 533 | 12.59 MB |
| docs/ | 251 | 7.40 MB |
| ledger/ | 72 | 7.39 MB |
| outputs/ | 39 | 7.13 MB |
| quality-artifacts/ | 49 | 2.90 MB |
| core/ | 124 | 2.69 MB |
| tests/ | 289 | 2.69 MB |
| tools/ | 211 | 1.90 MB |
| app/ | 135 | 1.78 MB |
| .paseo-session-migration-work-20260826/ | 91 | 1.62 MB |
| frontend/ | 98 | 0.82 MB |

**비중이 큰 파일 묶음:** ledger/data/ 43개·5.61MB, webapp/tests/ 366개·5.15MB, docs/history/ 135개·4.05MB, webapp/static/ 26개·3.65MB, docs/specs/assets/ 18개·1.51MB, core/golden/synthetic/ 11개·1.72MB. 각각 경로 내부 집계이며 위 표와 합치지 않는다.

## 2. 중요도별 발견 사항

### F01 · P0 · Git의 과거 회계·산출물·세션 자료 (삭제 금지, 분류 먼저)

**근거:** [추적 자료 정책](../../config/tracked-data-policy.json)은 ledger/data/, outputs/, .paseo-session-migration-work-20260826/를 보호 경로로 지정한다. [추적 자료 검사기](../../tools/check_tracked_data.py)는 이들에 대해 민감도·생산자·소비자·현재 사용 여부를 자동 확정하지 못한다.

| 범위 | 파일 수 | 비압축 크기 |
| --- | ---: | ---: |
| ledger/data/ | 43 | 5.61 MB |
| outputs/ | 39 | 7.13 MB |
| .paseo-session-migration-work-20260826/ | 91 | 1.62 MB |
| **소계(비중첩)** | **173** | **14.36 MB** |

- 이 파일들이 공개 Git에 **추적되어 있다는 사실**은 확인되었다. 실제로 고객 개인정보·비밀이 포함되어 있다는 판단은 하지 않았다.
- 예: ledger/data/ledger_current.xlsx와 ledger/data/ledger_latest.xlsx는 같은 blob SHA이며 각 566,121 bytes다. 동일하다고 둘 중 하나를 즉시 삭제하면 안 된다. 동적 경로 사용·외부 절차가 있을 수 있다.
- outputs/의 XLSX·JSON은 이전 대사·교정의 증거일 수 있다. .gitignore의 outputs/ 무시 규칙은 **이미 추적된 파일을 자동으로 제외하지 않는다**.
- 보호 자료가 실제로 불필요하다면 **사용처·생산자·복구 방법·보관 기한·민감도를 먼저 확인**하고, 별도 보존 위치에 해시와 복원 시험을 남긴다.
- [검사기](../../tools/check_tracked_data.py)의 정책 변경은 **먼저 별도 PR로 병합**, 삭제는 다음 PR로 수행하는 것을 전제한다. 보호 규칙 우회나 한 PR의 정책 완화+삭제를 금지한다.
- Git에서 현재 경로를 지워도 **기존 커밋의 공개 이력은 남는다**. 이력 재작성·force push는 일반 경량화 과제가 아니며 독립적인 보안·복구 판단 없이는 실행하지 않는다.

**효과:** 이 14.36MB는 **보존/이관 검토 대상 규모**이지 확보 가능한 공간 또는 삭제 승인량이 아니다.

### F02 · P1 · 검수 산출물과 오래된 디자인 증거

**근거:** quality-artifacts/admin-ui-ux/ 49개·2.90MB. 특히 ota-state-machine.html 441,764 bytes, ota-break.html 279,941 bytes와 다수의 before/after 이미지가 있다. docs/specs/assets/ 18개·1.51MB도 과거 UI 스냅샷이다.

**제안:** (1) 현재 회귀·검수 문서의 상대 링크와 자동 검사 사용처를 조사한다. (2) 필요한 스크린샷만 감사 보관함 또는 승인된 아티팩트 저장소로 옮기고 인덱스·해시를 남긴다. (3) 불필요한 복사본은 다른 날짜의 유효 증거와 혼동하지 않도록 명시한 뒤 정리한다.

**주의:** 파일명 before/after가 같아도 법적·업무적 증거 의미는 다를 수 있다. 파일이 깨지는 참조와 시각 회귀 검증을 먼저 확인한다. **2.90+1.51MB가 전부 삭제 가능하다는 뜻이 아니다.**

### F03 · P1 · 완전히 같은 내용의 파일을 다른 이름으로 추적

재귀 트리의 **동일 SHA 14그룹**에서 체크아웃 중복 분량 1.99MB를 확인했다. 대표 예시:

- ledger/data/ledger_current.xlsx = ledger/data/ledger_latest.xlsx (각 566,121 bytes)
- outputs/agoda-card-journal-shadow-detail-v3-clean-20260824.json = outputs/agoda-card-journal-shadow-detail-v3-clean-rebuild-20260824.json (각 337,386 bytes)
- outputs/agoda-card-journal-shadow-detail-v3-final-20260824.json = outputs/agoda-card-journal-shadow-detail-v3-rebuild-20260824.json (각 337,386 bytes)
- outputs/agoda-card-accounting-draft-detail-v3-clean-20260824.json = 해당 clean-rebuild 파일 (각 269,361 bytes)
- ledger/data/manual_periods.csv = ledger/data/manual_v4.csv (각 110,398 bytes)
- docs/agents/artifacts/card-login-paths-20261111.md = docs/playbooks/card-login-research-20261111.md (각 8,989 bytes)

**제안:** 별칭·운영 스냅샷의 의미를 구분해 단일 정본+명시적 접근 계층으로 통일하되, 생성 코드·테스트·문서·복원 절차의 사용처를 확인한다.

**용량 해석 주의:** Git은 같은 blob SHA를 객체 저장소에서 공유하므로 **경로 하나를 지운다고 Git 객체가 그 크기만큼 줄지 않는다**. 체크아웃 복제·탐색 혼란을 줄이는 개선이다. 해당 원본이 보호 경로면 F01을 따른다.

### F04 · P1 · Python의 초대형 책임 집중

| 파일 | 크기 | 확인된 구조 |
| --- | ---: | --- |
| [webapp/ledger_store.py](../../webapp/ledger_store.py) | 348,485 bytes | 6,657줄, LedgerStore 클래스가 약 6,367줄 구간 |
| [webapp/ledger_board.py](../../webapp/ledger_board.py) | 296,163 bytes | 5,800줄, Handler 클래스가 약 3,247줄 구간 |
| [webapp/card_flow.py](../../webapp/card_flow.py) | 274,591 bytes | 3,764줄, CardFlow 클래스가 약 1,707줄 구간 |
| [webapp/ota_payment_review.py](../../webapp/ota_payment_review.py) | 238,068 bytes | 3,453줄, CoreOtaPaymentBackend 클래스가 약 874줄 구간 |
| [webapp/receipt_review.py](../../webapp/receipt_review.py) | 153,119 bytes | 영수증 조회·검수 경로 |
| [app/ota_payments.py](../../app/ota_payments.py) | 140,369 bytes | OTA 연결·대사 구현 |
| [webapp/ledger_design.py](../../webapp/ledger_design.py) | 119,676 bytes | 화면·장부 표시 경로 |
| [webapp/access_control.py](../../webapp/access_control.py) | 110,595 bytes | 접근 제어 |
| [tools/core_bridge/golden.py](../../tools/core_bridge/golden.py) | 104,255 bytes | Python↔Rust 테스트 기준 생산 |

상위 4개만 **19,674줄, 약 1.16MB**다. 정적 분석에서 확인한 것은 **큰 책임 집중**이지 중복 구현·불필요 코드가 실제 존재한다는 증명은 아니다.

**변경 전 선행 조건:** M4의 공통 서버 장부 조회·React/기존 URL 수락 경로, M5의 작업 큐·임대·P2 실행기 소유 경계, M6의 고정 추출기 기준·퇴역 경계를 먼저 확정한다. 다음 항목은 **그 마일스톤의 구현 작업에 포함하거나 이후 수행**하고, 독립 대형 리팩터링 PR을 선행시키지 않는다.

1. LedgerStore의 저장·교정·원자성·감사·대사 헬퍼는 **M5 임대/작업 큐·M6 DB 통합 계약이 확정된 뒤** 공개 API를 유지하며 분리한다. 단일 작성자·revision·idempotency·수동 결정 보호를 유지한다.
2. Handler의 URL dispatch, 인증/권한, HTML 호환 페이지는 **M4 공통 조회·상세 교정 복귀 수락 후**, M5 서버/보조 노드의 계약을 훼손하지 않는 범위에서 분리한다.
3. CardFlow의 수집·판정/기록·화면 분리는 M4/M5 변경 영역과 겹치지 않는다고 확인된 범위부터 진행하며 환불/기장 보호를 각각 테스트한다.
4. `app/ota_payments.py`의 **OTA 사건 생성(`build_ota_payment_events`)과 `app/ota_mail.py`·포털 파싱은 M6 Rust 추출기 대상**이므로 선행 Python 리팩터링을 보류한다. Rust 사건↔카드 대사와 Python 사건 생성의 경계를 구별한다.

각 PR에서는 기존 함수·route·DB 계약을 유지한다. **줄 수 감소/모듈 분리 = 성능 향상으로 보고하지 않는다.** 회귀·리뷰 시간과 영향 범위가 작아지는지가 목표다.

### F05 · P1 · Python/Rust 전환 및 구형 HTML/React 이중 경로

**근거:** [현재 작업판](../agents/BOARD.md)은 Rust 판정 작성자와 2차 연결 producer 전환을 COMPLETE로 기록한다. 다만 M4 화면은 Python 웹 실행기·호환 경로를 사용하고, M5/M6까지 Python의 수집·추출·P2 운영 책임이 남는다([코어 안내](../../core/README.md), [명세](../SPEC.md)).

**제안:** 작성자 전환 완료와 **모든 소비자 대체 완료**를 혼동하지 않는 퇴역 후보 표를 만든다. 함수/경로마다 (가) 실제 route·CLI·작업자 호출 여부, (나) 테스트 호출 여부, (다) 운영 설정의 producer, (라) 롤백 의존성, (마) Python/Rust 동등 비교의 항목을 기록한다. **M6 추출기가 고정된 M3 기준(events 7,965건, SHA-256 `a26d446510faabe4cbdfd5d8cf114b0903e6b87b8453fdb3380d529e605cbaf6`)을 통과하고, Board/Core DB 이관·롤백까지 수락된 뒤** 전부 대체된 Python 단위만 별도 제거 PR로 다룬다. M5의 Python 기존 교정 반영 경로는 M5가 별도 작성자를 만들지 않는 동안 유지한다.

**보호:** Rust synthetic golden·환불/OTA 그림자 비교·복구 경로를 먼저 없애지 않는다. Rust 전환이 완료됐다는 사실만으로 Python 전체가 불필요한 것은 아니다.

### F06 · P1 · 테스트와 품질 구성의 유지비

**근거:** tests/ 289파일·2.69MB, webapp/tests/ 366파일·5.15MB. [영향 테스트 매핑](../../config/test-impact-map.json)은 112개 그룹을 관리한다. [기준 알려진 실패 목록](../../config/known-test-failures.txt)은 **2026-11-13 기준 항목 88개**이며 현재 88개가 실패한다는 뜻이 아니다. [품질 실행기](../../tools/run_quality_checks.py)는 기존 실패와 새로운 실패를 구분한다.

**제안:** 실행 시간 분포·모듈별 fixture 생성 비용·동일 계약 중복 검사·오랫동안 실패하는 오래된 계약을 분리해서 조사한다. 실효성이 입증된 중복 테스트만 줄이고 보호 테스트는 병합하거나 최신 계약으로 재작성한다. 오래된 실패 목록은 실측된 해소 여부에 따라 줄이고, 신규 실패는 차단한다.

**금지:** 전체 테스트를 삭제해 통과율을 높이거나 실패를 known에 일괄 추가하는 경량화. 영향 검사 0건·skip을 통과로 처리하는 것.

### F07 · P2 · 서비스에서 실제 쓰는 웹 폰트·이미지

- [webapp/static/fonts/PretendardVariable.woff2](../../webapp/static/fonts/PretendardVariable.woff2): **2,057,688 bytes**. [site_shell.css](../../webapp/static/css/site_shell.css)의 첫 줄 @font-face에서 참조하며 실제 웹 자산 후보라는 근거가 있다.
- [webapp/static/og/](../../webapp/static/og/): 두 PNG 합계 **1,205,414 bytes**. [social_preview.py](../../webapp/social_preview.py)는 두 파일 모두 공개 URL에 연결하고 공유 메타데이터에 하나를 사용한다.
- [webapp/static/css/ledger_design.css](../../webapp/static/css/ledger_design.css): 84,943 bytes, [webapp/static/js/ledger_design.js](../../webapp/static/js/ledger_design.js): 72,640 bytes.

**제안:** 브라우저 네트워크 기록으로 폰트 요청 수·실제 전송·캐시·첫 화면 렌더를 확인한다. 한국어 글립 범위가 유지되는지 검증한 뒤 WOFF2 subset·언어별 분할·시스템 폰트 대체안을 비교한다. OG 이미지는 URL 유지·미리보기 호환을 조건으로 무손실 또는 고품질 압축을 검토한다. CSS·JS는 기존 해시 URL·보안 헤더·캐시 계약을 보존한다.

**보류:** 실제 전송량/글꼴/미리보기 검증 없이 폰트를 없애거나 두 OG 이미지를 지우는 것. 이 크기는 Git blob이며 매 페이지의 다운로드 측정값이 아니다.

### F08 · P2 · React 컴포넌트와 실제 번들 분리

**근거:** [frontend/src/features/receipts/index.tsx](../../frontend/src/features/receipts/index.tsx) 69,808 bytes, [frontend/src/features/admin/google.tsx](../../frontend/src/features/admin/google.tsx) 54,182 bytes, [frontend/src/features/auxiliary/rules.tsx](../../frontend/src/features/auxiliary/rules.tsx) 30,775 bytes. [Vite 구성](../../frontend/vite.config.ts)은 base=/ui/다.

**제안:** production Vite build의 chunk별 gzip/brotli 크기와 초기 로드 route를 **읽기 전용으로 먼저 측정**한다. M4 공통 서버 조회·React/기존 상세 호환의 수락 기준과 화면 경계가 확정된 뒤에만, 실제 route에서 lazy import 및 데이터 요청 지연을 비교·적용한다. 분할 전/후 첫 화면·상세·권한·브라우저 회귀를 비교한다.

**주의:** TSX 소스 크기만으로 번들 과중·tree-shaking 실패·성능 문제를 확정하지 않는다.

### F09 · P2 · 문서·로그의 읽기 비용과 링크

**근거:** docs/history/ 135개·4.05MB. 그중 과거 명세 docs/history/specs-20261110/ 121개·1.68MB. 현행 [session_handoff.md](../session_handoff.md)와 [operations.md](../operations.md)는 누적 로그이며 매번 전문을 읽는 방식이 비효율적이다. [AGENTS.md](../../AGENTS.md)와 [문서 지도](../README.md)는 [MANAGER.md](../agents/MANAGER.md)를 현행 관리 지침처럼 안내하지만 이 문서 자체는 **2026-11-11부터 사용하지 않는다고 명시**한다.

**제안:** 현행 상태 1쪽(현재 운영 SHA/작성자/미검증 범위/다음 결정)과 날짜별 이력 파일을 분리해 전문을 읽을 필요가 없게 한다. 완료한 과거 기록은 링크로 남기되 매 작업 시작 시 전체를 재해석하지 않는다. AGENTS와 문서 지도에서 사용 중지된 관리 지침 링크를 **역사 자료**로 명확히 표시한다. 기존 링크의 단절이 없도록 리다이렉트 성격의 짧은 안내를 보존한다.

**효과 해석:** 문서 읽기·검색 부담 개선이 핵심이다. 기록을 보관하는 이상 Git 용량 절감은 제한적일 수 있다.

### F10 · P2 · 일회성 루트 패치 스크립트

**근거:** [fix_r55.py](../../fix_r55.py) 9,125 bytes, [fix_r57.py](../../fix_r57.py) 8,515 bytes, [migrate_safe.py](../../migrate_safe.py) 14,617 bytes는 ledger/domain 소스 파일에 직접 문자열 치환을 수행하는 스크립트다(합계 약 **32KB**). 이름과 내용상 **일회성 이관 후보**지만 현재 실행자/참조는 전수 검증하지 않았다.

**제안:** CI·README·운영 시작 코드·외부 배치에서 호출되지 않는지 확인하고, 정확한 실행 환경/적용 커밋을 기록한다. 실제 미사용 확정 후 history/tools 또는 승인된 archive로 이동한다. 반복적인 소스 텍스트 치환을 새 빌드·기동 경로로 채택하지 않는다.

**우선순위:** 작다. 데이터 보존/성능/대형 모듈보다 후순위다.

### F11 · P2 · 과거 코드·합성 골든을 삭제하면 안 되는 영역

**근거:** core/golden/synthetic/의 JSONL **11개·1.72MB**, Rust tests 및 Python bridge golden 생성 코드가 기준 비교의 핵심이다. 일부 ledger/baselines/와 테스트 fixtures도 과거 수치라 하여 삭제하면 재현 근거를 잃을 수 있다.

**제안:** M3의 고정 OTA 추출 기준(7,965건·확정 해시)과 M6 각 슬라이스의 동일 출력 수락, Python↔Rust 전환 일일 대조가 유효한 동안은 **관련 baseline·golden·생성기·브리지 파일을 경량화 삭제 후보에서 제외**한다. 기타 골든의 형식·케이스 coverage만 읽기 전용으로 조사하고, M6 수락 이후 중복 확인에 착수한다. Rust/Python 검증의 입력 기준 자체가 바뀌는 일은 별도 승인·동등성 확인을 요한다.

**금지:** 경량화를 위해 참조 골든 삭제 후 새 결과에 맞춰 테스트를 고쳐 통과시키기.

### F12 · P3 · 의존성·시작 경로 정리

[requirements.txt](../../requirements.txt)의 openpyxl·xlrd·pypdf·google-auth·PyJWT[crypto]·requests는 각각 카드 파일·PDF·Google OIDC의 지원 계약과 관련된다. [webapp/README.md](../../webapp/README.md)는 바이너리 XLS에 xlrd가 필요함을 명시한다. [frontend/package.json](../../frontend/package.json)과 lockfile은 재현 빌드를 위한 기준이다.

**제안:** 합성 경로에서 Python import-time/초기화 시간, 실제 의존 모듈 사용처, 프런트 build manifest를 먼저 측정한다. 사용처가 0인 것이 **소스·동적 호출·운영 환경에서 모두 입증**될 때만 의존성 삭제를 논의한다.

**금지:** requirements/lock을 줄이기 위해 실로그인·XLS·PDF 지원을 깨뜨리는 것.

## 3. M3~M6 마일스톤 연동 실행 순서

**선행 원칙:** 이 문서는 [SPEC §10~11.5](../SPEC.md#10-로드맵)와 [M5·M6 착수 설계](../design/m5m6-kickoff-20261117.md)를 대체하지 않는다. M3는 2026-11-17 인계에서 종료로 기록됐으며 추출 기준은 M6 수락의 고정 입력이다. M4 UI-0 운영 배포와 장부 공통 조회의 남은 통합은 별개다. **M5→M6이라는 단계 명칭상의 순서와 실제 작업 계획을 혼동하지 않는다:** M6 추출기 개발과 M5 제공자 비종속 큐·계측은 설계에 따라 병행할 수 있지만, 실제 클라우드 제공자 선택·과금·고객 원문 이전은 사용자 선택 게이트 이후다.

### 3.1 충돌 점검표

| 마일스톤 | 이미 확정된 기준·예정 변경 | 경량화 제한 | 선행 가능 작업 |
| --- | --- | --- | --- |
| **M3** 종료·M6 인수 | [추출 기준 생산 기록](../agents/artifacts/m3-extractor-baseline-20261117.md): 사건 7,965건·고정 SHA. 기존 Rust 판정/연결 전환 완료 | 추출기의 원본·canonical 출력·테스트·그림자 대조·복구 증거를 변경/삭제하지 않음 | 기준 manifest·사용처·보호 자료의 메타데이터 색인 |
| **M4** 장부 조회·UI | [SPEC §11.2.1](../SPEC.md#1121-장부-조회-통합)의 공통 서버 조회, React 목록·기존 상세/교정 URL 호환 수락 | 조회·합계·Handler 라우팅·React 구조의 **독립 분해 리팩터링을 선행하지 않음**. M4 구현과 중복하지 않도록 같은 변경 단위에서 처리 | 회귀 기준 수집, UI 번들·폰트 로드 **측정만** |
| **M5** 큐·노드·클라우드 | [착수 설계 §2](../design/m5m6-kickoff-20261117.md#2-m5--클라우드-서버보조-노드): 임대/재시도/예산/P2, 서버·노드의 기존 한 작성자, 백업·복원 | 작업 큐·DB·LedgerStore·Handler·P2 적용 경계를 먼저 임의로 재편하지 않음. 클라우드 이전/국외 원문 저장은 선택 게이트 전 금지 | 읽기 전용 요청량 계측·재현성 테스트, 제공자 비종속 구조화와 동시 설계 |
| **M6** Rust 추출기·Python 퇴역 | [착수 설계 §1](../design/m5m6-kickoff-20261117.md#1-m6--rust-추출기python-폐기): OTA 사건 생성, 메일/포털 파싱, 7,965건·고정 해시 수락, 최종 SQLite 통합 | `app/ota_payments.py::build_ota_payment_events`·`app/ota_mail.py` 등 Python 추출기를 **사전 분리·단순화·제거하지 않음**. 전환 전 기준과 브리지·동등성 검사 보존 | Rust 슬라이스 기준 추적/동등성·실행자 지도, 승인된 M6 자체 구현 |

### 3.2 우선순위와 변경 PR

| 차례 | 별도 PR 또는 조사 | 범위 | 수락·착수 조건 |
| --- | --- | --- | --- |
| 0 | **DATA-INVENTORY (읽기 전용)** | F01·F03 | 메타데이터·생산자/소비자·보존 가능성 조사만. M3/M6 기준·M5 백업에 걸린 파일은 보존 대상으로 잠금 |
| 1 | **DOC-ROUTING** | F09 | 현행 단계/사용 중지된 관리자 문서 라벨 정정, 기존 링크 유지. 기능 계약 변경 없음 |
| 2 | **UI-ASSET-MEASURE (측정 전용)** | F07·F08 | 현재 M4 산출물의 번들·폰트·OG 네트워크 기준 측정. 자산 교체·React 구조 변경은 M4 수락 이후 |
| 3 | **MILESTONE-BOUNDARY-MAP (읽기 전용)** | F04·F05 | M4 조회/URL, M5 큐/교정, M6 추출/DB 전환의 소유 파일·실행자·롤백·통합점 목록 생성 |
| 4 | **ARTIFACT-RETENTION (조건부)** | F02·F03 | M3 고정 기준·M6 회귀·M5 백업·M4 UI 수락 증거와 무관함이 확인되고 정책상 외부 보존·복원 완료 시에만 별도 삭제 PR |
| 5 | **UI-OPTIMIZE (M4 수락 이후)** | F07·F08 | M4 공통 조회·UI 기능/권한/복귀 호환 수락 및 같은 기준의 실제 성능 전후 대조 |
| 6 | **PY-BOUNDARIES (해당 마일스톤 후)** | F04 | M4 상세/공통조회, M5 큐·P2 적용, M6 Python 추출·DB 통합의 필요한 계약이 수락된 해당 범위만 분리·퇴역 |
| 7 | **TEST-DEBT / HISTORICAL-TOOLS** | F06·F10·F11·F12 | 각 마일스톤의 회귀 기준이 유지된 상태에서 사용처·대조·복구를 증명한 파일만 정리 |

**충돌 회피의 핵심:** 마일스톤이 곧 교체할 모듈은 **그 마일스톤 작업에서** 분리·퇴역시킨다. 독립 경량화 PR로 먼저 바꿔 작업을 중복하거나 M3 기준·M4 조회·M5 작성자·M6 추출기 검증을 흔들지 않는다.

**용량 우선:** 과거 산출물·복제 경로를 조사하되 protected 파일의 원본을 유지한다. **유지보수 우선:** 단계별 소유자·API 지도를 만든 뒤 확정된 경계만 나눈다. **속도 우선:** M4 실측 기준을 얻은 다음 웹 응답/요청을 최적화한다.

## 4. 삭제/변경 전 공통 게이트

- **원본·보호:** 카드 금액·부호·원승인·환불 묶음·원천 ID·수동 교정·Google 최종 장부가 불변인지 확인한다. 고객 원문·비밀은 PR·문서·로그에 복사하지 않는다.
- **보존:** protected 경로에 대한 삭제는 [tracked-data-policy](../../config/tracked-data-policy.json)의 외부 보존 manifest를 검증하고 신선 복원 테스트 후 **정책 PR과 삭제 PR을 분리**한다.
- **참조:** URL·import·문자열 경로·배치·운영 설정을 검사한다. 소스 내 문자열 한 번 찾았다고 활성 소비자라고 단정하지 않고, 없다고 미사용으로 단정하지 않는다.
- **테스트:** 변경 파일 기반 [영향 검사](../../tools/run_quality_checks.py), 금융 핵심 Rust fmt/clippy/test, 브라우저 계약, 해당 golden 차등 검사를 실행한다. 0 tests·skip·새 실패를 통과로 취급하지 않는다.
- **배포:** 빌드/PR 검증과 운영 적용은 별도다. 운영 SHA·현재 producer·같은 입력의 손익·권한·환불·복사·롤백 결과를 기록한다.
- **변경 기록:** 이전/이후 파일 수·Git 트리 합계, 실제 clone/pack 크기, 실제 브라우저 전송량, 테스트 소요, API p50/p95를 각각 별도로 측정한다. **측정하지 않은 성능 향상을 주장하지 않는다.**

### 재현용 명령 (로컬 체크아웃에서 승인된 합성/보호 환경으로 실행)

~~~sh
git rev-parse HEAD
git ls-tree -r -l HEAD
python tools/check_tracked_data.py --mode inventory --source-references
python tools/run_quality_checks.py --base origin/main --head HEAD --plan-json
python tools/run_quality_checks.py --base origin/main --head HEAD --run
# 프런트 변경이 있을 때만 frontend/에서:
npm ci && npm run typecheck && npm run build && npm run test:run
# Rust 경계 변경이 있을 때만 core/에서:
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
~~~

위 명령은 **이번 조사에서 실행하지 않았다**. inventory의 source-references는 정확히 적힌 Python 경로 문자만 찾으므로 동적 경로는 잡지 못하고, 원본 민감도를 판정할 수 없다. 출력·로그가 금융 원문을 포함하지 않는지 실행 환경 정책에 따라 별도 확인한다. 변경 PR이 없는 main에서 영향 검사는 NO_CHANGES가 나올 수 있으며 이를 테스트 통과라고 표시하지 않는다.

## 5. 이번 점검으로 확정하지 못한 사항

1. 보호 파일별 실제 민감도, 현 운영 소비자/생산자, 법적 보관 의무, 외부 보존본의 실제 복원 가능성.
2. Git 현재 checkout에서 파일을 없앤 뒤의 **실제 pack 저장량** 및 과거 이력 포함 clone 용량.
3. Python 모듈의 전체 import·실행 경로와 레거시 API가 더 이상 호출되지 않는지 여부.
4. 현재 라이브 네트워크·첫 화면 렌더·폰트 요청·브라우저 chunk 용량 및 API p95.
5. 최신 전체 테스트 실패 수·CI 사용량·느린 테스트 순위. known-failures의 88줄은 2026-11-13 기준선이지 현황 측정값이 아니다.

따라서 이 보고서는 **실제 삭제 후보를 가려내기 위한 정적 감사**다. 파일 보존 범위를 확정하거나 코드 퇴역을 승인하는 보고서는 아니다.
