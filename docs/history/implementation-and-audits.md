# 과거 구현·검토·실행 계획

**보관 기록 / ARCHIVED.** 아래 내용은 작성 당시 원문이다. 과거 TODO·READY·미구현·배포 SHA는 현재 작업 지시나 운영 상태가 아니다.

[시작 안내](../COST_V3_START_HERE.md) · [현재 상태](../session_handoff.md) · [운영 기록](../operations.md)

## 내용

- [아고다 예약 직접 조회와 메일 자료 통합 계획](#src-docs-agoda-aside-collection-plan-md)
- [아고다 Aside 수집·메일 통합 실행 기록](#src-docs-agoda-aside-execution-md)
- [COST UI 감사표 v2 — COST-UI-AUDIT-001](#src-docs-card-ui-audit-v2-20261025-md)
- [지출 정리 자동 처리 결과와 남은 근거 확인](#src-docs-cleanup-resolution-20261023-md)
- [지출 일괄 재분류 경로 감사](#src-docs-expense-bulk-audit-20261025-md)
- [실제 OTA 미결과 지출 정리 표시 진단](#src-docs-expense-cleanup-ota-diagnosis-20261024-md)
- [지출 정리 탐색과 여행 우선배정](#src-docs-expense-cleanup-task-index-md)
- [2026-10-20 채팅 세션 인계](#src-docs-handoff-session-20261020-booking-evidence-md)
- [OTA 미완결 연결 해결 실행](#src-docs-ota-resolution-execution-md)
- [참가자·수입 대조 작업 인덱스](#src-docs-participant-income-task-index-md)
- [COST 세션 인수 기록](#src-docs-session-takeover-20261012-md)
- [토요코인 예약 추론 연결 구현 계획](#src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md)
- [항공권 상세의 명시적 날짜 필터](#src-docs-superpowers-plans-2026-10-26-flight-manual-date-filter-md)
- [수동 테마 전환 구현 계획](#src-docs-superpowers-plans-2026-10-26-manual-theme-toggle-md)
- [카드결제검토 지연·카카오 잔여 진단 (2026-10-27)](#src-docs-superpowers-plans-2026-10-27-card-review-latency-md)
- [항공권 검색 장애·열린 PR 통합](#src-docs-superpowers-plans-2026-10-27-flight-search-integration-md)
- [Navigation read performance implementation plan](#src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md)
- [OTA provider scope and zero refund implementation plan](#src-docs-superpowers-plans-2026-10-27-ota-provider-refund-plan-md)
- [Pending COST work integration — 2026-10-27](#src-docs-superpowers-plans-2026-10-27-pending-work-release-md)
- [검수 지적 수정·모든 브랜치 통합·배포](#src-docs-superpowers-plans-2026-10-27-review-fixes-integration-md)
- [여행 장부 수입·지출 화면 통합](#src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md)
- [COST 웹 UI 감사 보고서 (2026-10-24)](#src-docs-ui-audit-20261024-md)
- [장부 화면 검토](#src-webapp-design-review-md)

---

<a id="src-docs-agoda-aside-collection-plan-md"></a>

## agoda-aside-collection-plan

통합 전 경로: `docs/agoda-aside-collection-plan.md`

<a id="src-docs-agoda-aside-collection-plan-md--아고다-예약-직접-조회와-메일-자료-통합-계획"></a>
### 아고다 예약 직접 조회와 메일 자료 통합 계획

기록일: 2026-10-20

후속 승인: 사용자가 계획 전체 실행을 지시했다. 아래 미실행 설명은 계획 작성 당시 상태다. 이후 구현과 실제 진행은 [실행 기록](implementation-and-audits.md#src-docs-agoda-aside-execution-md)을 따른다.

<a id="src-docs-agoda-aside-collection-plan-md--이번-요청과-완료-범위"></a>
#### 이번 요청과 완료 범위

사용자는 Aside REPL로 실제 예약 한 건을 확인하고, 누락된 결제 내역을 수집해 DB에 저장한 뒤 메일 자료와 통합할 실행 계획을 요청했다. 이번 요청의 완료 조건은 실제 상세 조회, 기존 저장 구조 확인, 확인한 사실에 기반한 계획 작성이다. 전체 수집·통합 코드 구현·운영 등록·장부 기록은 아직 실행하지 않았다.

현재 작업의 기준 문서는 이 계획이다. 이전 완료 과제를 다시 실행하지 않는다. 이번 브라우저 경로는 사용자의 최신 명시 요청에 따라 `aside repl`을 사용했다. 기존 IAB 전용 레거시 실행기 차단은 변경하거나 우회하지 않았다.

<a id="src-docs-agoda-aside-collection-plan-md--실제로-확인한-예약-한-건"></a>
#### 실제로 확인한 예약 한 건

- Aside 사용법과 내장 스킬 목록을 확인했다. 아고다 전용 내장 스킬은 없었다.
- 단발 `aside repl`의 새 탭은 명령 종료 후 유지되지 않았다. 대화형 `aside repl` 프로세스에서 같은 탭을 유지해 조회했다.
- 로그인된 아고다 홈페이지의 계정 메뉴 안에 있는 실제 `내 여행` 링크를 확인했다. 메뉴가 화면에 나타나지 않아 확인된 링크 주소로 이동했다. 주소를 추측하거나 숨겨진 API를 호출하지 않았다.
- `내 여행`은 예약이 많아 `모든 예약`으로 이동하도록 안내했다. 해당 버튼을 눌러 예약 목록에 들어갔다.
- 목록에는 `다가오는 예약`, `완료된 예약`, `취소된 예약` 탭, 체크인 날짜 정렬, 예약번호 검색, 이전·다음 페이지 버튼이 있다. 18개월 이전 예약을 위한 별도 `예약 보기` 버튼도 있다. 이 과거 예약 경로와 취소·예정 상세 형식은 이번에 검증하지 않았다.
- 완료 목록에서 특정 예약번호를 표시하는 카드와 같은 번호의 `예약 확인/변경하기` 버튼을 확인하고 상세로 들어갔다. 고객센터 버튼은 사용하지 않았다. 상세 화면의 예약번호가 목록 번호와 일치했다.
- 상세에서 연도가 있는 체크인·체크아웃, 투숙 완료 상태, 숙소명, 객실 요금, 세금·봉사료, 실제 결제 표시와 원화 금액, 카드 종류·끝자리를 확인했다. 객실 요금과 세금의 합이 표시된 결제액과 같았다. 목록의 날짜에는 연도가 없어 상세 날짜를 기준으로 삼아야 한다.
- `오늘 결제됨`에는 실제 결제일이 따로 표시되지 않았다. 조회한 오늘을 결제일로 해석하지 않는다. 취소 정책의 날짜도 결제일이 아니다.
- `이메일로 전자 영수증 받기`는 메일 발송이므로 누르지 않았다. 예약 변경·취소·새 예약·규칙 저장·거래 승인을 실행하지 않았다.

실제 예약번호·카드 끝자리·금액·개인정보가 포함된 스냅샷과 확인 결과는 Git 제외 경로 `.local-archive/agoda-aside-inspection-20261020/`의 `detail-snapshot.txt`, `inspection.json`에 보존했다. 이 문서에는 원문을 복사하지 않는다.

<a id="src-docs-agoda-aside-collection-plan-md--기존-자료와-대조한-결과"></a>
##### 기존 자료와 대조한 결과

운영 등록 목록의 포털 DB 11개에서 이 예약번호만 읽기 전용으로 조회했다. 10개 사본에 같은 예약이 있었으며, 대표 보존 DB에는 과거 예정 상태·총액 및 별도 과거 상세 관측이 있었다. 당시 상세의 결제 상태 표현과 금액 종류는 현재 정규 파서가 바로 실제 결제로 사용하는 형식과 달랐다. 최신 상세에서는 투숙 완료·결제 표시·카드를 확인했다. 이 차이는 새 예약 발견과 구분해야 한다.

등록된 메일 원본 5곳을 기존 로더로 읽어 중복을 제거한 1,919개 중 이 예약번호를 포함한 메일 한 건을 확인했다. 이는 이번 읽기 범위의 수치이며 전체 계정 메일 수나 전체 수집 완료를 뜻하지 않는다. 해당 한 건은 아고다 인증 검사를 통과했고, 실제 결제 파이프라인의 보조 파서는 예약번호와 이용기간을 읽지만 `reservation`·`not_card_charge`로 판단했다. 결제일·결제액·카드 끝자리는 추출하지 못했다. 메일이 없다고 보고하거나 단순 예약 메일을 결제 영수증으로 바꾸지 않는다.

따라서 이 표본은 **기존 예약의 결제 근거 보완 사례**다. 누락 카드 결제의 연결을 완료한 사례는 아니며, 카드 원행 대사나 여행 배정도 실행하지 않았다.

<a id="src-docs-agoda-aside-collection-plan-md--현재-저장통합-경로"></a>
#### 현재 저장·통합 경로

| 역할 | 현재 경로와 계약 |
| --- | --- |
| 자료 등록 | `app/ota_sources.py`, 운영 자료 폴더의 `ota-sources.json`. 메일 디렉터리 5곳과 포털 DB 11개를 등록한다. |
| 메일 원본 | 등록 디렉터리의 `gmail*.json`과 `collection.json`. 현재 실행 경로는 메일 원본 DB를 직접 읽는 구조가 아니다. |
| 포털 자료 | `bookings`, `direct_source_records`, `booking_source_evidence`를 읽는다. 원문 해시와 예약·기간·결제·카드·상태의 다섯 근거 역할을 검사한다. |
| 결제 정규화 | `app/ota_payments.py`의 `build_ota_payment_events()`. 메일과 포털 결제·환불 이벤트를 만든다. |
| 예약 목록 | `webapp/ota_catalog.py`. 결제 근거가 불완전한 예약도 조회한다. |
| 사용자 결정 | `app/ota_review.py`, 운영 `ota-review.sqlite`. 연결·제안·규칙·요청 등을 저장한다. 메일 원본 DB로 사용하지 않는다. |

현재 `portal_payment_date_required`는 참이다. 상세에 결제액·카드가 있어도 결제일이 없으면 새 자동 정확 연결을 완료할 수 없다. 이 보호를 끄지 않는다. 결제와 예약 이용기간은 별도 사실로 저장하고, 실제 결제가 연결된 뒤 여행 판단에는 이용기간을 우선한다.

<a id="src-docs-agoda-aside-collection-plan-md--구현-순서와-종료-조건"></a>
#### 구현 순서와 종료 조건

<a id="src-docs-agoda-aside-collection-plan-md--1-수집-대상과-재개-지점을-먼저-만든다"></a>
##### 1. 수집 대상과 재개 지점을 먼저 만든다

현재 미연결 아고다 카드 원행의 ID와 기존 보류·확정 연결을 읽기 전용으로 추출해 대상 목록을 만든다. 기존 예약·메일 색인과 비교해 `예약 없음`, `예약은 있으나 결제 근거 부족`, `결제일 부족`, `충돌`, `이미 연결됨`으로 나눈다. 예약번호가 있는 대상은 사이트의 예약번호 검색을 먼저 사용한다.

예약번호를 모르는 거래는 목록의 예약을 수집해 후보를 보완한다. 현재 카드 검토 기간을 우선하되 예약 생성일·결제일·이용기간이 서로 다르므로 체크인 날짜만으로 대상 결제를 제외하지 않는다. 종료 연도·페이지 수·예약 건수를 과거 수집 때의 값으로 고정하지 않는다.

종료 조건: 대상 거래별 누락 종류와 수집 큐가 저장되고, 같은 큐를 재시작해도 이미 끝난 상세 조회를 반복하지 않는다.

<a id="src-docs-agoda-aside-collection-plan-md--2-aside에서-목록을-먼저-색인하고-부족한-상세만-수집한다"></a>
##### 2. Aside에서 목록을 먼저 색인하고 부족한 상세만 수집한다

하나의 대화형 Aside 프로세스와 전용 탭을 한 작업자만 사용한다. 먼저 세 상태의 목록을 끝까지 조회해 예약번호·목록 상태·페이지별 예약 집합을 저장한다. 페이지 지문과 첫·마지막 번호로 페이지 중복과 누락을 확인한다. 목록 범위를 벗어나는 예약이 필요할 때만 18개월 이전 경로를 조사한다. 목록 날짜에 없는 연도는 만들지 않는다.

상세 큐는 새 예약과 필수 근거가 부족하거나 오래된 예약을 우선한다. 화면 스냅샷에서 예약번호와 해당 카드의 `예약 확인/변경하기` 버튼을 함께 확인하고 진입한다. 진입 뒤 예약번호가 다르면 저장하지 않고 해당 항목을 중단한다. 로딩 상태이면 새 스냅샷을 확인한 뒤 진행한다. 목록 재시도는 최대 다섯 번, 같은 예약 상세 진입은 최대 세 번이며 실패 원인을 남기고 다음 독립 항목으로 넘어간다. 인증·인증 코드·CAPTCHA는 사용자 단계로 남기고 우회하지 않는다.

예약별 저장 필드는 다음과 같다.

| 구분 | 필드와 해석 |
| --- | --- |
| 식별 | 공급자, 로컬 계정 구분값, 예약번호, 별도 참조 코드. URL의 암호화된 예약 토큰을 예약번호로 쓰지 않는다. |
| 이용기간 | 상세에 표시된 연도 포함 체크인·체크아웃, 시간과 시간대가 표시되면 원문도 보존한다. |
| 상태 | 예약 상태·결제 상태·취소 및 환불 상태를 따로 저장한다. 투숙 완료만으로 결제 완료를 추정하지 않는다. |
| 금액 | 객실 요금, 세금·봉사료, 예약 총액, 결제액, 캐시 사용액, 현지 추가 납부액을 종류별로 저장한다. 원문 문자열·통화·정수 최소단위·소수 자릿수를 유지한다. |
| 결제 수단 | 표시된 카드 종류·끝자리와 별도 결제 식별자. 카드 전체 번호와 보안 코드는 수집하지 않는다. |
| 날짜 | 실제 결제일, 결제 예정일, 환불일을 분리하고 화면에서 확인되지 않으면 빈값으로 둔다. |
| 출처 | 관측 시각, 원문 해시, 파서 버전, 실행·페이지·상세 확인 기록. 토큰이 포함된 원문 URL은 로컬 증거에만 두고 화면·Git에 노출하지 않는다. |

이번에 확인하지 않은 취소·예정·캐시 전용·복합 결제 양식은 실제 첫 표본을 확인한 뒤 파서를 확장한다. 아직 없는 표본을 이미 지원한다고 표시하지 않는다. `적립 AgodaCash`와 `사용 AgodaCash`를 구분한다. 환불 정책을 실제 환불 이벤트로 만들지 않는다. 화면에 환불 표시가 없다는 사실과 환불이 없다고 검증됐다는 사실도 구분한다.

종료 조건: 각 예약이 저장 완료 또는 구체적 수집 실패 상태를 가지며, 목록에 있는 예약이 상세 큐에서 조용히 빠지지 않는다.

<a id="src-docs-agoda-aside-collection-plan-md--3-운영과-분리된-로컬-증거-db에-저장한다"></a>
##### 3. 운영과 분리된 로컬 증거 DB에 저장한다

기본 저장 위치는 `.local-archive/agoda-aside-collection/<run-id>/evidence.sqlite`로 한다. 원본 메일·기존 포털 DB·운영 장부는 읽기 전용 입력으로 유지한다. 새 DB의 작성자는 하나다.

- `capture_runs`, `capture_pages`, `capture_items`: 계정 구분·상태 탭·페이지 지문·예약별 진행 상태·재시도·실패·재개 위치를 저장한다.
- `source_observations`: 원문과 정규화 결과의 해시, 원천 종류, 관측 시각, 파서 버전을 추가 방식으로 보존한다. 같은 원천 식별자와 같은 원문은 재삽입하지 않는다. 같은 식별자의 다른 원문은 새 관측으로 남기고 조용히 덮지 않는다.
- `bookings`, `direct_source_records`, `booking_source_evidence`: 기존 포털 읽기 계약과 호환되는 조회용 자료를 제공한다. 실제로 확인한 역할만 저장하며 다섯 역할을 통과시키기 위해 빈 근거를 채우지 않는다.
- `mail_sources`, `booking_mail_links`: 기존 메일 ID·원문 해시·인증 결과와 예약번호 연결을 저장한다. 기존 JSON 원본의 로컬 경로를 참조하고 기존 원본을 이동·삭제하지 않는다.
- `payment_observations`, `payment_evidence_links`, `evidence_conflicts`: 카드 결제·캐시 사용·예정 결제·환불을 분리하고, 같은 실물 결제임이 확인된 근거끼리만 연결한다.

메일 DB와의 통합은 이 출처 연결 계층에서 수행한다. 다른 메일 원본 DB가 추가로 확인되면 기존 메일 ID와 해시를 유지하는 읽기 어댑터로 연결한다. 존재를 확인하지 않은 별도 메일 DB를 있다고 가정해 마이그레이션하지 않는다.

종료 조건: 동일 입력의 반복 적재에서 예약·관측·실물 결제 수와 내용이 증가하지 않고, 원문이 다른 관측 및 실제 복수 결제는 각각 보존된다.

<a id="src-docs-agoda-aside-collection-plan-md--4-식별자와-상태-이력을-정리한-뒤-기존-통합기에-연결한다"></a>
##### 4. 식별자와 상태 이력을 정리한 뒤 기존 통합기에 연결한다

현재 `_portal_events()`의 출처 ID에는 DB별 이름공간 없이 숫자 레코드 ID가 들어간다. 독립 DB를 단순 추가하면 다른 예약의 같은 숫자가 충돌하거나, 같은 예약의 재수집이 별도 결제로 생길 위험이 있다. 운영 등록 전에 이 경계를 처리한다.

새 수집 자료에는 계정 구분·공급자·예약번호·실제 결제 식별자를 포함한 안정된 출처 키를 부여한다. 결제 식별자가 없으면 화면에서 단일 결제로 확인된 경우에만 안정된 구성요소 키를 사용하고, 복수 결제 구분이 안 되면 보류한다. 관측 시각·변경되는 금액·파일 경로를 실물 결제 식별자로 삼지 않는다. 기존 이벤트 ID와 사용자 수동 연결은 유지하고, 새 자료에는 별도 이름공간을 적용한다. 이전 근거와 동일한 결제라는 연결은 증명한 경우에만 추가한다.

예약 통합 키는 공급자·계정 구분·예약번호다. 같은 예약의 `예정 → 투숙 완료`는 시간에 따른 상태 변화로 보존한다. 같은 시점의 금액·기간 불일치나 명시 취소·환불은 별도 충돌 또는 상태 이벤트로 처리한다. 과거 사본이 여러 개라는 이유로 같은 과거 관측을 여러 결제로 세지 않는다. 예약 메일이 옛 포털 기록보다 앞선다는 사용자 규칙을 유지하고, 최신 자료라는 이유만으로 상충하는 메일·사용자 결정을 덮지 않는다.

메일과 포털의 같은 예약번호는 예약 단위로 묶되, 결제 이벤트는 현재 `_merge_proven_duplicate_payments()`의 보호를 유지한다. 같은 결제 식별자 또는 검증된 출처 연결이 있어야 합치며, 예약번호·금액이 같다는 이유만으로 이벤트를 합치지 않는다. 같은 출처 ID의 다른 원문은 검토 대상으로 남긴다.

이번 화면의 `오늘 결제됨`은 표시된 결제 사실과 액수로 보존하지만 실제 결제일로 변환하지 않는다. `collection_model`처럼 화면에서 확인하지 않은 사실을 기존 파서 통과 목적으로 채우지 않는다. 관측한 결제 표현을 정확히 다루는 어댑터를 추가하고, 부족한 필드는 진단에 남긴다.

종료 조건: 예약 목록에는 새 근거가 함께 보이고, 결제일 미확인·출처 충돌·복수 후보가 기존 보류 사유로 구분된다. 기존 메일·포털 결제의 ID와 확정 연결이 유지된다.

<a id="src-docs-agoda-aside-collection-plan-md--5-대상-카드만-대사하고-결과를-검토-가능하게-만든다"></a>
##### 5. 대상 카드만 대사하고 결과를 검토 가능하게 만든다

새로 보완한 예약과 직접 관련된 미연결 카드만 기존 결제 대사기에 입력한다. 원문 통화·정확 금액·카드·실제 결제일 또는 이미 승인된 예정일 대사·유일성 조건을 따른다. 결제일이 없으면 수집일·체크인·매입일을 대신 넣지 않는다. 동액 복수 예약과 실제 복수 거래를 하나로 합치지 않는다. 환율·할인·분할을 새로 만들어 맞추지 않는다.

결과는 `새 예약 발견`, `기존 예약 보완`, `결제 연결 가능`, `결제일 부족`, `후보 중복`, `출처 충돌`, `취소·환불 확인 필요`로 구분한다. 연결 가능 건은 원행 ID와 근거 해시를 함께 보여 준다. 연결이 늘어난 합계만으로 안전성이나 멱등성을 주장하지 않는다. 사용자 확정·보류·환불·기록된 장부 날짜는 유지한다. 카드와 캐시가 함께 있으면 같은 예약번호로 묶되 별도 지불 수단으로 보존한다.

종료 조건: 모든 대상 거래에 결과와 이유가 있고, 기존 원문·확정·보류·환불 연결과 장부 행이 바뀌지 않았다는 개별 비교 근거가 있다.

<a id="src-docs-agoda-aside-collection-plan-md--변경-범위와-필요한-한-번의-검증"></a>
#### 변경 범위와 필요한 한 번의 검증

예상 구현 위치는 신규 수집 실행기·증거 저장 모듈, `app/ota_portal.py`, `app/ota_payments.py`의 새 출처 어댑터와 식별자 처리다. `app/ota_sources.py`와 운영 등록 파일은 연결 준비가 끝난 뒤 필요한 범위만 변경한다. 화면 재설계·Render 이전·Google 자동 쓰기는 포함하지 않는다.

표적 검사는 실제로 구현한 범위에 한 번 수행한다. 합성 자료로 현재 상세 양식 추출과 실제 결제일 빈값, 잘못된 예약 버튼·재개, 동일 입력 반복, 상태 변화와 진짜 충돌, 서로 다른 DB의 숫자 ID 충돌, 기존 수동 연결 보존, 메일·포털 동일 결제와 실제 복수 결제, 취소·환불·캐시 분리를 확인한다. 기존 관련 검사는 `tests/card_pipeline/test_ota_portal.py`, `tests/card_pipeline/test_ota_sources_registry.py`, 변경 시 결제 identity 관련 표적 테스트만 지정한다. 전체 pytest·전체 OTA 재대사·반복 브라우저 확인을 기본 조건으로 추가하지 않는다.

운영 자료 등록은 준비된 새 DB와 기존 입력의 복구 사본·복원 검증, 사용자 결정과 금액·ID·환불 연결의 비교를 마친 뒤 별도 운영 반영 단계로 진행한다. 이번 요청에서는 운영 등록과 장부 기록을 실행하지 않는다. 웹 조회가 자동 기록 경로로 이어질 수 있으므로 운영 등록을 단순 파일 복사로 취급하지 않는다.

<a id="src-docs-agoda-aside-collection-plan-md--현재-상태와-다음-정확한-작업"></a>
#### 현재 상태와 다음 정확한 작업

- COMPLETE: 실제 예약 한 건의 Aside 상세 조회, 기존 포털·보존 메일의 해당 예약 확인, 로컬 증거 보존, 이 실행 계획 작성.
- 미실행: 전체 목록 수집, 증거 DB 구현·적재, 통합기 수정, 카드 대사, 운영 등록·배포·장부 기록.
- 확인이 더 필요한 사실: 취소·예정·캐시 양식, 과거 예약 경로, 표본 예약의 실제 결제일. 이번 한 건의 화면 확인을 전체 예약 형식 검증으로 확대 해석하지 않는다.

실행을 이어갈 때는 `git status -sb`로 사용자 변경을 확인하고, 이 문서의 1단계인 읽기 전용 대상 큐 생성부터 시작한다. 이미 확인한 표본과 로컬 증거를 재사용한다. Aside는 `aside guide repl`을 확인한 뒤 대화형 `aside repl` 세션 하나를 사용한다. 로그인 세션의 지속 여부는 그때 확인하며, 이번 세션 종료 뒤에도 새 탭이 계속 유지된다고 가정하지 않는다.

---

<a id="src-docs-agoda-aside-execution-md"></a>

## agoda-aside-execution

통합 전 경로: `docs/agoda-aside-execution.md`

<a id="src-docs-agoda-aside-execution-md--아고다-aside-수집메일-통합-실행-기록"></a>
### 아고다 Aside 수집·메일 통합 실행 기록

2026-10-20 사용자가 [계획](implementation-and-audits.md#src-docs-agoda-aside-collection-plan-md)의 전체 실행을 승인했다. 아래는 계획 이후의 실제 실행 상태이며 운영 반영 완료 선언이 아니다.

<a id="src-docs-agoda-aside-execution-md--최종-실행-결과"></a>
#### 최종 실행 결과

2026-10-21 관측 목록 40페이지·예약 1,550건과 우선 상세 370건을 단일 운영 DB에 적재했다. 상세 큐는 완료 370·실패 0·잔여 0이다. 취소 목록의 39개 페이지와 마지막 37개 페이지는 실제 전체 스냅샷을 그대로 보존했으며 임의로 예약을 채우지 않았다. 목록 전체와 우선 상세 범위를 구분한다. 아래 초기 실행 설명은 당시 기록이며 현재 진행 상태는 이 항목과 [운영 문서](../operations.md)를 따른다.

파서 버전 2는 실제 미래 예약의 콜론 없는 번호·숙박 날짜 범위·결제 실패 기한·현장 결제·캐시 사용·환불 예정을 처리한다. 이전 원문과 파서 이력은 삭제하지 않는다. 완료 224·확정 21·취소 125건의 상세에서 기간과 상태를 읽었고 미지원 양식 진단은 없었다. 실제 결제일은 370건 모두 표시되지 않아 빈값을 유지했다. 투숙 완료나 `오늘 결제됨`에서 날짜를 추정하지 않는다.

최종 DB는 `D:/WebLedgerHost/data/ota-evidence.sqlite`, 운영 릴리스는 `0a88cb7f63c6515c760ed0cb25b5d76dde9fae02`다. 메일도 같은 DB에 1,932개가 있다. 원문과 기존 이벤트 1,468개의 ID·금액·날짜·근거, 모든 보호 대상 행이 보존됐고 전체 캡처 반복 적재의 모든 행 해시가 같았다. 카드 213건의 진단 결과는 결제일 부족 138·정확한 금액과 카드 관측 부족 75건이다. 부족한 사실을 만들어 연결하지 않았다.

최종 원문·검사 결과는 `.local-archive/agoda-aside-collection/20261020/supervisor/`와 `.local-archive/ota-unified-20261020/`에 보존한다. 수집기는 종료됐고 실행 세션을 재개할 필요가 없다. 기존 캐시 비용 2건은 중복 기장하지 않았으며 새 22,500원 사용의 미기장 미리보기를 남겼다. 결제 거부 2건의 실제 화면 안내와 **10월 21일 21:43 전** 기한도 별도로 기록했다. 결제·카드 변경·Google 쓰기는 하지 않았다.

<a id="src-docs-agoda-aside-execution-md--구현과-실제-적재"></a>
#### 구현과 실제 적재

- `app/agoda_capture.py`: 계정·예약번호·진입 버튼 증명·원문 해시·관측 시각을 검사하고 원문과 변경 이력을 보존한다. 새 출처 ID의 `aside-v1` 이름공간은 레거시 숫자 ID와 충돌하지 않는다. 동일 예약의 관측이 바뀌어도 결제 이벤트 ID를 유지하며 금액·카드·기간 충돌은 보류한다.
- `tools/ingest_agoda_aside.py`: 캡처와 등록된 보존 메일을 로컬 증거 DB에 적재한다. DB 경로는 저장소의 `.local-archive` 아래만 허용한다.
- `app/ota_portal.py`: Aside에서 명시된 결제 표시·카드·금액을 읽는 제한된 형식을 추가했다. 실제 결제일 보호는 유지하고 확인되지 않은 `collection_model`을 만들어 넣지 않는다.
- 실제 보존 메일 1,919개와 아고다 예약의 메일 출처 연결 151개를 저장했다. 연결된 메일 모두가 결제 영수증이라는 뜻은 아니다. 실제 상세 표본과 수집 중인 목록도 적재했다.
- 같은 실제 상세·메일을 다시 적재한 전후에 증거 DB 모든 테이블의 행 수와 정렬된 전체 행 해시가 같았고 SQLite 무결성 검사도 통과했다. 증거는 로컬 `idempotence-evidence.json`이다.

관련 표적 검사 15개, 메일 반복 적재·원문 충돌·금액 검사 3개, 불완전 스냅샷 거부 검사 1개가 각각 통과했다. 전체 회귀·운영 DB 재대사·배포·서버 재시작은 아직 수행하지 않았다.

<a id="src-docs-agoda-aside-execution-md--목록-누락-원인과-보완"></a>
#### 목록 누락 원인과 보완

초기 `interactive:true` 캡처는 `superseded-interactive/`에 보존됐다. 새 적재기는 이 형식을 완전한 근거로 받지 않는다. 기존 파일과 행을 삭제하지 않고 불완전한 과거 관측으로 구분한다.

실제 전체 스냅샷에서는 완료 목록의 끝 페이지가 14였다. 초기 불완전 관측의 6이나 과거 페이지 수를 전체 페이지 수로 사용하지 않는다.

추가로 `다음` 버튼 클릭 후 화면이 아래쪽에 남으면 상단 일부 카드가 접근성 트리에서 빠지는 현상을 재현했다. 같은 페이지에서 검색창을 화면 안으로 올린 후 전체 스냅샷을 읽자 예약번호 수가 37개에서 40개로 늘었다. 페이지 이동 뒤 상단으로 이동하고 전체 스냅샷을 저장한다. 현재 페이지 번호·로딩 종료·이전과 다른 예약 집합도 확인한다. 누락이 확인된 캡처만 보완한다.

<a id="src-docs-agoda-aside-execution-md--현재-상태와-재개-위치"></a>
#### 현재 상태와 재개 위치

저장 모듈·제한된 읽기 어댑터·메일 적재·실제 표본·반복 적재 검증은 완료했다. 전체 목록·우선 예약 상세 수집, 최종 대사, 운영 자료 등록·배포는 진행 중이거나 미실행이다. 실제 값과 원문·DB·큐는 `.local-archive/agoda-aside-collection/20261020/`에만 둔다.

정확한 진행 위치는 `supervisor-checkpoint.json`과 최신 전체 캡처를 따른다. `collector/manifest.json`의 초기 완료 표시는 불완전 관측을 포함할 수 있어 단독 완료 근거로 쓰지 않는다. 확인하지 않은 취소·캐시·복합 결제 양식은 원문과 미지원 사유를 보존하며 사실을 만들어 기존 파서에 맞추지 않는다.

```powershell
python tools/ingest_agoda_aside.py --capture-root .local-archive/agoda-aside-collection/20261020/collector --db .local-archive/agoda-aside-collection/20261020/evidence.sqlite --run-id 20261020 --report .local-archive/agoda-aside-collection/20261020/collector-ingest-report.json
```

입력 폴더에는 검증한 최신 캡처를 지정한다. 웹 조회가 자동 기록으로 이어질 수 있으므로 진행 중인 증거 DB를 운영 등록 파일에 바로 추가하지 않는다. 수집 품질·충돌·기존 연결을 검토하고 승인된 운영 반영은 복구 사본·복원 검사 후 진행한다.

---

<a id="src-docs-card-ui-audit-v2-20261025-md"></a>

## card-ui-audit-v2-20261025

통합 전 경로: `docs/card-ui-audit-v2-20261025.md`

<a id="src-docs-card-ui-audit-v2-20261025-md--cost-ui-감사표-v2--cost-ui-audit-001"></a>
### COST UI 감사표 v2 — COST-UI-AUDIT-001

> **역사적 UI 감사(2026-10-25 기준 후속 변경 발생):** 이 문서는 PR #103 작업 당시의 단발 소스 감사로, 이후 PR #104(테마)와 PR #109(카드 전체 내역/항공/영수증/OTA UI 통합)이 main에 병합됐다. 하단의 `/cards/all 미구현`, `READY`, 브랜치 ahead/behind는 **이전 기준의 기록**이다. 최신 구현 vs 명세 상태는 [CURRENT HANDOFF §0.13](product-and-handoffs.md#src-docs-cost-v3-current-handoff-md) 참조. 기존 브라우저 미실행 이력은 PASS로 변경하지 않는다.


> 상태: PR-0 문서 전용 (§6). 구현·브라우저 테스트 미수행. 소스 확인 1회만 수행. 기존 feature branch는 git show 비교 후 미검증 참고.
> 기준 SHA: b2a470b910d96caea29c255d6b76c619dbdb4a9e (base of docs/cost-ui-audit-v2-20261025)
> 현재 branch: docs/cost-ui-audit-v2-20261025 (base b2a470b; 이전 22 behind/6 unique; 현재 HEAD=69e46e8; 현재 origin/main..HEAD=1 ahead; origin/main..feat/card-all-transactions-ui-audit=13 ahead; 단순 push 금지)

<a id="src-docs-card-ui-audit-v2-20261025-md--1-감사-기준-및-출처"></a>
#### 1. 감사 기준 및 출처
- 명세: docs/card-all-transactions-and-ui-design-system-spec-v1.md §1, §4.3, §6
- 범위: 메뉴/URL/렌더/CSS/JS/권한/카드 원행 데이터 출처/상세 ID 경로 추적. 운영 자료 읽지 않음.
- 브라우저: NOT_TESTED
- 테스트/빌드/배포: 금지 (§5.3, AGENTS.md)

<a id="src-docs-card-ui-audit-v2-20261025-md--2-소스-확인-1회-실제-경로"></a>
#### 2. 소스 확인 (1회, 실제 경로)
| 항목 | 경로/함수 | 증거 |
|---|---|---|
| 메뉴/라우트 | webapp/card_flow.py:1996,2007 | grep 확인 (path /cards, /import) |
| 렌더/네비 | card_flow.py:419-423, 2945-2963 | inline nav/work_menu_html |
| 인라인 CSS | card_flow.py:3001 | inline style block 확인 |
| 인라인 JS | card_flow.py:3038,3055 | el(), innerHTML, rule-propose |
| 권한/접근 | webapp/access_control.py:56 (ROLE_OWNER 상수), 97 (partial unique index) | 권한 증거; 카드 row ID 아님 (주의: 상수 존재 ≠ 거래 ID) |
| 카드 원행 DB | webapp/ledger_store.py:273-276 (card_import_rows 테이블: row_id, bank_batch_id, bank_row_index), 1466/1472 (batch_id order), 3741 (import_row), 4465 (link_bank_source) | 실제 DB 스키마/함수 확인; 거래 안정 ID는 row_id + bank_batch_id + bank_row_index |
| 거래 ID (카드 원행) | card_flow.py: preview.rows.find(r=>r.transaction_id); ledger_store card_import_rows row_id | 거래 ID 증거; ROLE_OWNER는 해당 없음 |
| 상세/다음 행동 | webapp/card_actions.py | next_action() → href 재사용 (§1.4) |
| 공통 레이아웃 | ledger_design.py (work_menu_html 참조) | 참조 확인 |

<a id="src-docs-card-ui-audit-v2-20261025-md--3-featde2beb1-비교-git-show만-미검증-참고"></a>
#### 3. feat/de2beb1 비교 (git show만, 미검증 참고)
- 브랜치: feat/card-all-transactions-ui-audit (de2beb1)
- 대상: docs/ui-audit-20261024.md, docs/design/cost-saas-ui-refresh.md (존재 확인)
- 사용: unverified reference; 이식/수정/테스트 금지. diff 로컬 보존, 감독 출력 제외.

<a id="src-docs-card-ui-audit-v2-20261025-md--4-ui-감사표-43--소스-확인-기준--브라우저-not_tested"></a>
#### 4. UI 감사표 (§4.3) — 소스 확인 기준 / 브라우저 NOT_TESTED
| URL/메뉴/렌더 | 운영 | 공통 레이아웃 | 하드코딩 CSS | 일관성 | 표/배지 | 모바일/대비 | 라이트·다크 | 리스크 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| /cards (card_flow.py:1996/2007, nav 419, inline CSS 3001, JS 3038/3055) | 예 | 부분 | 예(inline) | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | CSRF/권한/DOM/금융write | P0 | SOURCE-VERIFIED(라우트/렌더) / BROWSER-NOT_TESTED |
| /import?batch=... (card_flow/card_actions next_action) | 예 | 부분 | 예 | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 금융write/리비전/권한 | P0 | SOURCE-VERIFIED(경로/함수) / BROWSER-NOT_TESTED |
| 카드 원행 조회 (ledger_store card_import_rows: row_id, bank_batch_id, bank_row_index) | 예(DB) | N/A | N/A | N/A | N/A | N/A | N/A | 중복·취소·환불·충돌 보존 | P1 | SOURCE-VERIFIED(ID 계약) / BROWSER-NA |
| 실제 owner 메뉴 목록 (확인 가능) | /cards, /import (card_flow); work_menu_html (ledger_design 참조); 권한: access_control ROLE_OWNER | - | - | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 권한/CSRF/금융write | P0~P1 | SOURCE-VERIFIED(메뉴/권한) / BROWSER-NOT_TESTED |
| 하위 페이지 전체 / PR0 전수 메뉴 누락 | 불명/미검증 | 불명 | 불명 | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 금융write/CSRF/외부호출 | P1~P2 | NOT_VERIFIED / NOT_TESTED / REFERENCE_ONLY |

<a id="src-docs-card-ui-audit-v2-20261025-md--41-실제-owner-메뉴-항목-work_menu_html-기반-최종-추가-8행"></a>
#### 4.1 실제 owner 메뉴 항목 (work_menu_html 기반, 최종 추가 8행)
| URL (메뉴 href 원문) | 핸들러/렌더 파일·함수 (line) | 공통/전용 CSS·JS | 읽기/쓰기/권한 경계 | source 검증 | 브라우저 | 다음 조치 |
|---|---|---|---|---|---|---|
| /board (work_menu_html line 1003, ledger_board allowed 1070, card_flow 421) | webapp/ledger_board.py (route /board, 렌더 HTML 67/797/1070/1407/1482 등) | ledger_design.py .work-menu / site-links (125/135/191/980~1021); 카드 인라인 CSS card_flow 3001 별도 | 읽기(주요) + 쓰기(탭/검색/수정 via /row 등); 권한: access_control ROLE_OWNER + allowed paths | SOURCE VERIFIED (함수/경로 1회 확인) | NOT_TESTED | P0: 공통 레이아웃/메뉴 일관성 + 표적 검증 |
| /import (work_menu_html 1004) | webapp/card_flow.py (path /import 1996), webapp/card_actions.py (next_action) | ledger_design site-links 공통; card_flow 인라인 JS/CSS 별도 | 쓰기(업로드/분류/규칙 제안); CSRF/revision 보호; 권한 owner | SOURCE VERIFIED | NOT_TESTED | P0: 권한/CSRF/금융 write 경로 재검증 |
| /ota (work_menu_html 1005) | webapp/card_flow.py / ota_payment_review / ota_reconcile_child 참고; ledger_board 1070 allowed | 공통 site-links | 읽기/쓰기(OTA 결제 검토/재대사); 외부 호출 금지 | SOURCE VERIFIED (경로 존재) | NOT_TESTED | P1: OTA 정확 연결/환불/중복 보호 확인 |
| /receipts (work_menu_html 1007) | webapp/ledger_board.py / receipt 관련(참조 확인) | 공통 site-links | 읽기(영수증 조회); 쓰기 제한 | SOURCE VERIFIED (메뉴 href 존재; 상세 렌더 미완료) | NOT_TESTED | P1: 상세 렌더/표면 확인 필요 |
| /trips (work_menu_html 1011) | webapp/card_flow.py (line 427; /trips 링크); ledger_board 1070 allowed | 공통 site-links | 읽기(여행 목록); 쓰기(이동/배정 via 사용자 확정) | SOURCE VERIFIED | NOT_TESTED | P1: 여행 배정/이동 경로 안정성 |
| /reserve-links (work_menu_html 1012) | webapp/ledger_board.py / reserve-links 참고 | 공통 site-links | 읽기/쓰기(링크 관리) | SOURCE VERIFIED (메뉴 존재; 상세 미검증) | NOT_TESTED | P2: 저빈도; 상세 렌더 확인 후 순차 |
| /flight-passengers (work_menu_html 1014) | webapp/flight_passenger_page.py | 공통 site-links | 읽기/쓰기(탑승자) | SOURCE VERIFIED (파일 존재) | NOT_TESTED | P1: 개인정보/권한 경계 확인 |
| /access/admin (work_menu_html 1017, ledger_board 458) | webapp/access_control.py (ROLE_OWNER 56, 97); ledger_board /access/admin 경로 | 공통 site-links | 관리자 쓰기/권한 변경; 인증/로그/캐시 | SOURCE VERIFIED | NOT_TESTED | P0: 권한/접근 제어 재검증 |
| /rules (work_menu_html 780 reference; ledger_board 1070 allowed) | webapp/card_flow.py (rule-propose/approve 3054), ledger_design 780 | 인라인(JS) + 공통 | 쓰기(규칙 제안/승인); AI/재분류 경로; CSRF | SOURCE VERIFIED | NOT_TESTED | P1: AI 제안/승인 안전성 |

> 추가 행 수: 9개 메뉴 항목 (/board, /import, /ota, /receipts, /trips, /reserve-links, /flight-passengers, /access/admin, /rules). /cards는 기존 §4 표에 별도 행 있음(중복 제외하여 실제 menu 항목 9개 추가). bank_batch_id는 카드 원행 DB 스키마 증거로만 사용; 거래 ID 증거는 card_flow transaction_id / ledger_store row_id 사용. 없음: /cards/all 별도 라우트 확인 미완료(§2.1 권장 경로는 실제 코드에서 /cards로 처리됨).

<a id="src-docs-card-ui-audit-v2-20261025-md--5-후속-큐-ready-기준선-기록"></a>
#### 5. 후속 큐 (READY, 기준선 기록)
READY (후속 구현 티켓; 기존 완료/검증 HOLL 유지, 재시작 구분):
1. 공통 테마 토큰 최소 구축(PR-1 방향, 시스템 prefers-color-scheme) — 안전 의존성(기존 기능 깨지지 않음) 필수; NOT_TESTED 유지
2. 시스템 테마 영향 표적 검사(공통 CSS 변경 → 기존 핵심 페이지 표적 검증)
3. 카드 전체 조회 구현(PR-2, 월 그리드/4논리열/정렬/상세 링크) — 안전 의존성 필수

(기존 P1~P2 하위 페이지, 데이터 계약, 권한 재사용은 HOLD/미검증 상태 유지; 새로운 일반화 규칙은 사용 승인 전 적용 금지)

HOLD: feat/de2beb1 이식/수정 금지.

<a id="src-docs-card-ui-audit-v2-20261025-md--6-미확정위험-근거-기반"></a>
#### 6. 미확정/위험 (근거 기반)
- 브라우저 테스트 미수행 → PASS 금지; NOT_TESTED 유지 (§5.2, §5.3).
- 운영 DB/Google 쓰기 없음 → 코드/함수 증거만.
- PR100/102 완료 및 앞선 브랜치 정리 완료(재실행 금지).
- 배포·자동 병합: 금지. HEAD는 커밋 전(b2a470b 기준).

<a id="src-docs-card-ui-audit-v2-20261025-md--7-실제-검사-명령결과-1회-출력을-문서에-기록-긴-로그는-로컬-보존-감독-출력-제외"></a>
#### 7. 실제 검사 명령/결과 (1회, 출력을 문서에 기록; 긴 로그는 로컬 보존, 감독 출력 제외)
- `ls outputs/card-ui-audit-v2-evidence-20261025.md`: exit=1 (존재하지 않음 → 잘못된 인용 삭제함)
- `git diff --check`: exit=0 → 문서 공백 검사 통과(기능 PASS 아님; 브라우저/구현 검증 아님)
- `git ls-tree -r --name-only de2beb1 | grep -E 'ui-audit|cost-saas-ui-refresh'`: docs/ui-audit-20261024.md, docs/design/cost-saas-ui-refresh.md 확인 → 정확 경로 사용; 미검증 참고 유지
- `git rev-parse HEAD`: 69e46e8 (이전 감사 커밋); 현재 HEAD는 이 커밋 참조(자기참조 문제 피함; base b2a470b 별도 기록)
- `python -c "import os; print('evidence=',os.path.exists('outputs/card-ui-audit-v2-evidence-20261025.md'))"`: evidence=False
- `git rev-list --count origin/main..HEAD`: 1; `origin/main..feat/card-all-transactions-ui-audit`: 13

<a id="src-docs-card-ui-audit-v2-20261025-md--8-증거-경로-로컬-보존-감독-출력-제외"></a>
#### 8. 증거 경로 (로컬 보존, 감독 출력 제외)
- outputs/ (아래 새 증거 파일 없음; 명령 결과는 본 문서 §7에 기록)
- .local-archive/ (기존 보호, 변경 없음)
- git diff --cached --stat (2개 파일): audit + checkpoint (커밋 69e46e8)
- 기능 PASS/구현 완료: 없음 (NOT_TESTED 유지)

---

<a id="src-docs-cleanup-resolution-20261023-md"></a>

## cleanup-resolution-20261023

통합 전 경로: `docs/cleanup-resolution-20261023.md`

<a id="src-docs-cleanup-resolution-20261023-md--지출-정리-자동-처리-결과와-남은-근거-확인"></a>
### 지출 정리 자동 처리 결과와 남은 근거 확인

<a id="src-docs-cleanup-resolution-20261023-md--현재-결과"></a>
#### 현재 결과

운영 장부에 아고다 4건과 부킹닷컴 1건, 총 2,673,921원을 추가 기장했다. 5건 모두 원문 예약번호·카드 금액·검증된 여행과 일치하며 장부 날짜는 숙박 시작일이다. 원문, 기존 장부, 사용자 확정, 환불, 수동 고정과 학습 자료를 보존했다. Google 최종 장부 쓰기는 0건이다. 결과는 `.local-archive/targeted-checks/20261023-completed-stays-live-result.json`의 `PASS`로 확인했다.

현재 근거 확인 대상은 **161건**이며 항목 미분류 3건, 여행 근거 미확인 125건, 보호 대상 33건이다. 카드 장부 기록은 2,560건이고 전체 장부 행은 2,564개다. 기존 348건 중 확정 장부 121건을 재검토에서 제외했고, 카드 66건 4,951,218원을 실제 기장해 187건을 처리했다. 이전 장부 13건의 여행 보완은 이 건수에서 다시 차감하지 않는다.

최종 배포 후 Aside 실제 운영 화면에서도 161건과 세 가지 사유별 건수를 확인했다. 처음 열린 탭이 아직 로드되지 않아 첫 확인은 실패했지만, 같은 탭의 로드 완료 후 확인에 성공했다. 증거는 `20261023-final-ui-smoke.json`이다. 예약 검색 인증 화면은 닫지 않고 보존했다.

최종 운영 릴리스는 `6bda111bdc3100480f989f8ccb02aeeaf8c2209a`다. 일괄 기장 후 필요 없는 화면 자료 재계산을 생략해 결과 응답을 지연시키던 경로도 수정했다. 개별 카드 입력의 기존 응답은 유지한다. 관련 표적 검사 3개가 통과했고, 기장 검증과 기록 구문이 바뀌지 않았음을 AST로 확인했다. 변경 파일은 2개이며 나머지 860개 파일은 동일하다. 관리 배포가 성공했고 복구 검증 자료는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261023T013850/`에 있다. 원래 코드 검사와 유효한 재현 결과는 재사용했고 전체 회귀는 실행하지 않았다.

기장 관리 스크립트는 5건 기장과 모든 보존 검사에 성공한 결과 파일을 저장한 뒤, 종료 정리의 `service.stop(timeout=30)`에서 `RuntimeError: OTA snapshot worker did not stop in time`으로 종료 코드 1을 반환했다. 기장 실패가 아니라 후처리 워커 대기 시간 초과이며 두 결과를 구분한다. 해당 스크립트는 이미 기록된 5건을 다시 처리하지 못하도록 보호하며 **재실행하지 않는다**. 원문 오류와 마지막 단계는 `20261023-completed-stays-live.txt`에 보존했다.

트립닷컴의 추가 예약 조회는 실제 예약용 이메일의 일회용 인증에서 부분 차단됐다. 사용자에게 Aside 예약 검색 화면에서 직접 인증을 완료하도록 요청했다. 채팅으로 전달받은 인증코드는 문서·파일·로그에 옮기거나 대신 입력하지 않는다. 인증 후 해당 예약의 실제 결제 금액·카드·이용기간을 수집하고 기존 메일과 대조하는 단계가 남았다. 나머지 161건을 모두 해결했다고 보고하지 않는다. Aside 대화형 REPL 세션은 `86472`, 예약 검색 페이지는 `https://kr.trip.com/passport/ordersearch?curr=KRW&locale=ko-KR`이며 자동 수집이 진행 중인 것은 아니다.

재개 시에는 위 결과 파일과 사용자 인증 완료 여부부터 확인한다. 기장 스크립트를 반복하지 않고 기존 Aside 세션의 예약 검색 결과를 읽는다. 기존 문서 미커밋 변경 두 개와 원문 자료는 보존한다. 아래 문단은 시간순 조사 이력이며 현재 운영 수치로 재해석하지 않는다.

348건을 사용자가 직접 분류하도록 넘기지 않는다. 이미 확정된 정상 미배정 장부 121건은 재검토 대상에서 제외했고, 카드 61건 2,277,297원을 실제 자동 기장했다. 기존 장부 13건은 금액과 날짜를 유지하면서 여행과 추론 근거만 보완했다. Google 최종 장부에는 쓰지 않았다.

운영 금융 변경은 `34ee817a58790abe5bcb13587f4052123c01dc9b`, 화면 개선은 `3cd0e1f5da720a5e34dc08a5333590791c65e0e0`이다. 관리 배포는 성공했고 복구 검증 자료는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261022T203407/`에 있다. 금융 동작 여섯 함수는 화면 개선 전후 AST가 동일하다. 직접 영향 표적 검사 54개와 화면 표적 검사가 통과했다. 전체 회귀와 이미 유효한 검사는 반복하지 않았다.

2026-10-23 읽기 전용 집계에서 남은 거래는 166건이다. 항목 미분류 3건, 여행 근거 미확인 130건, 보호 대상 33건이다. 보호 대상에는 취소 거래 26건이 포함된다. 이전 예상 136건과 27건은 실제 최신 집계로 대체한다. 장부 카드 기록은 2,555건이고 전체 장부 행은 2,559개다. 취소 거래에는 새 비용 항목 입력을 요구하지 않고 원결제 근거 확인을 표시한다.

원문과 기존 금융 필드 보존, 기존 여행 보완 13건, 신규 61건의 복사본 검증 일치, OTA와 검토 자료 보존 검사는 통과했다. 근거는 `.local-archive/targeted-checks/20261022-resolve-348-protection-after-post.json`과 `20261022-resolve-348-live-result.json`이다. 이 기장 스크립트를 다시 실행하지 않는다.

트립닷컴 미분류는 같은 날 같은 금액 85,621원 두 건과 1,345,388원 한 건이다. 전체 수신 메일을 해독해 검색한 결과 85,621원과 일치하는 금액 원문은 발견되지 않았다. 1,345,388원은 서로 다른 예약의 카드 사전승인과 취소 수수료 안내에서 확인됐다. 따라서 금액만으로 결제 완료와 예약 연결을 확정하지 않는다. 원문 검토 자료는 `20261023-trip-decoded-amount-hits.json`에 로컬 보존했다.

Aside로 트립닷컴에 접속해 로그인 창을 확인했다. 이메일과 계정 선택이 필요한 비로그인 상태이며 인증 우회나 임의 계정 선택은 하지 않았다. COST 화면 재확인은 탐색 시간 초과와 `CDP command timeout: Page.enable`로 실패했다. 배포 성공과 서버 상태 확인을 실제 브라우저 표시 성공으로 혼동하지 않는다. 공통 런타임 재시작은 하지 않는다.

다음 단계는 운영 OTA 스냅샷과 미해결 거래를 읽기 전용으로 대조해 연결 실패 사유를 집계하고, 기존 근거로 해결 가능한 경로를 좁혀 수정하는 것이다. 예약 이용일을 결제일로 만들지 않고, 실제 복수 결제와 취소·환불·사용자 결정을 보존한다. 브라우저 인증이 필요한 예약만 별도 차단으로 남기며 독립적인 로컬 분석과 구현을 계속한다.

<a id="src-docs-cleanup-resolution-20261023-md--후속-조사와-실제-화면-확인"></a>
#### 후속 조사와 실제 화면 확인

Aside 새 탭으로 운영 화면 재확인에 성공했다. `근거 확인이 필요한 거래 166건`과 항목 미분류 3건, 여행 미배정 130건, 보류·오류 33건을 확인했다. 이전 탭의 탐색 실패는 이 성공 기록으로 보완했다. 증거는 `20261023-evidence-queue-ui-smoke.txt`다.

남은 거래 중 OTA 연결 결과가 있는 28건을 원문 이벤트와 대조했다. 트립닷컴 숙박 17건은 취소 예약, 트립닷컴 항공 4건과 클룩 2건은 이용기간이 없다. 아고다 투숙 완료 4건과 부킹닷컴 1건에는 이용기간과 카탈로그 여행 근거가 있다. 아고다 4건은 과거 직접 수집 해석에 비용 항목이 없어 연결 이후 분류로 전달되지 않은 결함을 발견했다.

개발 `2c6c759`와 `b5d1497`에서 Aside 형식의 투숙 완료와 이용기간이 모두 확인된 경우에만 숙박비를 보완하고, 파서 버전을 올려 이전 캐시를 재사용하지 않도록 했다. 다른 상태와 형식, 이용기간 누락, 기존 명시 항목은 보존한다. 원문과 이벤트 식별자, 금액, 카드 끝자리, 실제 결제일은 바꾸지 않는다. 표적 검사 4개와 코어 장부 연계 검사 2개가 통과했다. 운영 복사본의 대상 4건 분류 검증은 진행 중이며 이 수정의 운영 반영과 추가 기장은 아직 하지 않았다.

취소 거래 26건 중 원승인번호가 있는 거래는 7건이다. 동일 카드와 원화 금액으로만 보면 원결제 후보가 없는 거래 16건, 후보 하나인 거래 6건, 후보 여럿인 거래 4건이다. 같은 원결제에 취소가 여럿 있는 사례도 있어 단순 금액 연결을 실행하지 않는다. 후보 조사 결과는 `20261023-cancel-original-candidates-private.json`에 로컬 보존했다.

<a id="src-docs-cleanup-resolution-20261023-md--2026-10-23-운영-연결-누락-수정과-대상-기장-진행"></a>
#### 2026-10-23 운영 연결 누락 수정과 대상 기장 진행

후속 조사에서 아고다 4건의 실제 연결은 과거 포털 자료를 가리켰다. 해당 원문은 `product_type=lodging`을 명시하지만 `item`이 없었다. 명시 숙박 상품도 비용 항목으로 전달하도록 보완했다. 부킹닷컴은 같은 예약의 기존 결제 영수증에 이용기간이 없다는 이유로 다른 검증 자료의 이용기간까지 무시했다. 기존 카드와 예약, 원문 식별자가 같은 단일 연결에만 기간을 보완하며 기존 기간·취소·충돌·다른 예약·중복 연결은 보존한다.

일괄 정리의 긴 원문 해석도 데이터 잠금 전에 마치도록 바꿔, 그동안 입력 확인 워커가 갱신을 진행할 수 있게 했다. 최신 연결의 유효 시간이나 보호 조건은 완화하지 않았다. 파서·동일 예약 기간 보완·잠금 관련 표적 검사와 운영 분리 브랜치 검사를 통과했다. 운영 입력 전체를 재사용한 매칭 재현에서 대상 5건 모두 올바른 여행으로 배정됐으며, 원문과 기존 금융 자료 보존 검사도 통과했다. 재현 결과는 `20261023-completed-stays-trial-v4/replay-result.json`이다. 앞선 복사본 검증에서는 아고다 배정이 실패했으며 그 기록을 삭제하거나 통과로 해석하지 않는다.

운영 전용 브랜치와 릴리스 `146b528e73a9b67f8b8e859c4f3883ec5818f7ef`를 push하고 관리 배포에 성공했다. 변경 파일 6개만 포함했고 다른 856개 파일의 동일성을 검증했다. 운영 복구 검증은 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261023T012436/`에 있다. 개발 main의 다른 미배포 변경과 이전 문서 미커밋 변경은 분리해 보존했다.

승인된 실제 대상 5건은 운영에서도 여행 배정 검사를 통과했다. `.local-archive/targeted-checks/apply_completed_stays_20261023.py`가 표준 검증과 자동 기장 경로를 실행 중이다. 현재 기록은 `20261023-completed-stays-live.txt`의 단계와 최종 `20261023-completed-stays-live-result.json`으로 판단한다. 최종 결과 파일이 생기기 전에는 기장 완료로 보고하지 않으며, 실행 중인 스크립트를 다시 실행하지 않는다. 예상 금액은 2,673,921원이고, 실제 장부 날짜는 4건의 숙박 시작일과 부킹닷컴 숙박 시작일이어야 한다.

Aside에서 트립닷컴 구글 로그인에 성공했지만 현재 로그인 계정에는 예약이 없었다. 실제 결제 메일 수신 주소는 예약용 다른 이메일이며, 예약 검색 화면에서 해당 주소의 일회용 인증을 요구했다. 코드를 발송하고 사용자에게 Aside 화면에서 직접 인증하도록 요청했다. 인증 코드는 읽거나 대신 입력하지 않는다. 인증이 필요한 예약 상세 수집만 보류하며 독립적인 운영 검증은 계속한다. 실제 Gmail에서도 85,621원의 정확한 검색 결과는 0건이었다. 결제일 전후 메일 10개를 검색했고 결제 원문 두 스레드를 로컬에 보존했다. 엔화 결제액을 임의 환산해 원화 카드와 확정 연결하지 않았다. 임시 원문은 `20261023-trip-live-thread-captures-private.json`이며 인증 근거가 없는 관측을 결제 확정 메일로 만들어 DB에 넣지 않는다.

---

<a id="src-docs-expense-bulk-audit-20261025-md"></a>

## expense-bulk-audit-20261025

통합 전 경로: `docs/expense-bulk-audit-20261025.md`

<a id="src-docs-expense-bulk-audit-20261025-md--지출-일괄-재분류-경로-감사"></a>
### 지출 일괄 재분류 경로 감사

기준: `d4c5934` 작업 트리 소스와 합성 테스트 코드. 운영 DB/API, 실제 금융자료, 배포 동작은 확인하지 않았다.

<a id="src-docs-expense-bulk-audit-20261025-md--호출-경로와-쓰기-영향"></a>
#### 호출 경로와 쓰기 영향

- 일반 화면 `render_expense_cleanup()`은 owner 역할에서만 내용을 렌더링한다. 이전 UI의 전용 스크립트는 클릭 시 CSRF 헤더를 붙여 `POST /api/imports/reclassify-pending`를 호출했다. 이 요청은 화면 조회와 별개인 쓰기 요청이다.
- `dispatch()`의 해당 POST 분기는 owner 및 CSRF 검증 뒤 `reclassify_cleanup(board)`를 직접 호출한다. 이 일괄 요청 전체에는 재전송 키, 미리보기 버전, 다중 프로세스 실행 게이트가 없다. 인증된 직접 재전송은 계속 가능하다.
- `reclassify_cleanup()`의 `board._lock`은 전체 요청이 아니라 쓰기 구간을 프로세스 안에서 직렬화한다. OTA `warmup`/`request_check` 호출은 이 잠금 밖에서 일어나며 외부 워커에 접촉할 수 있다. 운영 워커 동작은 확인하지 않았다.
- `app.classify.classify_batch`는 `transactions`, `import_batches`, `change_log`를 `BEGIN IMMEDIATE` 또는 기존 트랜잭션용 `SAVEPOINT`로 갱신한다. `app.ledger.commit`은 `ledger_entries`, `transactions`, `import_batches`, `requests`, `change_log`와 `CardFlow.project`의 `board_rows`, `board_revisions`를 하나의 `BEGIN IMMEDIATE` 안에서 반영한다. `assign_existing_local_expenses()`는 `board.save`를 호출해 `board_rows`, `board_revisions`, `board_requests`를 행 단위로 별도 저장하므로 전체 재처리는 원자적이지 않다. 결과에 일부 성공과 실패가 함께 반환될 수 있다.
- 규칙 설정 직후의 `reclassify_pending()`은 미래 적용 설정에 따라 미기장 거래를 재분류하는 별도 경로다. 카드 업로드 후 자동 처리는 업로드 처리에서 `_classify()`와 `_auto_record_locked()`를 부르는 별도 흐름이다. 둘 다 일반 화면 조회와 다르며 이번 UI 수정에서 제거하지 않았다.

<a id="src-docs-expense-bulk-audit-20261025-md--현재-보호와-남은-위험"></a>
#### 현재 보호와 남은 위험

- 일반 화면과 해당 POST는 owner 역할 및 CSRF 검사를 사용한다. 화면 전용 JS는 중복 클릭 중 버튼을 잠시 비활성화했지만, 서버는 일괄 요청 전체에 재전송 키나 다중 프로세스 게이트를 적용하지 않는다.
- 재분류/기장 경로에는 수동 결정·보류·충돌·파싱 오류·중복·취소/환불 및 기존 기장 보호 분기가 있다. 개별 여행 이동은 요청 기록과 revision을 확인한다. 이는 모든 거래가 불변이라는 보증은 아니다.
- 이번 변경은 일반 화면의 일괄 버튼과 전용 클릭 동작만 제거했다. `POST /api/imports/reclassify-pending`와 서버 처리 함수는 남아 있다. 유효한 owner 세션과 CSRF 토큰을 가진 직접 호출은 여전히 분류, 내부 장부 기록, 기존 장부 여행 귀속을 바꿀 수 있다.
- GET 화면 렌더링은 읽기·집계만 수행하고 해당 일괄 POST를 호출하지 않는다. 배포된 운영 코드와 실제 자료의 동작은 검증하지 않았다.

<a id="src-docs-expense-bulk-audit-20261025-md--다음-유지보수-작업"></a>
#### 다음 유지보수 작업

별도 `EXPENSE-BULK-MAINT-01`에서 owner 전용 경로와 읽기 전용 사전 미리보기, 미리보기 이후 최신성 확인, 범위 동의, 중복/동시 실행 통제, 비밀정보 없는 감사 기록을 설계해야 한다. 기존 POST를 포함한 모든 쓰기 진입점을 같은 게이트에 묶고 합성 자료로 검증하기 전에는 새 관리 UI를 열지 않는다.

<a id="src-docs-expense-bulk-audit-20261025-md--표적-검증"></a>
#### 표적 검증

실행 명령: `python -m pytest -q webapp/tests/test_cleanup_reclassification.py webapp/tests/test_expense_cleanup.py webapp/tests/test_cleanup_ota_contract.py::test_cleanup_reads_change_no_card_decision_or_ledger_state`.

실제 결과 출처: 검사 결과는 29 passed, 1 failed(3.85초)였다. 실패는 `test_expense_cleanup.py::test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence`이며, 기준 커밋 `d4c5934`의 `webapp/card_flow.py`를 메모리에 읽어 별도 프로세스에서 해당 테스트 하나를 실행해 기준 실패를 재현했다(0.45초). 기준 검증에서 작업 파일을 복원하거나 초기화하지 않았다. 기존 실패를 수정하지 않았으며, 그 뒤 반복 검사는 생략했다. 변경된 지출 정리 UI, 건별 처리, 페이징, 조회 불변성 표적 검사는 통과했다.

전체 회귀, 브라우저 E2E, 운영 API/DB, 배포, 실제 일괄 POST는 실행하지 않았다.

<a id="src-docs-expense-bulk-audit-20261025-md--인계"></a>
#### 인계

AUDIT-01 및 UI-01 개발과 합성 검토를 완료했다. 작업 브랜치는 `feat/expense-bulk-ui-safety-20261025`, 구현 커밋은 `1d585cb`다. MAINT는 별도 PR 및 위험 검토 전까지 시작하지 않았다. push, PR 생성, 병합, 배포는 하지 않았다. 다음 검토는 이 브랜치에서 `git show --stat 1d585cb`로 시작하고, 운영 POST는 실행하지 않는다. 기존 `C:\AX\cost` 작업공간과 stash는 보존했다.

---

<a id="src-docs-expense-cleanup-ota-diagnosis-20261024-md"></a>

## expense-cleanup-ota-diagnosis-20261024

통합 전 경로: `docs/expense-cleanup-ota-diagnosis-20261024.md`

<a id="src-docs-expense-cleanup-ota-diagnosis-20261024-md--실제-ota-미결과-지출-정리-표시-진단"></a>
### 실제 OTA 미결과 지출 정리 표시 진단

진단은 2026-10-24 운영 runtime `d9c5adc`와 최신 main `4fb4e70`을 구분해 수행했다. 고객 원문은 로컬에서만 읽었고, 원본 DB는 `mode=ro`로 열었다. 이 문서는 거래 식별자·카드 끝자리·예약번호·고객명을 포함하지 않는다. 세 거래는 날짜·금액·가맹점에 맞는 원행이 각각 1건이며 필요한 금융 식별자는 로컬에서만 대조했다.

<a id="src-docs-expense-cleanup-ota-diagnosis-20261024-md--확인된-거래별-상태"></a>
#### 확인된 거래별 상태

| 거래 | 카드 금융 상태 | OTA 근거 상태 | 중앙 매칭 결과 | 여행 귀속 | 화면 문제 | 해결 여부 |
| --- | --- | --- | --- | --- | --- | --- |
| A · Trip.com · 09-23 · 230,191원 | 구매 원행 정상, 충돌·중복·파싱 오류 없음, 미기록 | 같은 숫자가 있는 예약 안내는 있으나 결제 완료 근거가 아니다. 등록 원문에서 이 카드 금액의 검증 결제 사건은 없음 | 연결·점유 없음. 같은 날 Trip 결제 사건 11개 중 카드 정체성 불일치 8개·금액 불일치 3개 | 기존 탭에 배정돼 있으나 Google 기간 매핑과 일정 권위 기록이 없어 `trip_no_longer_valid` | 범용 예약 확인 문구가 실제 여행 권위 보류를 가림 | 원인 확인. 표시 수정·배포 완료이며 결제·여행의 실제 확정은 추가 자료 필요 |
| B · Trip.com · 09-23 · 690,318원 | 구매 원행 정상, 충돌·중복·파싱 오류 없음, 미기록 | 같은 숫자가 있는 예약 안내는 있으나 결제 완료 근거가 아니다. 등록 원문에서 이 카드 금액의 검증 결제 사건은 없음 | 연결·점유 없음. 같은 날 Trip 결제 사건 11개 중 카드 정체성 불일치 8개·금액 불일치 3개 | A와 같은 기존 탭이며 권위 미확인, `trip_no_longer_valid` | 결제 근거 부재와 여행 권위 무효를 구별하지 않음 | 원인 확인. 표시 수정·배포 완료이며 금액만으로 예약을 확정하지 않음 |
| C · Agoda · 09-22 · -625,280원 | 깨끗한 취소 원행. 같은 카드·원승인번호의 +625,280원 원결제와 유일하게 연결. 환불 1건, 순액 0원, 양쪽 미기록 | 등록 OTA 원문에 해당 금액의 결제·환불 사건은 없음. 카드 자체의 원승인 연결은 존재 | OTA 연결 없음. 카드 원결제 연결은 전액 상쇄 | 원결제의 여행 확인 자동 보류가 유지됨 | 원결제가 있는데도 모두 “원결제 근거 필요”로 안내 | 원인 확인. 연결 완료와 `refund_pair_incomplete`를 함께 표시하며 금융 보호 유지 |

<a id="src-docs-expense-cleanup-ota-diagnosis-20261024-md--단계별-근거"></a>
#### 단계별 근거

1. **카드 원행:** 세 거래 모두 원행은 각 1개다. 등록된 CSV 원본을 다시 읽어 해당 행을 각 1개 재현했고 금액 보존·파싱 오류 0을 확인했다. 원본에 외화 금액·통화 열이 없으며 재파싱으로 복원되지 않는다. 빈 외화 값을 일치 근거로 사용하지 않았다. A/B는 사용자 확정이나 수동 OTA 연결·고정 그룹 점유가 없다. C는 원결제와 취소를 합치거나 새 지출로 바꾸지 않았다.
2. **등록·수집·파싱:** 운영 manifest의 통합 OTA DB를 읽었으며 등록 경로 누락·읽기 오류는 없었다. 메일 원문 3,036개를 읽었다. A/B 금액 문자열이 있는 예약 안내는 파서에서 `reservation / not_card_charge / payment_status=unknown`으로 분리됐으며 이용기간은 11-07~11-08이다. 결제 완료 문구가 없고 별도 서명 결제 파서도 같은 예약 관측으로 판정했다. 금액 문자열이 있다는 이유만으로 카드 지불 사실로 승격하지 않았다. 전체 Trip 관측은 922개이며 결제 사건 수와 같은 의미가 아니다.
3. **계보·이벤트:** 현재 파서로 등록 원문을 읽어 생성한 이벤트 ID가 중앙 generation 261에 모두 존재했다. 해당 안내의 예약 관측도 중앙에 있다. 관련 동일 날짜 결제 사건에 lineage·observation 식별자가 존재한다. 이 세 거래에서 수집 실패·계보 유실·이벤트 누락을 원인으로 확인하지 않았다.
4. **중앙 세대:** generation 261, 생성 시각 `2026-10-24T12:14:18+00:00`을 기준으로 진단했다. 이후 워커 로그에서 같은 세대의 `held=true`, `failed=false`, `refreshing=false` 확인 기록을 읽었다. 생성 시각이 오래됐다는 이유만으로 stale이라 단정하지 않았다. 디스크 파일에는 전체 근거와 실시간 `checked_at`이 없으므로 파일 단독으로 현재 화면의 freshness를 보장하지 않는다.
5. **후보·거절:** A/B는 해당 원화 금액의 검증 결제 사건 자체가 없으며, 같은 날의 다른 사건은 카드 식별 또는 금액에서 탈락했다. 허용 오차를 늘리거나 다른 카드의 예약을 가져오지 않았다. 복수 후보가 있는 합성 조건은 실제 거래 원인과 별도로 검증한다.
6. **사용자 결정·점유:** 세 카드에 수동 OTA link나 frozen group 점유가 없다. 기존 결정·원행·기장 이력은 바꾸지 않았다.
7. **여행 권위:** A/B의 기존 여행 탭 자체는 삭제·보관 상태가 아니지만 해당 탭의 Google 기간 매핑과 일정 권위 기록이 없다. `trip_valid=False`의 원인을 확인했다. 예약 안내의 이용기간만 보고 탭을 권위 있는 여행으로 승격하지 않았다.
8. **경비 미리보기:** 추가 보호를 제외한 기본 금융 preview와 실제 자동 기록 보호를 합친 preview를 구별했다. A/B는 모두 `trip_no_longer_valid`다. C의 기본 preview는 연결된 전액 환불이지만, 실제 자동 보호를 적용하면 원결제의 `trip_needed`가 `review_hold`로 전달되고 환불은 `refund_pair_incomplete`다. 이를 준비 가능이라고 표시하지 않는다.
9. **기존 화면:** `_ota_entries_by_card()`는 예약 캐시의 확정 `card_matches`만 읽어 미확정 후보와 거절 사유가 사라지고, 카드별 단일 dict의 마지막 예약이 앞선 예약을 덮을 수 있었다. 예외도 빈 결과가 돼 실제 자료 부재처럼 안내했다. 취소 행의 문구는 실제 원결제 연결과 무관하게 동일했다.
10. **다음 조치:** A/B는 검증된 결제 원문 또는 카드사의 외화 승인·청구 식별 근거와 해당 여행의 Google 일정 권위가 필요하다. C는 원결제의 여행 확인 보류를 기존 검토 경로에서 해결해야 한다. 조회나 이번 코드 변경으로 실제 배정·환불 기록을 처리하지 않는다.

<a id="src-docs-expense-cleanup-ota-diagnosis-20261024-md--변경과-검증-경계"></a>
#### 변경과 검증 경계

표시 경로는 한 요청에서 확보한 중앙 결과·후보·거절 사유·오류·신선도를 사용한다. 결제 연결, 여행 배정, 금융 준비는 별도 상태로 안내한다. 예약 목록 캐시는 탐색 용도로 남기고 결제 확정 여부의 권위로 사용하지 않는다. snapshot 표시 조회는 대사 실행·갱신 요청·DB 쓰기를 수행하지 않는다.

진단 당시 운영 자료와 비식별 결과 경로는 `.local-archive/spec-completion/three-ota-cards/`였다. 2026-10-25 재개 환경에서는 해당 경로가 없어 다시 읽지 않았다. 호스트의 배포·복원·보존 증거는 남아 있다. `private-*`는 외부 모델과 Git에 전달하지 않는다. 원본 조회 중 SQL 변경은 0건이며 이번 작업의 운영 고객 자료·Google 쓰기는 0건이다. 후속 사용자 승인으로 PR #100 병합과 운영 배포를 완료했다. runtime은 `1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`이며 실제 거래 확정·기장 완료를 뜻하지 않는다. 합성 검사와 PR 결과는 [현재 인계 0.12절](product-and-handoffs.md#src-docs-cost-v3-current-handoff-md--012-2026-10-24-실제-ota-미결-진단과-지출-정리-표시-복구)에 기록한다.

수정한 지출 정리 25건, 중앙 표시 계약 11건, 환불 표시 6건, 원자적인 스냅샷 표시 1건과 기존 금융 준비·사용자 이동·부분 그룹 계약 3건을 표적으로 검증했다. 실제 세 거래의 로컬 렌더링도 A/B 여행 권위 보류·C 원결제 연결과 금융 보류 표시를 확인했고, 요청당 snapshot 읽기 1회·DB 변경과 쓰기 시도 0건이었다. 원본·수동 연결·금융 매칭·장부 쓰기 함수는 수정하지 않았다. 전체 회귀와 추가 전체 OTA 대사는 반복하지 않았다. 후속 승인 배포에서는 파일 925개 대조와 DB 5개·보호 파일 59개 백업·별도 복원·전후 보존을 확인했다. 외부 health/ready 200·비인증 OTA/import 401과 Aside 기존 소유자 화면의 새 표시를 확인했다. 중앙 근거 갱신 중 안내 확인과 새 세대의 거래별 확정 판단은 구별하며, 화면 조작으로 실제 거래를 처리하지 않았다. 복구 경로는 `D:/WebLedgerHost/data/backups/expense-cleanup-20261024T225203/`이며 자세한 배포 근거는 [운영 기록](../operations.md)을 따른다.

---

<a id="src-docs-expense-cleanup-task-index-md"></a>

## expense-cleanup-task-index

통합 전 경로: `docs/expense-cleanup-task-index.md`

<a id="src-docs-expense-cleanup-task-index-md--지출-정리-탐색과-여행-우선배정"></a>
### 지출 정리 탐색과 여행 우선배정

사용자 승인 범위는 스크롤 중 메뉴 접근 개선과 여행 배정 필요가 남는 코드 경로의 수정이다. 과거 작업 큐를 다시 실행하지 않는다.

<a id="src-docs-expense-cleanup-task-index-md--nav-구현과-합성-검증-완료"></a>
#### NAV: 구현과 합성 검증 완료

- 명세: [스크롤 메뉴](../specs/ui.md#src-docs-expense-cleanup-navigation-spec-md).
- 모바일 공용 상단 메뉴를 고정한다. 장부 검색 막대도 고정하고 표 머리글은 실제 막대 높이 아래에 둔다. 데스크톱의 기존 독립 스크롤은 유지한다.
- 표적 검사 `tests/test_ledger_navigation_scroll.py`: 3 passed.
- Aside 합성 `/import`를 폭 390px의 같은 출처 iframe으로 확인했다. 스크롤 8509.6px에서 메뉴 막대 top=0, 버튼 top=8px이었다. 메뉴 열기 후 마스크와 expanded=true를 확인했고 Escape 후 닫힘과 마스크 숨김을 확인했다. 스크롤 위치는 유지됐다. 실제 모바일 기기 검증과 운영 배포는 하지 않았다.

<a id="src-docs-expense-cleanup-task-index-md--assign-구현과-합성-검증-완료"></a>
#### ASSIGN: 구현과 합성 검증 완료

- 기존 분류기는 예약 결제의 정확 연결 또는 좁은 현지 사용 규칙이 없으면, 유효한 기존 여행이 있어도 일반적인 우선 후보를 생성하지 않았다.
- 원본에 결속된 낮은 신뢰의 여행 규칙을 기존 분류 엔진에 전달한다. 기존 여행만 가맹점 지역명, 카드 이용일과 기간의 거리, Google 수입과 비용 차액으로 정렬한다. 카드 이용일을 예약 이용일로 저장하지 않는다.
- 검증된 예약 이용기간 후보가 있으면 그 기간 경로를 우선한다. 토요코인 중앙 예약 후보를 여행 추론에 연결하되 결제 연결과 예약번호는 확정하지 않는다. 숙박은 체크아웃 전날까지의 밤으로 비교한다.
- 사용자 결정, 기존 기장, 중복, 보류, 원본 오류, 취소 원결제, frozen 그룹, 카드 3820의 기존 분기 정책을 제외한다. 현재 항목·설명 규칙을 여행 추론으로 되돌리지 않는다.
- `webapp/tests/test_priority_trip_assignment.py`: 분류→미리보기→합성 내부 기록 및 요청 재시도의 단일 기록, 원본 보존, 예약번호 공란, 후보·보호 조건을 검사한다.
- 인접 분류·기록·기존 여행 보완·중앙 스냅샷 검사: 11 passed, 70 deselected. 전체 회귀는 실행하지 않았다.

<a id="src-docs-expense-cleanup-task-index-md--운영-조사와-적용-구분"></a>
#### 운영 조사와 적용 구분

2026-10-24 읽기 전용 집계에서 미기록 카드 158건과 검증된 여행 60개를 확인했다. 새로운 우선배정 규칙의 초기 후보는 103건이었다. 이 수치는 OTA 고정·실제 기간과 현재 규칙의 최종 제외 전 후보 수이며 처리 완료 수가 아니다. 운영 카드·장부·Google 쓰기와 서비스 재시작은 하지 않았다. 새 코드의 운영 배포와 실제 재분류는 미실행이다.

별도 승인된 L0~L1 동등성 리팩터링은 최신 원격 main을 기준으로 수행한다. 이 동작 변경과 리팩터링 PR을 섞지 않는다.

---

<a id="src-docs-handoff-session-20261020-booking-evidence-md"></a>

## session-20261020-booking-evidence

통합 전 경로: `docs/handoff/session-20261020-booking-evidence.md`

<a id="src-docs-handoff-session-20261020-booking-evidence-md--2026-10-20-채팅-세션-인계"></a>
### 2026-10-20 채팅 세션 인계

<a id="src-docs-handoff-session-20261020-booking-evidence-md--최신-사용자-요청과-작업-범위"></a>
#### 최신 사용자 요청과 작업 범위

사용자의 최신 요청은 “이 채팅 세션 내용 handoff 후 push”다. 이 문서와 인계 진입점을 커밋하고 origin/main에 push한다. 새 기능 개발이나 운영 데이터 변경을 시작하지 않는다.

직전 요청은 “예약근거를 카드자료에서 확인해달란게 무슨말이야”, 이어서 “계속”이었다. 카드 자료만으로 예약 이용기간을 확인하라는 부정확한 화면 안내의 조건을 조사하고 문구를 수정·배포했다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--대화-배경"></a>
#### 대화 배경

이 채팅에는 이전 Paseo 세션 `5763e9b1-2852-43b5-b00d-4f36920449e8`의 인수 요청과 다음 요구가 포함돼 있다.

- 자동 기록과 일반 장부 기록의 보호 조건을 맞추고 보류 자동 해제를 막는다.
- 지출 정리의 300건 제한과 누락을 점검하고 정확한 집계·페이지 조회를 적용한다.
- 실제 장부 기록 여부는 상태 문자열만으로 판단하지 않는다.
- 장부 반영 대기·기록 가능·ready 표시를 제거하고 상세 검토에서 여행을 바로 수정한다.
- 선택할 수 없는 결제 표시, 수동 여행 수정 거래의 검토 분류, 초기 로딩과 홈 이동 지연을 조사한다.
- 과거 화면의 483건 검토 대상과 이후 263건 화면을 조사하고 자연어 규칙 제안 형태로 화면을 개선한다.

이전 구현·배포의 근거는 `docs/operations.md`와 `docs/session_handoff.md`에 있다. 위 목록은 대화 배경이며 미완료 개발 목록이 아니다. 이 세션에서 과거 전체 요구를 다시 검증하거나 483건을 새로 전수 조사하지 않았다. 483건과 263건은 다른 시점의 화면 수치이며 차이만으로 처리 성과를 주장하지 않는다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--인수-시-확인한-상태"></a>
#### 인수 시 확인한 상태

- 작업 경로는 `C:/AX/cost`, 브랜치는 main이었다. 시작 시 작업 트리는 깨끗했다.
- 인수한 HEAD는 `dcc4285`, 운영 코드 릴리스는 `d90bef2e8370c4bca065328dc0df64df7a24616e`였다.
- 이전 아고다 자연어 제안은 비용 항목 변경 제안이며 실제 적용에는 별도 승인이 필요하다. 예약 이용기간을 해석하는 새 자연어 여행 배정 엔진을 구현한 상태로 해석하지 않는다. 기존 OTA 이용기간 배정 규칙과도 구분한다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--이번-세션에서-확인한-원인과-수정"></a>
#### 이번 세션에서 확인한 원인과 수정

`webapp/card_flow.py`의 `render_expense_cleanup()`은 `_ota_entries_by_card()` 결과에서 해당 거래를 찾지 못하고 OTA 가맹점 또는 `booking_evidence_needed` 분류이면 “예약 근거를 카드 자료에서 확인해 주세요.”를 표시했다.

이 조건은 현재 검토 목록에 연결된 예약이 없다는 뜻이다. 예약 메일 전체 조사가 완료됐다거나 예약 자체가 없다는 근거가 아니다. 카드 결제일은 체크인·체크아웃 날짜를 증명하지 않는다.

다음 문구로 수정했다.

> 이 결제와 연결된 예약 자료가 현재 검토 목록에 없습니다. 예약 확인서에서 예약번호와 이용기간을 확인해 주세요. 카드 결제일만으로는 여행을 정할 수 없습니다.

예약 연결·여행 배정·분류·장부 쓰기 로직은 바꾸지 않았다. 운영 거래 승인·여행 저장·장부 기록 요청을 수행하지 않았다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--변경-파일과-커밋"></a>
#### 변경 파일과 커밋

- `webapp/card_flow.py`: 예약 자료 미연결 안내를 수정했다.
- `webapp/tests/test_expense_cleanup.py`: 격리 DB의 아고다 거래에 대한 표적 테스트 하나를 추가했다.
- `docs/operations.md`, `docs/session_handoff.md`: 운영 결과와 미검증 사항을 기록했다.
- 코드 커밋과 운영 릴리스는 `f5e27d3a06ad010656dd43f8d01af2ccc42cb5b5`다.
- 직전 문서 커밋은 `3da454b`다. 두 커밋 모두 origin/main에 push했다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--실제-검증-근거"></a>
#### 실제 검증 근거

실행한 표적 테스트는 다음 하나다.

```powershell
python -m pytest webapp/tests/test_expense_cleanup.py::test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence -q
```

수정 전 안내 검증에서 실패했고, 코드 수정 후 `1 passed in 1.07s`였다. 합성 격리 DB에서 새 안내와 이전 문구 제거를 검증하고 조회 전후 transactions의 해당 행 전체 필드가 같은지 확인했다. `git diff --check`와 배포 릴리스 파일의 Git 객체 일치 검사를 통과했다. 문구만 바꿨으므로 전체 pytest·전체 브라우저 검사·전체 OTA 재대사는 실행하지 않았다. 이번 인계 문서 변경에도 코드 검사·배포를 반복하지 않는다.

기존 `D:/WebLedgerHost/bin/deploy_cost_v2_owner_ui.ps1`로 백업·복원 검증 후 배포해 `OWNER_UI_DEPLOYMENT_PASS`를 확인했다. 이전 운영 릴리스는 `d90bef2e8370c4bca065328dc0df64df7a24616e`다.

백업 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261020T154914/restore-evidence.json`이다. DB 4개·파일 55개, 운영 원본 불변과 복원된 검토 연결 일치를 확인했다. 실제 요청 재실행이나 실제 가져오기는 하지 않았다.

배포 절차에서 로컬 health/ready 각각 200과 Board·SourceRefresh Running을 확인했다. 후속 PowerShell 요청은 health 200·비로그인 import 401이었다. 마지막 작업 상태는 Board Running·SourceRefresh Ready였다. SourceRefresh의 Ready만으로 장애를 단정하지 않는다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--시도했으나-완료하지-못한-확인"></a>
#### 시도했으나 완료하지 못한 확인

Aside 지침을 읽고 기존 탭 목록을 확인한 뒤 운영 `/import`를 새 탭으로 열었다. 결과가 빈 페이지였고 후속 탭 목록에도 새 탭이 유지되지 않았다. 따라서 로그인된 실제 화면의 새 문구는 확인하지 못했다. 다른 브라우저나 인증 우회로 대체하지 않았다.

Python urllib의 로컬 import 요청은 기본 설정과 프록시 제외 설정 모두 시간 초과됐다. PowerShell의 동일 경로는 401로 응답하고 health도 200이었다. Python 요청 실패만으로 서버 장애나 화면 성능 문제라고 단정하지 않는다. 원인 미확인 상태에서 서버 재시작·재배포를 반복하지 않았다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--완료-상태와-다음-정확한-단계"></a>
#### 완료 상태와 다음 정확한 단계

- COMPLETE: 안내 조건 조사, 격리 재현, 최소 문구 수정, 표적 테스트, 코드 커밋·push, 백업·복원 검증과 운영 배포.
- PARTIAL: 로그인된 운영 화면에서 새 안내가 표시되는지 확인하는 작업.
- 이 문서 작성은 최신 사용자 요청의 인계 작업이다. 최종 push 결과와 작업 트리는 실행 결과로 확인한다.

다음 세션은 먼저 `git status -sb`와 `git log -3 --oneline`으로 사용자 변경과 HEAD를 확인한다. 브라우저 확인을 이어가라는 요청이 있으면 `aside guide repl`을 읽고 기존 탭을 조회한 뒤 정상 로그인된 운영 `/import`에서 아고다 거래의 상세 검토를 펼쳐 안내만 읽기 전용으로 확인한다. 승인·여행 수정·규칙 저장을 누르지 않는다. 이 확인을 위해 이미 통과한 테스트·백업·배포를 반복하지 않는다. 인증이 필요하면 해당 화면 확인만 남기고 미검증 사실을 알린다.

<a id="src-docs-handoff-session-20261020-booking-evidence-md--유지할-경계"></a>
#### 유지할 경계

`AGENTS.md`와 사용자 확정 업무 규칙을 따른다. 원본 금액·날짜·ID, 사용자 확정·보류·회사 경비 제외, 중복·취소·환불, OTA 연결 보호와 수정 이력을 유지한다. 운영 데이터 일괄 수정·상태 마이그레이션·새 상태 머신·대규모 리팩터링·과거 작업의 자동 재실행을 하지 않는다. 비밀정보나 고객 원문을 인계 문서와 Git에 넣지 않는다.

---

<a id="src-docs-ota-resolution-execution-md"></a>

## ota-resolution-execution

통합 전 경로: `docs/ota-resolution-execution.md`

<a id="src-docs-ota-resolution-execution-md--ota-미완결-연결-해결-실행"></a>
### OTA 미완결 연결 해결 실행

<a id="src-docs-ota-resolution-execution-md--2026-10-22-실행-결과와-남은-작업"></a>
#### 2026-10-22 실행 결과와 남은 작업

통합 OTA 증거 DB에 아고다 상세 캡처 672건이 추가돼 있다. 최신 자료에 대한 복제 장부 시험에서 확정한 24건, 7,188,006원을 2026-10-22 운영 DB에 실제 기장했다. 아고다 21건과 트립닷컴 3건이며, 장부 행 2,225→2,249건 및 전기 2,221→2,245건을 확인했다. 기존 행·사용자 결정·보류·카드 원본의 보존과 예약번호·금액·이용일·멱등성을 검증했다. 이전 절의 기장 예정 15건 또는 미해결 36건은 **과거 체크포인트**다. 실행 근거는 `docs/operations.md`와 Git 제외 로컬 보고서 `live-recording-20261022.json`이다.

아고다 기존 48개 미연결 조사 대상 중 21개가 기장됐고 27개는 남아 있다. 최신 재점검 기준으로 정확한 예약 근거가 없는 거래 13개, 복수 예약 후보가 있는 거래 14개다. 추가 수집 473개 및 실패 35개는 전용 Aside 인증 세션을 확인하지 못해 보류 중이다. 확보된 원본만으로 유일하게 대응하지 않는 결제는 연결하거나 기장하지 않는다. 트립닷컴·부킹닷컴의 추가 결제 차액과 환불은 카드 승인 또는 실제 환불 완료 근거가 필요하다. 공급자 이름 이상 행 7개의 증거 병합도 원본과 식별자 보존을 전제로 후속 검토한다.

<a id="src-docs-ota-resolution-execution-md--현재-재개-기준-수집부터-장부-기록까지"></a>
#### 현재 재개 기준: 수집부터 장부 기록까지

사용자가 전체 목표 미달을 지적했다. 앞선 완료는 개별 수정의 완료이며 전체 업무 완료가 아니다. 트립닷컴 두 건이 화면에서만 연결되고 분류·장부 행은 없음을 운영 읽기로 확인했다. 현재 큐는 다음과 같다.

1. ACTIVE: 코어의 검증된 연결과 예약 근거가 분류·미리보기·예약번호·이용일·장부 기록에 같은 의미로 이어지게 수정한다. 화면 보완만으로 완료 처리하지 않는다.
2. PENDING: 실제 운영 사본에서 해결된 미기장 OTA의 전체 목록과 보호·보류 사유를 집계하고, 승인된 안전한 기록 경로로 해결 가능한 거래를 반영한다. Google 자동 쓰기는 하지 않는다.
3. PENDING: 아고다 목록 1,550건 중 상세 370건 밖의 범위를 이용기간과 기존 카드 범위에 대조한다. 남은 36건을 외부 자료 부족으로 단정하기 전에 수집·해석·중복 관측 문제를 조사한다.
4. PENDING: 공급자별 수집·대사·배정·기장 수치를 분리해 최종 검증한다. 실제 필요한 외부 근거만 남긴다.

현재 승인 기준은 2026-10-21 사용자의 요청이다. 이미 제공한 자료로 해결을 시도하고 실제 필요한 정보만 구체적으로 설명한다. 단일 DB 이전은 완료한 선행 작업이며 다시 실행하지 않는다.

사용자는 같은 날 “규칙 자체를 해당 건에 맞게 수정”하도록 추가 지시했다. 고정 예약 번호의 예외가 아니라 아고다 전체 자료에서 정확 금액과 카드 끝자리가 일치하고 예약·카드가 서로 유일하며, 취소·환불·기간 충돌과 기존 결정·보류가 없는 경우에만 결제일 없는 추론 연결을 허용한다. 실제 결제일은 빈값으로 유지한다. 기존 결제일 필수 기본값은 다른 공급자와 조건 미달 거래에 그대로 적용한다.

목적은 보유 원문으로 해결 가능한 결함을 수정하고 현재 미해결 상태를 정확히 구분하는 것이다. 직접 영향 범위는 외화 금액 비교, 인증된 동일 예약 메일의 기간과 상태 근거 결합, 카드사 근거 및 자료 범위 진단이다. 카드 원문·ID·금액·사용자 결정·기록 날짜·원결제·환불 완료 조건은 유지한다.

표적 검사는 올바른 숫자 형식의 외화 연결, 잘못된 숫자 거부, 동일 예약의 기간 보완과 충돌, 취소·환불 요청·변경 금액 구분을 확인한다. 실제 원문은 로컬 보존하고 합성 자료로 검사한다. 운영 반영 전 복구·복원과 영향받는 기존 연결을 한 번 비교한다. Google 최종 장부 자동 쓰기는 하지 않는다.

현재 작업 큐는 다음과 같다.

1. 기존 장부·사용자 결정·정확 연결을 포함해 실제 미완결 상태를 다시 집계한다.
2. 외화 숫자 형식 결함을 수정하고 표적 검사한다.
3. 보유 메일의 예약별 기간·취소·변경·카드사 근거를 안전하게 결합한다.
4. 카드 원행이 없다면 보관 파일부터 조사하고, 필요한 경우 승인된 조회 경로로 수집을 시도한다.
5. 분리한 릴리스에 수정만 반영하고 실제 사례를 확인한다. 남는 외부 자료·인증 필요 사항을 구체적으로 기록한다.

종료 조건은 안전하게 가능한 수정·검증·운영 반영을 마치고, 남은 항목의 실제 원인과 필요한 자료 또는 사용자 인증 단계를 특정하는 것이다. 직접 수집 자료에 날짜가 없다는 사유를 전체 예약의 미해결 사유로 사용하지 않는다.

<a id="src-docs-ota-resolution-execution-md--실행-결과와-남은-근거"></a>
#### 실행 결과와 남은 근거

| 항목 | 상태 | 실제 결과 |
| --- | --- | --- |
| 실제 미완결 재집계 | COMPLETE | 과거 213건 중 이미 장부 163건을 분리했다. 자동 연결 대상 48건 중 12건 연결, 36건 보류다. |
| 외화 숫자 비교 | COMPLETE | 정확 숫자 형식만 정규화하며 부킹닷컴 실제 쌍이 통과한다. 기존 비용은 재기장하지 않는다. |
| 메일 예약 맥락 | COMPLETE | 기간·충돌·취소·환불 요청·변경 총액과 실제 결제수단의 카드사를 구분한다. 금융 원문·ID·금액·날짜는 유지한다. |
| 하나 원본 반영 | COMPLETE | 보관 원본에서 358행을 추가했다. 기존 77개 테이블 행 보존과 반복 가져오기 추가 0행을 확인했다. |
| 아고다 승인 규칙 | COMPLETE | 고정 번호 예외 없이 전역 일대일 조건을 적용했다. 12건은 추론 표시하며 결제일을 만들지 않았다. |
| 캐시 비용 | COMPLETE | 기존 사용자 규칙에 따라 22,500원 1건을 검증된 여행에 기장했다. 동일 요청 중복을 방지하고 기존 비용을 보존했다. |
| 코어와 예약 화면의 누락 | COMPLETE | 코어 연결을 화면에서 보완하고 반복 순서 근거를 표시한다. 기존 화면 연결 313개 보존, 추가 38개다. 실제 Trip 화면 확인과 표적 검사 통과다. |
| 분리 운영 반영 | COMPLETE | 릴리스 d26a160, 관리 배포 PASS, health/ready 200, DB 5개·파일 56개 복원 검사 통과다. 보호 테이블의 모든 행은 새 자료·캐시 반영 뒤 기준선과 같다. |
| 아고다 잔여 36건 | PARTIAL | 22건은 보유 검증 근거에서 정확 금액·카드 대응이 없고 14건은 같은 조건의 후보가 여러 개다. 해당 카드 거래를 어느 예약에 썼는지 증명하는 결제 확인서·개별 결제 식별 근거가 필요하다. |
| 트립닷컴 취소·변경 차액 | PARTIAL | 취소·환불 요청·변경 총액은 반영했다. 추가 차액의 카드별 근거와 환불 입금 완료 자료는 확인되지 않아 개별 연결·완료 환불 생성을 보류했다. 사용자 분리 결정은 유지한다. |

정확한 상태·배포·검사 근거는 [현재 운영 첫 항목](../operations.md)을 따른다. 앞선 종료 판단은 개별 수정에 한정되며 전체 목표의 종료 근거로 사용하지 않는다. 추가 근거를 받으면 `.local-archive/ota-resolution-20261021/remaining-agoda-open.json`과 해당 거래 원문을 먼저 대조하고, 해당 예약만 기존 공통 대사로 확인한다. 새 운영 자료를 넣기 전 복구·복원 검증과 원본 보존 게이트를 적용한다. 이번 코드의 변경이 없는 전체 pytest·전체 OTA 수집·전체 브라우저 검사는 의도적으로 생략했다.

---

<a id="src-docs-participant-income-task-index-md"></a>

## participant-income-task-index

통합 전 경로: `docs/participant-income-task-index.md`

<a id="src-docs-participant-income-task-index-md--참가자수입-대조-작업-인덱스"></a>
### 참가자·수입 대조 작업 인덱스

> 작업 단위: 보험가입 명단 기반 참가자 확정과 수입 대조
> 갱신일: 2026-10-20 KST
> 현재 명세: [버전 1.0](../specs/participants.md#src-docs-participant-income-reconciliation-spec-md)

이 인덱스는 이 기능의 현재 요청과 실행 범위만 관리한다. 다른 독립 작업의 승인·진행 상태를 변경하지 않는다. 과거 ACTIVE 문서를 구현 지시로 읽지 않는다.

| 작업 ID | 요구사항 | 상태 | 근거 또는 다음 단계 |
| --- | --- | --- | --- |
| SPEC | 계획 및 명세 작성 | COMPLETE | 사용자 요구, 기존 Google 수입 경계, 전달·대조·예외·화면·검증 계획을 명세에 기록했다. |
| P0 | 구조화 명단 수신·참가자 저장 | COMPLETE | `app/participant_roster.py`, `tools/ingest_participant_roster.py`, 커밋 `945c218`. 표적 테스트 `tests/card_pipeline/test_participant_roster.py` 통과. |
| P1 | 금액 없는 Google 이름 행 조회 | COMPLETE | `app/google_authority.py` 이름 인덱스, 커밋 `650b730`. 검토 보강 후 `tests/card_pipeline/test_google_authority.py` 59건 통과. |
| P2 | 수입 대조·연결·수동 결정 | COMPLETE | `app/participant_income.py`, 커밋 `b2366f2`. 검토 보강과 마지막 이력 경계 검사 결과는 아래 최신 기록을 따른다. |
| P3 | 관리자 참가자 대조 화면 | COMPLETE | `webapp/participant_income_page.py`, 커밋 `a14a414`. 검토 보강 후 화면·권한·합성 브라우저 흐름 27건 통과. |
| P4 | 합성 통합 확인 | COMPLETE | `tests/card_pipeline/test_participant_integration.py`, 커밋 `b94204c`. 수신→표시→수동연결→재수신→Google 변경 한 번 확인. |
| TI-COST-ADAPTER | Travel INS 최종 명단 로컬 변환과 COST 참가자·수입 대조 연결 | COMPLETE | Travel INS `tools/build_cost_roster.py`와 기존 `tools/send_cost_roster.py`를 통해 COST 수신 저장소 및 `app/participant_income.py`에 합성 사진·명단·Google 수입 행을 연결했습니다. Travel INS 표적 검사 6건 통과. 운영 자료·Google 쓰기·배포는 수행하지 않았습니다. |

구현은 승인된 범위 안에서 끝까지 수행했고 운영 배포·실제 명단 등록은 하지 않았다. Google 쓰기·수입 자동 기장·미납·완납 추정은 구현하지 않았다. 2026-10-20 검토로 지적된 명세 누락과 결함도 반영해 표적 검사로 닫았다.

2026-10-20 후속 요청으로 P0~P4의 실제 구현을 승인받았다. 표의 상태는 작업자가 착수·검증 근거에 맞춰 갱신했다. SPEC은 완료된 설계 근거로 유지한다. 운영 배포와 실제 고객 명단 등록은 이번 요청에 포함되지 않는다.

구현은 기존 COST 작업 공간에서 진행하며 같은 파일을 동시에 수정하지 않는다. 전달 자료는 코드·명세·합성 자료로 제한하며 기존 미커밋 아고다 변경은 수정·stage하지 않는다. 설계·구현 방법은 현재 승인 범위 안에서 결정하고 다시 승인을 요청하지 않는다.

<a id="src-docs-participant-income-task-index-md--구현-실행-결과-2026-10-20"></a>
##### 구현 실행 결과 (2026-10-20)

작업 공간 `C:/AX/cost`, 착수 HEAD `a1efbda`에서 구현했다.

커밋(모두 `main`, 다른 작업의 아고다 변경 미포함):

| 커밋 | 내용 |
| --- | --- |
| `945c218` | P0 참가자 명단 수신·저장 (`app/participant_roster.py`, `tools/ingest_participant_roster.py`) |
| `650b730` | P1 Google 수입 이름 인덱스 (`app/google_authority.py`, `webapp/google_ledger_page.py`) |
| `b2366f2` | P2 대조·수동 결정 (`app/participant_income.py`) |
| `a14a414` | P3 관리자 전용 화면·API (`webapp/participant_income_page.py`, `webapp/ledger_board.py`, `webapp/access_control.py`) |
| `b94204c` | P4 합성 통합 확인 (`tests/card_pipeline/test_participant_integration.py`) |

구현한 경계:

- P0: `manifest.json`·`participants.json` 필드·타입·해시·페이지·경로 검증, 개인정보 필드 거부, 여행 연결 확인(`TRIP_MAPPING_REQUIRED` 보류), 참가 확정 저장, 부분 명단·판독 대기, 재수신 멱등성, 같은 배치 id 충돌(`SOURCE_ID_CONFLICT`), 이름 변경 정정 제안, 같은 사람의 항목 재사용, 명단 트랜잭션과 동시 등록.
- P1: 이름·닉네임이 있는 수입 행을 금액 집계와 분리된 비공개 이름 인덱스로 저장. 금액 행·합계·오류 플래그 계약은 그대로이고, 이름 인덱스가 없는 세대·비표준 탭·오래된 동기화는 누락 판정을 보류한다.
- P2: 유일한 이름 일치만 자동 연결하고 동명이인·복수입금은 `연결 확인 필요`로 남긴다. 수동 연결·해제·공동입금·정정·별칭·같은 사람 확인을 저장하고, 원문 지문이 바뀌면 그 연결만 `연결 확인 필요`로 되돌린다. 사용자가 해제한 행은 이름이 맞아도 다시 연결하지 않는다. 입금 행은 고유 원본 행을 한 번만 센다.
- P3: `/participants`, `/api/participants/state`, `/api/participants/link`, `/api/participants/unlink`, `/api/participants/participant`. 소유자 세션만 처리하고, 일반 열람자는 403, 익명 요청은 401로 거절한다. 기존 장부 화면·기존 API·XLSX에는 실명·참가 표시·원본 경로가 들어가지 않는다. 오래된 화면의 결정은 409 `STALE_RECONCILIATION`으로 거절한다.

실제로 실행한 검증(모두 변경 기능과 직접 인접 계약에 한정):

| 명령 | 결과 |
| --- | --- |
| `python -m pytest tests/card_pipeline/test_participant_roster.py -q` | 23 passed |
| `python -m pytest tests/card_pipeline/test_participant_income.py -q` | 19 passed |
| `python -m pytest tests/card_pipeline/test_participant_integration.py -q` | 1 passed |
| `python -m pytest tests/card_pipeline/test_google_authority.py -q -k participant` | 6 passed, 52 deselected |
| `python -m pytest tests/card_pipeline/test_google_authority.py -q` | 58 passed |
| `python -m pytest webapp/tests/test_participant_income.py -q` | 8 passed |
| `python -m pytest webapp/tests/test_access_control_phase7.py -q` | 47 passed |

기존 실패(변경과 무관): `webapp/tests/test_google_ledger_page.py` 23건, `webapp/tests/test_google_canonical_workflow.py` 5건, `webapp/tests/test_google_viewer_http.py` 6건은 기준 커밋 `945c218`을 별도 worktree로 체크아웃해 그대로 실패함을 확인했다. Google 장부 화면 경로가 이미 제거된 뒤 남은 테스트이며 이번 변경과 무관해 고치지 않았다.

의도적 생략과 이유:

- 전체 pytest·전체 브라우저 E2E·OTA 전수 대사·전체 회귀는 실행하지 않았다. 카드·OTA 연결과 회계 쓰기를 건드리지 않고, 위 표적 검사와 인접 통합 검사만으로 변경 범위를 확인했다.
- 운영 배포·운영 스키마 변경·운영 DB 확인·브라우저 E2E는 하지 않았다. 승인 범위가 구현까지이고 운영 적용은 별도 승인 단계다.
- 실명 명단 등록·실제 여행 연결·Google 쓰기는 하지 않았다. 실제 자료와 여행 참조가 필요하고 원본을 건드리지 않는 것이 이번 범위다.

실제 차단:

- 없음. 표적 테스트가 정상 실행됐다.

<a id="src-docs-participant-income-task-index-md--검토-반영-2026-10-20"></a>
##### 검토 반영 (2026-10-20)

초기 구현 검토에서 지적된 결함을 반영했다. 기능 확장이 아니라 원래 명세의 누락과 결함을 고친 것이고, 지적 항목은 모두 코드와 표적 검사로 닫았다.

| 지적 | 반영 |
| --- | --- |
| 같은 배치 재전달이 최초 결과와 개수를 바꾸고 이력을 다시 썼다 | 같은 지문의 재전달은 최초 결과·등록시각·개수를 그대로 돌려주고 항목과 감사 이력을 다시 쓰지 않는다(`945c218` 이후 보강). 보류→연결 전이만 따로 허용한다. |
| `PARSER_VERSION`이 두 번 정의돼 이름 인덱스를 만들지 못했다 | 정의를 하나로 정리해 실제 세대가 `quarter-expense-v2`다. 구버전 스냅샷도 같은 workbook 해시여도 다시 읽어 이름 인덱스를 만든다. |
| 수동 해제 결정을 전달해도 이름이 다시 연결됐다 | 명시적으로 해제한 쌍은 자동 연결하지 않고 기존 결정을 보존한다. |
| 쓰기에 지문·여행·ref 검증과 원자성이 없었다 | 모든 쓰기가 지문을 필수로 받고, 참가자의 현재 여행 소속·현재 정본에 있는 수입 행·실제 여행 대상을 확인한 뒤 한 트랜잭션으로 결정과 이력을 함께 남긴다. 지문은 수동 결정 revision을 포함한다. |
| 정본 선택을 수동 기록에만 의존했다 | 기존 `owner_payload` 정본 선택 계약을 재사용해 한 사본뿐인 여행도 연결된다. 원본 수입 행과 이름 인덱스를 고유 행 기준으로 합쳐 이름이 공란인 금액 행도 잃지 않는다. |
| 화면에서 임의 수입 행 연결·정정·별칭·동일인 확인이 없었다 | 참가자별 폼으로 임의 행 연결(대리·공동입금), 이름 정정, 여행 연결 수정, 별칭 확인, 같은 사람 확인, 서로 다른 사람 확인을 제공한다. 근거는 내부 상태 문자열 대신 설명으로 보여 준다. |
| 참가 확정 인원이 이름 연결 상태에 따라 줄었다 | 명단으로 확정된 활성 참가자 전체를 참가 인원으로 세고 대조 확인 대상은 따로 센다. 미연결 수입의 명시적 검토 결정을 저장·표시한다. |
| 문서를 완료로 표시했다 | 아래 검토 반영 뒤에만 완료로 갱신한다. |

이 반영으로 추가·보강한 커밋: `8f20e84`(재전달·파서 세대·지문·참가 확정 분리), `3a67c41`(쓰기 안전·여행 연결 수정·0원 표기·동명이인), `65af90c`(표적 검사), `6bf27f3`(여행 상세 수입 영역의 관리자 링크), `e47a6f6`(대조 실행 기록), `3512731`(대조 이력에 완료 여부 보존).

마지막 이력 저장 결함: 결정 뒤의 실제 대조 상태를 다시 계산해 이력으로 남기고, 명단 범위가
아니라 실제 명단 버전과 Google 세대를 기록한다. 이력 요약에는 인원 집계와 함께 완료 여부와
보류 이유를 보존하고, 같은 입력 재기록은 기존 완료 이력을 덮지 않는다. 변경 이력 경계의
검사 1개와 인접 검사 1개만 새로 실행했다: `python -m pytest
tests/card_pipeline/test_participant_income.py -q -k run_history` → 1 passed, `python -m pytest
webapp/tests/test_participant_income.py -q` → 27 passed. 나머지 통과 근거는 이전 결과를
재사용했다.

실제로 실행한 검증(변경 기능과 직접 인접 계약에 한정):

| 명령 | 결과 |
| --- | --- |
| `python -m pytest tests/card_pipeline/test_participant_roster.py -q` | 23 passed |
| `python -m pytest tests/card_pipeline/test_participant_income.py -q` | 25 passed |
| `python -m pytest tests/card_pipeline/test_participant_integration.py -q` | 1 passed |
| `python -m pytest tests/card_pipeline/test_google_authority.py -q` | 59 passed |
| `python -m pytest webapp/tests/test_participant_income.py -q` | 27 passed (합성 브라우저 흐름 1건 포함) |
| `python -m pytest webapp/tests/test_trip_google_income.py -q` | 16 passed |
| `python -m pytest webapp/tests/test_access_control_phase7.py -q` | 47 passed |

합성 브라우저 흐름은 소유자 세션으로 참가 대조 화면을 열어 이름만 있는 수입 행을 골라 연결하고, 결과가 `수동 연결`로 남는 것까지 한 번 확인했다. 전체 브라우저·전체 회귀는 반복하지 않았다.

재개점: 실명 명단을 등록하려면 `.local-archive/participant-rosters/<batch_id>/`에 `manifest.json`·`participants.json`·`sources/`를 놓고 `tools/ingest_participant_roster.py --batch-dir <경로> --db .local-archive/participant-rosters/participant.sqlite --mapping <google-tab-mapping.json>`을 실행한다. 여행 연결이 모호하면 `TRIP_MAPPING_REQUIRED`로 보류되고 참가 확정은 저장되지 않는다. 그다음 소유자 계정으로 `/participants?trip=<탭 id>`에서 대조를 확인한다.

<a id="src-docs-participant-income-task-index-md--변경-파일과-보호-범위"></a>
#### 변경 파일과 보호 범위

이 문서 작업의 파일은 이 인덱스, [상세 명세](../specs/participants.md#src-docs-participant-income-reconciliation-spec-md), [README](../../README.md), [상위 목표 명세](../specs/google-ledger.md#src-docs-target-workflow-google-authority-md)다. 원본 명단과 실명은 포함하지 않는다.

작업 시작 시 `main`의 HEAD는 `8aaf09c`였다. 기존 변경 `app/ota_portal.py`, `docs/session_handoff.md`와 미추적 `app/agoda_capture.py`, `docs/trip-booking-mail-investigation.md`, `tests/card_pipeline/test_agoda_capture.py`, `tools/ingest_agoda_aside.py`는 별도 작업으로 보존한다. 기존 변경은 이번 커밋에 포함하지 않는다.

문서 검증은 변경 diff, 상대 링크, 상태 선언과 개인정보 없는 합성 예시를 확인한다. 문서만 바꾸므로 코드 테스트·빌드·브라우저·운영 DB 조회·백업·배포·재시작은 수행하지 않는다. 실제 검사와 커밋 결과는 완료 보고와 Git 이력으로 확인한다.

후속 구현(P0~P4)에서 만든 파일은 `app/participant_roster.py`, `app/participant_income.py`, `webapp/participant_income_page.py`, `tools/ingest_participant_roster.py`, `tests/card_pipeline/test_participant_roster.py`, `tests/card_pipeline/test_participant_income.py`, `tests/card_pipeline/test_participant_integration.py`, `webapp/tests/test_participant_income.py`이고, 수정한 파일은 `app/google_authority.py`, `webapp/google_ledger_page.py`, `webapp/ledger_board.py`, `webapp/access_control.py`, `tests/card_pipeline/test_google_authority.py`, `README.md`, 이 문서와 상세 명세다. 위의 아고다 변경 파일은 이번 구현에서도 수정·stage하지 않았다.

<a id="src-docs-participant-income-task-index-md--세션-인수-기록"></a>
#### 세션 인수 기록

2026-10-20 Paseo 세션 `7356c450-1d14-43e9-bf90-b0c8d636faa1`의 사용자 요청과 활동 기록을 인수했다. 원래 요청은 계획·명세 작성이며, 이전 세션은 사용량 한도로 중단됐다. 남아 있던 문서 초안을 검토해 이 범위만 완료한다. 원본 첨부 사진은 이번 인수 과정에서 열람하지 않았고, 실제 명단 전사나 여행 연결을 완료했다고 주장하지 않는다.

코드 근거로 `app/google_authority.py`의 `_sum_block`이 유효한 정수 금액 행만 상세 자료에 넣는 동작과 `webapp/google_ledger_page.py`의 `owner_rows`가 그 자료를 사용하는 경로를 확인했다. `.local-archive`의 Git 제외 설정과 P1에서 사용할 기존 테스트 파일의 존재도 확인했다. 문서 검사는 이번 작업의 네 문서에 있는 상대 링크와 상태 선언, diff 형식으로 한정한다.

검증 결과: 문서 4개의 로컬 상대 링크 37개가 존재하며, SPEC은 COMPLETE이고 P0~P4는 PLANNED인 상태가 일치했다. 추적 문서의 `git diff --check`도 통과했다. 코드 테스트·빌드·운영 조회·배포는 문서 변경에 필요하지 않아 생략했다. 원래 요청에 남은 문서 작업은 없으며 구현 단계는 후속 요청 전까지 실행하지 않는다.

<a id="src-docs-participant-income-task-index-md--다음-정확한-시작점"></a>
#### 다음 정확한 시작점

구현(P0~P4)은 완료했다. 다음 단계는 승인 뒤에만 진행한다.

```powershell
Get-Content -Encoding UTF8 docs/participant-income-task-index.md
Get-Content -Encoding UTF8 docs/participant-income-reconciliation-spec.md
git status --short
```

실제 첨부 명단 등록에는 기존 Google 여행 참조와 전사 자료가 필요하다. 여행 참조가 없으면 해당 등록만 대기하고, 이미 만든 합성 구현 경로와는 분리한다. 운영 적용(배포·운영 스키마·운영 DB)을 시작하기 전에 복구 사본과 복원 확인을 먼저 수행한다.

---

<a id="src-docs-session-takeover-20261012-md"></a>

## session-takeover-20261012

통합 전 경로: `docs/session-takeover-20261012.md`

<a id="src-docs-session-takeover-20261012-md--cost-세션-인수-기록"></a>
### COST 세션 인수 기록

> **2026-10-12 과거 세션 검증/배포 이력**. 당시 `integration/cost-final` 언급과 세션 인수 TODO는 현재 V3 구현 지시가 아니다. 후속 개발은 [단일 진입점](../COST_V3_START_HERE.md) 및 [최신 인계](../session_handoff.md)로 이동한다.


인수 대상은 `f49a35a1-aabd-4917-bc3c-1b6906211ffe`다. 사용량 한도로 중단됐고 실행 중인 턴은 없었다. 전체 대화의 사용자 지시, 최근 활동, 미커밋 테스트와 현재 운영 release를 확인했다.

| 요구 | 상태 | 실제 결과 |
| --- | --- | --- |
| 기존 세션 인수 | COMPLETE | 같은 integration 브랜치의 미완료 테스트를 이어 구현했다. |
| 카드 검토 개선 | COMPLETE | 자료 선택 접기, 상태별 건수, 검색·월·항목 필터, 날짜·금액 정렬, OTA·분류 아이콘과 조건 유지·거래 수정 경로를 구현했다. |
| 수입 중복 표시 정리 | COMPLETE | 빈 COST 수입·차액을 숨기고 Google 수입과 실제 COST 수입 행은 유지했다. |
| Google 원본 직접 링크 | COMPLETE | 선택된 메인·보관 파일과 실제 시트명을 사용한다. 실제 계정의 새 탭 이동은 미검증이다. |
| 운영 반영 | COMPLETE | 백업·복원 후 `adaa50ba27af532a7522ba9e47f6a0b89fdcbca6` 배포, 공개 health/ready 200, 비로그인 import 401, 서버·수집기 Running이다. |

구현 `873797fa0140cf59879a174e9d2829655b440f24`, 운영 `adaa50ba27af532a7522ba9e47f6a0b89fdcbca6`, 통합 `f778c5b`를 PR #85에 push했다. 기존 운영 위에 이번 표시 변경만 적용했고 main과 사용자 checkout의 dirty·미추적 파일은 유지했다.

기존 기록 API는 전체 묶음을 처리하므로 필터 조회 중에는 기록 버튼을 잠갔다. 합성 검사에서 거래 ID·원본 해시·금액·날짜·가맹점 보존과 장부 미기록을 확인했다. 운영 원본 전수 비교를 수행했다는 의미는 아니다.

검사는 카드 검토 초기 1 passed / 2 subtests, Google·장부·카드 인접 묶음 24 passed / 4 subtests와 기대값 오류 2건, 오류 수정 후 해당 2 passed / 2 subtests, 최종 변경 5 passed / 2 subtests다. 결과를 합산하지 않는다. 전체 회귀·전체 OTA 대사·운영 시험 기록·실제 고객 메시지 발송은 표시 변경에 필요하지 않아 생략했다. 실제 운영 로그인 화면과 실제 Google 링크 이동은 미검증이다.

백업·복원과 전환 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T220642/restore-evidence.json`과 `deployment.json`이다. 후보·스모크·인수 사본은 `C:/AX/cost/.local-archive/card-review-takeover-20261012/`에 있다. 추가 비용·Google 쓰기·스키마 변경은 없다.

별도 예약 알림톡 수정은 reservation PR #18 `0a66d6e`, OPEN·운영 미반영 상태로 유지한다. 기존 검사 11개·타입 검사 근거를 반복하지 않았다. 이전 PDF 입력·자동 영수증 분리·실제 ADC·viewer 검증·Render 이전의 미완료 기록을 이번 카드 화면 요청의 완료로 바꾸지 않는다.

다음 상태 확인은 `git -C C:/AX/cost status --short`와 WebLedger-Board 예약 작업의 release 경로 조회로 시작한다. 후속 코드 작업은 PR #85의 `integration/cost-final` 최신 HEAD에서 수행한다. 관련 변경이 없으면 이번 통과 검사를 반복하지 않는다.

---

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md"></a>

## 2026-10-24-toyoko-reservation-links

통합 전 경로: `docs/superpowers/plans/2026-10-24-toyoko-reservation-links.md`

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md--토요코인-예약-추론-연결-구현-계획"></a>
### 토요코인 예약 추론 연결 구현 계획

> 사용자 승인: 예약 연결과 결제 검증을 분리하자는 네 단계 제안에 대한 2026-10-24의 `ㄱㄱ`. 추가 설계 승인을 요구하지 않는다.

**Goal:** 토요코인 예약을 카드 거래와 근거에 따라 연결하고, 결제 검증과 구분하여 보여 준다.

**Architecture:** 중앙 OTA 대사의 예약 연결 결과를 카드 및 OTA 화면이 공유한다. 자동 연결은 계산 결과로만 만들고, 사용자 확인은 별도의 예약 관계로 보존한다. 기존 결제 확정 links에 예약을 결제 완료로 위장해 넣지 않는다. 기존 카드 readiness, 여행 수동 이동, Google 복사 보호를 재사용한다.

**Tech Stack:** Python, SQLite, 기존 HTML 및 JavaScript, pytest.

**Spec:** 이 문서의 승인 범위와 docs/COST_V3_START_HERE.md의 서로 다른 상태 축 및 A 정책.

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md--승인-범위와-완료-조건"></a>
#### 승인 범위와 완료 조건

1. 지점, 숙박기간, 원문 통화와 금액이 일치하고 예약과 카드가 서로 유일하면 자동 추론 연결한다. 결제일 미상과 결제 검증 미완료를 그대로 보존한다. 금액이 원본에 없는 경우에는 지점과 기간이 확인되는 서로 유일한 관계만 낮은 신뢰의 추론 연결로 표시한다. 지점을 확인할 수 없거나 여러 예약이 경합하면 사용자 확인이 필요하다.
2. 객실별 예약과 합계 예약은 별개의 실제 결제로 취급하지 않는다. 묶음 합계만 맞는 경우 개별 예약을 확정하지 않는다. 서로 유일성 판단은 이미 기장하거나 점유된 카드 및 경합 근거를 임의로 제거해서 만들어서는 안 된다.
3. 원본의 외화금액 누락을 읽기 전용으로 조사한다. 실제 추출 오류이면 원본 보존과 identity를 유지하는 표적 수정으로 해결한다. 원문에도 금액이 없다면 환산액으로 외화 금액을 창작하지 않는다. 운영 원행을 재작성하거나 재수입하지 않는다.
4. 복수 후보 및 금액 차이는 화면에서 설명한다. 사용자 확인은 미리보기, 명시적 저장, stale 재검사, 중복 요청 멱등성, 기존 점유 보호를 갖춘다. 사용자 확인 관계를 이후 자동 대사가 바꾸지 않는다. 실제 결제 검증 미완료와 예약 관계의 사용자 확정을 분리한다.
5. 취소, 근거 충돌, 환불, 중복, 파싱 오류, 기존 수동 결제 links 및 frozen group을 보호한다. 예약 연결만으로 비용을 생성하거나 금액과 원문을 바꾸지 않는다. 추론 예약번호를 장부 또는 Google F열에 넣지 않는다. 기존 수동 여행 이동은 유지한다.
6. 표적 검사와 인접 통합 경계의 보호 검사를 한 번 수행한다. 변경 범위 전체 검토 후 commit, PR, 병합, 검증된 백업 및 복원 게이트, 승인된 운영 배포와 최소 스모크를 수행한다. 기존 배포 승인은 이번 후속 수정에도 유지한다. 고객 원문과 비밀정보는 커밋하지 않는다.

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md--review-focus"></a>
#### Review Focus

실행 판단: 지점 미상인 토요코인 카드도 제공자와 숙박기간이 맞으면 금액·지점 미확인을 표시한 사용자 확인 전용 후보로 보여 준다. 자동 연결은 지점과 숙박기간이 확인될 때만 가능하다. 후보 유일성은 기존 점유를 제외하기 전 전체 후보로 확인한다. 명시 금액 불일치는 사용자 확인 대상이며 자동 연결하지 않는다. 같은 요청의 멱등 재응답은 기존 저장 결과를 돌려주는 정상 동작이다. 최신 근거 변경 경고는 현재 중앙 스냅샷에서 표시한다.

- 동일 금액의 여러 객실과 그룹 합계가 동시에 존재할 때 자동 개별 연결이 생기지 않는다.
- 취소 또는 근거 변경 뒤 사용자 확인 관계를 삭제하거나 새 카드로 자동 이동하지 않는다. 현재 유효성과 보존 이력을 구분한다.
- 기존 결제 링크 및 그룹 점유와 예약 관계가 충돌하지 않는다.
- 금액 누락과 명시 금액 불일치를 서로 다른 사유로 보여 준다. 근거 부족을 정확 연결로 표시하지 않는다.
- 서버 재시작, stale 화면, 중복 요청, 동시 확인에서도 사용자 관계와 원본이 보존된다.

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md--t1-중앙-예약-관계와-사용자-확인"></a>
#### T1: 중앙 예약 관계와 사용자 확인

**Files:** app/toyoko_mail.py 및 필요 시 집중된 예약 관계 모듈, app/ota_payments.py, app/ota_review.py, webapp/ota_payment_review.py, app/ota_core_projection.py, app/ota_labels.py, webapp/ota_catalog.py 및 직접 소비하는 카드/OTA 화면. 기존 결제 solver를 광범위하게 재구성하지 않는다.

**Interfaces:** 중앙 결과에 예약 관계의 상태, 거래 ID, 추론 근거, 금액 확인 여부, 결제 검증 미완료를 명시한다. 기존 MATCHED_AUTO/MATCHED_USER가 결제 확정으로 소비되는 경로와 분리한다. 관계 저장은 기존 review DB에서 lazy 생성하고, 읽기 전용 경로는 DB를 생성하거나 스키마를 바꾸지 않는다. 새로운 저장 메서드는 stale 및 멱등성 계약을 명시한다.

- [x] 승인 계약의 실패하는 합성 표적 검사를 작성하고 실패를 확인한다.
- [x] 서로 유일한 추론 연결, 미확인 금액 표시, 경합과 묶음 설명을 구현한다.
- [x] 사용자 예약 관계 확인 저장 및 화면을 구현한다. 실제 결제 확인 API의 가드를 완화하지 않는다.
- [x] 카드 및 OTA 화면이 같은 중앙 상태를 표시하고 준비 및 복사 경로의 보호가 유지되는지 검사한다.
- [x] 관련 표적 검사와 git diff --check를 통과시키고 코드 커밋을 만든다. 불필요한 전체 회귀와 브라우저 테스트는 실행하지 않는다.

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md--t2-원문-누락-진단과-통합-검토"></a>
#### T2: 원문 누락 진단과 통합 검토

- [x] 운영 카드 원문의 금액 열 존재 여부만 로컬에서 읽기 전용 집계하고 원인을 기록한다.
- [x] 실제 diff와 합성 검사를 검토하여 구현 계약 및 데이터 보호를 확인한다.
- [x] 변경에 영향을 받는 저장 경계, 카드 readiness, 추론 예약번호 복사 제외를 확인한다. 이미 유효한 검사는 반복하지 않는다.

<a id="src-docs-superpowers-plans-2026-10-24-toyoko-reservation-links-md--t3-승인된-운영-반영"></a>
#### T3: 승인된 운영 반영

- [x] PR을 만들고 검토 결과를 반영하여 main에 병합한다. 사용자 root main의 미커밋 파일과 stash를 보존한다.
- [x] 실제 merge SHA의 release를 준비하고 원본, review DB, 기존 관계 및 사용자 결정의 복구 사본과 별도 복원을 검증한다.
- [x] 현재 release에서 새 release로 전환하며 Board 및 MailCollect 경로를 일관되게 바꾸고 실패 시 복구한다.
- [x] 최소 health/ready 및 변경된 예약 관계 경로의 합성/읽기 전용 운영 상태를 확인한다. 운영 자동 추론은 읽기 결과이며 사용자 확인을 대신 저장하지 않는다.
- [x] 실제 결과, 누락 근거, commit 및 배포 SHA, 표적 검사와 생략한 검사를 현행 인계와 작업 기록에 남긴다. 완료한 작업 공간은 미커밋·참조 보존을 확인한 뒤 별도 정리한다.

---

<a id="src-docs-superpowers-plans-2026-10-26-flight-manual-date-filter-md"></a>

## 2026-10-26-flight-manual-date-filter

통합 전 경로: `docs/superpowers/plans/2026-10-26-flight-manual-date-filter.md`

<a id="src-docs-superpowers-plans-2026-10-26-flight-manual-date-filter-md--항공권-상세의-명시적-날짜-필터"></a>
### 항공권 상세의 명시적 날짜 필터

근거: 항공권 예약 확인 명세의 예약일 미확인 처리와 FLIGHT-VERIFY-CARD-01.

- 목적: 예약일이 없는 경우에도 사용자가 직접 고른 날짜의 저장 카드 원행을 읽을 수 있게 한다. 지정 날짜를 예약일이나 연결 근거로 확정하지 않는다.
- 범위: card_transactions의 읽기 전용 일별 투영, 기존 owner 카드 API의 day 경로, 항공권 예약 상세의 선택적 날짜 조회. 원행·분류·중복·취소·환불을 필터로 숨기지 않는다.
- 페이징: 100건씩 모든 행에 접근한다. 조회 세대 지문이 바뀌면 더보기를 거부하고 재조회를 안내한다.
- 검증: 1,005건/동일 금액/취소·중복·오류 보존, 엄격한 날짜·커서, 원본 DB 무쓰기, owner/no-store 및 UI 날짜 명시·더보기·오류 경로만 표적 검사한다.
- 종료: 검토 후 정상 PR 병합, 기존 고정 릴리스 절차로 배포하고 해당 조회 경로만 최소 스모크한다. 권위 있는 예약일 자동 후보는 별도 원천 근거 없이는 생성하지 않는다.

---

<a id="src-docs-superpowers-plans-2026-10-26-manual-theme-toggle-md"></a>

## 2026-10-26-manual-theme-toggle

통합 전 경로: `docs/superpowers/plans/2026-10-26-manual-theme-toggle.md`

<a id="src-docs-superpowers-plans-2026-10-26-manual-theme-toggle-md--수동-테마-전환-구현-계획"></a>
### 수동 테마 전환 구현 계획

승인 기준: UI 통합 명세 §13, THEME-TOGGLE-01.

1. 공통 셸의 네이티브 장부와 독립 페이지에 동일한 아이콘 버튼을 한 개 주입한다. 별도 헤더 행으로 업무 컨트롤과 겹침을 피한다.
2. 공통 모듈에서 첫 표시 전에 루트 테마를 정하고 기존 스타일시트의 색상 미디어 조건을 선택한 테마에 맞춘다. 기존 페이지별 토큰·상태 색상을 보존한다.
3. 저장은 localStorage 단일 키로 제한한다. 시스템 변경, 다른 탭의 저장 변경, 저장소 오류를 처리한다. 업무 데이터·네트워크는 변경하지 않는다.
4. 합성 Chromium에서 장부/카드/항공권/영수증 스타일과 다섯 너비, 확대, 키보드, 페이지 유지, 오류 경로를 검증한다. 관련 셸 단위 검사도 실행한다.
5. 검토 후 PR을 정상 병합하고 통합 릴리스를 배포한다. 운영 로그인 화면 수락은 별도로 기록한다.

---

<a id="src-docs-superpowers-plans-2026-10-27-card-review-latency-md"></a>

## 2026-10-27-card-review-latency

통합 전 경로: `docs/superpowers/plans/2026-10-27-card-review-latency.md`

<a id="src-docs-superpowers-plans-2026-10-27-card-review-latency-md--카드결제검토-지연카카오-잔여-진단-2026-10-27"></a>
### 카드결제검토 지연·카카오 잔여 진단 (2026-10-27)

현재 승인 요청: 카카오 결제건 미처리 사유 확인과 카드결제검토 진입 지연 수정. 이전 Paseo `d9040fc3-c1e4-4eed-825f-3e8c290780ca`의 진단 단계에서 이어받았다. 과거 완료 큐는 재실행하지 않는다.

| 요구 | 변경/확인 | 상태·근거 |
| --- | --- | --- |
| 진입 지연 | 현재 페이지 카드 ID만 OTA 표시 근거로 투영. 배치 조회에 이미 포함된 원문 필드를 보호 검사에서 재사용 | COMPLETE: PR #167 운영 b577e7f, generation374 수락 |
| 카카오 잔여 | 지출 정리 잔여 택시 11건 모두 취소·원승인번호 없음·취소 승인번호와 같은 구매 없음. 보관 원문에도 괄호형 원승인번호 없음 | 읽기 전용 진단 완료, 실제 처리 BLOCKED_EVIDENCE |
| 누락 설명 | 미연결 취소 근거에 원승인번호 부재와 취소 승인번호 단독 확정 불가 표시 | COMPLETE: 실제 로그인 카카오 상세에서 두 문구 확인 |

운영 메뉴 GET 1회: TTFB 12,411.6ms / DOM 12,920.8ms. 동일 보관 OTA 입력의 cProfile에서 표시 45.0초 → 5.3초; 제공자 대조 429,157회가 병목이었다. 프로파일과 운영 시간을 혼동하지 않는다. 원문 자료·식별자·금액은 문서/PR/외부 검토자에게 전달하지 않았다.

카카오 11건의 14일 같은 카드/가맹점 조회에서 10건은 동액 후보 없음, 1건은 총 4개 후보 중 동액 1개다. 동액/가맹점만으로 원결제를 확정하거나 가승인 해제를 매입 환불로 간주하지 않는다. 실제 처리를 위해 원결제 대응이 확인되는 카드사 상세 또는 카카오T 증빙이 필요하다. 현재 있는 원승인번호 기반 1:N 연결 계약은 그대로 유지한다.

표적 검사: navigation performance / OTA 표시 관련성 / 환불 표시 / cleanup OTA 계약 / partial refund **81 passed**. 원문 재사용 최종 변경 후 관련 보호 **1 passed + 6 passed**, 원승인번호 부재 문구 **3 passed**. 인접 화면 묶음 **35 passed / 3 failed**이며 3개 문구 기대값 실패는 변경 전 `3d73b9c` 별도 archive에서도 **3 failed**로 동일 재현했다. 무관한 기존 문구 실패는 수정하지 않는다. 전체 pytest/전체 재대사/기장/Google 쓰기는 생략한다.

검토 중 제기된 source=None 우려는 추가 조회를 없애고 get_batch 원문 필드로 튜플을 만들어 해소했다.

종료 조건: 검토 → PR/main 병합 → 검증된 고정 SHA Windows 릴리스 → health/ready·보호 API·같은 메뉴 최소 스모크 → SHA·속도·보호 근거 기록. 실제 금융 처리는 증빙 차단으로 별도 남긴다. 기존 사용자 미추적 계획 파일은 보존한다.

완료 근거: main merge/운영 `b577e7f5f296de29138166a3617c81eb93f3e23e`, 965개 blob 일치, 작업/프로세스/단일 리스너 SHA 일치, health/ready200·보호API401, 2DB/13개 표 내용·스키마 보존. generation374 신선한 자료 메뉴 GET200, TTFB3,136.3ms·DOM3,362.6ms·자동화 관찰7,085ms. 시작 시 갱신 중 수치는 별도로 보존한다. 정확한 경로는 [운영 기록](../operations.md) 첫 절. 별도 #166 Agoda 추론 진단은 이 요청에서 실행하지 않았다. 카카오 실제 처리를 재개하려면 11건의 원결제 대응을 증명할 추가 근거를 읽기 전용으로 확인한 뒤 해당 금융 조치의 승인/보호 게이트를 적용한다. 현재 구현을 다시 실행하거나 보류 해제를 자동 수행하지 않는다.

---

<a id="src-docs-superpowers-plans-2026-10-27-flight-search-integration-md"></a>

## 2026-10-27-flight-search-integration

통합 전 경로: `docs/superpowers/plans/2026-10-27-flight-search-integration.md`

<a id="src-docs-superpowers-plans-2026-10-27-flight-search-integration-md--항공권-검색-장애열린-pr-통합"></a>
### 항공권 검색 장애·열린 PR 통합

- 승인: 이전 Paseo 에이전트 `2b2ca7be-a0ee-402d-a9c8-84be15b392de`의 마지막 사용자 요청은 항공권 예약 조회 점검 및 모든 PR 병합·배포. 후속 세션은 기록을 읽고 기존 로컬 통합을 이어간다.
- 범위: #172/#174/#176/#177/#179/#180 및 추가 #183. 과거 미추적 `2026-10-26-cost-open-work-plan.md`는 사용자 파일로 보존한다.
- 원인: 이름 검색이 전체 OTA/카드 대사 freshness를 요구해 갱신 중 인증된 항공 메일까지 검색 불가.
- 변경: 메일 내용 지문·파서 버전으로 분리한 비동기 항공권 색인, 최초 화면 진입 예열과 최대 60회/2초 재조회. 변경·누락·오류는 최신 근거로 표시하지 않는다. 결제 연결/참가자 확정은 기존 금융·참가자 게이트를 유지한다.
- 통합 보완: #179 합성 DB의 원거래 ID/누락 열 수정 및 수동 결정·보류·제외·원본 충돌 보호. #183 데스크톱 테마 버튼 유지·모바일 단일 버튼·44px 유지. #180 CLI의 엔진 import 실패를 false 진단으로 숨기지 않는다.
- 금융 경계: #174의 동일 카드/카카오 포함 가맹점/동액 추론은 읽기 전용 후보 표시로 통합했다. 원승인번호 없이 `refund_links`/`refund_group`의 금융 연결·상쇄에 편입하지 않는다. 번호 근거 1:N은 보존한다. 기존 장부 귀속 전달은 명시적인 기존 지출 실행 경로 안에 유지하며 이번 운영 스모크는 실행하지 않는다.
- 검사: 보호/cleanup/테마/지연로딩/장부 귀속 묶음 82 passed. 항공권/날짜/분리 색인/모바일/카카오/귀속 묶음 27 passed. 이후 자동 갱신 브라우저·수동 보호·CLI 진단·카카오 영향 6 passed (12 deselected). 참가자/기존 색인 18 passed. 중복 포함 묶음 수치이며 고유 검사 총합으로 합산하지 않는다. 초기 fixture 누락으로 실패한 2건은 보완 후 통과, 없는 테스트 파일명을 지정한 명령은 실행 0건으로 계산하지 않는다.
- 원본 읽기 관찰: 메일 전용 추출 45.419초/예약210건. 금융 대사 성능과 구분한다. 원문/고객 이름은 보고서·Git에 복사하지 않았다.
- 운영 전 기준: `.local-archive/flight-search-integration-20261027/protection-before.json` (2DB/13개 보호 표). 기존 복원 검증·이전 고정 릴리스 재사용 예정.
- 상태: **COMPLETE**. #184 병합·운영 `94c8e8c293d784da3886879ad024d3c5d12061a5` 배포, 관련7개 PR 전부 MERGED/열린PR0개. 979blob 일치·health/ready200·보호API401·2DB/13개 보호 표 동일. 실제 이름 검색 예약1건/여정2편/최초 메일 수신일·금융 미확정 안내, 지출 정리 표시를 확인했다. 운영 메일 색인 최초 생성67.77초이고 전체 OTA 대사 갱신 중에도 검색됐다. 증빙 문서만 추가 병합하며 앱 재배포는 생략한다.
- 배포 보완: 첫 시도는 이전 SHA 불일치 `TASK_MISMATCH`로 서버 교체 전 중단. 현재 운영 #178 `2f51cb208d411d1913546e9bdc16a3f319eaeb48`의 정상 배포 증거 및 새 릴리스 조상 관계를 확인해 복구 기준을 바로잡고 공식 절차로 성공했다. 추가 권한·배포 인프라 변경 없이 진행했다.
- 의도적 생략: 전체 pytest/E2E·대량 재대사·실제 장부/Google/참가자 쓰기. 변경 영향과 무관한 과거 개발 큐는 재실행하지 않는다.

---

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md"></a>

## 2026-10-27-navigation-performance-plan

통합 전 경로: `docs/superpowers/plans/2026-10-27-navigation-performance-plan.md`

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--navigation-read-performance-implementation-plan"></a>
### Navigation read performance implementation plan


**Spec:** User explicitly requests Aside REPL navigation measurements, root cause diagnosis and fixes for slow page transitions. Preserve auth, financial guards, customer originals, decisions and read-only GET behavior.

**Goal:** Reduce server wait in OTA/import pages and prevent avoidable expensive work from queueing other menus. No financial policy, data or schema changes.

**Architecture:** Keep server DB serialization intact. Reuse projection index within one `automatic_holds` call; inspect the catalog index build/signature before choosing its minimal fix. Read-only scopes never outlive a request. Stale display, if used, must be visibly labeled; strict write/detail validation remains fresh.

**Evidence:** Aside actual link clicks: cards 1.440s (TTFB .919s), OTA 16.795s (TTFB 16.359s), receipts .791s (TTFB .269s), board 2.307s (TTFB 1.855s), import 23.768s (TTFB 23.232s). Source-copy cleanup profile 10.812s: `automatic_holds` 8.636s; 1,374 `_projection_index` calls repeatedly aggregate all board rows, 7.494s. Background full OTA worker is separate and must not be triggered by profiling.

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--tasks--single-verification-boundary"></a>
#### Tasks / single verification boundary

1. Add synthetic guard-parity/query-count regressions to `webapp/tests/test_navigation_read_performance.py`, watch fail, reuse one index in `automatic_holds` without changing matching rules. Preserve transaction identity, signed legacy key and fresh next-call state. Verify with existing relevant projection/refund checks; compare the same source copy profile after changes once.
2. Identify catalog profile hot path. Add targeted regression before modifying it; keep changes to reads, no migrations/financial writes. Verify only catalog/profile-adjacent tests.
3. Review complete branch independently (code and synthetic evidence only), commit/PR/merge, fixed-SHA deployment with existing restore evidence and one health/protected-route smoke. Repeat exact Aside link routes once and record TTFB/DOM separately. Record results in operations/current handoff. No whole pytest/browser suite or actual ledger writes.

**Review focus:** projection source/decisions freshness; manual/financial/refund guards unchanged; catalog freshness labeling and write validation; thread/board ownership and lock order; no source contents or credentials in profiling outputs/Git.

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--implementation--evidence-ledger"></a>
#### Implementation / evidence ledger

- Root causes: per-row projection version aggregate, repeated refund display matching/count checks, catalog GET legacy fallback when central snapshot is pending, startup prewarm holding the publication lock, and identical trip boundary calculation inside every booking iteration.
- RED reproduced each new performance contract. Changes reuse projection once per batch hold scan and refund display data once per render, use fresh canonical snapshot or pending state, move index computation behind a separate builder lock, serve visibly provisional catalog while refreshing, and compute trip handover boundaries once per build. Strict detail/write lookups remain synchronous and fresh; global server DB serialization is unchanged.
- Same source-copy cleanup profile: 10.812s before / 2.092s final, projection scans 1,374 → 2; catalog foreground after 0.723s. Initial cold catalog profile was stopped when full legacy fallback was identified; a subsequent synchronous no-fallback build still took 114.753s under cProfile (mail parsing 82s and repeated boundaries 27.5s), confirming the need for asynchronous list reads. These are profile timings, not browser acceptance numbers.
- Verification: projection/refund boundary checks 19 passed; catalog/booking/performance checks 31 passed; after bulk refund optimization 39 passed / 4 failed. One old unlinked copy assertion also fails at baseline cb7c575 and remains out of scope. Three old async tests were updated to seed a complete index explicitly and then passed (3 passed / 22 deselected). Final performance/catalog selection: 19 passed. No full regression.
- Review identified disk serialization/save and stale-file loading still under the publication lock. Moved both outside that lock while retaining the single builder lock and atomic file replacement. Added build/save contention regression (save failed before fix); relevant concurrency/stale/save selection: 6 passed. Reviewer follow-up found no actionable issues. Financial projection/duplicate/existing-ledger selection: 18 passed, 8 subtests passed; save failure preservation test passed.
- PR #139 merged and pinned Windows deployment completed at a08cb815aa54be08a8361892a6fec3802aed616b. Release 956 blobs match; runtime/task SHA, health/ready 200, protected API 401 verified. Two DBs / 13 protected table content/schema hashes unchanged. See operations latest entry for evidence.
- Local profiles/copy under `.local-archive/navigation-20261027`, never Git. Existing untracked 2026-10-26 plan preserved. Actual after-deployment expense page observed, but Aside Page.navigate then Runtime.evaluate timeouts prevented five-menu timing: NOT_MEASURED / PARTIAL. Next command: Aside attach a working COST tab, snapshot nav then actual link clicks and navigation timing for the same five routes. Do not repeat successful tests/deployment or claim browser performance acceptance from profiles.

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--retry--remaining-board-bottleneck"></a>
#### Retry / remaining board bottleneck

- User requested retry; existing COST tab now responds. Actual #139 after-click/TTFB/DOM ms: cards 3221/2594/2867, OTA 8874/3284/3527 (Aside readiness wait 4311ms), receipts 5057/4118/4295, board 7517/6907/7111, cleanup 2968/2563/2725. Same browser health GET 215ms. Cleanup/OTA server wait improved, while common request contention and board computation remain observable; do not claim every page became faster from this sample.
- Board source-copy profile: 126 list_tab_rows calls (every tab read for both income and expense), 3.456s. Share tab reads only inside existing read_scope; copy rows before display projection, preserve next-render freshness. After profile 63 calls, 1.152s (timings include variable host load; call reduction is deterministic).
- New synthetic test failed for duplicate calls before fix then passed, with identity/amount/revision parity and SQLite dump unchanged. Read scope selection 2 passed; adjacent refund display/split/allocation/remainder selection 15 passed plus 3 subtests. No full suite or source migration. Pending review, pinned deployment and exact menu click acceptance.

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--cold-start-contention-discovered-during-acceptance"></a>
#### Cold-start contention discovered during acceptance

- #141 deployed bc7cd0bb993576e92c3417b2da02a825e0cba615; actual first cards click returned524. Rolled back to prior a08cb815aa54be08a8361892a6fec3802aed616b with task/process/health/ready/401 verified. A further import request on a08 also queued (ready timed out8s), so the shared-row change is not established as the cause. Two old-release reconciliation child processes left after deployment were identity/ancestry checked and stopped; current listener was excluded. No original/DB files removed.
- Read-only py-spy stacks on a08: catalog startup parsing mail on an active GIL thread, import inside pipeline preview→tab_valid→trip_valid→get_trip, another HTTP request awaiting store_lock. Later sample had no active request/prewarm thread. This establishes overlap and shared request queueing, not a financial policy defect.
- Preview repeatedly validates identical trips/tabs and may reread schedule evidence per transaction. Cache only the bound validators local to one read-only cleanup render; actual write validators and next render remain current. New synthetic RED16 calls→GREEN2, changed validation seen on next render, DB dump unchanged. Cleanup/refund selection15 passed. Pending review and final deployment/menu timing. Keep previous acceptance explicitly incomplete until actual clicks pass.

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--session-takeover--catalog-process-isolation"></a>
#### Session takeover / catalog process isolation

- Resumed Paseo `31f49529-12a2-494d-9fac-94bdf1090e90` after its provider usage-limit error. Preserved the existing workspace, four modified code/test files, new child module and unrelated untracked October 26 plan. Current live release verified as `13dcf7d5c401f7621725025a2fa715d73bfc7719` (#142), so earlier pending-deployment notes above are historical.
- Purpose: remove startup mail parsing contention in the HTTP interpreter. Parse catalog sources in an isolated child with read-only SQLite/query_only, clean temporary exchange on success/timeout, and skip unused legacy startup prewarm in central mode. Financial matching/writes/auth remain unchanged. The child module participates in saved-index code identity.
- Verification: `python -m pytest webapp/tests/test_navigation_read_performance.py webapp/tests/test_ota_catalog.py webapp/tests/test_ota_booking_trip.py -q`: **41 passed in 11.48s**. Synthetic direct/child parity, board/portal dump invariance and timeout cleanup included. Added snapshot-service shutdown before test store close. No full regression. Subsequent code-identity list/docstring edits do not change execution paths; no redundant rerun.
- Review in progress; deployment and actual five-menu clicks pending. Local protected-table baseline: `.local-archive/navigation-resume-20261027/protection-before.json` (13 tables). Exit condition: review resolved, fixed-SHA release/health/ready/protected-route checks and real menu timing recorded, protected tables unchanged; browser/tool failures must stay explicit.

<a id="src-docs-superpowers-plans-2026-10-27-navigation-performance-plan-md--final-acceptance--complete-for-this-navigation-request"></a>
#### Final acceptance — COMPLETE for this navigation request

- Reviewer on `f73226c` found no actionable Critical/Important issues. PR #143 merged; pinned runtime `a079700a8f513c91e87b8e2e2f54d8a2d2897748`, release 957 blobs equal, Board Running/single loopback listener/task/process SHA checked, health/ready200 and unauthenticated protected API401. Prior `13dcf7d` release and verified restore evidence preserved.
- Actual Aside menu click/TTFB/DOM ms: cards3391/1681/1930; OTA1001/494/624; receipts613/145/260; board2269/1806/1911; cleanup2616/2210/2328. Each HTTP200, one observation. Click includes automation/snapshot overhead; cache/load not controlled. OTA/cleanup long waits improved versus original; cards not universally faster. No average/percentile or unrelated mobile acceptance claim.
- Two production DBs/13 protected tables content and schema hashes unchanged. Local sanitized evidence: `.local-archive/navigation-resume-20261027/{browser-after.json,protection-before.json,protection-after.json}`. Full regression, repeat successful smoke, financial writes and Google writes intentionally omitted. Historical pending notes above are superseded; source-session measurement blocker resolved. No remaining action in this approved scope.

---

<a id="src-docs-superpowers-plans-2026-10-27-ota-provider-refund-plan-md"></a>

## 2026-10-27-ota-provider-refund-plan

통합 전 경로: `docs/superpowers/plans/2026-10-27-ota-provider-refund-plan.md`

<a id="src-docs-superpowers-plans-2026-10-27-ota-provider-refund-plan-md--ota-provider-scope-and-zero-refund-implementation-plan"></a>
### OTA provider scope and zero refund implementation plan


**Spec:** User 2026-10-27 screenshots and requests: remove unrelated OTA comparisons in engine/UI, Trip events only against Trip-related merchants, show actual amounts, inspect linked full refund stuck in review. Existing full-offset policy: `app/ledger.py:REFUND_TAB`.

**Goal / changed behavior:** Match/search uses provider compatibility before amount comparisons; the cleanup view shows actual card and OTA payment amounts. Classified, linked full-offset groups no longer wait for an automatic trip selection. No operating transaction/ledger/Google writes.

**Architecture:** Reuse shared alias rules in `app/ota_payments.py`; preserve explicit links and unfiltered date browsing. Filter historical unconfirmed candidate notes in `webapp/card_flow.py` using the same compatibility predicate. Remove only automatic `trip_needed` for a complete, linked full refund; leave core commit and all persisted holds intact.

**Global constraints:** Windows PowerShell/UTF8. No customer source/identifiers in Git. No migrations, broad regression, import, reclassification or live commit. No arbitrary FX conversion. Existing manual/frozen links remain occupied.

**Review focus:** Approved provider aliases and unknown processors; same-card cross-provider collisions; historical snapshot notes and missing metadata; partial/excess/multi-refund and cross-batch groups; persisted holds/exclusions and immutable source/decisions.

<a id="src-docs-superpowers-plans-2026-10-27-ota-provider-refund-plan-md--tasks-and-completion-gates"></a>
#### Tasks and completion gates

1. Add synthetic engine tests in `tests/card_pipeline/test_ota_provider_scope.py`: cross-provider rows must never be candidates, rejected amount comparisons or auto matches; Trip with unknown merchant and matching last4 must not auto match, but Trip merchant aliases still work. Watch RED, implement shared provider predicate and early filtering in exact/search/pair checks, run this file and relevant matching/defaults tests once.
2. Add cleanup rendering tests in `webapp/tests/test_cleanup_ota_contract.py`: legacy cross-provider rejects disappear; Trip note shows card KRW and OTA native amount/currency, including missing fields and escaping. Watch RED, implement in `_index_ota_display_candidates`, verify rendering reads do not write.
3. Add tests in `webapp/tests/test_cleanup_refund_display.py`: classified full refund with blank trip can preview both rows in refunds; partial/excess, active holds, source conflict and absent batch member remain blocked. Watch RED, remove only automatic trip hold in `CardFlow.automatic_holds`. Verify pair source/decisions unchanged and synthetic group commit stays atomic/idempotent using existing tests.
4. Review fixed diff independently using code/synthetic data only. Commit/push/PR/merge after required targeted checks. Reuse verified release/restore procedure, audit Git blobs, pin SHA, health/ready/protected GET and changed view smoke once. Record actual results and remaining external blockers in operations/current handoff. No document-only redeployment.

<a id="src-docs-superpowers-plans-2026-10-27-ota-provider-refund-plan-md--evidence--ledger"></a>
#### Evidence / ledger

- Investigation: candidate search compares amount before provider, `_has_corroborator` has unconditional Trip fallback. Both linked full refund rows are classified, unassigned, unrecorded, with no persisted review hold; net zero link exists. `automatic_holds` adds `trip_needed` to original and propagates it to the pair.
- RED: new targeted scope showed 10 failed / 8 passed (wrong-provider automatic links, missing amounts, full-offset trip hold reproduced).
- GREEN: scope/cleanup/refund files 36 passed. Adjacent matching/defaults/refund integration 149 passed / 1 failed; the one fixture intentionally allowed Agoda→Trip, so its allowed merchant was corrected to Agoda under the new policy; its focused rerun passed with UI/index checks (20 passed / 38 deselected). Backend/snapshot action boundary checks 23 passed / 33 deselected.
- Matcher policy version now participates in snapshot input keys; no parser version bump or source changes. Legacy amount-mismatch comparisons no longer count as valid payment candidates. Manual/automatic established result history remains visible.
- No whole regression or operating transaction/ledger writes. Existing untracked open-work plan remains untouched. Pending: final review and pinned deployment/smoke/evidence.
- Review confirmed undated inference/scheduled-card bypasses; both were separately reproduced RED and fixed before amount checks. Follow-up tests: provider/inference 34 passed; exact/scheduled 35 passed, 2 legacy Trip-unrelated expectations updated to related Trip fixtures with explicit unrelated rejection. Original `classification_needed` refund inheritance is pre-existing and preserved; the only removed original hold is automatic `trip_needed`.
- Delivery: PR #135 merged and release `909e4ad4ffc3ca4786d61a8b01686101406c79c7` deployed. 953 files blob verified, task/process SHA aligned, health/ready 200 and protected API 401. Protection hashes for 13 tables across two DBs unchanged. Implementation/review/host checks COMPLETE; final authenticated screen/375px PARTIAL due Aside navigation then Page.enable timeouts. See operations/current handoff for precise resume boundary; no real ledger changes.

---

<a id="src-docs-superpowers-plans-2026-10-27-pending-work-release-md"></a>

## 2026-10-27-pending-work-release

통합 전 경로: `docs/superpowers/plans/2026-10-27-pending-work-release.md`

<a id="src-docs-superpowers-plans-2026-10-27-pending-work-release-md--pending-cost-work-integration--2026-10-27"></a>
### Pending COST work integration — 2026-10-27

Scope: user requested document takeover, remaining work and deployment. Base main `6c14bb0`; prior runtime `a079700a8f513c91e87b8e2e2f54d8a2d2897748`. Integrate existing #133 card/sidebar UI, #138 explicit flight date evidence, #145 expense/OTA/Kakao review UI. Preserve the unrelated untracked October 26 plan. No financial matching/writes, customer decisions, Google writes, migrations or original-source edits.

Behavior: card display names and responsive layout; closed previous quarters/refund drilldowns; theme-consistent OTA review and diagnostic-only Kakao groups; source-bound booking dates. Preserve timestamp/zone and project a proven instant to Korea's card day; date-only/unknown-zone evidence stays informational. Auto GET requires fresh unlinked, uncancelled, nonconflicting evidence. Parser v3 invalidates stale passenger indexes. Multiple refs reject date attribution. A browser test exposed an existing deferred-card `fact` ReferenceError; lift the helper into shared scope, add keyboard/aria to the 44px candidate toggle, wrap long booking headers.

Verification evidence (separate runs, not a whole-suite total):

- First broad targeted attempt including historical OTA browser tests was interrupted after repeated old lazy-load expectation failures; NOT_PASS. Source-only baseline substitution of main's OTA module reproduces the old amount-mismatch card wait timeout (1 failed / 8 deselected), so do not repeat this obsolete suite or claim it passes.
- Remaining selected files: 69 passed / 16 failed. Fourteen refund failures were collection-time `WEBLEDGER_CARD_SCHEMA_POLICY=require` pollution from existing card-page tests; run refund tests independently. One theme assertion raced the asynchronous media event; replace immediate reads with Playwright `expect`. One new structural test expected the wrong descendant selector; correct it.
- Refund/expense visual selection, independent process: **18 passed in 2.88s**, including unchanged synthetic DB dumps and financial refund protections.
- Flight parser, passenger index, name search and date tests: **42 passed in 7.75s**, including source revision, manual lookup and automatic-day blockers. Earlier date/cards browser selection: **7 passed / 22 deselected in 5.88s**; covers 375/390/759/760/1280 widths and event-aware theme checks.
- New OTA browser flow: **1 passed / 3 deselected in 4.61s**. Folded facts → keyboard candidate load → select → CSRF preview → clear; confirm never sent. Required widths, system/manual opposing themes and component CSS zoom stress checked. Long-header overflow reproduced and fixed. Actual browser 200%/physical touch remains unverified; CSS zoom does not substitute for it.
- Existing lazy diagnostics browser path: **1 passed / 8 deselected in 4.26s**. Independent read-only review of integration and follow-up: no remaining Critical/Important issues.

Read-only local source audit: 285 authenticated flight messages, 0 supported explicit date labels, 0 zoned automatic-card days, 0 date conflicts. Do not invent real booking dates; supplier order-created evidence remains external. Kakao/UPay inventory: 36 merchant/direction groups, 108 taxi-family rows and 30 other rows. These are diagnostic family counts, never confirmed payment/cancellation links. No names, booking refs, card IDs or transaction contents in the report. Local aggregates: `.local-archive/pending-work-20261027/readonly-source-counts.json`.

PR #108's unique diff against its merge base is whitespace-only (`--ignore-all-space --ignore-blank-lines` empty); retain HOLD without merging or deleting its branch. OZE has no new reproduced user failure; preserve earlier confirmed income display and do not run unrelated reprocessing.

Exit condition: review resolved; integrated PR merged normally; fixed-SHA release, prior restore evidence, one health/ready/auth smoke and changed live paths recorded; protected-table hashes equal. Runtime/deployment and actual UI acceptance are pending until observed. Live real-reservation date flow remains BLOCKED_EXTERNAL_EVIDENCE without a matching authenticated source; physical-device/actual browser zoom acceptance remains external.

<a id="src-docs-superpowers-plans-2026-10-27-pending-work-release-md--first-deployment-and-required-read-path-correction"></a>
#### First deployment and required read-path correction

- #146 merged as `da41f407716ba6fd9c20f983033c39f0dc58951d`; #133/#138/#145 automatically became MERGED. Release 960 blobs, task/process SHA, health/ready200 and protected API401 passed. Live card header/months/October32 rows/trip labels/default-closed quarters and no horizontal overflow confirmed. Import showed 9 closed refund panels, 8 comparison panels, 4 Kakao inventory panels and the new OTA surface.
- Live flight-name lookup returned unavailable evidence while the passenger cache still carried parser v2 and normal refresh was active. An actual OTA candidate GET then remained pending. Read-only py-spy reproduced foreground `/api/imports/{batch}` → `_state` → preview metadata → legacy mail reconciliation holding the shared request lock. Do not call this first deployment accepted.
- Rolled back to verified `a079700a8f513c91e87b8e2e2f54d8a2d2897748`, preserving both releases and separate `rollback146` task/evidence files. Runtime/prior SHA, health/ready200 and protected API401 passed. No customer data/DB/Google changes.
- Fix only read-state metadata: `preview_metadata(display_only=True)` uses fresh central projection or empty provisional metadata; `_state` opts in. Default commit/classification metadata and financial guards are unchanged. New full-state/metadata regressions: **3 passed / 13 deselected in 1.93s**, synthetic dump unchanged, default write resolver still called. Adjacent metadata/provenance/digest protections: **11 passed / 58 deselected / 16 subtests passed in 2.87s**. Pending review and final release/smoke. The new live failure justifies this additional deployment; no broad regression repeated.

<a id="src-docs-superpowers-plans-2026-10-27-pending-work-release-md--user-policy-update-first-received-mail-day"></a>
#### User policy update: first received mail day

- #147 was reviewed, merged and deployed as `6b1b4fec268c1ce750e5460c030d1f34d013be7e`; 960 blobs and health/ready200/auth401 passed. The user then explicitly authorized earliest mail reception as booking date when a separate date is absent. This supersedes the original-date external blocker for this fallback, not financial/cancellation/freshness guards.
- Parser v4 collects valid mailbox reception times only from authenticated provider+single booking-ref messages, including earlier reference-only mail, without creating flights from those messages alone. UNKNOWN date status gets `FIRST_RECEIVED` with UTC receipt provenance and exact Korean day; explicit dates/date conflicts take precedence. An itinerary conflict may retain an informational receipt date but keeps the conflict flag and blocks automatic queries. Source digests/revision change if an earlier receipt appears. UI labels the basis and requires fresh/unlinked/uncancelled/nonconflicting evidence before automatic GET.
- New collector/parser/index/name selection: **39 passed / 1 failed in 8.77s**. Existing immediate visibility assertion raced name-search rendering; changed it to Playwright `expect`. Follow-up original name-search browser plus explicit/first-received automatic-day blockers: **3 passed / 14 deselected in 9.59s**. Final first-received collector selection: **5 passed in 0.91s**, including informational conflict preservation. No finance/API writes added.
- New source audit and latest fallback deployment/live smoke pending. Historical original-date-only blockers above describe the earlier policy. Source timestamps/customer names remain out of Git/PR/logs.

<a id="src-docs-superpowers-plans-2026-10-27-pending-work-release-md--resumed-candidate-read-fix-and-final-release"></a>
#### Resumed candidate read fix and final release

- Took over Paseo `218f9538-bc30-4e09-b3fc-bda7eeec516a` after its recorded usage-limit error. Confirmed existing changes and review evidence before editing. Concurrent takeover `f55d5af6-48c0-4c8f-a445-b7bec0d13449` stopped mutations; its additional browser test is preserved in the follow-up evidence PR. The unrelated untracked October 26 plan remains untouched.
- #148 merged fallback policy as `0a75f45b193c498e05df05b658134f320c7d7407`. Source audit: 200 booking groups, 16 FIRST_RECEIVED Korean days, 184 UNKNOWN; 167 cancelled or conflicting groups across all bookings. These counts do not establish eligibility for automatic card lookup. Its deployment exposed a second foreground read: candidate GET called `_data()` and parsed original mail. The earlier agent rolled runtime back to verified `6b1b4fe`.
- #149 / code `ca2e182d60f8e367956481630c01a0320ae258d7` changes only candidate reads/error handling: `_action_data()` checks fresh snapshot/input fingerprint without foreground reconciliation; pending/stale returns 409 `OTA_SNAPSHOT_NOT_READY` and a retry hint. Financial action implementations are unchanged. New pending-route regressions and existing candidate parity checks: **5 passed / 37 deselected in 2.29s**. Prior review and concurrent review report no important unresolved bugs. Additional concurrent browser regression: **1 passed / 3 deselected in 5.72s**, 375px keyboard retry from 409 to loaded cards, preview remains disabled, GET-only. This exact evidence is reused without rerunning.
- #149 merged and deployed **`4cd12adebad6ebcac110130803d35f589d1f8bb0`**. Release audit: 962 tracked files, zero blob mismatches. Existing verified restore evidence and prior release are preserved; before/after task XML, task Running, one loopback listener and process SHA verified. health/ready 200 and unauthenticated protected API 401. Initial deployment invocation occurred before the archive marker was ready and stopped at marker read, before task/process mutation; deployment proceeded only after archive verification completed.
- Live authenticated import showed OTA review and refresh state. Opening its first candidate displayed the new retry hint with loading=false; a subsequent read-only candidate GET returned 409/OTA_SNAPSHOT_NOT_READY in **665ms**. No candidate selection, preview/confirm, link or financial write was sent. Navigation to OTA and the flight name-search screen succeeded. Protected 2DB/13-table schema/content hashes equal the original pre-integration baseline (`protection-after.json`).
- Full pytest, repeated successful prior UI/synthetic checks, physical touch/actual browser zoom, live financial actions and Google writes intentionally omitted. At this checkpoint the passenger cache is still parser v2 during normal background refresh; live first-received name-search acceptance must be recorded separately after the fresh index is published. Do not report old-cache results as parser v4 acceptance.

<a id="src-docs-superpowers-plans-2026-10-27-pending-work-release-md--fresh-first-received-live-acceptance"></a>
#### Fresh first-received live acceptance

- Normal background refresh completed in **476.56s**, published generation359 / `flight-evidence-v4-first-received` at 07:38:13 KST. No manual reconcile/restart was invoked while waiting.
- Existing owner Aside tab: selected a noncancelled/nonconflicting FIRST_RECEIVED booking from the published index, searched its passenger name without printing it, and observed **1 reservation / 1 receipt-basis label / 1 automatically opened day filter / 9 of 9 card rows**. The date status explicitly says payment links are not confirmed. No financial action or participant assignment sent. The previous old-index block is resolved.
- #150 merged test/evidence-only changes as `2e3b2cabfbb948b1eb0584edc192c136b63d8c6d`; runtime stays `4cd12ad` because no application source changed. Local document targets (24) and diff whitespace checked; existing passed evidence reused.
- After publication the same OTA candidate GET returned **200 / 2473ms / 683 candidate rows**. These are existing comparison candidates, not verified payments. The whole import-click/observation CLI call took 34.541s, distinct from API timing; no claim of an overall import-page latency fix. Changed candidate read paths now have actual pending and fresh response evidence.

---

<a id="src-docs-superpowers-plans-2026-10-27-review-fixes-integration-md"></a>

## 2026-10-27-review-fixes-integration

통합 전 경로: `docs/superpowers/plans/2026-10-27-review-fixes-integration.md`

<a id="src-docs-superpowers-plans-2026-10-27-review-fixes-integration-md--검수-지적-수정모든-브랜치-통합배포"></a>
### 검수 지적 수정·모든 브랜치 통합·배포

사용자 현재 승인: Paseo `4b30b36d-8542-49d1-9708-206d30d49ade` 검수 지적 수정 후 모든 브랜치 통합 및 운영 배포. 기존 미추적 CloudMail.gs와 작업 계획은 보존한다. 금융/Google/원본 쓰기·마이그레이션은 범위에 없다.

<a id="src-docs-superpowers-plans-2026-10-27-review-fixes-integration-md--변경-및-검증"></a>
#### 변경 및 검증

- 수입 불일치·미검증 시 검색 요약에 전체/검색 지출 금액과 건수를 구별한다. 미검증 수입 금액·차액은 표시하지 않는다. 비검색 표시를 유지한다.
- 콘솔 창 완전 차단 주장을 `pythonw.exe` 전환 완료·다음 예약 실행 수락 NOT_RUN으로 정정한다. 메일 수집을 추가 실행하지 않는다.
- 시작 시 원격 main만 있었으나 진행 중 `fix/lazy-ota-expense-review-20261027` / PR #189가 추가됐다. 고유 커밋 `3051892`, `d0795f7`, `30e0ab9`를 통합했다. OTA 검토는 닫힌 상태에서 조회하지 않으며 펼칠 때만 읽는다. 닫았다 다시 펼칠 때 조회 재개와 summary 포커스 때문에 초기 렌더가 보류되는 문제를 추가 보완했다. 기존 선택·미리보기·확정 보호 코드는 유지한다.
- `test_income_summary_display.py`: **9 passed**.
- `test_trip_google_income_browser.py -k discrepancy`: **1 passed, 2 deselected**.
- 새 OTA 지연조회 계약/브라우저 검사: 계약·닫힘·열기·재열기·선택 보존 **2 passed**; 직접 링크 두 종류는 테스트 응답의 UTF-8 헤더 누락을 고친 뒤 **2 passed, 2 deselected**. 변경 없는 통과 검사는 반복하지 않았다.
- `test_ota_payment_review.py`: **38 passed, 1 failed**. 실패는 Windows 임시 DB 정리 잠금이며 기준 main의 해당 검사에서도 **1 failed**로 재현했다.
- `test_ota_payment_review_browser.py`: **5 passed, 10 failed**(subtest 포함). 기준 main은 **3 passed, 동일 10 failed**. 추가 통과2개는 새 지연조회 검사다. 실패는 기존 후보 상세의 즉시 노출 가정 및 임시 DB 정리 문제이며 수정 범위로 확대하지 않았다.
- `test_ota_preview_race_browser.py` + `test_ota_matching_defaults_browser.py`: **2 passed, 3 failed**; 기준 main도 **2 passed, 동일 3 failed**. 기존 접힌 예약 근거의 가시성 기대에서 실패한다. 이번 지연조회 동작에 맞춰 테스트의 최상위 OTA 영역만 명시적으로 연다.

<a id="src-docs-superpowers-plans-2026-10-27-review-fixes-integration-md--실행-상태"></a>
#### 실행 상태

**COMPLETE:** #189/#190 정상 병합·운영 SHA `183d813301a4fcc4cab78d52a8d7e2ff2074be63` 한 번 배포. 982개 blob 일치, 작업/프로세스 SHA 일치·단일 loopback listener·health/ready200·보호API401·13개 보호 표 전후 동일. 이전 운영 SHA `84e602ee76f4b50a072e43520af3cd886cebb423`와 기존 복원 검증 사본을 보존했다. 운영 `/import` 초기 접힘/API0건·펼침200·재접힘, 장부 검색 전체/결과 지출 구분과 원래 화면 복귀 확인. 두 경고 상태는 배포된 모듈의 합성 입력으로 검증했다. 전체 pytest/전체 E2E·금융 재대사·메일 수집·Google 쓰기는 실행하지 않았다. 콘솔 다음 예약 실행 수락은 NOT_RUN 유지. 문서 증빙 후속 PR은 앱 재배포 없이 통합한다.

로컬 증거: `.local-archive/income-summary-fix-20261027/`의 기준 main archive·실패 비교 로그·고정 릴리스 생성/검증·배포/보호 스크립트.

---

<a id="src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md"></a>

## 2026-10-27-unified-trip-ledger

통합 전 경로: `docs/superpowers/plans/2026-10-27-unified-trip-ledger.md`

<a id="src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md--여행-장부-수입지출-화면-통합"></a>
### 여행 장부 수입·지출 화면 통합

<a id="src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md--현재-승인범위"></a>
#### 현재 승인·범위

사용자는 카카오/Agoda 환불 PR의 실제 해결 여부를 묻고, 첨부 화면의 불필요한 상세 영역·분리된 수입/지출·수입표와 떨어진 총계·디자인 불일치를 개선하도록 요청했다. 현재 작업은 이 화면의 읽기 전용 표시 개선과 환불 상태 진단이며, 과거 미결 목록 전체 재실행이나 금융 자동 확정 권한을 만들지 않는다.

- 변경 목표: 수입/지출 공통 시각 체계, 표 가까이 붙는 합계와 검증 경고, 불필요한 상세 접기 제거, 지출 중복 헤더 제거. 원본/대조 링크와 동기화 정보는 접근 가능하게 유지한다.
- 보존 경계: 금액·실거래 행·환불·수동 결정·권한·원본을 변경하지 않는다. 수입 행합계와 시트 집계의 차이/검증 미완료를 숨기지 않는다. Google 수입을 SQLite 수입 행으로 복제하지 않고 허위 회계 확정/차액을 만들지 않는다.
- 검증: 변경된 수입/장부 렌더링 표적 테스트와 필요한 375px/1280px·라이트/다크 합성 브라우저 검사. 전체 pytest/전체 E2E는 실행하지 않는다. 내용 검토 후 정상 PR 병합·SHA 고정 배포·health/ready·해당 화면 최소 스모크·증거 기록까지 기존 자동 배포 승인을 적용한다.

<a id="src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md--환불-읽기-전용-진단-2026-10-27"></a>
#### 환불 읽기 전용 진단 (2026-10-27)

`mode=ro`/`query_only`/일관된 읽기 트랜잭션에서 현재 엔진을 조회했다. 실제 연결/장부를 쓰지 않았고 `total_changes=0`이다. 비식별 근거는 `.local-archive/unified-trip-ledger-20261027/refund-diagnosis.json`에 보존한다.

| 항목 | 현재 근거 | 상태 |
|---|---|---|
| 카카오 PR | #169 번호 공백·보호 보완, #172 진단, #174 동액 추론은 #184에서 후보 표시만 허용해 병합·배포 | PR 존재/운영 반영 |
| 카카오 취소 | 39건 중 금융 연결28건, 미연결11건 모두 원승인번호 없음. 후보 표시1건 | 미연결11건 해결 아님 |
| Agoda #176 | 기존 원결제·환불 연결을 원결제 화면에도 표시. 새 매칭 알고리즘 수정 아님 | 표시 보완 반영 |
| Agoda 625,280원 쌍 | 취소1건/금융 연결1건/순액0원1건 | 연결·상쇄 근거 있음, 실제 환급/장부 완료와 별개 |
| Agoda 전체 | 취소76건/금융 연결73건/미연결3건 | 일부 근거 미확인 |
| Agoda 미연결3건 | 모두 원승인번호 없음. 2건은 외화 금액은 있지만 같은 카드의 동일 외화 금액·통화 구매0건, 1건은 외화 금액도 없음 | 현행 매칭 근거 부족. 임의 연결/정산 확정 금지 |

<a id="src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md--실행-상태"></a>
#### 실행 상태

- **구현 완료 파일:** (`webapp/google_ledger_page.py`, `webapp/ledger_design.py`, `webapp/tests/test_trip_google_income.py`, `webapp/tests/test_trip_google_income_browser.py`).
  - 상단 요약 바(`#sum`) 수입·지출·차액 통합 렌더링 및 불일치 시 허위 차액 미표시.
  - 지출 테이블 중복 열 헤더(`tbody.colhead`) display:none 처리.
  - 수입 테이블 하단 행 합계 `<tfoot>` 즉시 부착.
  - `<details class='income-detail'>` 중첩을 평탄화하여 `.income-meta-bar`로 정리.
- **표적 검사 통과:**
  - 수입 유닛 및 권한/검증 테스트: `python -m pytest webapp/tests/test_trip_google_income.py webapp/tests/test_income_summary_display.py webapp/tests/test_ledger_display_updates.py webapp/tests/test_mobile_income.py` -> **34 passed (4.34s)**
  - 브라우저 E2E 테스트(Playwright 375px/1280px Light/Dark, 불일치 경고): `python -m pytest webapp/tests/test_trip_google_income_browser.py webapp/tests/test_ledger_display_browser.py` -> **4 passed (10.85s)**
- **진행 단계:** **COMPLETE**. PR #187 정상 병합 및 운영 `84e602ee76f4b50a072e43520af3cd886cebb423` 배포 완료. 980개 blob 일치, health/ready 200, 보호 API 401, 2DB/13개 보호 표 해시 동일 (`unchanged: true`). 운영 실시간 화면 (`trip-46d817cfb8c2`) 수입 35건(46,170,000원)·지출 81건(6,989,884원)·차액(39,180,116원) 상단 바 통합, tfoot 부착, 중복 지출 헤더 제거 확인 완료.

<a id="src-docs-superpowers-plans-2026-10-27-unified-trip-ledger-md--추가-사용자-요청-콘솔-창-비노출"></a>
#### 추가 사용자 요청: 콘솔 창 비노출

사용자는 로컬 COST 스크립트 창을 보이지 않게 하라고 추가 지시했다. 21:09:25에 시작한 `WebLedger-MailCollect`의 `python.exe -m app.mail_collect`와 같은 시각·실행 파일 제목의 Windows Terminal 창을 확인했다. 조치 시점에는 수집 프로세스와 창이 자연 종료돼 별도 숨김/강제 종료는 하지 않았다. 다음 실행부터 창이 뜨지 않도록 같은 설치 디렉터리의 `pythonw.exe`로 예약 작업 실행 파일만 교체했다. XML 비교에서 실행 파일 외 인자·작업 디렉터리·트리거·설정은 모두 동일함을 확인했다. 작업 재시작/추가 메일 수집/원본 변경은 하지 않았으며, 다음 예약 실행 자체는 NOT_RUN이다. 현재 보이는 터미널 창이 없음을 확인했다. 복원 가능한 작업 XML 전후와 근거는 `.local-archive/mail-console-hidden-20261027T211154/`에 보존했다.

---

<a id="src-docs-ui-audit-20261024-md"></a>

## ui-audit-20261024

통합 전 경로: `docs/ui-audit-20261024.md`

<a id="src-docs-ui-audit-20261024-md--cost-웹-ui-감사-보고서-2026-10-24"></a>
### COST 웹 UI 감사 보고서 (2026-10-24)

> 기준: docs/card-all-transactions-and-ui-design-system-spec-v1.md (PR #101 병합됨)
> 목적: 카드 전체 내역 기능과 웹 전체 디자인 시스템 구현을 위한 현재 상태 조사

<a id="src-docs-ui-audit-20261024-md--1-현재-라우트-및-페이지-구조"></a>
#### 1. 현재 라우트 및 페이지 구조

<a id="src-docs-ui-audit-20261024-md--11-주요-진입점-owner-기준"></a>
##### 1.1 주요 진입점 (owner 기준)
| 메뉴 | URL | 렌더링 파일 | 비고 |
|------|-----|-------------|------|
| 여행 장부 | `/board` | `ledger_design.py:page()` | 메인 대시보드 |
| 지출 정리 | `/import` | `card_flow.py:page()` | 카드 업로드/검토 |
| OTA 내역 | `/ota` | `ota_catalog.py` | OTA 결제 검토 |
| 영수증 처리 | `/receipts` | `receipt_review.py` | 조건부 활성화 |
| 여행 관리 | `/trips` | `ledger_board.py` | 여행 CRUD |
| 예약 명단·여행 연결 | `/reserve-links` | `reserve_link_ui.py` | |
| 항공권 참가자 연결 | `/flight-passengers` | `flight_passenger_page.py` | 조건부 활성화 |
| 계정·권한 관리 | `/access/admin` | `access_control.py` | |

<a id="src-docs-ui-audit-20261024-md--12-카드-관련-기존-경로"></a>
##### 1.2 카드 관련 기존 경로
- `/import` - 지출 정리 (메인 카드 업로드/검토 화면)
- `/import?scope=all` - 전체 카드 거래 검색 (`card_catalog.py`)
- `/api/imports/<batch_id>` - 배치별 상세 JSON
- `/api/imports/<batch_id>/decision` - 거래 결정 저장

<a id="src-docs-ui-audit-20261024-md--13-네비게이션-구조-ledger_designpy_nav_html"></a>
##### 1.3 네비게이션 구조 (`ledger_design.py:_nav_html`)
Owner 메뉴에 다음 항목들이 있음:
- 여행 장부 (`/board`)
- 지출 정리 (`/import`)
- OTA 내역 (`/ota`)
- 영수증 처리 (`/receipts`) - 조건부
- 관리 섹션: 여행 관리, 예약 명단·여행 연결, 항공권 참가자 연결, 계정·권한 관리

**누락: "카드 전체 내역" 메뉴 항목**

<a id="src-docs-ui-audit-20261024-md--2-카드-원행-저장소-및-조회-계약"></a>
#### 2. 카드 원행 저장소 및 조회 계약

<a id="src-docs-ui-audit-20261024-md--21-핵심-테이블-transactions"></a>
##### 2.1 핵심 테이블: `transactions`
| 필드 | 타입 | 설명 |
|------|------|------|
| `transaction_id` | TEXT | 안정적 고유 ID (PK) |
| `batch_id` | TEXT | 업로드 배치 ID |
| `approval_date` | TEXT | 승인일 (YYYY-MM-DD) |
| `posting_date` | TEXT | 매입일 (YYYY-MM-DD) |
| `issuer` | TEXT | 카드사 |
| `card_tail` | TEXT | 카드 끝자리 |
| `transaction_direction` | TEXT | purchase/cancellation/refund |
| `transaction_kind` | TEXT | 국내/해외 등 |
| `merchant` | TEXT | 가맹점 원본명 |
| `amount_krw` | INTEGER | 원화 금액 (부호 포함) |
| `foreign_amount` | REAL | 외화 금액 |
| `foreign_currency` | TEXT | 통화 코드 |
| `item` | TEXT | 분류 항목 |
| `description` | TEXT | 상세 내용 |
| `classification_state` | TEXT | needs_review/booked/preserved |
| `decided` | INTEGER | 사용자 직접 분류 여부 |
| `duplicate_of` | TEXT | 중복 원본 ID |
| `conflict_reason` | TEXT | 충돌 사유 |
| `parse_error` | TEXT | 파싱 오류 |
| `display_tab_id` | TEXT | 배정된 여행 tab_id |
| `classification_source` | TEXT | 분류 출처 |

<a id="src-docs-ui-audit-20261024-md--22-이용일-계산-규칙-기존-계약-준수"></a>
##### 2.2 이용일 계산 규칙 (기존 계약 준수)
- `TRADE_DATE = COALESCE(NULLIF(t.approval_date,''), t.posting_date)`
- 이용일 없으면 승인일, 승인일 없으면 매입일
- `card_pipeline.md` 및 `business_rules.md` 규칙 따름

<a id="src-docs-ui-audit-20261024-md--23-여행-배정-권위-순서-기존-계약"></a>
##### 2.3 여행 배정 권위 순서 (기존 계약)
1. 사용자 확정 배정 (`display_tab_id` + `decided=1`)
2. 자동/근거 배정 (`classification_source` = inference, guide_airfare_evidence 등)
3. 미배정

<a id="src-docs-ui-audit-20261024-md--24-기존-상세-링크-경로-card_actionspynext_action"></a>
##### 2.4 기존 상세 링크 경로 (`card_actions.py:next_action`)
- 반환값: `{'label': str, 'href': str, 'reason': str, 'group': str}`
- href 예: `/import?batch=<batch_id>&transaction=<transaction_id>`
- 기존 권한/CSRF/revision 보호 그대로 사용

<a id="src-docs-ui-audit-20261024-md--3-현재-cssjs-구조"></a>
#### 3. 현재 CSS/JS 구조

<a id="src-docs-ui-audit-20261024-md--31-디자인-토큰-ledger_designpystyle---root"></a>
##### 3.1 디자인 토큰 (`ledger_design.py:STYLE` - `:root`)
```css
:root {
  --bg:#F7F9FC; --paper:#FFFFFF; --ink:#182230; --mut:#667085; --line:#E4E7EC;
  --line2:#F2F4F7; --line-strong:#D0D5DD; --hover:#F8FAFC; --focus:#2266F5;
  --sel:#ECF5EF; --grn:#1C7A52; --grn-dk:#166444; --grn-lt:#F1F7F3;
  --warn:#B54708; --neg:#B42318; --bad:#B42318;
}
```
- **다크 모드 미지원** (`@media (prefers-color-scheme: dark)` 없음)
- 라이트 테마만 하드코딩됨
- Pretendard Variable 폰트 사용

<a id="src-docs-ui-audit-20261024-md--32-공통-컴포넌트-스타일"></a>
##### 3.2 공통 컴포넌트 스타일
- 테이블, 폼, 버튼, 배지, 모달, 패널, 네비게이션
- 인라인 스타일 일부 존재 (하드코딩된 색상)
- 반응형: 759px 브레이크포인트 기준 모바일 대응

<a id="src-docs-ui-audit-20261024-md--33-자바스크립트"></a>
##### 3.3 자바스크립트
- `ledger_design.py` 내 임베디드 스크립트 (네비게이션, 라이브 동기화, 스티키 바 등)
- `card_catalog.py` 내 필터 팝오버 스크립트
- `card_flow.py` 내 대량의 인라인 JS (검토 UI, 규칙 편집, 구글 복사 등)

<a id="src-docs-ui-audit-20261024-md--4-카드-전체-내역-현재-구현-card_catalogpy"></a>
#### 4. 카드 전체 내역 현재 구현 (`card_catalog.py`)

<a id="src-docs-ui-audit-20261024-md--41-현재-기능"></a>
##### 4.1 현재 기능
- 검색 (가맹점, 분류, 설명, 승인번호, 여행)
- 필터: 카드, 상태, 월, 정렬 (오름차순/내림차순)
- 페이지네이션 (50건/페이지)
- 테이블 컬럼: 거래일, 카드, 지급처, 구분, 원본 금액, 분류, 여행, 상태, 다음 행동
- 읽기 전용 (DB 변경 없음)

<a id="src-docs-ui-audit-20261024-md--42-설계-명세와의-차이-pr-101-23"></a>
##### 4.2 설계 명세와의 차이 (PR #101 §2~§3)
| 요구사항 | 현재 상태 | 차이 |
|----------|-----------|------|
| 메뉴명 "카드 전체 내역" | "전체 카드 거래 검색" | 메뉴 항목 없음, 페이지 제목 다름 |
| 연도 선택 (기본 2026) | 월 필터만 있음 | 연도 선택 UI 없음 |
| 4×3 월 그리드 + 건수 | 월 드롭다운만 | 그리드 UI 없음 |
| 월 단일 선택/접기 | 항상 전체 목록 표시 | 확장/접기 기능 없음 |
| 4열: 이용일시, 가맹점명, 금액, 배정 여행 | 9열 테이블 | 컬럼 구조 다름 |
| 날짜별 소제목 그룹핑 | 없음 | 그룹핑 없음 |
| 시간 없는 거래 뒤 배치 | 정렬만 처리 | 표시 로직 없음 |
| 날짜 없는 원행 별도 섹션 | 제외됨 (WHERE 절) | 별도 섹션 필요 |
| 모바일 카드형 레이아웃 | 테이블 → 그리드 변환 | 카드형 미구현 |
| 시스템 다크 모드 자동 적용 | 미지원 | CSS 변수만 라이트 |

<a id="src-docs-ui-audit-20261024-md--5-하위-페이지-ui-일관성-현황"></a>
#### 5. 하위 페이지 UI 일관성 현황

<a id="src-docs-ui-audit-20261024-md--51-감사-대상-페이지-우선순위"></a>
##### 5.1 감사 대상 페이지 (우선순위)
| 페이지 | URL | 공통 레이아웃 | 하드코딩 색상 | 모바일 | 다크모드 | 우선순위 |
|--------|-----|--------------|---------------|--------|----------|----------|
| 지출 정리 | `/import` | 일부 | 다수 | 부분 | 없음 | P0 |
| 여행 장부 | `/board` | 예 | 일부 | 예 | 없음 | P0 |
| OTA 내역 | `/ota` | 별도 | 다수 | 부분 | 없음 | P1 |
| 영수증 처리 | `/receipts` | 별도 | 다수 | 부분 | 없음 | P1 |
| 항공권 참가자 | `/flight-passengers` | 별도 | 일부 | 부분 | 없음 | P1 |
| 여행 관리 | `/trips` | 별도 | 일부 | 부분 | 없음 | P2 |
| 예약 연결 | `/reserve-links` | 별도 | 일부 | 부분 | 없음 | P2 |

<a id="src-docs-ui-audit-20261024-md--52-주요-불일치-사항"></a>
##### 5.2 주요 불일치 사항
- 각 페이지별 독립적인 CSS/스타일
- 색상 변수 미사용 (하드코딩된 hex 값 다수)
- 네비게이션 구조 불일치 (일부 페이지는 site_shell 사용, 일부는 독자적)
- 테이블/폼/버튼 스타일 각기 다름

<a id="src-docs-ui-audit-20261024-md--6-테스트-현황"></a>
#### 6. 테스트 현황

<a id="src-docs-ui-audit-20261024-md--61-기존-테스트-webappteststest_card_catalogpy"></a>
##### 6.1 기존 테스트 (`webapp/tests/test_card_catalog.py`)
- `test_catalog_reads_every_batch_without_writing_or_hiding_refunds`
- `test_search_filters_and_pagination_preserve_zero_and_original_amount`
- `test_all_pages_are_reachable_without_repeating_transactions`
- `test_date_sort_month_filter_and_links_are_read_only`

<a id="src-docs-ui-audit-20261024-md--62-설계-명세-요구-테스트-51"></a>
##### 6.2 설계 명세 요구 테스트 (§5.1)
현재 미구현:
1. 초기 진입: 2026년, 월 12개, 모두 접힘, 선택 없음
2. 월 그리드: 4×3 데스크톱, 모바일 2~3열
3. 연도 변경 시 선택 월 해제
4. 월 건수: 전체 원행 기준 (중복 출처 제외)
5. 정렬: 이용일시 오름차순, 시간 없음 맨 뒤
6. 표시: 원본 금액 부호/통화, 시간 없음, 가맹점 미상, 미배정, 취소/환불
6. 날짜별 소제목, 0건 월 빈 상태
7. 행 클릭 → 기존 상세 경로
8. 권한: 비인증 차단, CSRF 보호
9. 페이지네이션: 100건 초과 월 전체 조회
10. 날짜 없는 원행 별도 섹션
11. XSS 방어, 파라미터 검증

<a id="src-docs-ui-audit-20261024-md--7-기술적-위험-및-미확정-사항"></a>
#### 7. 기술적 위험 및 미확정 사항

<a id="src-docs-ui-audit-20261024-md--71-데이터-관련"></a>
##### 7.1 데이터 관련
- 이용시간(`approval_time` 등) 컬럼 존재 여부 확인 필요 → 현재 스키마에 시간 컬럼 없음
- 시간 없는 거래를 같은 날짜 맨 뒤에 배치하려면 정렬 키 필요
- 날짜 없는 원행(`approval_date`/`posting_date` 모두 NULL) 처리: 현재 WHERE 절에서 제외됨

<a id="src-docs-ui-audit-20261024-md--72-라우팅"></a>
##### 7.2 라우팅
- 새 URL 경로: `/cards/all` 권장 (기존 `/import?scope=all`과 충돌 없음)
- 기존 라우터(`ledger_board.py:do_GET`)에 새 경로 추가 필요

<a id="src-docs-ui-audit-20261024-md--73-디자인-시스템-적용-범위"></a>
##### 7.3 디자인 시스템 적용 범위
- 기존 `ledger_design.py:STYLE`을 확장해 다크 모드 지원
- `card_catalog.py:CATALOG_STYLE`도 디자인 토큰 사용하도록 리팩토링
- 점진적 적용: PR-1(토큰/다크모드) → PR-2(카드 전체 내역) → PR-3+(하위 페이지)

<a id="src-docs-ui-audit-20261024-md--8-다음-단계-작업-계획"></a>
#### 8. 다음 단계 작업 계획

<a id="src-docs-ui-audit-20261024-md--pr-0-ui-감사-완료-본-문서-"></a>
##### PR-0: UI 감사 완료 (본 문서) ✓
<a id="src-docs-ui-audit-20261024-md--pr-1-공통-디자인-토큰--다크-모드"></a>
##### PR-1: 공통 디자인 토큰 + 다크 모드
- `ledger_design.py:STYLE`에 `@media (prefers-color-scheme: dark)` 추가
- 다크 테마 토큰 정의 (명세 §4.2 표 B안 기준)
- FOUC 방지: 인라인 초기 스크립트 또는 CSS 미디어 쿼리만으로 처리

<a id="src-docs-ui-audit-20261024-md--pr-2-카드-전체-내역-신규-페이지"></a>
##### PR-2: 카드 전체 내역 신규 페이지
- 새 라우트 `/cards/all` 추가 (`ledger_board.py`)
- 네비게이션에 "카드 전체 내역" 추가 (`_nav_html`)
- 연도 선택 + 4×3 월 그리드 렌더러 구현
- 월별 상세 조회 API (기존 `card_catalog.catalog` 재사용/확장)
- 클라이언트 사이드 월 선택/접기 로직
- 거래 목록: 4열 + 날짜 그룹핑 + 상세 링크
- 날짜 없는 원행 별도 섹션
- 모바일 반응형 (카드형 레이아웃)
- 합성 테스트 추가

<a id="src-docs-ui-audit-20261024-md--pr-3-하위-페이지-순차-개선"></a>
##### PR-3+: 하위 페이지 순차 개선
- UI 감사표 P0/P1 순서로 개별 PR
- 각 페이지: 디자인 토큰 적용 → 모바일/다크모드 검증 → 기존 기능 회귀 테스트

---

*작성일: 2026-10-24*
*기준 커밋: main `b6e1ff7`*

---

<a id="src-webapp-design-review-md"></a>

## DESIGN_REVIEW

통합 전 경로: `webapp/DESIGN_REVIEW.md`

<a id="src-webapp-design-review-md--장부-화면-검토"></a>
### 장부 화면 검토

<a id="src-webapp-design-review-md--현재-화면과-검증-상태"></a>
#### 현재 화면과 검증 상태

2026-10-08 기준이다. 여행 목록의 금액은 수입 합계임을 표시하고 미기록 카드 거래와 구분한다. 홈·카드 미리보기의 ready는 같은 고유 거래 기준을 사용한다. 장부에는 734건이 기록됐고 여행 탭과 분류대기 장부를 구분한다. 최신 운영 데이터의 렌더러 검증과 실제 로그인 브라우저 검증은 별개다.

과거 화면 변경의 전체 회귀 숫자와 당시 장부 0건은 아래 날짜별 실행 기록이다. 현재 코드 검증 결과와 남은 테스트 문제는 [운영 문서](../operations.md)를 따른다. 과거 링크·캡처는 당시 비교 근거로만 유지한다.

<a id="src-webapp-design-review-md--과거-화면-작업-기록"></a>
#### 과거 화면 작업 기록


2026-10-05 기준으로 문서보다 실제 실행 코드와 브라우저 검증을 우선한다.

<a id="src-webapp-design-review-md--제품-흐름과-유지할-기능"></a>
#### 제품 흐름과 유지할 기능

card_flow.py는 카드 업로드, 기존 규칙 분류, 질문 답변, 규칙 재사용, 장부 미리보기와 기록을 담당한다. ledger_design.py는 기록된 장부의 여행별 거래 목록과 상세 편집을 렌더링한다. ledger_board.py가 기존 저장 API, 수입 입력, 은행 파일 가져오기, 입금 배분과 XLSX 출력을 연결한다. ledger_store.py의 저장 계약과 데이터 모델은 디자인 작업에서 변경하지 않는다.

거래 원문 보호, 사용자 확정 보호, revision 충돌 검사, 요청 중복 방지, 취소·환불 부호, 수입 배분 합계와 실시간 수정 보호를 유지한다. 장부 기록 전 카드 자료와 실제 장부 행은 서로 다른 단계이므로 저장된 카드 자료를 이미 장부에 기록된 거래라고 표시하지 않는다.

<a id="src-webapp-design-review-md--개선-기준"></a>
#### 개선 기준

- PC에서는 여행 목록, 검색·필터, 거래 테이블과 우측 편집 패널을 유지한다.
- 거래처·내용과 분류를 먼저 읽고, 금액은 오른쪽에 일정한 숫자 폭으로 표시한다.
- 원본 식별자와 처리 버전은 필요한 경우에만 펼쳐 본다.
- 거래 전환과 닫기는 미저장 입력 및 저장 중인 요청을 보호한다.
- 모바일은 거래 요약 목록을 사용하고, 편집 본문이 길어져도 저장 버튼에 접근할 수 있어야 한다.
- 실제 저장 상태에서 확인할 수 없는 완료 상태나 새로운 영속 상태를 만들지 않는다.
- 프레임워크, 의존성과 데이터 모델을 유지하며 기존 HTML, CSS와 작은 자바스크립트 변경으로 구현한다.

<a id="src-webapp-design-review-md--참고한-제품-자료"></a>
#### 참고한 제품 자료

[Ramp의 거래 검색·필터](https://support.ramp.com/expenses-transactions-and-reimbursements-filters/)에서 테이블 중심 업무 화면을 참고했다. [QuickBooks의 거래 검토](https://quickbooks.intuit.com/learn-support/en-us/help-article/banking/categorize-match-online-bank-transactions-online/L1bTafTz3_US_en_US)는 원본 거래의 분류·대조 후 기록이라는 업무 단계의 기준이다. [Zoho Books의 검색](https://www.zoho.com/au/books/kb/banking/advanced-search.html)과 [Odoo의 대사](https://www.odoo.com/documentation/master/applications/finance/accounting/bank/reconciliation.html)는 상태별 탐색과 필요한 상세정보만 펼치는 방식의 참고 자료다.

<a id="src-webapp-design-review-md--검증"></a>
#### 검증

변경 전 관련 검사 66개와 하위 검증 3개가 통과했다. 통합 뒤 기존 장부 화면 검사 52개와 하위 검증 4개, 새 PC·모바일 검사 21개, 카드 화면 검사 12개를 확인했다. 데이터 저장·수입·입금 배분·실시간 갱신·카드 파이프라인 검사 234개와 하위 검증 3개도 통과했다. 통신 실패 후 입력 보존, 현재 필터에 맞는 이전·다음 거래, 고정 원문 보호, 수입 날짜·금액 수정, 저장 버전과 요청 ID 갱신을 실제 브라우저로 검사했다.

전체 검사를 함께 실행하면서 카드 브라우저 테스트가 닫힌 임시 저장소를 전역 연결에 남기는 문제를 발견했다. 각 테스트 종료 때 연결을 해제하도록 보완한 뒤 카드 브라우저와 분류 규칙 검사 107개가 함께 통과했다.

전체 웹 검사는 778개와 하위 검증 67개 통과 후 서버 시작 테스트 3개 실패에서 중단됐다. `test_local_host_startup.py`의 예약 설정 파일 접근 검사, 프로세스 종료 호출 개수 검사, 모의 명령 목록 검사가 기존 `start_web_ledger_host.ps1`과 일치하지 않았다. 화면 변경 전 사본에서도 같은 3개 실패를 재현했다. 재시작 요청 파일 검사와 추가 프로세스 종료 경로, `Sort-Object`가 기존 테스트 가정에 반영되지 않은 문제이며 이번 작업에서는 운영 시작 스크립트나 해당 테스트 기대값을 변경하지 않았다. 전체 검사 통과로 보고하지 않는다.

1440×900, 1920×1080, 390×844에서 합성 자료로 실제 브라우저 화면을 캡처하고 직접 확인했다. 모두 가로 넘침이 없었고 편집 패널의 저장 버튼이 화면 안에 있었다. 카드 질문 25개 중 한 페이지 20개를 유지하며 첫 질문만 펼쳐 표시했고, 접힌 질문도 펼쳐 수정할 수 있었다. 이미지와 측정 결과는 `C:/AX/cost-ui-work/20261005/visual`에 보존했다.

<a id="src-webapp-design-review-md--운영-반영"></a>
#### 운영 반영

2026-10-05 운영 복구 사본과 별도 복원 검증을 마친 뒤 기존 서버 재시작 절차로 반영했다. 마지막 화면 정리까지 반영한 복구 사본은 `D:/WebLedgerHost/data/backups/operational-20261005T045848742545Z`다. 모든 DB 테이블과 열·원행, 원본 파일 해시와 복원된 입력 연결이 일치했다. 로컬 상태·준비 응답과 공개 서버 상태 응답은 모두 200이었다.

운영 계정으로 실제 로그인해 홈·카드 검토·장부 이동과 새 거래 열을 확인했다. 카드 질문은 20개 중 1개만 펼쳐 표시됐다. 운영 브라우저 화면 캡처도 직접 확인했다. 운영 브라우저에서 화면 폭 변경은 지원되지 않아 390px 검증은 합성 자료를 사용한 실제 Playwright 브라우저에서 수행했다. 운영 거래의 저장·배정·전기는 이번 화면 검증에서 실행하지 않았다. 기존 카드 자료 1,676건과 장부 기록 0건을 유지했다.

<a id="src-webapp-design-review-md--2026-10-05-모바일-기능-공백과-화면-경계-검증"></a>
#### 2026-10-05 모바일 기능 공백과 화면 경계 검증

최초 화면 경계 검증은 `60314292fb13e4c657249912995a90cf435f0089` 기준의 깨끗한 작업 사본에서 시작했다. 이후 baseline test debt를 정리한 `58205e1132c4db1cfc0a0d92bfc3c60f56c39906`을 최신 main 기준으로 삼아 검증된 UI diff를 다시 적용하고 재검증했다. 이번 통합은 소스 코드와 합성 HTTP 서버만 대상으로 했으며 운영 배포, 운영 재시작과 운영 거래 변경은 수행하지 않았다.

실제 Chromium에서 모바일 폭 375·390·391·430·759의 `.tw`가 숨겨지고 `.lst`가 표시될 때 수기 지출 링크가 보이지 않았다. 모바일 지출 헤더에 기존 `.btn`과 `/expense/new`를 사용하는 링크를 추가했다. 지출이 없거나 검색 결과가 비어 있어도 해당 화면에 진입한다. 새 저장 로직이나 API는 추가하지 않았다.

긴 수입 편집 패널을 실제 열었을 때 1100×900과 1440×900에서 footer 하단이 938.03px로 화면 아래에 있었다. 원본 정보를 펼치면 본문 대신 문서가 길어졌다. `#panel-slot{display:flex;min-height:0}` 한 줄로 패널 높이를 전달했다. 수정 후 footer 하단은 900px이고, 필요한 경우 패널 본문이 스크롤한다. 1920×1080의 footer 하단은 1080px다.

저장 POST를 실제 중단하면 입력은 보존됐지만 `data-saving="1"`이 남아 다음 거래 이동이 계속 차단됐다. 실패 catch에서 진행 표시를 제거하는 한 줄을 추가했다. 수정 후 미저장 이동 확인에 접근할 수 있고, 거절 시 입력·현재 행·저장소 revision을 보존하며 재시도 저장도 성공했다.

<a id="src-webapp-design-review-md--실제-화면-크기별-결과"></a>
##### 실제 화면 크기별 결과

Playwright Chromium `141.0.7390.37`에서 글꼴 로드 후 검사했다. 각 크기에서 여행 nav, 수입·지출, 금액 잘림, 검색·필터, 수기 지출 진입을 확인했다. 편집 패널의 위치·본문 스크롤·저장·취소·이전·다음·위치 표시·버튼 겹침과 footer 넘침도 확인했다.

| 화면 크기 | 장부 가로 넘침 | 편집 가로 넘침 | 기능 흐름 |
| --- | ---: | ---: | --- |
| 375×844 | 0px | 0px | 정상 |
| 390×844 | 0px | 0px | 정상 |
| 391×844 | 0px | 0px | 정상 |
| 430×900 | 0px | 0px | 정상 |
| 759×900 | 0px | 0px | 정상 |
| 760×900 | 0px | 0px | 정상 |
| 1099×900 | 0px | 0px | 정상 |
| 1100×900 | 0px | 0px | 정상 |
| 1440×900 | 0px | 0px | 정상 |
| 1920×1080 | 0px | 0px | 정상 |

각 크기에서 검색, 거래 선택·수정·저장, 다음·이전, 미저장 이동 거절, 실제 통신 실패와 입력 보존·재시도, 미배정 거래의 여행 선택·이동을 수행했다. 패널 행·선택 행·주소·위치 표시가 일치했다. 신규 검사는 기존 unittest helper와 parameterized subTest를 재사용한다. 선택 행이 반영되기 전에 읽는 검사 실패를 확인하여 실제 선택 상태를 기다리도록 테스트만 보완했다. 임의 sleep이나 assert 완화는 추가하지 않았다.

391·430·759px의 Ctrl·Enter·Esc 힌트를 텍스트 Range와 각 `.kbd`의 실제 범위로 측정했다. 모두 버튼 안에 들어오며 겹침과 가로 잘림은 없었다. 따라서 단축키 표시, 버튼 간격·색·크기와 모바일 CSS는 변경하지 않았다. 375·390px의 기존 힌트 숨김 조건과 실제 단축키 동작도 유지했다.

<a id="src-webapp-design-review-md--회귀-검사와-동결-판단"></a>
##### 회귀 검사와 동결 판단

최종 관련 UI 검사 118개와 하위 검증 11개, 저장소·수입·카드 파이프라인 검사 225개와 하위 검증 3개가 통과했다. 열 가지 화면 크기의 신규 검사 1개와 하위 검증 2032개가 통과했다. 카드 검토는 25건 중 20건·5건 페이지 이동, 이전 페이지 복귀, 첫 질문만 펼침, 접힌 질문 펼침과 접었다 다시 펼칠 때 입력 보존을 실제 브라우저로 확인했다.

UI 안정화 당시 별도로 남아 있던 baseline 회귀 실패 8개는 이후 `58205e1132c4db1cfc0a0d92bfc3c60f56c39906`에서 test debt와 harness 문제로 정리됐다. 해당 최신 main 위에 UI diff를 통합한 뒤 장부·카드 브라우저 관련 집중 검사는 28개와 하위 검증 2039개가 통과했다. 현재 활성 pytest 수집은 2145개이며, 전체 회귀는 2141개 통과·4개 건너뜀·실패 0개와 하위 검증 2330개 통과로 끝났다. 기본 Windows pytest 임시 폴더의 접근 권한 문제를 피하기 위해 작업 전용 `--basetemp`를 사용했다.

UI 1차 안정화 완료 — 동결. 모바일 수기 지출 진입, 편집 footer 접근, 저장 통신 실패 뒤 입력 보존과 상태 해제, 열 가지 화면 크기의 가로 넘침 0px, 검색·필터·이전·다음·미저장 보호·여행 이동과 카드 검토 회귀를 모두 확인했다. 추가 UI 변경은 실제 장부 사용 데이터와 사용자 피드백에서 구체적인 문제가 확인될 때만 수행하며, 미확인 문제를 예상해 기능이나 화면을 추가하지 않는다.

코드와 합성 자료만 담은 별도 사본에서 작업하고 경계 검사와 모바일 브라우저 검사를 수행했다. 제품 diff와 합성 검사 결과를 검토했다.

직접 실행 증거는 `C:/AX/cost-ui-work/20261005-stabilize/`에 보존했다. `baseline-geometry.json`은 변경 전 모바일 링크 부재와 힌트 측정이며, `final-geometry-confirmed/results.json`은 통합 코드의 열 가지 화면 크기 결과다. `visual/`에는 합성 화면 캡처가 있다.

최종 실행 결과는 `final-related-ui.log`, `store-card-corrected.log`, `final-breakpoints-confirmed.log`, `final-full-regression.log`에 보존했다. 기존 시작 실패는 `baseline-startup.log`, 변경 전 넓은 검사 결과는 `full-web-baseline.log`, 추가 실패의 개별 재현은 `extra-baseline-isolated.log`로 대조할 수 있다. sqlite 연결 ResourceWarning도 출력됐으며 원인 조사는 이번 범위에서 수행하지 않았다.

<a id="src-webapp-design-review-md--2026-10-06-secondhome-시각-체계-비교"></a>
#### 2026-10-06 Secondhome 시각 체계 비교

실제 Chromium에서 Secondhome 공개 화면과 cost를 같은 크기로 확인했다. 비교 이미지는 `.local-archive/ui-reference-20261006/`의 `reference-desktop.png`, `reference-mobile.png`, `cost-before-desktop.png`, `cost-before-mobile.png`, `cost-after-desktop.png`, `cost-after-mobile.png`, `cost-after-desktop-panel.png`, `cost-after-mobile-panel.png`에 보존했다. 데스크톱은 1440×900, 모바일은 390×844 기준이다. Secondhome은 공개 상태에서 로그인 화면까지만 직접 확인할 수 있었으므로 그 화면에서 확인 가능한 시각 체계와 반응형 표현만 참고했다.

비교 뒤 다음처럼 범위를 정했다.

- 그대로 유지: 232px sidebar, 36px 거래 행, 400px 상세 panel, 데스크톱 table과 모바일 list 전환, green 선택 의미, tabular amount, sticky header, 기존 keyboard와 저장 보호 동작.
- 가져올 것: 차가운 neutral 배경과 surface 계층, 더 또렷한 border 단계, title/body/muted 글자 위계, 6~8px control radius, blue focus ring, 차분한 hover, badge와 detail panel 간격, mobile header와 action 정리.
- cost에 맞지 않아 버릴 것: HR card 구조, dashboard, KPI, chart, 기능 card, 과한 radius와 card 분할, gradient, 의미 없는 animation, HR 도메인 요소.

구현은 `ledger_design.py`의 기존 HTML 구조와 동작을 유지한 CSS 중심 시각 조정이다. 업무 순서, 장부 정보 구조, API, DB, 분류 규칙, 저장 계약, 장부 column은 바꾸지 않았다. selected 상태의 green 의미는 유지하고, focus 표현만 blue 계열로 통일했다. input, select, button, badge, source box와 detail panel의 radius와 border, spacing, typography를 같은 계열로 정리했다.

관련 회귀 검사는 61개와 하위 검증 2039개가 통과했다. 실제 Chromium 측정에서도 1440×900과 390×844 모두 문서와 body의 가로 넘침이 0px였다. 데스크톱 상세 panel은 400px 폭을 유지했고 footer 하단은 900px, 모바일 footer 하단은 844px로 저장 action에 접근할 수 있었다.

전체 회귀 결과는 `2198 passed, 4 skipped, 1 failed, 2355 subtests passed`다. 실패한 `test_serve_actually_binds_the_address_it_is_given`은 저장소 루트의 `webledger.work.sqlite`가 생기지 않아야 한다는 검사다. 이번 UI 변경 파일과 무관한지 확인하기 위해 현재 `HEAD`의 깨끗한 임시 worktree에서도 이 검사만 다시 실행했고 동일하게 실패했다. 따라서 전체 회귀를 전부 통과했다고 기록하지 않는다. 이번 범위에서는 `ledger_board.py`, 호스팅 동작, DB 생성 동작과 해당 테스트를 변경하지 않았다.
