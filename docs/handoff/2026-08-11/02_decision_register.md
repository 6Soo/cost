# 사용자 결정 등록부

상태 표기:

- `CONFIRMED`: 사용자가 명시적으로 확정
- `IMPLEMENTED`: 코드에 반영됨
- `PENDING`: 설계·검증 필요
- `BLOCKED`: 외부 권한·원문·검증 부족

| ID | 사용자 결정 | 상태 | 적용 메모 |
|---|---|---|---|
| D-001 | VAT 항목 자체를 비용 분류에서 제외 | IMPLEMENTED | 세 축만 유지 |
| D-002 | 수기장부는 거래 증거로 쓰지 않음 | IMPLEMENTED | 학습·대상 분류 자료 |
| D-003 | 여행탭 존재·지역·날짜는 분류값으로 사용 가능 | PENDING | 대만 Phase 2는 별도 검증 필요 |
| D-004 | 여행탭 분류 자체는 강한 대상 분류 근거 | IMPLEMENTED | 개별 거래 증거와 분리 |
| D-005 | 카드 원장에 OTA 예약번호가 없어도 매칭 가능 | IMPLEMENTED | 승인번호·가맹점·금액·날짜·메일 조합 |
| D-006 | 결제일과 행사일이 다른 OTA·항공·숙박을 분리 처리 | IMPLEMENTED | 결제일을 행사일로 사용하지 않음 |
| D-007 | M:N은 공통 대상만 확정하고 1:1을 주장하지 않음 | IMPLEMENTED | 동일 cardinality·유일 대상 필요 |
| D-008 | 일반적인 2% 허용은 금지하고 근거 있는 경로만 허용 | IMPLEMENTED | tolerance는 candidate/finality 계약에 한정 |
| D-009 | 2026 행사 비용을 우선 처리 | IMPLEMENTED | 연도 무결성 Phase 1 |
| D-010 | 2025년 소액·오래된 건은 개별적으로 배정 제외 가능 | PENDING | 전체 일괄 삭제 금지 |
| D-011 | 사용자 질문을 기다리는 동안 남은 대사를 병렬 진행 | PROCESS | 다음 세션도 병렬 분석 유지 |
| D-012 | 대만 여행은 2026-01-07~14 | CONFIRMED | `0107_대만` 후보 context |
| D-013 | `0107_대만` 임시 대상명을 사용하고 추후 확정 가능 | PENDING | canonical allocation 경계 보완 필요 |
| D-014 | 메일은 kkokko-hero와 kew2000 원천을 전수 확인 | BLOCKED | 현 세션에서는 redacted/local evidence 범위만 사용 |
| D-015 | 후보를 게시·장부 전기하기 전에 독립 검증 PASS 필요 | IMPLEMENTED | Gate 4·6도 필요 |
| D-016 | 한 번에 500건 이하를 강제하지 않고 엄격한 규칙을 단계적으로 추가 | IMPLEMENTED | Phase 1 완료, Phase 2 설계 FAIL |

## 금지된 해석

- booking number가 없다는 이유만으로 카드 행을 탈락시키지 않는다.
- 결제일이 여행기간 안에 있다는 이유만으로 OTA 행사일로 확정하지 않는다.
- 수기행 하나를 카드 거래 하나의 영수증으로 취급하지 않는다.
- `auto_provisional`을 `final`로 세지 않는다.
- 과거 결과 수치를 현재 증거로 재사용하지 않는다.
- `Gate 5 passed`를 전체 cutover PASS로 말하지 않는다.

