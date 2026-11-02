# COST 능동 감사·자율 QA 실행 기록 (2026-11-02)

## 2026-11-02 운영 반영 후 상태

PR30 분석은 완료했다. 발견 결함 수정과 영향 기반 QA는 [PR #513](https://github.com/6Soo/cost/pull/513), 다중 업로드·대기열 회귀의 영향 매핑은 [PR #514](https://github.com/6Soo/cost/pull/514)로 병합하여 운영 `20da556e174c66570a856324c770e05ad422aa69`에 반영했다. #513의 PR 검사 825/86 subtests와 감사 704/86 subtests, #514 영향 검사 280/30 subtests는 통과했다. 보호 13표 전후 불변 및 health/ready·보호 API 확인 근거는 [운영 기록](../operations.md)에 있다.

전체 서비스 능동 감사는 **PARTIAL**이다. 합성 업로드·복사·검색 복귀·여행 충돌·실제 Windows OCR 및 일부 화면 수락은 확인했으나 모든 승인 업무의 end-to-end 최신 수락을 주장하지 않는다. 배포 후 기존 ego TaskSpace 21을 찾지 못해 인증된 운영 영향 화면 수락이 남았다. 상세 미결과 재개 지점은 [현재 상태](../session_handoff.md), 기존 수락 근거 대조는 `.local-archive/autonomous-qa-20261102/final-acceptance-review-v103.md`를 따른다. 아래의 과거 진행 상태와 CI 수치는 실행 이력이다.

현재 승인: 최근 PR **30개**의 실제 코드·원인·테스트·후속 수정을 분석하고, 운영 서비스의 업무 완료 가능성을 감사하며, 발견한 문제와 재발 방지 자동 검증을 구현·테스트·PR·배포한다. 분석 보고서만으로 종료하지 않는다. 구현은 다수의 **GPT-6 Luna medium**에 위임하고 주 에이전트는 감사·우선순위·통합·독립 검증을 맡는다.

선행 요청인 임시 workspace/branch/작업사본 정리는 완료했다. 기본 사본을 `ae85fd10` main으로 동기화하고 임시 worktree 5개와 병합/동등 패치 브랜치를 제거했다. 미추적 242파일·과거 문서·검증자료·복구 bundle을 `.local-archive/workspace-cleanup-20261102/`에 보존하고 원래 stash 3개를 유지했다. PR477은 표적4건/ego8조건 후 병합했고 최종 코드 배포에 포함한다. PR484는 제안·미구현 문서로 병합했으며 해당 과거 제안을 새 제품 정책으로 실행하지 않는다.

## 범위·상태

| 요구사항 | 상태 | 완료 근거/남은 일 |
|---|---|---|
| 선행 정리 | COMPLETE | cleanup checkpoint·root review·bundle 검증, 단일 root/main·clean 확인 |
| 최근30 PR 실제 분석 | COMPLETE | 생성순 #512~#483의 실제 diff·검사 빈틈·후속 관계 30행 분석 완료. 당시 수동 검사 실행률과 사용자 지적 감소율은 자료 부족으로 미측정 |
| 전체 서비스 능동 감사 | IN_PROGRESS | 아래 업무 목록의 운영 읽기·합성 저장/오류/권한/복귀 흐름 확인 |
| 자율 발견 문제 수정 | PENDING | 재현→Luna 위임→표적/인접 보호 검사→독립 수락 |
| 향후 PR 자동 QA | IN_PROGRESS | 영향 범위별 테스트와 합성 브라우저·실패 증거, 기존 테스트/CI 재사용 |
| PR·배포·최종 지표 | PENDING | 실제 CI, 고정SHA배포·health/ready·금융보호·영향 업무 수락·결과 기록 |

## 보호 경계

원본·금액·ID·수동 교정·중복·OTA exact/manual·환불·권한·CSRF·원자성을 유지한다. Google Sheets 최종 장부 쓰기는 금지한다. 운영 감사는 읽기 전용이며 실제 저장·오류·중복 제출·권한 시나리오는 격리 합성 자료에서 수행한다. 실제 고객 원문/스크린샷은 Git·외부 모델에 보내지 않는다. 신규 제품 정책·비가역 데이터 변경은 별도 판단이 필요하다. 같은 source/DB/배포의 작성자는 하나이며, 병렬 작업은 파일 소유권으로 분리한다.

## 업무 감사 목록

홈→여행 장부, 카드 업로드→진행/새로고침→분류·검토→장부/복사, 카드 전체 검색→원본 상세→필터 복귀, 예약(OTA)→결제/환불 근거→여행, 수입→보험/참가 명단 연결, 영수증/수기 입력→교정/복사→원래 여행, 여행 메타 교정→충돌/입력 보존, 항공권 이름 조회→여행/근거 복귀, 규칙 제안→미리보기/적용, XLSX 출력→실제 산출물, owner/viewer·CSRF·원본 접근 거부, 작은 화면/키보드/테마·비동기 상태를 확인한다. 접근 차단·외부 비용/자료 의존은 구체적으로 기록하며 캡처만으로 업무 완료를 선언하지 않는다.

## 측정 기준

PR별 검증 실행률(필수 시나리오 실제 실행/선택), 배포 전 자율 발견 결함 수·원인별 재발 수, 배포 후 사용자 최초 발견 결함/기능PR 10개, 동일 원인 후속 수정 PR 비율, 업무 완료율·클릭/재입력 횟수·p50/p95 시간, 보호 실패·누락/중복 건수, flaky/skip/0-test 비율을 구분한다. 과거 PR30을 기준선으로 삼고 향후 실측 전 사용자 지적 감소율을 창작하지 않는다.

## 현재 진행 근거

로컬 `.local-archive/autonomous-qa-20261102/`에 원 PR 메타데이터·diff, 분석, 운영/합성 브라우저 캡처와 실행 근거를 보존한다. 운영 원문이 포함된 자료는 Git에서 제외한다. 문서의 IN_PROGRESS/PENDING을 실제 구현·검증·배포 근거가 생긴 뒤에만 완료로 바꾼다.

## 최근 PR30 분석 결과

분석 대상은 생성순 #512~#483으로 고정했다. 실제 변경 파일 기준 코드 PR16개와 문서 PR14개(제안 명세 포함)이며, PR 메타데이터의 check 기록은 **30개 모두 0건**이었다. 로컬 검사·기존 수동 브라우저 수락이 없었다는 뜻은 아니다. 그 검사가 PR마다 자동 실행·공유·강제되지 않았다는 뜻이다. 문서 수락 PR을 별도 기능 결함이나 중복 테스트로 합산하지 않았다.

공통 원인은 다음과 같다.

- 전역 UI 변경의 영향이 한 화면 테스트로 축소됐다. #493 장식 도입 이후 #495 복합 컨트롤, #497 보험 행, #503 자체 디자인 보존의 후속 보정이 이어졌다. 유발 PR과 후속 수정·문서 PR을 구분해야 한다.
- 완료·근거·금융 처리·실제 환급이 화면별 문자열/오래된 완료 표식과 결합됐다. #489는 영속 분류와 유효 여행으로 목록·건수·필터 조건을 함께 고쳤다. #491은 무관한 UI 변경까지 섞였던 범위를 복구했다.
- 테스트가 HTML 존재·상태코드·0건 이상만 검증하면 업무 미완료도 통과한다. 이번 독립 검토에서도 초기 여정 테스트가 기록 0건과 빈 XLSX를 허용하는 것을 발견해, 실제 양성 완료·정확한 기록 수·워크북 내용 검증을 요구했다.
- 오류·재시작·중복 제출·동적 DOM·브라우저 history 같은 시간에 따른 변화가 부족했다. #494 비동기화 뒤에도 완료된 동일 파일의 새 worker 실행이 남아 있었으며 이번 합성 여정에서 재현됐다. #504의 정확 문자열 HTML 조립과 필수 DOM 무조건 참조도 변형 입력에서 재현됐다.
- 성능 검증이 일부 핵심 경로에만 있었다. #498/#507 최적화 뒤에도 출력 페이지는 행별 충돌 조회 때문에 운영 읽기 전용 프로파일 24.4초가 걸렸다. 기존 일괄 충돌 조회를 같은 요청에 재사용해 해결했다.
- 기준에서도 재현되는 실패는 이번 변경 회귀가 아니라는 증거일 뿐, 현재 업무 수락을 대신하지 않는다. 실행한 검사, 빠진 시나리오, 외부 자료 의존, 실제 수락을 따로 기록하고 필수 시나리오의 skip/0건 실행을 성공으로 바꾸지 않아야 한다.

다음 표는 각 PR의 실제 diff·현재 코드·관련 테스트·후속 관계를 읽은 결과다. 기존 PR이 보고한 검사 수치는 이번 세션의 재실행 결과와 구분한다. 파일/함수 위치는 분석 시점 기준이며 세부 원 diff·메타데이터는 로컬 `prs/{번호}/`에 보존했다.

| PR | 목적·발생 원인 | 실제 검사와 빈틈 | 후속 관계 | 현재 위험·재발 방지 |
|---|---|---|---|---|
| **512 문서** | operations/handoff에 PR505 보험 연결 액션 운영 수락·배포·금융 보호 근거를 추가. 기능 변경 없음. 배포 수락을 추적할 문서 필요가 목적. | diff는 문구·SHA·증거 경로만 증명. 기록된 87 검사·browser·보호표는 재실행하지 않았고 status checks 비어 있음(detail.json). | PR505 merge c0d45b46, PR512 faf63669. operations.md:1–7은 연결·취소·운영 저장 미실행을 구분. 독립 위험 없음. | 대상 PR, SHA, 증거 파일, 미실행 경계를 기록하고 문서 PR을 기능 결함으로 세지 않는다. |
| **511 문서** | PR510 조회기간 기능 수락 기록 및 명세 RELEASE_PENDING→COMPLETE. 기능 없음. | 명세는 52 pass와 baseline에도 있던 UI fixture timeout을 제외했다고 기록. 문서 diff는 결과를 재검증하지 않음. | PR510 merge a7aa8c7f, PR511 e9499109. card-upload-coverage-implementation-20261102.md:29–40. timeout은 별도 기록이며 신규 회귀로 입증되지 않음. | 상태 변경은 merge/배포 근거와 연결하고 timeout/deselected/미실행을 pass와 분리. |
| **510 기능** | 명시 조회 메타데이터·source hash·카드 맥락으로 조회 및 gap 구간을 계산하고 기존 change log 사용. 거래일만으로 알 수 없던 무거래 날짜가 원인. | sparse/0행·metadata 위조·identity·날짜·멱등·hash·원본 불변(test_card_upload_coverage.py:41–197), API 권한·CSRF 테스트. 명세가 기존 UI fixture timeout 1건의 baseline 재현·제외를 기록(spec:30). 전체 회귀·고객 파일 미실행. | PR511이 API/UI 수락 기록. 현재 기존 log만 사용. issuer export preamble 형식 및 날짜/호스트 경계 다양성은 잔여 위험. | issuer별 합성 fixture 확대, 기준일 주입 테스트. 모호 metadata는 확인으로 승격하지 않는다. |
| **509 문서** | PR507 성능/배포, Python/Rust 비교를 기록. 코드 없음. | diff는 성능·운영 상태를 증명하지 않음. 명세가 HTTP와 계획 성능을 구별. | PR507 merge 699eb8ed, PR509 0bf7c809. expense-performance-20261102.md. 중복 결함 없음. | 동일 입력·median·환경·미측정 범위를 함께 기록. |
| **508 문서** | PR504 UI 운영 수락 기록. 코드 없음. | 표적/viewport/URL/키보드/async와 전체 회귀 미실행을 기록하나 문서 diff 자체는 실행 증거가 아님. | PR504 merge ec2a37ab, PR508 6271c0d3. operations.md:25–31. 기능 위험은 PR504만 계상. | 합성/운영·viewport·미실행 경계를 구분. |
| **507 기능** | 자동분류에서 단일 plan의 canonical trip periods를 재사용. plan 밖 호출은 재검증. 반복 canonical_trip_periods 호출이 원인. | 여행/net 변경 사이 독립 호출 freshness 검사(test_classification_trip_reuse.py:11–36). 명세상 79 targeted+109 adjacent, 출력 동등; 실제 apply/전체 회귀 미실행. | PR509가 운영 성능 기록. automatic_classification.py:128–137, provisional_assignment.py:21–28. private _canonical을 후속 호출자가 오래 재사용할 위험; 전역 cache 없음. | map 수명을 단일 plan으로 제한하고 독립 호출/freshness 검사를 유지. |
| **506 문서** | 전역 action button 조사와 PR493/495/497/503 배포 결과. 코드 없음. 공통 summary decorator가 개별 스타일에 부작용을 낸 배경 기록. | 명세가 source template 수와 실제 화면을 구분하고 /export 운영 수락 미완료를 기록. 문서 PR은 증거 재실행 안 함. | PR503 merge 05755753, PR506 642fb596. 현재 site_shell.js:16–22, ledger_design.css:169–173에 예외. 보험 행 회귀는 PR499와 하나로 집계. | 공통 DOM observer에 SVG summary·복합 disclosure·async 삽입 테스트. |
| **505 기능** | 미연결 양수 보험 수입에서 기존 연결 폼 진입 버튼, 연결 상태 텍스트화, 선택 수입/오류 안내. 클릭만으로 저장하지 않으며 기존 확인 POST 사용. | 환불 제외·Google 가용성·원본/링크 불변·roster 부재 합성 테스트(test_insurance_connect_action.py:21–55). 운영 연결 저장은 하지 않음. | PR512가 수락 기록. 기존 confirmation/write path ledger_design.js:88–108. 늦은 panel load/DOM 교체 상호작용 위험. | 합성 async load·확인·취소·CSRF·상태 불변 검사; 화면 수락과 링크 저장 구분. |
| **504 기능** | expense_workspace.py와 CSS/JS로 4개 탭을 구성하고 card_flow에서 화면 decorate. 중첩 메뉴가 원인. | 테스트는 unique ID·정적 tab-panel·CSRF encoding·marker(test_expense_workspace.py:31–50). 문서 browser가 다양한 상태를 다뤘지만 전체 회귀/실제 upload 미실행. 정확한 h1/main 문자열 치환(expense_workspace.py:24–44)은 markup 변경 시 silent no-op 위험. | PR508 운영 수락 기록. PR510의 기존 timeout은 baseline에도 있어 같은 원인이라고 단정 불가. 현재 marker는 존재. | raw string 치환 대신 mount point/구조화 render. cleanup 삽입·탭·deep-link/history·async upload browser 합성 검사. |
| **503 기능** | PR503은 PR493 전역 decorator 도입 후 PR495 compound disclosure 예외, PR497 보험 summary 예외·행 회귀 수정에 이어 SVG/image가 있는 summary까지 장식 보존을 일반화하고 패널 CSS를 정리했다. PR503은 기존 보험행 높이 회귀의 원인이 아니다. | 테스트는 SVG·복합 disclosure·보험 panel heading·Space·dynamic DOM을 확인(test_site_action_buttons.py). 연결 행 전용 높이 검사는 PR497이 먼저 추가했다. | 실제 높이 회귀는 PR493 장식으로 발생했고 PR497이 수정. PR503은 이후 보존 규칙 일반화. 현재 site_shell.js:18–22, ledger_design.css:169–173. PR488 무관, 한 회귀로 집계. | 공통 decorator 변경 전후에 보험 연결/미연결/환불 행 높이·margin·focus·async 동작을 유지 검사. |
| **502 문서** | PR500 issuer 검색 수정의 원인 및 운영 수락 기록. 기능 없음. | 218행·pagination·baseline 실패 2건 제외 기록이나 이 diff는 운영 조회를 실행하지 않음. | PR500 merge 3b72d0e5, PR502 438c6df7. operations.md:40–47. 기능은 PR500에만 계상. | baseline·통과 수·운영 조회 범위를 나눠 기록. |
| **501 문서** | PR498 SQL/refund 최적화 benchmark, 배포, Rust 미도입 기록. 기능 없음. | 동일 입력·출력·median 및 전체 회귀 미실행 구분. 문서 diff 자체는 성능 검증 안 함. | PR498 merge 114af50d, PR501 c6405143. cleanup-read-performance-20261102.md:5–16. | benchmark 범위·반복·환경·쓰기 여부와 HTTP 효과 구분. |
| **500 기능** | card search에 issuer와 숫자 4자리 tail 추가. IBK alias는 issuer 조건에서만 기업으로 정규화. 원인은 검색이 issuer를 보지 않음. | alias·날짜/무날짜·월/연·필터·SQL injection·malformed tail·cursor·불변(test_card_issuer_search.py:20–58). baseline 실패 2건 제외, 전체 회귀 미실행. | PR502는 218행/3페이지 운영 수락 주장. 현재 card_transactions.py:46–70은 parameterized predicate. 미등록 은행 별칭은 자동 검색 안 될 수 있음. | issuer alias 제한 및 filter/cursor/tail matrix 유지; 새 issuer fixture 추가. |
| **499 문서** | PR497 보험 행 회귀의 원인·수정·운영 기록. 기능 없음. | 문서는 viewport/theme/상태별 결과와 SHA를 적으나 diff 자체는 browser 검사 안 함. | PR497 merge/운영 e95a8239, PR499 49cef041. 현재 ledger_design.css:160–173, site_shell.js:18–21. PR493 회귀의 후속 수정 기록이며 중복 결함 아님; PR503은 사후 일반화. | inducing/correcting PR, runtime selector, 배포 SHA 연결. |
| **498 기능** | cleanup correlated EXISTS/OR를 uncorrelated tuple IN으로 교체하고 NULL을 COALESCE(...,0)로 보정. Refund purchase를 issuer/tail/amount bucket으로 색인. dirty/occupied/요청 밖 후보는 uniqueness에 계속 포함. | nullable seeded rows를 기존 EXISTS oracle과 비교하고 무쓰기 확인(test_cleanup_query_equivalence.py:11–52). 명세상 원본/권한/refund 인접 검사. 전체 회귀 미실행. | PR501은 486 links·동등성·median 범위를 기록. 현재 card_cleanup_queries.py:63–75 및 partial_refund.py:278–317. 향후 direction/NULL 변화가 위험. | NULL/empty/dirty/occupied/out-of-request 후보를 포함한 차등 oracle 테스트 유지. |
| #497 | 보험 연결 상태의 `summary`가 #493 공통 decorator에 잡혀 site-action의 padding/margin이 더해짐. 연결 행 60.4px, 미연결·환불 45px. 해당 summary만 decorator에서 제외. | 패널 실제 렌더 + shell, 비동기 삽입, 320/390/1440px 및 양 테마의 연결/미연결/환불 행 높이, 가로 넘침, 키보드 disclosure를 검사하는 `test_insurance_row_site_actions.py`; 본문은 25 관련 테스트와 ego-browser 실측을 보고. 단일 보험 summary 회귀는 직접 커버하지만 다른 disclosure 조합 전수성은 별도. | #503가 SVG/icon-owning disclosure 일반 규칙을 보완. #499는 원인·실운영 수락 기록(문서만). #512는 다른 PR #505 보험 연결 액션 기록. | 현재 예외 selector가 남아 있고 회귀 테스트도 포함. 유사 신규 summary 클래스/중첩 버튼은 새 변형 가능: shell decoration 대상 전체의 고유 디자인/행높이 snapshot을 합성 DOM에서 비교 권고. |
| #496 | #494 운영 배포·수락 기록 문서 변경. | 문서 diff/기존 evidence 참조만 대상. 코드를 바꾸지 않고 테스트 재실행하지 않는 것이 기록과 일치. 문서 PR의 운영 수락·수치는 기능 PR 검사와 중복 합산하지 않음. | #494의 문서 근거를 추가. | 기능 결함 위험 없음. 링크·SHA/evidence 실재성만 문서 검수 대상으로 유지. |
| #495 | #493에서 compound disclosure summary와 내부 icon button이 동시에 장식돼 이중 프레임 생길 수 있음. 해당 summary를 건너뜀. | `test_site_action_buttons.py`가 plain/existing SVG/중첩 버튼/보험 패널 heading, 동적 삽입·라벨 변경, keyboard/disabled 및 화면 크기를 검사. 합성 DOM 중심으로 임의 애플리케이션 마크업의 CSS 조합 전부를 보장하진 않음. | #497은 별도 insurance summary 회귀 보완. #503은 기존 아이콘/design disclosure 전반으로 건너뛰기 규칙을 일반화. #506은 통합 UI 배포 기록(문서). | 현재 JS에서 summary 안에 svg/img/button/role=button이 있으면 decorator 제외. 동적 대상 포함. 추가 widget의 새 상호작용 요소는 회귀 문서에 fixture 추가 권고. |
| #494 | 동기 POST가 분류·OTA·기록/검증 완료까지 응답을 붙들어 네트워크 끊김이 파일 미접수로 오인됨. 저장된 source batch 이후 202와 owner-only status polling을 제공하고 작업을 직렬 writer lock 아래 처리. | `test_card_upload_jobs.py`: 느린 분류 중 202·status·shell 응답, 동일 batch coalesce, status가 DB를 읽지 않음, viewer 403/owner 미존재 404. 본문에는 보호 포함 표적 검사, 합성 UI 재개/완료/오류 및 좁은 화면 결과. 비동기 OTA refresh 예외는 `unavailable`로 흡수되고 기록/coverage 검증은 이어짐. 실제 외부 OTA 장애의 사용자 표시/운영 부하와 프로세스 재시작 중 worker 복원은 합성 범위 밖. | #510이 coverage API/UI와 최신 async upload 결합 검사(52개, 그 중 upload/job 선택 등)를 추가, #511 문서 수락. #504는 upload tab UX 및 재개 오류 안내를 검증. #498/#507은 별개 성능 변경. | status map은 프로세스 메모리라 재시작 시 UUID poll은 404지만 현 JS가 localStorage 작업을 지우고 배치 상세 링크를 안내; 재업로드 필요하다고 말하지 않음. 자동 재시작 이후 최종 상세 결과의 worker 완료 반영은 코드/worker 경계별 보강 여지. 현재 owner gate는 status와 POST 양쪽 확인됨. 자동검증은 202→재시작/404→저장 배치 상세 진입 및 durable worker 완료 상태를 합성으로 검증 권고. |
| #493 | 텍스트형 액션 인식성이 낮아 공통 shell JS/CSS pseudo-icon·border·focus·touch target 적용. 실제 DOM/text/handler는 보존. | `test_site_action_buttons.py`, shell asset 소유권 및 카드 카탈로그 browser 검사: native Enter/Space, disabled, data link, dynamic insert/label, 320/390/1440·양 테마. 경계 실패 3건은 PR 본문상 baseline `752eff0c` 재현 후 제외. 전역 selector의 의미론적 예외는 초기 검사로 완전 포착되지 않아 실제 보험 summary·compound summary 회귀가 후속 발생. | #495 → #497 → #503이 연속 예외/기존 디자인 보존. #506은 통합 감사 문서, #499는 보험 회귀 문서. 후속 코드 패치로 세 결함은 현재 JS에 반영. | decorator는 document 전체의 button/summary/a를 관찰하므로 새 custom disclosure가 기존 border/spacing을 갖는 경우 위험 유형은 잔존. 대상별 예외 규칙에 의존. 통합 shell fixture에 실제 패널 markup과 decorator 전/후 computed metrics를 넣는 제안. |
| #492 | 완료 거래가 반복해서 지출 정리에 남는 원인과 운영 수락/배포 기록 문서. | 문서 PR; 코드 검사/재배포 없음이 의도. #489 테스트 수치와 중복 집계하지 않음. | #489 및 #491 완료 근거를 기록. | 문서상 동작은 #489 계약에 따름. |
| #491 | #489 기능 변경에 카드 자료 관리 제목 2곳 변경이 섞여 범위를 넓힘. 기존 main 문구로 복구해 기능 diff를 완료 조건으로 한정. | diff상 title 문자열 2개 복귀와 #489 쿼리/완료 조건 최종 검사가 별개 변경. PR 본문은 후보 표적 38 및 환불 보호 39와 추가 최종 후보 검사를 보고. UI 문자열을 포함한 전체 기능 검증은 당시 targeted evidence를 따름. | #489는 핵심 동작; #491은 그 UI 계약 변경을 되돌림. 이후 #504는 카드 자료/업로드를 가로 탭으로 재구성(의도된 별도 후속). | 현재 제목은 후속 #504에서 workspace tab UI로 바뀌었으므로 과거 title 회귀를 현재 동일 위험으로 취급하지 않음. 자동검증은 cleanup eligibility diff에서 무관한 자료 관리 UI 변경을 탐지하는 scope review. |
| #490 | #488 국내 여행 보험 UI 구현의 설명·운영 수락을 기록한 문서 PR. | 문서 3개 파일만 변경. #488의 수치 재집계 금지. | #488 완료 선언과 UI/운영 근거를 문서화. | 기능 결함 여부는 #488 코드·테스트에서 판단. |
| #489 | 이미 항목·유효 여행이 저장된 거래가 예전 완료 표식 부재로 cleanup 목록/건수에 남음. 목록·카운트·필터에서 동일 완료 조건을 공유하고 실제 여행 권한 검증. | 신규 `test_cleanup_completed_assignment.py`는 inference/rule/manual 완료, ledger/decision 무작성, 권한 상실 후 재표시와 refund/source/hold/missing-data 보호를 검사. PR은 표적 38·환불 보호 39, baseline 문자열 검사 실패 1은 제외했다고 보고. 화면별 문자열 검사만으론 쿼리/건수 불일치 잡기 어려운데 신규 테스트가 목록·count·breakdown·HTML을 함께 확인. | #491이 무관 title 두 곳을 복구하고 최종 후보 검사 추가. #486은 helper/query ownership과 관련 cleanup read path를 리팩터하면서 `completed_assignment_sql` 동작을 유지; #498은 refund candidate query 성능 최적화. | 현재 `completed_assignment_sql(board)`를 목록 필터에 공통 적용, memoize는 render scope. 위험 경계는 trip_valid 권한/ledger·board_rows/refund/source/basis 예외. 자동검증: 같은 fixture로 list/count/breakdown/page/filter 동치 + authority 변경 무쓰기. 기존 두 신규 테스트가 핵심 부분을 커버. |
| #488 | 국내여행에 보험 명단이 없는 정상 상태가 보험 누락처럼 표시되고 불필요한 lazy/API 대조까지 실행됨. destination 기반 기존 `trip_region` 재사용, 안내 표시·보험 열/패널/후보·조회 제거. | `test_domestic_insurance_ui.py`와 participant income 테스트의 HTML 계약, 국내/해외/미상, 권한·요청 생략·원본 불변을 보고. PR은 관련 93, 소스 문자열 assertion 실패를 실제 HTML 헤더 assertion으로 교체 후 통과, 합성 browser 9 viewports/theme 조합. 국내 지역명 목록을 확대하지 않아 미인식 지역은 unknown 경로가 의도됨. | #490 문서 수락. #497/#503은 공통 action styling으로 생긴 다른 보험 disclosure 높이/테두리 문제를 수정; #505는 보험 수입 연결 액션을 별도 추가. | 현재 적용 판별은 `trip_region()` 재사용, 외부 쓰기 없음. 국가/지역 정규화가 넓어지면 표시 분류 위험. 자동검증은 국내·해외·미상 판별과 보험 API 호출 0/1, income 합계 불변을 테스트하는 현 계약 지속. |
| #487 | #483/#486 리팩터링 배포, 구조 비교 및 검증 경계를 기록한 문서 PR. | operations/handoff/spec 결과 문서만 수정. #483/#486 검사와 성능 수치를 다시 수행/합산하지 않음. | #483 자동분류 plan 분해와 #486 follow-up을 문서적으로 닫음. | 문서의 “COMPLETE”는 지정된 refactor 범위에만 적용; 새 기능 승인으로 해석하지 않음. |
| #486 | 잔여 자동분류/cleanup 복잡성과 stale 계약을 정비. cleanup의 중복 집계·cancel ID/query/helper 및 renderer 호출을 줄임; HTML 여행 metadata conflict의 409/escaped 입력 보존, OTA13 기존 테스트·화면 7건을 현 계약으로 교정. | 표적 348 passed. HTML 동등성/읽기 무쓰기, 합성 browser, 인접 권한 보호 15 passed + 3 failed/26 subtests; 3 실패는 baseline `f1e6453d` 재현(이전 drawer/internal ID 기대)으로 통과에서 제외. AST/라인·시간 측정은 결과 문서에 전후 모두 기록, 실행 코드 총량·중복·imports 개선이 없거나 미미한 것도 공개. 빈틈: baseline 재현은 회귀 배제 근거이지 해당 경로의 현재 사용자 수락은 아님; 3 failure는 별도 계약 검토 대상. | #483 자동분류 helper가 앞선 stage 분리를 제공, #486 후속이 cleanup/OTA/UI stale 계약을 다룸. #487 결과 문서. #498은 이후 SQL/refund 후보 scan 최적화. | 현재 코드는 helper/query 모듈과 renderer 최적화가 반영. 3 baseline failures의 기대치가 현 계약과 맞지 않는다면 테스트 갱신/실행경로 evidence 필요; stale 기준 assertion이 재발할 위험은 있음. 자동검증은 현재 문서 계약에 맞춘 public behavior assertion + read-only/전체 HTML·DB 동등성, OTA13 각각의 이름 있는 시나리오 회귀 유지. |
| #485 | 숙박 이용일 표기 수정(#482)의 원인·검증·운영 근거 기록 문서. 지정 범위 내 PR 485 자체는 docs-only. | operations/handoff 두 문서만. 테스트/DB/브라우저 재검증을 하지 않는 것이 PR의 전용 변경 계약. 구현 #482의 상세 검사는 이 PR에 중복 산입하지 않음. | #482 완료 사실 및 배포 근거 기록. #486이 stale OTA13 test contracts를 정비했지만 숙박 projection과 동일 버그는 아님. | #482 코드 동작 자체는 이번 코드 checkout와 별도 확인하지 않았고 docs claim만 참조. 문서 결함으로 기능 중복 집계하지 않음. |
| #484 | 지출 거래 행 인라인 편집 및 다중 선택 UX를 상세 명세로 추가하고 감사 문서에서 링크. `상태: 제안·미구현` 명시. | 기능 구현/테스트 없음이 명세 PR 범위. 다만 시나리오 수락 조건은 구체적: 기본/열림·저장·다중 전환/선택·필터 경계·고정 bar·전체 성공/취소·접근성·모바일. 특히 3건 중 1건 차단 시 3건 전부 무변경과 전체 통과 시 3건 변경, 중복 제출/revision 충돌 등. | #483–#512 중 이 기능 구현 PR 없음. `full-ux-audit`도 “신규 요구사항(미구현)”으로 별도 링크하므로 완료/실패로 취급하지 않음. | 동일 시나리오 부재는 버그가 아니라 구현 전 상태이며, 승인된 명세 실행 여부와 분리. 사용자 요청에 있는 시나리오가 없어진 것이 아니라 별도 명세의 완료 조건으로 이미 적혀 있음. 구현 PR이 생기면 각 번호별 acceptance test를 작성하고 특히 atomic all-or-none API, 권한/refund/manual protection, browser interaction을 자동검증. |
| #483 | 182-line/139-branch `automatic_classification.plan`의 보호·이력 복구·환불 상속·P2 재검토 책임이 뒤섞여 변경 검토가 어려움. row 보호/환불 완료/이력/복구/신규 추론 helper로 분리. | PR 본문상 분류·재검토·교정·worker·완료/quarter 표적 76 passed, py_compile/diff-check 통과. stale quarter-label test를 당시 출처 계약에 맞게 바꿈. 코드 통계는 같은 범위 비교: 총행 +17, branch -1, >100 line 함수 -1; plan hotspot 100행 아래. helper 분리 자체는 복잡성/동등성 판단이지 성능 향상 증거가 아님. | #486가 #483과 결합한 후속 구조 정비. #507은 다른 automatic-classification 경로에서 이미 검증된 trip period 재사용 성능 최적화; 전체 결과/digest 동등성 테스트 및 native 실험은 별도. | 현재 helper가 반영. `valid_fact`로 변경된 이력 복구 조건은 test suite의 reconsideration/source protection이 핵심. 자동검증은 전체 Plan output/digest 및 manual/source/refund/AI guard 전후 동일성; 성능 효과는 #507와 별도로 측정. |

## 자율 발견·수정 및 실측

| 문제 | 전 | 수정·검증 상태 |
|---|---|---|
| 출력 화면 읽기 증폭 | 운영 `/export` 25초 navigation timeout; 읽기 전용 프로파일 24.4초 중 충돌2,584회가22.4초 | 기존 `conflicting_row_ids()`를 요청당1회 재사용, 여행별 행도1회만 로드. 원본·XLSX 선택 정책 유지. 합성67검사 통과 |
| 동일 파일 완료 후 중복 처리 | 같은 batch라도 새 status UUID/worker로 분류·예약 대사·기록 재실행 | 완료 결과·status URL 재사용, running coalescing·실패 retry 유지. worker1회/오류retry 표적4검사 통과 |
| 지출 정리 DOM 계약 | h1 속성/공백 변화 시 mount 누락, 부분 DOM에서 observe(null) TypeError | 조립 경계 유일성 검사·유연한 속성 처리, 선택 노드 guard, keyboard/history/loader 회귀11검사 통과. 실제 브라우저 수락은 별도 |

출력의 같은 읽기 전용 트랜잭션·동일 nonce·전체 HTML 비교(호스트 Python, 순서 교대2회씩): 기존22.305/25.979초, 개선0.807/0.619초, 중앙값 **24.142→0.713초**, SQL **3,146→362회**, 전체 HTML 동일·쓰기0. 단일 프로파일/cold 계측·HTTP/네트워크 시간과 구분한다. 실행 부하·캐시·표본2회 한계가 있으며 실제 운영 HTTP 수락은 배포 뒤 따로 기록한다.

원격 main branch protection은 조회가 HTTP403(현재 private 저장소의 요금제 제한)으로 거부됐다. 유료 플랜 전환이나 저장소 공개를 하지 않는다. 자동 PR/정기 실행과 에이전트의 CI 성공 후 병합 절차는 구축하되, 관리자/사용자가 GitHub UI에서 검사 실패를 무시하는 행위를 서버 측에서 강제 차단한다고 주장하지 않는다.

## 통합 검증 진행 (2026-11-02)

PR #513의 정확한 `e2b6a36b` CI는 499개 중 491 passed·8 failed이며 병합·배포하지 않았다. 첫 CI의 452개/15실패와 후속 결과를 합산하지 않는다. 최신 실패의 브라우저 assertion과 합성 입력을 현재 업무 계약에 대조하고, 정상 기록·예약 근거·원본/수동 교정 보호의 검증을 유지한다. 정기 감사에서는 폐기된 Google 페이지를 여전히 성공으로 기대하는 검사와, Linux에서 절대경로가 아닌 Windows 전용 OTA 테스트 설정을 발견했다. Google은 현행 경로의 접근 거부·무변경 및 금융 투영 검사로 교체하고, OTA는 OS별 임시 디렉터리의 절대경로로 고쳤다. 제품의 폐기 경로를 재활성화하지 않는다.

추가 업무 감사에 남은 영수증 11실패와 참가 명단 인접 실패는 미결로 추적한다. 수집만 완료한 브라우저 검사는 실행 통과로 세지 않는다. 전체 업무 감사·정기 감사·정확한 SHA의 CI 성공·병합·고정 배포·운영 보호 수락 전까지 전체 완료로 올리지 않는다. 모바일 합성 화면에서 390px 탭 전환→뒤로가기의 선택 복귀와 가로 넘침 0을 확인했다. 실제 고객 분류·여행·Google 최종 장부 쓰기는 수행하지 않았다.
