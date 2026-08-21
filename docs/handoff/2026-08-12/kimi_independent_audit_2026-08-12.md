# Kimi CLI 독립 감사 보고서 — 2026-08-12

**감사 범위:** `ledger/` 파이프라인 코드·스키마·문서·비식별 산출물(원천 ledger/data 행은 읽지 않음)  
**대상 브랜치:** `codex/p07-canonical-cutover-candidate` (`243fb8240eddbbcd71133c0788f8561064c5a2e4`)  
**감사자:** Kimi Code CLI 독립 검증 슬롯

---

## 1. 요약

현재 후보는 Gate1~4·Gate7 PASS, Gate5 `accepted_with_auto_provisional_queue`, Gate6 `direct_baseline_unavailable`로 전체 `passed=false`다. 코드 품질·테스트 커버리지·fail-closed 설계는 양호하나, **Gate5의 자동 임시큐 수용 기준, 하드코딩된 상수들, OTA 금액 허용률이 원장 지시사항과 충돌**, 그리고 **Gate6 baseline 부재가 운영 전환을 영구 차단**하는 구조적 취약점이 있다. 본 감사는 현재 수용안을 운영 정본으로 승격할 수 없다고 판단한다.

---

## 2. 규칙 과잉 (Rule Excesses)

### 2.1 Gate5 수용 상한이 임의적
- `transition_gates_v2.py:124` `TRAVEL_UNASSIGNED_ACCEPTANCE_LIMIT = 5`
- `transition_gates_v2.py:125` `OWNER_CONFIRMATION_ACCEPTANCE_LIMIT = 50`
- `transition_gates_v2.py:129` `AUTO_PROVISIONAL_ACCEPTANCE_LIMIT = 500`

이 상수들은 비즈니스 근거나 과거 운영 데이터 유도가 드러나 있지 않다. 5건/50건/500건은 테스트 경계를 만족시키기 위한 값으로 보이며, 실제 잔여 묶음 크기(3,144건)와 무관하게 설정돼 있다.

### 2.2 UNKNOWN 임시활동 창이 지나치게 좁음
- `direct_trip_cluster_registry.py:42` `UNKNOWN_MIXED_ACTIVITY_MAX_SPAN_DAYS = 3`
- 조건: 혼합국가 parent run, 명시 국가 수=명시 행 수, markerless 행이 명시 행보다 많음, 모든 markerless 행이 양수 외화금액.

이 조합은 KBO 7건·CARPISA 1건에만 딱 맞춘 것처럼 보이며, 동일한 패턴의 미래 데이터는 여전히 `travel_unassigned`로 남아 Gate5를 다시 실패시킬 가능성이 크다. 레지스트리가 "bounded foreign-card use window"라고 명시했지만, 3일이라는 기준은 항공+숙박 선결제의 실제 시간 간격을 반영하지 못한다.

### 2.3 하드코딩된 가맹점/지역 사전
- `direct_high_coverage_classifier.py:241-284` `EXPLICIT_DOMESTIC_NONTRAVEL`
- `direct_high_coverage_classifier.py:148-153` `KNOWN_DIRECT_TRAVEL_TOKENS`
- `direct_high_coverage_classifier.py:157-167` `FOREIGN_DIRECT_USE_MERCHANT_TOKENS`
- `direct_trip_cluster_registry.py:46-71` `REGION_COUNTRIES`, `REGION_LABELS`

이 목록들은 규칙상 "학습 자료로만 사용"함에도 불구하고 high-coverage 정책의 핵심 분기를 좌우한다. 새로운 PG, 새 여행지, 병합/브랜드 변경 시 silent misclassification 위험이 있다.

---

## 3. 논리적 허점 (Logical Loopholes)

### 3.1 Gate5가 비최종 상태를 'PASS'로 위장
Gate5는 `final_count=2,184`, `nonfinal_count=3,144`, `auto_provisional_count=3,143`인데도 `accepted_with_auto_provisional_queue`로 통과한다. 전체 결제 5,328건 중 **59%가 자동 임시큐에 묶여 있으면서도 Gate5는 PASS**다. 이는 "fail-closed"라는 전체 설계와 모순된다. `auto_provisional`은 여전히 `needs_review`이며, 비용축 확정·배분·전기로 흐르지 않지만, Gate5 PASS는 후보가 "충분히 검증됐다"는 인상을 준다.

### 3.2 OTA 금액 허용률이 원장 지시사항 위반
- `direct_high_coverage_classifier.py:131` `OTA_AMOUNT_TOLERANCE_RATIO = 0.02`
- `docs/비용분류_지시사항_원장.md` A-최신: "일반적인 ±2% 차이는 근거가 아니다. 정확금액 또는 원천에 명시된 할인·수수료·환율 조정식이 있어야 금액 일치로 승격한다."

±2% 허용은 명시적으로 금지된 태도이며, 현재 코드에서 이를 `amount_tolerance` 경로로 허용하는 것은 지시사항 충돌이다. 다행히 tolerance 경로는 unique target 조건을 갖춰야 하지만, 원천에 조정식이 없는 한 여전히 근거 부족이다.

### 3.3 Manual travel-tab 금액 컴포넌트 매칭이 날짜를 무시
- `direct_high_coverage_classifier.py:661-740` `_manual_travel_amount_component_match`
- source + 절대금액만으로 매칭. 같은 금액의 다른 날짜 결제가 동일 여행탭으로 분류될 수 있다.
- merchant discriminator는 substring match(`in`)이라 오분류 가능성이 있다.

이 경로는 "결제일을 행사일로 쓰지 않는다"고 강조하지만, 반대로 날짜를 전혀 쓰지 않아 M:N 컴포넌트 내에서 날짜 충돌을 감지하지 못한다.

### 3.4 수기장부 신뢰도 왜곡
`docs/비용분류_지시사항_원장.md`는 "수기장부와 과거 분류값은 학습·후보 생성용일 뿐 증거가 아니다"라고 한다. 그러나:
- `direct_high_coverage_classifier.py:194-205` `CONFIRMED_TRAVEL_TARGET_PATHS`에 `manual_travel_tab_exact`, `manual_travel_tab_mn_target_invariant` 등이 포함돼 있어, 수기 여행 탭 분류가 allocation_target 확정 근거가 된다.
- `direct_validated_purchase_classifier.py`는 과거 라벨을 LOO 검증에 사용. 비록 target row를 peer set에서 제외하지만, 여전히 "정답"을 사후 채점에 사용해 모델 신뢰도를 과대평가할 수 있다.

A-최신 원칙과 A-최신-여행분류예외 절의 긴장이 있다. 후자는 "수기 여행 탭 분류 사실 자체는 강한 분류 근거"라고 하지만, 사용자 확인(`needs_review`) 전까지는 흐르지 않아야 한다. 현재 코드는 `CONFIRMED_TRAVEL_TARGET_PATHS`에 포함시켜 확정 경로로 사용하는 경우가 있다.

### 3.5 HAN equality 패키지가 외부 권한에 의존
- Gate4는 HAN equality validation이 정확히 1개 있어야 통과한다.
- `han_master_candidate.py`를 통해 외부 `master_ledger.csv`와 비교하는데, 이 파일은 저장소에 없고 외부 입력이다.
- 현재 `applied=false`, `authority_status=unattested`.

이는 납득할 수 있는 안전 장치이지만, **운영 정본이 되려면 외부 권한 파일이 없으면 영원히 PASS할 수 없는 구조**라 대안이 필요하다.

### 3.6 Gate6 baseline이 외부 파일에 의존
- Gate6는 `ledger/baselines/direct.json` 형태의 direct semantic baseline이 필요하다.
- 현재 `direct_baseline_unavailable`로 실패.
- baseline 생성 절차가 저장소/문서에 명확하지 않으며, 첫 후보는 어떤 baseline도 없어 항상 Gate6 실패가 불가피하다.

첫 baseline은 어떻게 승인되는가? 외부 승인 파일(approved transitions)도 `validate_approved_transitions`로 검증하지만, 저장소에 샘플/템플릿이 없어 재현 불가능하다.

---

## 4. 현재 수용안의 위험

| 위험 | 설명 | 영향 |
|---|---|---|
| **대량 자동 임시처리** | 3,144건을 `auto_provisional`로 묶고 Gate5 PASS | 운영자가 "통과"로 오인, 실제 확정률 41%에 불과 |
| **금액 허용률 충돌** | ±2% OTA 매칭이 원장 지시 위반 | 세무 신뢰성 저하, 향후 검토 시 반박 대상 |
| **하드코딩 의존** | 가맹점/지역/한도 상수 고정 | 새로운 거래 유입 시 silent 오분류 증가 |
| **Gate6/HAN 외부 의존** | baseline·master ledger 없으면 영구 차단 | 운영 전환 불가, 지속적인 수동 개입 필요 |
| **수기→확정 누수** | 수기 여행탭이 확정 경로에 포함 | A-최신 "증거 아님" 원칙 훼손 가능성 |

---

## 5. 대안 계획

1. **Gate5를 단계별로 엄격화**
   - `auto_provisional`을 Gate5 PASS 조건에서 제외하거나, 최소한 `final_count / total > 80%` 같은 비율 게이트를 추가.
   - `TRAVEL_UNASSIGNED_ACCEPTANCE_LIMIT`을 상수가 아닌 "이전 승인 baseline 대비 증감률"로 정의.

2. **OTA 금액 허용률 제거 또는 제한**
   - `OTA_AMOUNT_TOLERANCE_RATIO = 0.02`를 0으로 조정하거나, 명시적 원천 조정식(`discount_formula`, `exchange_adjustment`)이 있는 경우에만 허용.
   - `OTA_MAIL_SERVICE_PERIOD_TOLERANCE_*` 경로를 별도 검토 게이트로 이동.

3. **manual travel-tab 매칭 강화**
   - `_manual_travel_amount_component_match`에 날짜 윈도우(예: ±7일) 추가.
   - merchant discriminator를 substring match에서 정규화된 토큰 교집합으로 변경.

4. **하드코딩 사전 외부화**
   - `REGION_COUNTRIES`, `EXPLICIT_DOMESTIC_NONTRAVEL`, `KNOWN_DIRECT_TRAVEL_TOKENS`를 JSON 설정 파일로 분리하고 버전 관리.
   - 변경 시 별도 regression 테스트를 통과하도록 문서화.

5. **Gate6 baseline 부스트래핑**
   - 첫 baseline은 "모든 결제가 `travel_unassigned`/`기타비용`으로 fail-closed 종결"된 상태로 생성.
   - 이후 사용자 확인/OTA 추가/수기 매칭이 이뤄질 때마다 approved transitions 파일로 baseline을 점진 승격.

6. **HAN equality 권한 절차 문서화**
   - `master_ledger.csv` 생성 주체, 검증 주기, 권한 갱신 절차를 `docs/`에 기록.
   - 테스트 환경에서 HAN equality를 mock으로 통과하는 샘플 패키지를 저장소에 포함해 재현 가능성 확보.

---

## 6. 검증 이력

- `python3 -m unittest discover -s ledger/tests -p 'test_direct_trip_cluster_registry.py'` — 17 tests OK
- `python3 -m unittest discover -s ledger/tests -p 'test_direct_high_coverage_classifier.py'` — 36 tests OK
- `python3 -m unittest discover -s ledger/tests -p 'test_transition_gates_v2.py'` — 57 tests OK
- 전체 테스트 스위트는 실행 중(별도 background task).

원천 `ledger/data/` 행이나 개인정보는 읽거나 출력하지 않았음.

---

## 7. VERDICT

**VERDICT: FAIL**

사유:
1. Gate5가 3,144건(59%)의 비최종 `auto_provisional` 상태를 'PASS'로 처리해 후보의 실제 완성도를 왜곡한다.
2. OTA ±2% 금액 허용이 `docs/비용분류_지시사항_원장.md` A-최신 원칙과 직접 충돌한다.
3. Gate6 baseline과 HAN equality 권한이 외부에 의존해 재현·운영 승격이 불가능한 상태다.
4. manual travel-tab 금액 컴포넌트 매칭과 하드코딩된 상수/사전이 미래 데이터 정확성을 위협한다.

PASS 조건:
- Gate5에서 `auto_provisional`을 PASS 조건에서 제외하거나 비율/품질 기준 추가.
- OTA 금액 허용률을 원장 지시에 맞게 제거/제한.
- Gate6 baseline 생성 및 HAN equality 권한 절차를 문서화하고 저장소에 재현 가능한 샘플 포함.
- 위 변경에 대한 추가 regression 테스트와 Sol/Luna 재검증 완료.
