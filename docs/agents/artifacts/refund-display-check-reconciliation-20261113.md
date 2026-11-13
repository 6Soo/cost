# 환불 표시 검사 대조표 (2026-11-13)

승인 범위는 헤드의 A~D 및 후속 1~4다. 기준 SHA는 `335b9eda`이며 병합·배포는 헤드가 한다. 아래 표는 수정 단위별 근거다. 검사 실행 실패 개수와 파일 개수는 구분한다. 이전 물음표로 손상된 표와 잘못된 #810 근거를 이 표로 대체한다.

## 대체 근거

- **P3**: [PR #737](https://github.com/6Soo/cost/pull/737), PROC-003·PROC-004. 분류 대기·unassigned 화면을 폐지하고 실여행 또는 원문 날짜 기준 분기 목적지를 표시한다. legacy GET 인자는 수용하지만 분류 필터로 쓰지 않는다. 원본 오류·중복·환불·수동 교정 보호는 유지한다.
- **W3**: [PR #799](https://github.com/6Soo/cost/pull/799), `/cards/all`이 정식 거래 진입점인 wave3 내비게이션 계약. #816 대조표의 동일 근거를 참조한다.
- **DATE**: [PR #755](https://github.com/6Soo/cost/pull/755), 승인/이용일 우선·매입일 fallback의 모든 조회 일관성. 날짜 원본은 보존한다.
- **ORIGIN**: [PR #481](https://github.com/6Soo/cost/pull/481), `08486b88`: `assignment_status.classification_source_label`을 공통 `classification_provenance.label`에 연결. 알려진 자동 출처는 `자동`, 모르는 출처는 `출처 미확인`. #810의 AI 배지 변경을 일반 출처 변경 근거로 쓰지 않는다.
- **RELATION**: [PR #435](https://github.com/6Soo/cost/pull/435)·[PR #438](https://github.com/6Soo/cost/pull/438), `1f070bb7`, [M:N 명세의 운영 수락 기록](../../history/specs-20261110/ota-undated-many-to-many-20261101.md). 게시 projection에 `payment_relation`이 추가됐다.
- **CLOSED**: [PR #815](https://github.com/6Soo/cost/pull/815), PROC-072, `f9bca8b9`. 완료 자료 제외를 위해 실제 `posting_date`와 여행 객체 mapping/조회가 필요하며 `user_completed_period`는 보존한다.
- **REGION**: [TRIP-044](../../policy/trip.md#trip-044--국내외-구분), 2026-10-31 소유자 결정. 해외 사용국과 여행국은 달라도 되며 국내외 구분과 검증 일정·이용일이 우선한다.
- **AIR**: [ITEM-029](../../policy/item.md#item-029--스카이티켓-항공료), 2026-11-08 소유자 결정. 어드벤처코리아의 새 거래는 항공료 기본값이며 기존 원행의 사용자 교정은 보존한다.

## 건별 변경

경로 약어: CP=`tests/card_pipeline/`, T=`tests/`, W=`webapp/tests/`. (b)는 승인된 계약에 뒤처진 검사/fixture다. 운영 코드 결함을 고쳤다는 뜻이 아니다.

| 검사 | 분류 | 옛 기대값 또는 fixture | 대체 근거 | 새 검사와 유지 보호 |
| --- | --- | --- | --- | --- |
| W/test_card_refund_destination.py::test_refund_destination_matches_tab_and_unassigned_counts (6개 parameter) | (b) | unassigned 조회에서 환불 행 제외, 비환불은 미배정, 승인일 공란이면 무날짜 | P3, DATE | legacy 조회가 전체 조회와 같음, 환불 탭 멤버·링크·연도 합계 유지, 비환불 분기 표시, 승인일 공란/매입일 유효 조회와 양쪽 날짜 공란 조회를 구분. 조회 전후 transactions 전체 불변 유지 |
| T/test_cards_all_quarter_labels.py::test_raw_internal_source_is_not_shown_in_details | (b) | 자동 분류 · 카드 잔여 비용 규칙 | ORIGIN | 자동 표시, owner_card_residual 내부 ID 미노출 유지 |
| T/test_cards_all_quarter_labels.py::test_unknown_source_does_not_expose_internal_identifier | (b) | 자동 분류 · 기타 근거 | ORIGIN | 출처 미확인. 내부 ID를 사용자 출처명으로 쓰지 않음 |
| CP/test_ota_coverage_audit.py::test_snapshot_worker_list_and_detail_share_one_solver_result | (b) | 게시 dict에 payment_relation 키 없음 | RELATION | fixture의 관계 미제공을 payment_relation=None으로 표현. 상태·transaction_id와 목록/상세 동일성 기대값 유지 |
| T/test_card_quarter_assignment_consistency.py::test_legacy_unassigned_filter_is_accepted_without_classification_filtering (옛 test_unassigned_filter_excludes_quarter_buckets) | (b) | 분기 제외 SQL과 valid_trip_ids 매개변수 | P3 | 폐지된 필터는 빈 where·빈 params |
| T/test_card_quarter_assignment_consistency.py::test_effective_destination_and_conflicts_are_separate_for_all_cases | (b) | completion_for_row에 여행 ID set만 제공 | CLOSED | 실제 계약인 ID→여행 mapping 제공. stale trip의 complete=False 기대값 그대로 |
| T/test_card_quarter_assignment_consistency.py::test_legacy_unassigned_sql_keeps_all_source_rows_including_refunds (옛 test_unassigned_sql_uses_same_verdict_and_preserves_refund_exclusion) | (b) | 폐지 필터에서 분기와 환불 행을 숨김 | P3 | legacy 조회는 원행을 모두 유지. 이는 금융 환불 보호 해제가 아니라 폐지 필터의 no-op 계약이며 실제 멤버십/장부 검사는 별도로 유지 |
| T/test_card_quarter_assignment_consistency.py::test_legacy_card_row_fallback_uses_quarter_without_trip_name_context (옛 test_legacy_card_row_fallback_keeps_trip_id_without_trip_name_context) | (b) | 검증 여행 context 없이 opaque ID를 표시 | P3 | 분기 표시, opaque ID 미노출, 입력 row.trip_id 불변 |
| CP/test_card3820_reconcile.py::test_refund_takes_the_original_purchase_placement | (b) | 최소 transactions schema에 posting_date 없음 | CLOSED | nullable posting_date 컬럼만 fixture에 추가. pair_refunds=1과 원결제 목적지·항목·refund_original 기대값 그대로 |
| CP/test_history_recovery.py::test_overseas_region_can_match_a_different_country_but_requires_valid_schedule (옛 test_currency_and_stale_schedule_cannot_supply_a_location) | (b) | 해외 국가가 다르면 거부 | REGION | SG 사용/JP 여행도 검증 일정에 맞으면 귀속. stale schedule 거부와 원본 country 판독 유지 |
| CP/test_history_recovery.py::test_explicit_overseas_trips_use_region_and_actual_use_date (옛 test_explicit_myoko_and_mongolia_trips_match_only_their_source_country) | (b) | JP/MN 국가 동일성 강제 | REGION | 실제 날짜로 각각 묘코·몽골 선택, country 인자 차이로 거부하지 않음 |
| CP/test_history_recovery.py::test_old_transactions_are_classified_without_a_preserved_state[True] | (b) | 기존 user_completed_period도 preserved 0건 | CLOSED | 기존 명시 preserved 1건 유지(False는 계속0). source_hash·금액·ID 및 ledger_entries=0 유지 |
| CP/test_history_recovery.py::test_owner_answers_keep_office_shared_and_travel_product_source_bound | (b) | 다른 source_hash의 어드벤처코리아는 needs_review | AIR | 새 source는 항공료/provider_default, 여행 없음. 기존 원행의 source-bound 여행상품비와 원문 hash·금액 불변 유지 |
| CP/test_history_recovery.py::test_online_supplier_cannot_be_assigned_by_payment_date_even_with_an_old_local_rule | (b) | 기본 항공료도 needs_review | AIR | classified/provider_default/항공료, 여행은 없음. 명시 source-bound 사용자 교정 우선과 결제일 기반 여행 오배정 금지 유지 |
| CP/test_history_recovery.py Board fixture의 get_trip (기존 추론 검사들) | (b) | list_trips만 있는 가짜 Board | CLOSED | 실제 Board의 get_trip 조회를 list_trips에서 제공. 추론·원본·수동 우선·유효 여행 기대값은 변경하지 않음 |
| W/test_card_destination_ui.py::test_home_and_sidebar_have_material_navigation_only | (b) | execute 결과 순회 미지원, 카드 내역 문구 필수 | CLOSED, W3 | SQLite cursor처럼 빈 순회 제공, 정식 /cards/all 링크 검사. 질문/확인 CTA 부재 유지 |

위 표는 (b) 변경 단위16행이다(동일 parameter 및 fixture 영향 검사 수와 구분). (a) 운영 코드 결함 수정0, (c) 검사 수정0, (d) 검사 수정0. 전체 실패의 분류 집계는 전체 실행 종료 후 별도 기록한다.

## 금융 보호 재확인

운영 소스 diff는 없다. `pair_refunds` 연결 1건·원결제 목적지/항목/refund_original 단언을 삭제·완화하지 않았다. 환불 탭 멤버십 6 parameter, 원본 SELECT * 불변, 합계 일관성은 유지했다. 순액·초과 환불·원본 충돌·수동 교정·다중도 검사의 기대값은 변경하지 않았다. 폐지된 unassigned 조회에서 환불을 숨기지 않는 것은 금융 기록 허용 조건을 바꾸지 않는다. skip/xfail 추가 없음.

## SRC-045

[기존 격차 기록](../../policy/CODE_GAPS.md)의 같은 tick 메타데이터 캐시는 **미해결**이다. 이전 #815 합성300회 중70회 재현과 별도로 이번 재개 세션에서 합성 파일300회 중1회 stamp가 같았다(내용 변경·크기 동일·mtime 복원). 실행은 저장된 `probe_same_tick.py`, 루트 PYTHONPATH를 설정한 Python이며 고객 자료는 없다. 캐시·해싱·읽기 예산을 변경하지 않았고 최초 ChangeTime을 과거로 결정화한 회귀 검사가 실제 동일 tick 누락을 해결했다는 주장도 하지 않는다. (c) 관측1건이며 검사 수정 건수0과 구분한다.

## 실행 상태

- 기준 전체: detached worktree `.local-archive/main-baseline-335b9eda-20261113/`에서 `335b9eda` 기준 1회 완료. **398 failed / 7222 passed / 4 skipped / 1511 subtests passed, 11472.34s(3:11:12), exit 1.** 로그 `pytest-full.log`, JUnit `pytest-full.xml`.
- 수정 전체: 메인 worktree에서 브랜치 `4f8e837c` 기준 1회 완료. **373 failed / 7248 passed / 4 skipped / 1510 subtests passed, 10285.18s(2:51:25), exit 1.** 로그 `.local-archive/refund-display-checks/branch-solo.log`, JUnit `branch-solo.xml`.
- 차집합 검증: 기준선 대비 실패 25건 감소 = 위 (b) 16단위가 덮는 실패 25건과 정확히 일치. 신규 실제 회귀 0. 간헐 요동 2건은 재실행으로 (c) 확정 — `test_receipt_page_flow…test_committed_upload_recovers_truncated_or_stalled_response_body`(브랜치 전체에서 우연 실패→단독 재실행 통과), `test_card_catalog_browser…test_menu_search_and_source_review_at_390`(기준선 우연 실패→브랜치 통과, 브랜치 미수정 파일). 재실행 2 passed/2 subtests 14.94s.
- 전체 결과·잔여 실패 분류 상세: [full-suite-20261113.md](full-suite-20261113.md).
- 영향 검사: `python tools/run_quality_checks.py --base origin/main --run` **PASSED.** 병합 커밋 `57c7c027`(base `3f5f7515`) 기준 **670 passed / 4 subtests passed / skip 0 / browser_skipped 0**, pytest_exit 0, 514.95s(8:34). 근거 `quality-artifacts/run-summary.json`·`pytest.log`(미추적). 이전 재실행의 유일 실패였던 OTA 브라우저 검사는 이번 통과.
- origin/main 이동: 작업 중 main이 `335b9eda`→`abaa5ba3`→`3f5f7515`(PR #823·#825·#827·#828·#829·#830, prep-cost=preparation_cost 계열 포함)로 진행. 기준선·수정 전체는 태스크 시작 시점인 `335b9eda`/`4f8e837c` 기준이며, PR 전 최신 origin/main을 브랜치에 통합했다(`test-impact-map.json` 자동 병합, `session_handoff.md` 양쪽 절 보존).
- PR·독립 검수: 대기. 병합·배포·운영 데이터 변경 없음. 테스트/영향 맵/문서뿐이어서 서버 배포 불필요.
