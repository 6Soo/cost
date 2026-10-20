# COST 세션 인수인계 — 2026-10-20

> **문서 목적**: 이번 ChatGPT 세션의 설계 결정, 개발 에이전트 보고, 검증 범위, 추가 요청, 남은 과제를 새 세션으로 인계한다. **이 문서의 분석·아이디어·프롬프트는 구현 완료 증거가 아니다.**
>
> GitHub 대조: 2026-10-20 KST, 원본 저장소 \`6Soo/cost\`, 기준 \`main\` **\`3da454b9f1830f3adeccf9b845a5ca2eb55053d7\`** (기준 SHA 직전 코드 변경 \`f5e27d3a06ad010656dd43f8d01af2ccc42cb5b5\`). 이 인계 문서는 별도 \`docs/cost-session-handoff-20261020\` 브랜치에서 작성했다.
>
> **권위 분리**: 현재 배포 실적은 [operations.md](operations.md)의 *최상단 최신 절*, 진행 중 기능은 현행 소스·Git 로그를 먼저 따른다. 오래된 운영 수치와 세션 보고는 당시의 기록이다. Windows 현지 프로세스/DB 실측은 이 문서 작업에서 수행하지 않았다. 문서 작업을 이유로 운영 서비스를 재시작하거나 DB를 수정하지 않는다.

## 1. 새 세션 1분 요약

- 제품: 숲길따라 감성여행의 비공개 COST 회계/지출 플랫폼. 운영 URL \`https://ledger.foresttour.kr\`, 저장소 \`6Soo/cost\` (private), Windows \`D:/WebLedgerHost\`, Cloudflare Tunnel, SQLite 내부 장부. Google 시트는 목표 업무에서는 최종 회계 정본이며 COST는 사용자 승인 없는 자동 Google 쓰기를 하지 않는다.
- 사용자 지향점: **사람이 건별 확인·확정하지 않는 자동 분류형 장부**. 업로드·수집 → 기존 규칙 및 검증된 OTA 근거로 자동 분류 → 안전한 거래 자동 기록 → **불확실한 예외만 ‘지출 정리’에서 해결**. 신규 화면·상태를 늘리지 말고 단순화한다.
- 2026-10-14 PR #85는 **병합·종료**됐다(merge SHA \`f23b080bbd0484c5f371d44ff1ce4bd3860588ec\`). 이전 \`integration/cost-final\`을 최신 개발 브랜치라고 가정하면 안 된다. 2026-10-20 \`main\`의 상태를 새로 확인한다.
- 현재 코드에는 단순 수동 기록 UX 제거, 지출 정리 통합·페이지 분할, 다음 행동 표시, 원본/환불/OTA 차단, 자연어 제안 UI, 제한된 로컬 AI 문장 해석이 존재한다. **자연어 메시지 하나가 기존 규칙을 검색·갱신하여 미래 거래에 영구 적용하는 완결 UX는 아직 아니다.**
- **Cursor 공식 pstack을 Codex/Claude Code에 통합하고 Paseo의 Muse Spark 1.3 Free·Space Bunny Free·Inkling Free를 병렬 서브에이전트로 쓰는 구성은 이 세션에서 프롬프트만 작성했다. 설치·연결·요금·실행 검증 완료 증거 없음.**
- 최종적으로 이 문서 및 최소한의 문서 정리를 PR로 제안할 뿐, 운영 배포/DB 변경/기존 PR 재오픈은 하지 않는다.

## 2. Git / 운영 / 증거의 구분

| 사항 | Git 대조 또는 출처 | 상태 |
| --- | --- | --- |
| 2026-10-20 Git 기준 \`main\` | \`3da454b9f1830f3adeccf9b845a5ca2eb55053d7\` | 확인 |
| 마지막 기능 커밋 | \`f5e27d3a06ad010656dd43f8d01af2ccc42cb5b5\`, 지출 정리의 예약 미연결 안내 수정 | 확인 |
| 2026-10-20 문서 보완 | \`3da454b9f1830f3adeccf9b845a5ca2eb55053d7\`, 배포/검증 한계 기록 | 확인 |
| 마지막 **문서상 운영 배포** | \`f5e27d3\`, \`docs/operations.md\` 최상단, \`OWNER_UI_DEPLOYMENT_PASS\`; 백업 \`v2-owner-ui-20261020T154914\` | **운영 문서상의 실행 보고**. 현지 실측 재수행 안 함 |
| PR #85 | 2026-10-14 병합 완료, merge \`f23b080\` | 확인 |
| 운영 및 소스 DB 정합성 | 최신 운영 문서: 4 DB·55 파일 백업/복원, health/ready 200, 비로그인 \`/import\` 401 | 과거 실측 결과 재사용. 현행 데이터 규모의 실시간 조회 아님 |
| 미검증 운영 화면 | 10/20 예약 미연결 안내의 **로그인된 실화면**; Aside 연결 실패로 PARTIAL | 차후 읽기 전용 1회 확인 |
| Git 브랜치 | \`main\`, 보존된 \`feat/*\` 브랜치들; 현재 열린 PR 조회 당시 0 | 이 문서 브랜치/PR을 제외한 조회 시점 |
| 로컬 개발 작업 트리 | GitHub 원격만 확인 가능. 사용자 Windows checkout의 dirty/stash·운영 SHA는 별도 확인 필요 | 미검증 |

### 숫자와 연혁 주의

- 이번 세션에서 2026-10-14 자동 기록·수입 UI 릴리스 \`70ca965\`에 대해 **장부 896건, 86,498,939원** 및 3개 DB 백업 불변을 에이전트가 보고했다. 이는 당시 보고 수치일 뿐 **2026-10-20 운영 잔액으로 재사용하지 말 것**. 다른 과거 단계의 734/736/753행 집계와 다른 시점·조건의 숫자를 직접 비교해 회계 오류를 단정하지 않는다.
- 2026-10-13 실제 자동 기록 17건 및 기존 행 불변, 2026-10-18 실화면 정리 대상 263건·한 페이지 20건은 [operations.md](operations.md)의 해당 날짜 근거다. 현재 실시간 건수가 아니다.
- 2026-10-09 README의 6,037 원본/734행 등 숫자는 과거 스냅샷이다. 후속 재개에서는 운영 읽기 전용 기준선과 실제 연결 상태를 다시 구분한다.

## 3. 사용자 확정 업무 원칙 (최상위)

1. **과도한 건별 검토·승인 단계를 제거**한다. 신뢰할 수 있는 분류 결과는 자동 기록하고, 사용자에게는 실제 해결이 필요한 예외만 제시한다.
2. **기능 추가보다 감산(경량화)**: 중복된 카드 검토/미배정 화면·중복 목록·대형 수정 폼·기술 진단 장문을 최소화한다. 데이터 보호 계층까지 제거하는 뜻은 아니다.
3. **거래 원천 불변**: 원본 승인/매입/취소/환불/원화 금액·외화 금액·날짜·ID·source_hash·사용자 수정 이력 보존. 다른 원문이 같은 ID에 들어오면 충돌 보류. 중복 기록 금지.
4. **회계 경계 보존**: 원본 거래(\`transactions\`), 내부 전기(\`ledger_entries\`), 화면 장부(\`board_rows\`), 증빙(승인/영수증), OTA 연결은 별도 존재 목적을 갖는다. UI만 통합하고 테이블을 함부로 합치지 않는다.
5. **Google 시트에 자동 쓰지 않는다.** 7열 TSV 복사 → 사용자가 Google에 직접 붙여넣기. 수입·은행이체는 사용자 Google 입력을 COST가 읽는다. 자세한 계획과 *미확정* 범위는 [target-workflow-google-authority.md](target-workflow-google-authority.md). 이 목표 명세가 이미 완전히 운영 전환됐다고 가정하지 않는다.
6. **여행 배정은 검증된 일정/예약 이용기간이 우선**이고 결제일만으로 다른 여행을 만들어내지 않는다. 실제 사용자 합의는 [AGENTS.md](../AGENTS.md), [business_rules.md](business_rules.md), [reconciliation-rules.md](reconciliation-rules.md)가 우선한다.
7. **로컬 AI는 업무 지시 해석자이지 회계 원장을 직접 쓰는 행위자 아님**. 규칙은 구조화·검증·미리보기·명시 범위 선택·버전/감사 기록을 거쳐 활성화하고 이후 거래에서는 결정론적 규칙 엔진이 수행한다. AI가 응답하지 않아도 수동 예외 수정은 가능해야 한다.
8. **추가 과금 0원 조건**: 외부 유료 API, 무료 모델→유료 자동 폴백, 사용자 비밀·고객 원본의 외부 전송 금지. 무료/Contributor 모델의 데이터 이용약관 검토 없이는 비공개 원문·소스 전송 금지.
9. 운영 DB·Google 원본·Cloudflare Tunnel·다른 프로젝트의 프로세스·Windows 작업 스케줄을 임의로 변경하지 않는다. 단일 작성자, 격리 작업 공간, 백업·복원 검증, SHA 릴리스, 롤백을 따른다.
10. 코드를 변경하면 **변경 범위 표적 테스트 + 실제 영향받는 회계 불변조건 1회**가 원칙. 이미 검증한 테스트 무의미 재실행·무관한 기존 실패까지 수리·무기한 백그라운드 테스트 금지. 문서 전용 변경에는 코드 테스트·운영 배포를 하지 않는다.

## 4. 이번 대화의 의사결정/요청 순서와 현재 결과

### A. 자동 기록 전환 및 \`70ca965\` (10/13–14 대화에서 보고)

- 출발점은 카드 파일을 업로드한 뒤 \`미확정 → 미리보기 → 기록\` 단계를 사람이 반복하는 문제였다.
- 당시 구현: \`app/auto_record_policy.py\`, \`webapp/card_flow.py\`의 업로드→분류→자동기록, \`app/quarter_tab.py\` 분기 비용 기록, 영수증의 지급처/항목 자동 힌트, 카드 수동 기록 버튼 제거, 소유자 전용 기존 \`/api/imports/{batch}/commit\` API는 호환 목적 유지, 환불 묶음 보호 유지.
- 과거 배치를 받기 시작한 \`received_at\` 날짜로 제한하자는 **당시 방안은 더는 현행 정책이 아니다**. 2026-10-15 사용자 결정으로 \`app/auto_record_policy.py:batch_is_new()\`는 **존재하는 배치 전체**를 인정한다. 새 세션은 이전 타임스탬프 게이트를 재도입하지 말고 현재 정책·별도 보존/차단 계약을 확인한다.
- \`70ca965\` 보고: 수입 기본 요약의 장문 진단 안내를 접어 넣음. 행 합계와 집계 합계 불일치에는 짧게 ‘수입 합계 차이 있음’; 원본·검증 불가 시 ‘수입 확인 필요’로 구분하며 확인되지 않은 금액/거래자 이름 노출 방지. **실제 수식 범위/합계 불일치 원인이 있으면 UI 문구만 숨기지 말고 진단해야 한다.**
- 당시 표적 결과: 카드 자동 8, 분기 3, 수입 UI 25, 환불 5, Google 7열 표적 1 등으로 각각 보고. 카드 브라우저 21건 및 일부 레이아웃 2건 결과는 확보되지 않았거나 기준 이전 실패였음. 이 결과를 **현재 HEAD의 전체 회귀 통과**라고 보고하지 않는다.
- 이미 운영 코드가 10/13–20 동안 크게 바뀌었으므로, 이전 릴리스의 미완료 작업을 무조건 다시 실행하지 않는다.

### B. 테스트 반복이 너무 긴 문제

- 에이전트가 5분 제한(종료코드 124) 후 요약 없는 백그라운드 테스트를 여러 번 재실행했다. 사용자는 이런 소모를 명시적으로 비판했다.
- 합의: 위험 기반 표적 테스트, 확실히 통과한 증거 재사용, 무관한 기존 2건 레이아웃 실패 제외, 중복 테스트 중단. 미검증을 숨기지 말고 최소 필수 계약(7열 출력·환불 중복·자동기록 멱등성)만 확인한다.
- [AGENTS.md](../AGENTS.md)의 ‘검증 최소화·재검증 금지’ 정책으로 이미 정식 기록돼 있다. 테스트 정책을 새로 복제해 또 다른 프레임워크로 만들지 말 것.

### C. 카드 검토와 미배정 지출의 UX 통합

- 문제: \`/import\` 원본 배치 검토, \`/import?scope=all\` 전체 거래, \`/board?tab=unclassified\` 이미 전기된 미배정 지출이 서로 다른 메뉴에 분산돼 같은 일을 반복했다.
- 사용자의 요청: 기본 메뉴 **‘지출 정리’**로 결합, 정상 거래는 감추고 여행/항목 미배정·예약 증빙·환불/원본 충돌만 표시. 한 거래 한 작업(여행 선택·항목 수정·예약 연결), 완료 즉시 작업 목록에서 제거. 카드 업로드·전체 검색·규칙 편집은 보조 기능. 모바일 375/390px 우선.
- 현재 \`webapp/card_flow.py\`의 \`render_expense_cleanup()\`, \`_cleanup_card_items()\`, \`cleanup_total()\`는 **카드 미기록 예외+기존 장부 미배정**을 한곳에 그리는 기능을 구현했다. 2026-10-17 \`31fa79a\`에서 전체 건수 계산과 페이지 분할을 반영했고, 10/17 미리 수정된 거래 제외와 10/18 UI 카드형·인라인 규칙 제안을 반영했다.
- \`webapp/card_actions.py\`는 기록 완료/제외/확인 필요의 다음 행동 및 딥링크를 제공한다. 현행 화면 실측(10/18): 페이지당 20개 거래, 인라인 자연어 입력·상세 검토, 실제 운영 쓰기 미시행.
- **아직 ‘UX 완벽’이라고 판단하지 않는다.** 사용자 실사용 관점의 클릭 수·검색·장부 수정 흐름, 실제 모바일 화면, 오류 메시지·기록 후 사라짐 등을 다음 실사용 피드백으로 보완한다. 데이터 계층 통합/새 상태 머신은 금지.
- 과거의 “300건 제한으로 누락”, “단순 여행 지정이 보류를 무조건 해제”, “분기 별도 기록 가드 부족”에 관한 진단은 당시 기준. 10/17 이후 페이지 집계·\`resolve_hold\` 기본 제거 및 \`app/quarter_tab.py\`의 \`_recording_guard\` 구현을 **현행 코드에서 확인**했으므로 해결 전 상태처럼 다시 보고하지 않는다.

### D. Cursor pstack 검토와 무료 병렬 에이전트 구상

- 사용자가 의미한 pstack은 **Cursor 공식 \`cursor/plugins/tree/main/pstack\`**. 다른 이름의 pstack 저장소가 아니다.
- 평가: \`correct\`, \`blast-radius\`, \`interrogate\`, \`poteto-mode\`를 **선별적으로** 활용하는 것이 적합. 일상적 UI 수정에 전체 \`poteto-mode\`와 다중 검토/전체 회귀를 상시 적용하면 COST의 과검증 문제가 더 심해질 수 있음.
- 후속 상세 프롬프트를 이번 대화에서 작성: Codex CLI 또는 Claude Code가 메인 지휘자, Paseo+OpenCode에서 Muse Spark 1.3 Contributor Free·Space Bunny Free·Inkling Free를 필요할 때 최대 3개 병렬로 호출. Cursor 에이전트와 유료 폴백 금지, 읽기 전용 위임 기본, 비공개 데이터 금지, worktree 분리.
- **실제 설치·세 모델 정확 ID/이용약관/가격·Paseo run ID·Codex 및 Claude Skills 인식은 미검증/미구현**. 현재 Git 트리에 pstack 설정 파일이 없다는 사실만으로 개발자 로컬 환경에도 없다고 단정하지 않는다. 요청이 재개되면 실제 환경부터 조사한다.

### E. 거래 상태 전체 조사 (10/16 코드 기준, 현재는 일부 후속 수정)

- 카드 원본 \`transactions.classification_state\`: \`needs_review\`, \`classified\`, \`booked\`(레거시 표현), \`preserved\`. 이 값과 내부 장부 기록 여부(\`ledger_entries\`)는 다른 축. \`board_rows\`에는 별도의 \`classification_state\`(예: \`unclassified\`, \`auto_classified\`, 빈 값) 및 여행 배정이 있음.
- 분류 상태 외 보조 플래그: \`duplicate_of\`, \`parse_error\`, \`conflict_reason\`, 사용자 결정(\`decided_at\`/\`review_decisions\`), 회사 경비 제외, 사용자 보류(\`transaction_review_holds\`), 자동 기록 preview의 \`blocked\`, 이미 기록된 행 탐지, 원본 충돌/중복 가능성.
- 환불/취소: \`purchase\`, \`cancellation\`과 원결제 연결·전액(\`full\`)/부분(\`partial\`)/초과(\`excess\`), 원결제 없음, 쌍 일부 기록, 다수 취소 개수 그룹 보류. 실제 한 결제를 여러 승인/환불 자료로 중복 전기하지 않는다.
- 승인 증빙 \`approval_evidence.link_state\`: \`unreconciled\`, \`linked\`, \`group_linked\`, \`group_partial\`, \`approval_only\`, \`ambiguous\`, \`cancelled_before_acquisition\`, \`cancelled_after_acquisition\`. 승인 자체는 최종 매입 지출이 아님.
- OTA 결제 매칭: \`MATCHED_AUTO\`, \`MATCHED_USER\`, \`PENDING_PAYMENT\`, \`NOT_CARD_CHARGE\`, \`HOLD_NO_CARD\`, \`HOLD_AMOUNT_MISMATCH\`, \`HOLD_DATE_UNKNOWN\`, \`HOLD_AMBIGUOUS\`, \`HOLD_PARTIAL_GROUP\`, \`HOLD_GROUP_CHANGED\`, \`HOLD_EVIDENCE_CONFLICT\` 등; 예약 자체의 \`confirmed\`/\`completed\`/\`cancelled\`/\`observed\`/\`upcoming\` 상태와는 구별.
- 영수증: 비전 작업 \`queued\`/\`running\`/\`done\`/\`failed\`, 후보 \`ready\`/\`not_ready\`, \`LOW_CONFIDENCE\`, \`FIELD_MISSING\`, \`TOTAL_UNCLEAR\`, \`CURRENCY_UNKNOWN\`, \`PAYMENT_UNKNOWN\`, \`CARD_NOT_FOUND\`, \`CARD_MATCH_AMBIGUOUS\`, \`CARD_PAYMENT_CONFLICT\`, \`DUPLICATE_CONTENT\`, \`TRIP_UNASSIGNED\`, \`GROUP_INCOMPLETE\` 등.
- 사용자가 보는 상태는 **‘정상 처리’, ‘분류 필요’, ‘근거 확인’, ‘기록 제외’, ‘처리/기록 대기’** 정도로 줄이는 것이 권장됐다. **DB 단일 상태값으로 억지 통합하지 않는다.** UI상 \`기록 대기\`를 일반 수동 작업으로 재도입할 필요 없음.
- 위 열거는 계층별 대표 상태 및 코드 조사 목록이다. 운영 DB의 실제 상태별 건수·금액·모든 가능한 조합은 별도 읽기 전용 집계 없이는 주장하지 않는다.

### F. ‘건별 수정’ 대신 ‘로컬 AI에게 메시지 → 규칙 자체 변경’

- 최신 사용자 요청: 사용자는 거래마다 여행/항목을 수동 수정하기보다 **해당 거래의 자연어 메모로 반복 처리 규칙을 고치고 싶음**.
- 좋은 UX: 거래에 \`AI에게 처리 방법 알려주기\` → \`이번만\` / \`앞으로 같은 조건\` / \`기존 규칙 수정\` / \`규칙 충돌·추가 질문\` 분류 → 영향 거래 건수/여행/금액과 예외를 보임 → 한번 승인 → 버전·감사 기록 → 이후 자동 실행. 현행 회계 보호와 과거 원본 불변.
- **현재 구현 사실**: \`app/local_rule_ai.py\`는 \`WEBLEDGER_LOCAL_RULE_AI=1\`일 때 \`127.0.0.1:8088/v1/chat/completions\`에 **사용자 문장만** 전송하며 \`THIS_ONLY/MERCHANT_RULE + 한국어 단일 항목\`을 추출. 실제 가동 여부는 미검증.
- \`app/rule_proposals.py\`의 결정론적 문장 해석과 \`webapp/rule_review.py\`의 미리보기·원자적 답변 적용, \`webapp/classification_rules.py\`/ \`webapp/ledger_store.py\`의 검증·적용·미래 규칙 버전 관리, \`app/rules.py\`의 카드 규칙 검증을 **재사용**해야 한다.
- 2026-10-19 \`d90bef2\`는 **아고다 문장 중 비용 항목만** 처리하고 예약 이용기간에 따른 새로운 자연어 여행 배정 규칙은 만들지 않았다. 기존 사용자 승인·충돌 보호가 우선한다.
- **남은 제품 간극**: 자연어 제안 적용과 ‘향후 사용 규칙 초안 저장’이 분리돼 있고 기존 중복 규칙 검색·수정/대체까지 단일 흐름이 아니다. AI가 임의로 여러 여행 배정/회사 경비 제외를 확정하지 않아야 한다.
- 2026-10-11 목표 명세 [target-workflow-google-authority.md](target-workflow-google-authority.md#5-지출-검토-ui--로컬-ai에-자연어로-규칙-수정-요청--목표)에 비슷한 방향이 기록돼 있다. 목표와 현재 구현을 구분한다.

## 5. 최신 파일별 코드 읽기 순서

1. [AGENTS.md](../AGENTS.md) — 사용자 확정 업무규칙, 개인정보, 표적 검증·운영 보호(가장 먼저).
2. [operations.md](operations.md) 최신 절 — 실제 실행·배포 보고, 백업/복원, 미검증을 분리.
3. [session_handoff.md](session_handoff.md) — 이전 세션별 작업 이력·그 시점의 블로커. 이 문서와 함께 참조.
4. [business_rules.md](business_rules.md), [reconciliation-rules.md](reconciliation-rules.md) — OTA 이용기간 우선/환불/분기비용 규칙의 권위.
5. \`webapp/card_flow.py\` (자동 분류·기록, 지출 정리 UI, 거래별 자연어 입력), \`webapp/card_actions.py\` (다음 행동), \`webapp/card_catalog.py\` (카드 전체 조회).
6. \`app/auto_record_policy.py\`, \`app/ledger.py\`, \`app/quarter_tab.py\`, \`app/review.py\`, \`app/review_holds.py\`, \`app/partial_refund.py\` (회계 쓰기·차단).
7. \`app/local_rule_ai.py\`, \`app/rule_proposals.py\`, \`webapp/rule_review.py\`, \`app/rules.py\`, \`webapp/classification_rules.py\`, \`webapp/ledger_store.py\` (자연어 제안과 영구 규칙의 미연결 경계).
8. \`app/ota_payments.py\`, \`app/ota_exact.py\`, \`webapp/ota_catalog.py\`, \`webapp/ota_payment_review.py\`, \`app/ota_cash_use.py\` (OTA 결제·여행·포인트·캐시 귀속).
9. \`webapp/google_ledger_page.py\`, \`docs/google-workbook-layout.md\` (수입 검증·7열 계약), \`webapp/receipt_review.py\` (영수증).
10. \`tools/start_web_ledger_host.ps1\`, \`tools/run_lightweight_deployment.ps1\`, \`docs/operations.md\` (운영 시작·배포/롤백 계약).

## 6. 우선순위 및 확인할 쟁점

### 즉시 재개 가능한 일 (별도 사용자 구현 요청이 있을 때)

1. **로컬 자연어 규칙 학습 UX**: 단일 거래 메시지에서 기존 규칙 후보 검색→이번만/미래 규칙 수정 선택→영향 범위 미리보기→기존 규칙 버전 갱신·감사 이력·이후 거래 재사용. 무조건 새 규칙을 생성하지 않는다. 원본·보류·환불·유효 여행 근거 불변.
2. **실사용 지출 정리 UX 평가**: 사용자 화면에서 미기록 카드와 이미 기록된 미배정 지출을 명확하게 구별하면서 거래 수정 1회, 처리 후 제거, 실패 시 입력 보존, 탐색성과 모바일 375/390px 확인. 이미 구현된 카드형·페이지 분할을 재구현하지 않는다.
3. **필요시 pstack–Paseo 연결**: 실제 설치·Skill 인식·모델 ID/무료 약관/권한·병렬 run ID 테스트. 반복되는 쉬운 작업에는 서브에이전트 호출 0회, 어려운 리뷰에만 무료 1–3개. 로컬 모델과 외부 무료 모델을 구별하고 데이터 최소화.
4. **운영 확인 1개**: 10/20 수정된 예약 미연결 안내를 정상 로그인 브라우저에서 읽기 전용으로 1회 확인. 이미 보고된 health/ready 및 기존 테스트 전체를 다시 반복하지 않는다.

### 운영·제품에서 아직 확인되지 않은 것

- 실제 Windows 로그인 브라우저의 10/20 문구. API health 200으로 인증 화면 UX를 증명할 수 없다.
- 현재 운영 DB의 거래 상태별 정확한 건수/합계, 무결성 전체 비교. 과거 숫자 재사용 금지.
- pstack/Codex/Claude/Paseo/OpenCode 세 무료 모델 호출과 과금 0원 확인.
- 로컬 AI \`127.0.0.1:8088\`의 실제 Windows 프로세스/서비스 활성화 및 자연어 실사용 성공률.
- Google 수입 집계/행 합계가 실제로 일치하는지, 예전 경고가 원본 시트 수식 범위 문제인지. 불일치를 숨기거나 확인되지 않은 금액을 확정값처럼 보여 주지 않는다.
- 구형 브라우저 21건 등 이 세션에서 과거에 결과 미확보로 남은 테스트는 현재 코드에서 직접 영향을 받을 때만 표적 검증한다.

## 7. 안전한 변경·검증·배포 규율

- **문서만 수정**: 새로운 세션 인계 작성/과거 설명 업데이트만 수행. \`pytest\`, 전체 E2E, 서버/DB 스모크, 프로덕션 배포 금지. 원격 문서 diff·Git 브랜치·PR 상태만 확인.
- **실제 코드 변경**: 작업 시작 SHA/영향 경계/완료 기준 명시 → 구현 → 직접 관련 표적 테스트 → 회계 보호 영향이 있다면 격리 SQLite에서 동등성·멱등성·환불·원본 보존 확인 → 리뷰 → 커밋 → 운영 필요시 백업·복원·SHA 릴리스 및 최소 1회 스모크.
- 과거 세션의 요청 프롬프트·정책을 무차별 재실행하지 않는다. 최신 \`main\`에 구현된 기능을 다시 만들지 않는다.
- Windows 운영 환경의 사용자가 남긴 dirty/stash/보호 파일(\`edit_card_flow.py\`, \`pending-card-evidence*.patch\`, SQLite checkpoint JSON)은 재설정·삭제·스테이지하지 않는다.
- 기존 Google 복사만 사용, Google 자동 쓰기 금지, 카드 원문·실제 개인정보·비밀키·API 토큰을 Git 또는 무료 모델에 전달하지 않는다.
- 운영 작업은 다른 프로젝트/Cloudflare 중복 프로세스를 건드리지 않는다. \`main\` 강제 push 금지; PR에서 리뷰하고 병합한다.

## 8. 새 세션 시작용 프롬프트

> COST(\`6Soo/cost\`) 새 세션을 시작한다. 먼저 \`AGENTS.md\`, \`docs/operations.md\` 최상단, \`docs/session_handoff.md\`, **\`docs/cost-session-handoff-20261020.md\`**를 순서대로 읽고, 실제 최신 \`main\` HEAD·열린 PR·작업 트리·운영 릴리스 SHA가 문서 기록과 달라졌는지 확인하라. 지난 대화의 핵심 요구는 **사용자 승인 없는 신뢰 가능한 자동 분류/기록, 불명확한 거래만 ‘지출 정리’에서 처리, 자연어 메시지로 기존 분류 규칙을 수정·버전 관리하여 미래 거래에 재사용**하는 것이다. 이미 구현된 UI/자동 기록/환불 가드를 재구현하지 말고 현재 코드와 제품 목표의 차이를 먼저 짧게 정리하라. 운영 SQLite·Google 원본·사용자 결정·환불·OTA 권위·중복 차단을 보호하고, 무료 모델의 과금·데이터 약관을 검증하기 전에는 외부 AI에 자료를 전송하지 마라. 구현 요청이 오면 작은 변경/표적 테스트/명확한 종료 조건으로 처리하라. 현재 요구를 새로 받기 전에는 과거 미결 구현을 자동으로 수행하지 마라.

---

*작성 근거: 이 대화의 사용자 요구 및 개발 에이전트 보고, 2026-10-20 GitHub \`main\` 소스 및 기존 \`docs/operations.md\`·\`docs/session_handoff.md\` 조회. 실제 런타임/DB를 이 문서 작업으로 새로 검사하지 않았음.*
