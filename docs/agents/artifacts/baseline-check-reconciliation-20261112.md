# 배포된 계약과 기존 검사 대조 (2026-11-12)

기준은 `f4b60b3594c01fae2cb6e029b6fbe9ed587d5e53`이다. #815의 완료 기간 정책은 이 브랜치에 포함하지 않는다. 현재 소유자 지시는 기존 실패 22건의 원인을 분류해 먼저 별도 PR로 검수하는 것이다. skip·xfail로 실패를 숨기거나 원본·금융·수동 교정 보호 기대값을 낮추지 않는다.

근거:

- **P3**: [통합 명세 §1](../../SPEC.md), [PROC-003·PROC-004](../../policy/process.md). 사용자 확인 대기·미배정·미분류 UI를 폐지하고 분기 검수에서 완료된 판정을 교정한다. 기존 코드 `4ef19b67db9f7b7334ad1fc415fbcf055466d919`의 목적지 중심 전환도 기준 main에 포함돼 있다.
- **W3**: [승인·배포된 wave3 #799](https://github.com/6Soo/cost/pull/799), merge `e5e7bb5f551db5ce69365c2bc10899f12863d416`. 현재 홈의 자료 상태/업로드 CTA, 여행 목록, 카드 내역, 명시적인 거래 수정 패널로 정렬한다. [운영 인계](../../session_handoff.md)의 #809·wave3 단일 배포 기록이 배포 근거다.
- **AI**: [AI 판정 표시 #810](https://github.com/6Soo/cost/pull/810), merge `0da7e052d861a90b58ee52ee58dc2886e4d0a667`. 출처·근거 표시와 금융 보호를 사용자 질문과 구분한다.

아래 22건은 **(a) 코드 결함 2건, (b) 승인된 변경으로 대체된 옛 계약 검사 20건**이다. 12·13번은 옛 질문 DOM을 정렬한 뒤 실제 코드 결함을 확인해 고쳤다. 390/1440 하위 검증은 각각 한 실패로 센다. `CardFlowBrowserTests` 이름은 `webapp/tests/test_card_flow_browser.py`, 그 밖의 이름은 표의 파일 안에 있다. 최종 실행 결과와 SHA는 PR에 기록한다.

| # | 검사 | 옛 기대값 | 대체 근거 | 새 검사 |
| --- | --- | --- | --- | --- |
| 1 | `tests/test_board_export_helpers.py::test_tabs_html_parity_with_baseline` | 2384cfd의 분류대기·미배정 표시와 바이트 동일 | P3/PROC-004 | 대체된 두 표시만 기타비용으로 정규화한 뒤 전체 HTML·조회 동등성 유지 |
| 2 | `test_autonomous_workflows.py::test_import_cleanup_keeps_legacy_filter_bookmarks[no_item-classification]` | 내 확인 필요 안내·링크 | P3, W3 | 같은 유효 필터 URL·302·200 유지, 카드 내역과 P3 링크 부재 |
| 3 | 위 검사 `[no_trip-classification]` | 위와 같음 | P3, W3 | 위와 같음, 잘못된/중복 필터 400 유지 |
| 4 | 위 검사 `[protected-evidence]` | 위와 같음 | P3, W3 | 위와 같음, 보호 필터 매핑 유지 |
| 5 | 위 검사 `[other_review-classification]` | 위와 같음 | P3, W3 | 위와 같음 |
| 6 | `test_autonomous_workflows.py::test_browser_home_trip_export_download` | 옛 주요 메뉴 /board 및 이전 여행 아코디언 | W3 | 홈의 전체 여행 링크로 이동·실제 여행 선택·XLSX 다운로드와 셀 값 검증 유지 |
| 7 | `test_card_cleanup_ui.py::test_render_cleanup_breakdown` | 항목 미분류12·여행 미배정12 | P3 | 원 입력20건의 카드 자료·장부7건 표시 및 대기 문구 부재 |
| 8 | `CardFlowBrowserTests.test_legacy_cleanup_links_migrate_to_actions_and_history` | /import 해시→/my-actions | P3, W3 | /cards/all 이동·P3 부재·잘못된 필터 거부·모바일 너비 유지 |
| 9 | `CardFlowBrowserTests.test_home_has_no_pending_ledger_state_at_mobile_and_desktop_widths` | .home-status/.home-review/.home-trip·5여행이 첫 화면 안에 있음 | W3, P3 | .home-overview/.home-primary/여행 표, 대기 CTA 부재·전체6여행·첫 행 가시성·마지막 행 실제 스크롤·가로 넘침0 |
| 10 | `CardFlowBrowserTests.test_home_card_upload_cta_opens_integrated_workspace_without_writing` | 홈 질문함 CTA·보조 업로드 링크 | W3, P3 | 주 업로드 CTA 실제 클릭·닫기·파일 선택 상태·원본 hash·장부 무쓰기 유지 |
| 11 | `CardFlowBrowserTests.test_upload_entry_opens_new_file_details_without_changing_selection` | .home-secondary 업로드 링크 | W3 | .home-primary 실제 클릭·파일 입력·초기 선택 상태·JS 오류 없음 |
| 12 (a) | `CardFlowBrowserTests.test_low_confidence_assignment_is_editable_and_does_not_require_approval_to_preview` | 질문 항목·저장하고 자동 반영 버튼·미배정 장부0행; 정렬 후 분기 목적지를 여행 ID로 검증해409 | P3/W3는 DOM 정렬 근거. PROC-004는 미배정 대신 분기 탭으로 종결 | 유효 분기 탭 저장 때 trip_id는 빈 값. 탭 검증·수동 교정 재분류 후 유지, 유효 분기 내부 장부/화면 각1행·중복 없음. Google 쓰기 없음 |
| 13 (a) | `CardFlowBrowserTests.test_legacy_batch_transaction_link_and_scoped_rule_edit` | #questions 안의 거래·자동 판정 질문; 정렬 후 기존 규칙 목록이 비어 있음 | P3/W3는 DOM 정렬 근거. 코드에는 renderRules 최초 호출/GET이 없고 저장 후에만 목록을 그림 | 최초 상세·규칙 진입 때 기존 읽기 API로 규칙을 로드. 실제 브라우저 규칙 선택·저장 및 source/amount/조건 범위·중복 기록 보호 유지 |
| 14 | `CardFlowBrowserTests.test_mobile_full_flow_and_reupload` | 업로드 후 질문 답변·재사용 질문 체크박스 | P3, W3 | 업로드 후 명시적 교정·규칙 관리·동일 파일 재업로드, 원행 및 장부 1회 기록 유지 |
| 15 | `CardFlowBrowserTests.test_review_evidence_labels_render_distinct_reasons_without_generic_warning` (390) | 질문 항목의 확인 권장 배지와 #questions | P3, W3, AI | 결과 표의 거래·귀속 근거·명시적 수정, 질문/보류 대기 DOM 부재·가로 넘침 검사 |
| 16 | 위 검사 (1440) | 위와 같음 | P3, W3, AI | 같은 실제 결과 표·명시적 수정 및 넓은 화면 너비 |
| 17 | `test_expense_cleanup.py::test_the_primary_menu_has_one_expense_cleanup_entry_and_no_rail_unassigned_section` | 지출 정리 메뉴 | W3, P3 | 정식 /cards/all의 거래 메뉴 하나·미배정/정리 메뉴 부재 |
| 18 | `test_expense_cleanup.py::test_cleanup_cards_hide_per_row_ai_inputs_and_protect_held_rows` | 일반 행 분류 상태 배지 문구 | W3, P3 | 현재 출처 배지와 근거/수정, 보호 행 폼·AI 제안·보호 해제 부재 유지 |
| 19 | `test_expense_cleanup.py::test_cleanup_shows_reason_counts_without_hiding_unposted_expenses` | 내 확인 필요0건 제목 | P3 | 질문 카운터 부재, 기존 전체5건·진단 필터별3/1/1·원행 노출 유지 |
| 20 | `test_expense_workspace.py::test_core_tasks_are_primary_and_management_is_disclosed_with_reachable_panels` | questions 및 별도 분류 지시 rule-panel/rule-text 필수 | P3, W3 | edit-panel·기존 규칙 편집 입력 필수, 질문·별도 지시 패널 부재, 4개 탭/ARIA/관리 접힘·CSRF 유지 |
| 21 | `test_provisional_trip_review.py::test_import_has_one_review_flow_and_does_not_write` | /import GET200·검토 컴포넌트 | W3, P3 | 정식 카드 경로302·no-store·DB 전체 무변경 |
| 22 | `test_provisional_trip_review.py::test_real_browser_owner_review_paging_pending_approval_without_hold_controls` | 옛 /import 페이지의 전역 csrf | W3 | 합성 서버 토큰으로 독립 컴포넌트 초기화, 기존 페이징·수동 교정·규칙 승인·보호/감사·반응형 행동 유지 |

별도 **(c)** 재현·결정성 개선 대상:

| 검사 | 관측/원인 | 수정 및 확인 |
| --- | --- | --- |
| `tests/test_p2_lock_io_regression.py::test_same_size_edit_with_restored_mtime_invalidates_source_stamp` | Windows `utime` 정밀도 반올림으로 set 전후 ns 자체가 달라질 수 있음 | 파일 생성 직후 표현 가능한 정수초 ns로 고정한 뒤 stamp 취득. 동일 크기·동일 mtime·내용 변경 감지 단언은 유지 |
| `ReceiptPageFlowTests.test_lost_upload_response_recovers_committed_original_without_retry` | 앞선 전체 1/1 timeout, 같은 head/base 단독 각각0/1; route.abort의 응답/body 완료 경합 의심 | 실제 POST 응답 body를 읽은 직후 브라우저 fetch 경계에 TypeError 1회 주입. 실제 저장·조회·복구 UI·원본1개·POST1회·새로고침 유지 검증. 실제 서버 네트워크 손실의 모든 타이밍을 결정적으로 재현했다는 주장은 아님 |
| `tests/test_p2_lock_io_regression.py::test_split_prompts_count_all_assembled_cases_toward_first_fifty` | 이번 파일 전체 실행1/1에서40≠30, 동시 영향 검사0/1. 네 번 sweep 사이 실시간1초가 지나 split 재시도가 due가 되는 실행 시간 의존 | 이 검사가 의도한 동일 시점의 벽시계만 고정하고 실제 monotonic 예산은 유지. first50·AI30 기대값은 그대로 검사 |

원본 실패 로그와 기준 대조는 #815 담당 worktree의 비공개 `.local-archive/closed-period-*`에 보존한다. 새 실행 로그는 이 브랜치 `.local-archive/`와 `quality-artifacts/`에 보존한다. 고객 원문·금액·식별값을 이 문서와 PR에 넣지 않는다.
