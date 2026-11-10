# PR458 후속 리팩토링 검증 결과

[승인 범위](python-refactor-followup-20261102.md)의 자동분류 계획·지출정리 읽기/렌더와 기존 실패20건을 처리했다. 최초 기준은 `3410f395`다. 원 구현 `c5ee972d`와 후속 PR483을 복구·통합하면서 최신 상태/AI 출처 정책을 보존했다. 아래 최종 구조 비교는 **동일한 최신 기능을 가진 `f1e6453d` → 이번 통합 트리**를 비교하므로, 중간에 추가된 Google/상태 정책을 리팩토링 성과로 섞지 않는다. 실행 배포 SHA는 운영 기록에 따로 남긴다.

## 변경과 한계

- 자동분류 `plan`: 보호 판정, 환불 완료 판정, 이력 판정, 기존 배정 복원, 새 행 추론을 같은 모듈의 함수로 분리했다. 이미 검증한 fact 조건을 재사용하고 대상 조립을 한 경로로 통일했다. 미리보기의 전체 출력/digest, 원결제 의존 조회, 원자 적용 경계와 AI 판단 보호를 유지했다. 새 행 추론은 여전히 90행/82분기의 복잡한 정책 함수이며 전체 분류 엔진을 단순화했다고 주장하지 않는다.
- 지출정리: 카드/장부 집계 한 번을 건수·필터·페이지에 재사용하고, 취소 ID 조회를 재사용한다. 화면에 보이는 추론 행의 근거를 일괄 조회한다. 취소→충돌→보류→수정 순서는 기존 렌더러가 책임져 호출부의 네 중복 호출을 하나로 줄였다. 최신 네 사유 분류를 보존했다.
- 실제 결함: HTML 여행정보 저장 충돌에서 JSON만 반환해 입력 이름이 사라졌다. 409·최신 저장값을 보존하면서 입력 이름/작성일/담당자를 escape한 읽기 전용 입력으로 보여준다. 재저장·최신값 덮어쓰기는 하지 않는다. JSON 오류 응답 계약은 유지한다.
- Rust는 도입하지 않았다. 반복 조회 제거가 확인된 병목이고, 자동분류 계산 시간의 의미 있는 개선이 입증되지 않아 네이티브 변환·Windows 빌드/배포 비용을 추가하지 않았다. Rust 구현과의 성능 비교를 수행한 것은 아니다.

## 동일 방법의 구조 비교

`tools/python_structure_metrics.py`를 수정 없이 사용했다. AST 분기는 McCabe 전체 측정이 아니며 함수의 내부 분기도 포함한다. 물리 행에는 SQL/HTML 문자열·주석이 포함된다.

| 지표 | f1e6453d | 통합 후 | 판정 |
| --- | ---: | ---: | --- |
| 실행 Python 파일 | 209 | 209 | 동일 |
| 실행 Python 물리 행 | 83,809 | 83,809 | **코드량 감소 없음** |
| 실행 함수 AST 분기 합 | 21,674 | 21,670 | 4 감소, 0.02% 미만 |
| 실행 100행 초과 함수 | 102 | 101 | 1 감소 |
| 실행 동일 본문 중복 사본 | 2 | 2 | 개선 없음 |
| plan 길이 / 분기 | 186 / 140 | 63 / 29 | 정책별 책임 분리; 로직 삭제량과 다름 |
| render_expense_cleanup 길이 / 분기 | 338 / 132 | 304 / 130 | 집계·중복 호출 감소, 큰 함수 자체는 남음 |
| 비테스트 Python 전체 행 | 118,304 | 118,304 | 동일 |
| 전체 파일/import 이름 쌍 | 5,965 | 5,976 | 테스트에서 11 증가; 결합도 감소 아님 |

변경한 실행 세 파일의 import 이름 집합은 각각 전후 동일하다. 실행 의존성 감소는 없다. 동일 본문 검출에 잡히지 않는 반복 SQL·렌더 호출은 실제 diff와 조회 수로 별도 검증했다. PR483 단독의 이전 중간 수치는 기준이 다르므로 최종 수치와 합산하지 않는다. 저장소 전체의 작은 총분기 감소를 대규모 구조 개선으로 해석하지 않는다.

## 성능과 동등성

| 같은 합성 입력 | 기준 중앙값 | 통합 후 중앙값 | 결과 |
| --- | ---: | ---: | --- |
| 자동분류 200행·이력20행·실제 여행 형태20개, 7회 교차 | 64.44ms | 64.12ms | 실질적으로 동일, 개선 주장 안 함 |
| 지출정리 2,000행·페이지20행, 9회 순서 교대 | 148.30ms | 133.46ms | 약11% 처리량 비율 개선(시간 약10% 감소) |
| 지출정리 SELECT 수 | 58 | 35 | 23회/약40% 감소 |

전체 계획/digest와 전체 HTML을 같은 입력으로 비교해 동등함을 확인했다. DB 전체 테이블 전후 비교로 조회 무쓰기도 확인했다. 첫 순차 측정은 142.81→177.74ms로 느렸으며 이를 숨기지 않는다. 실행 순서·기계 부하에 민감해 후속 순서 교대 결과를 제한된 합성 성능으로만 보고한다. 이전 세션에서도 자동분류 89.92→91.18ms로 느린 표본이 있었다. 운영 전체 성능·메모리·장애율·개발시간은 미측정이다.

## 기존 실패20건의 판정

OTA13건은 `test_ota_matching_defaults.py`의 다음 과거 기대를 현 계약으로 교정했다. 임의 단일 카드 배정·원문 날짜 생성·금융 기록 확정은 허용하지 않는다. exact/manual·환불·고정 그룹 보호는 인접160건과 통합 집합에서 함께 검증했다.

| 테스트 식별자(`test_` 생략) | 판정 및 보존한 검증 |
| --- | --- |
| missing_payment_date_never_exposes_card_candidates | 낡은 날짜 필수 기대. 정확 근거 연결·paid_on 공란 유지 |
| partial_group_reserves_every_card_against_an_overlapping_group | 낡은 유일성 기대. 겹친 그룹의 M:N·원행 ID 보존 |
| missing_issuer_with_same_tail_across_issuers_is_ambiguous | 발급사 미상은 후보 그룹 유지, 임의 단일 선택 없음 |
| one_ota_with_two_same_card_candidates_is_a_reserved_partial_group | 1:2 관계·모든 카드 예약·개별 transaction_id 없음 |
| partial_repeated_group_preserves_all_ids_and_blocks_individual_posting | 관계 완료와 개별 금융 배정 분리·ID/건수 보존 |
| two_ota_one_card_keeps_ambiguous_status_with_exact_partial_counts_and_reservation | 2:1 관계·미대응 건수·카드 예약·개별 배정 없음 |
| repeated_group_never_crosses_issuer_or_card_tail | fixture의 미상 발급사와 같은 끝4 후보 유지; 명시 발급사 충돌 검사는 별도로 유지 |
| card_claimed_by_an_absent_linked_event_is_excluded_from_repeated_group | 수동 점유 a는 제외, 남은 b 관계만 보존 |
| frozen_group_signature_change_holds_members_and_keeps_cards_reserved | 고정 그룹 변경 보류·원 카드 예약 유지, 자유 카드만 새 관계 |
| equal_optimum_singleton_candidates_across_signatures_hold_as_a_component | 동률 후보를 그룹으로 유지, 임의 단일 선택 없음 |
| new_card_completes_partial_group_without_replacing_any_event_facts | 새 카드로 관계 추가, 예약 원문 사실 보존 |
| acceptance_04_signed_lag_range_matches_candidates_and_rejects_outside_days | 승인된 -1~+2일만 후보, 범위 밖 제외 |
| acceptance_07_item_scoped_rule_exposes_exact_and_delta_edges_separately | 숙박 exact/delta와 항공 exact의 항목 경계 유지 |

화면6/안내1건은 아래와 같다. 충돌1건은 테스트의 접힌 영역 접근을 고친 뒤 실제 입력 손실 결함도 고쳤다. 따라서 20건은 단순 문구 교체만으로 해결한 것이 아니다.

| 테스트 | 판정·현재 검증 |
| --- | --- |
| ViewStateTests.test_the_filter_keeps_itself_when_the_trip_changes | 접힌 이전 여행의 분기까지 펼쳐 실제 링크 클릭·필터 유지 |
| ViewStateTests.test_the_row_screen_uses_the_shared_chrome_and_keeps_its_meaning | 내부 revision 노출 기대 제거, 숨김 expected_revision=1 검증 |
| ViewStateTests.test_the_trip_screen_uses_the_shared_chrome_and_keeps_its_actions | 실제 관리 영역 펼침·h1·저장/보관/삭제·revision 값 검증 |
| ViewStateTests.test_archiving_from_the_trip_screen_moves_it_to_the_drawer | 관리 영역 펼침 후 실제 보관과 보관 목록 검증 |
| ViewStateTests.test_the_delete_preview_still_shows_and_confirms | h1 기대 정비·실제 deleted 상태/목록 제거 추가 검증 |
| ViewStateTests.test_a_stale_trip_revision_is_reported_and_the_typed_name_is_kept | 409·원래 입력/최신 저장값 동시 보존·읽기 전용·XSS 차단 |
| ScreenTests.test_an_unset_profile_asks_for_the_assignee_at_creation | 폐기된 안내 대신 빈 담당자 입력·기존 여행 불변 안내·미설정 상태 검증 |

인접 검사에서 현재 main에도 재현되는 분기카드 출처 문구1건(PR483), 지출정리 문구3건과 준비 가능 문구1건도 현재 계약으로 정비했다. 숨김 입력·여행 선택·보류·조회 무쓰기·링크 보호 단언은 보존했다.

## 검증 근거와 미실행

- 최종 통합 표적 `verified-final.xml`: **348 passed**. OTA/M:N/환불, 자동분류/P2 교정, 전체 계획/digest, 전체 HTML/조회 무쓰기, 기존 화면/안내 및 지출정리 포함. 추가 단건 문구 최종 확인1 passed는 합산하지 않는다.
- 권한/CSRF·HTML 거절 인접 검사 `resume-permissions.xml`: **15 passed / 3 failed / 26 subtests passed**. 3실패는 기준 `f1e6453d`에서 동일 재현(`refusal-baseline.xml`): 과거 `#archived a.arch-view`, `#arch-toggle`, 규칙 화면의 내부 row ID 노출 기대. 이번 변경의 통과나 기존20건에 포함하지 않으며 관련 없는 셸 재작성으로 확대하지 않았다.
- ego-browser 실제 합성 HTTP: 2페이지20행·21~40건, 사용자 보류 빈 필터, 390px 넘침0, 충돌409·입력 정확 유지·읽기 전용·스크립트 실행0·최신 여행 링크 PASS. TaskSpace4 정상 종료. 운영 고객 자료 수정을 위한 브라우저 쓰기는 하지 않았다.
- 과거 일괄 결과는 중복이 있어 합산하지 않는다. 보관 근거 `.local-archive/refactor-followup-20261102/`: ota-final.json, seven-before.xml, verified-final.xml, resume-equivalence.xml, resume-permissions.xml, refusal-baseline.xml, pr483-before.json, verified-structure.json, automatic/cleanup-benchmark.json, resume-browser-final.json.
- 전체 회귀·실기기·실제 고객 입력 부하/운영 전체 성능은 미실행. 금융/분류/여행 대량 재처리·Google 최종 장부 쓰기·신규 스키마/마이그레이션은 범위 밖이며 수행하지 않는다.
