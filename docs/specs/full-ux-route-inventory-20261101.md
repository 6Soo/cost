# COST 운영 서버 라우트 조사 — 2026-11-01

`ledger_board.Handler`와 직접 dispatch하는 모듈의 경로 비교·접두사·ROUTES 상수를 조사했다. 아래의 접두사는 하위 동적 ID 경로를 포함한다. 정적 목록은 브라우저 수락 증거가 아니며, owner-only prefix는 실제 라우트 선언과 구분한다. 별도 비교 도구 `webapp/server.py`의 `/queue` 등은 운영 COST 라우트로 합산하지 않는다.

권한: 익명은 로그인/공개데모·health/ready·공개 자산만, owner 전용 업무와 API는 기존 서버 판정 유지. viewer의 장부·행·증거는 배정 여행과 허용 필드로 제한되며, 비허용 리소스404·owner 전용 작업 거절·CSRF를 유지한다. 정확한 메서드/인증 경계는 아래 소유 핸들러와 보호 테스트를 따른다.

|경로·접두사|소유 파일:줄|핸들러·선언|
|---|---|---|
|`/`|`webapp/card_flow.py:1981`|`dispatch`|
|`/`|`webapp/card_flow.py:2027`|`dispatch`|
|`/`|`webapp/card_flow.py:2029`|`dispatch`|
|`/`|`webapp/ledger_board.py:2554`|`_phase7_get`|
|`/`|`webapp/ledger_board.py:2560`|`_phase7_get`|
|`/`|`webapp/ledger_board.py:3538`|`do_GET`|
|`/`|`webapp/ledger_board.py:3630`|`do_GET`|
|`/`|`webapp/ledger_board.py:3659`|`do_GET`|
|`/`|`webapp/ledger_board.py:3667`|`do_GET`|
|`/`|`webapp/ledger_board.py:3673`|`do_GET`|
|`/`|`webapp/ledger_board.py:3706`|`do_GET`|
|`/`|`webapp/ledger_board.py:3730`|`do_GET`|
|`/`|`webapp/ledger_board.py:3746`|`do_GET`|
|`/`|`webapp/ledger_board.py:3848`|`do_POST`|
|`/access/admin`|`webapp/ledger_board.py:2457`|`_phase7_get`|
|`/access/logout`|`webapp/ledger_board.py:2299`|`_auth_routes`|
|`/access/me`|`webapp/ledger_board.py:2454`|`_phase7_get`|
|`/access/providers`|`webapp/ledger_board.py:2463`|`_phase7_get`|
|`/access/rows`|`webapp/ledger_board.py:2510`|`_phase7_get`|
|`/api/audit/changes`|`webapp/ledger_board.py:3685`|`do_GET`|
|`/api/bank-imports`|`webapp/access_control.py:152`|`owner-only prefix`|
|`/api/bank-imports`|`webapp/ledger_board.py:3985`|`do_POST`|
|`/api/board/tsv`|`webapp/ledger_board.py:3509`|`do_GET`|
|`/api/cards/transactions`|`webapp/access_control.py:144`|`owner-only prefix`|
|`/api/cards/transactions`|`webapp/ledger_board.py:3751`|`do_GET`|
|`/api/cards/transactions/day`|`webapp/ledger_board.py:3753`|`do_GET`|
|`/api/cards/transactions/day`|`webapp/ledger_board.py:3802`|`do_GET`|
|`/api/cards/transactions/detail`|`webapp/ledger_board.py:3753`|`do_GET`|
|`/api/cards/transactions/detail`|`webapp/ledger_board.py:3794`|`do_GET`|
|`/api/cards/transactions/summary`|`webapp/ledger_board.py:3815`|`do_GET`|
|`/api/cards/transactions/undated`|`webapp/ledger_board.py:3819`|`do_GET`|
|`/api/cards/transactions/years`|`webapp/ledger_board.py:3811`|`do_GET`|
|`/api/classification`|`webapp/access_control.py:154`|`owner-only prefix`|
|`/api/classification/conversation`|`webapp/ledger_board.py:3711`|`do_GET`|
|`/api/classification/conversation/advance`|`webapp/ledger_board.py:3950`|`do_POST`|
|`/api/classification/conversation/advance`|`webapp/ledger_board.py:3973`|`do_POST`|
|`/api/classification/conversation/confirm-draft`|`webapp/ledger_board.py:3952`|`do_POST`|
|`/api/classification/conversation/confirm-draft`|`webapp/ledger_board.py:3975`|`do_POST`|
|`/api/classification/conversation/late`|`webapp/ledger_board.py:3971`|`do_POST`|
|`/api/classification/conversation/open`|`webapp/ledger_board.py:3969`|`do_POST`|
|`/api/classification/conversation/owner-draft`|`webapp/ledger_board.py:3953`|`do_POST`|
|`/api/classification/conversation/reasons`|`webapp/ledger_board.py:3951`|`do_POST`|
|`/api/classification/conversation/reasons`|`webapp/ledger_board.py:3974`|`do_POST`|
|`/api/classification/conversation/turn`|`webapp/ledger_board.py:3970`|`do_POST`|
|`/api/classification/dialog`|`webapp/ledger_board.py:3720`|`do_GET`|
|`/api/classification/dialog/answer`|`webapp/ledger_board.py:3947`|`do_POST`|
|`/api/classification/dialog/answer`|`webapp/ledger_board.py:3966`|`do_POST`|
|`/api/classification/dialog/close`|`webapp/ledger_board.py:3948`|`do_POST`|
|`/api/classification/dialog/close`|`webapp/ledger_board.py:3967`|`do_POST`|
|`/api/classification/dialog/note`|`webapp/ledger_board.py:3946`|`do_POST`|
|`/api/classification/dialog/note`|`webapp/ledger_board.py:3972`|`do_POST`|
|`/api/classification/dialog/open`|`webapp/ledger_board.py:3965`|`do_POST`|
|`/api/classification/dialog/resume`|`webapp/ledger_board.py:3949`|`do_POST`|
|`/api/classification/dialog/resume`|`webapp/ledger_board.py:3968`|`do_POST`|
|`/api/classification/rules`|`webapp/ledger_board.py:3737`|`do_GET`|
|`/api/classification/rules/`|`webapp/ledger_board.py:3726`|`do_GET`|
|`/api/classification/rules/`|`webapp/ledger_board.py:3742`|`do_GET`|
|`/api/classification/rules/apply`|`webapp/ledger_board.py:3955`|`do_POST`|
|`/api/classification/rules/apply`|`webapp/ledger_board.py:3961`|`do_POST`|
|`/api/classification/rules/draft`|`webapp/ledger_board.py:3959`|`do_POST`|
|`/api/classification/rules/preview`|`webapp/ledger_board.py:3954`|`do_POST`|
|`/api/classification/rules/preview`|`webapp/ledger_board.py:3960`|`do_POST`|
|`/api/classification/rules/revise`|`webapp/ledger_board.py:3962`|`do_POST`|
|`/api/classification/rules/scope`|`webapp/ledger_board.py:3964`|`do_POST`|
|`/api/classification/rules/supersede`|`webapp/ledger_board.py:3963`|`do_POST`|
|`/api/demo/top3`|`webapp/google_demo_page.py:76`|`dispatch`|
|`/api/demo/top3`|`webapp/google_demo_page.py:17`|`dispatch constant`|
|`/api/expenses/manual`|`webapp/ledger_board.py:3982`|`do_POST`|
|`/api/exports`|`webapp/access_control.py:153`|`owner-only prefix`|
|`/api/exports/`|`webapp/ledger_board.py:3658`|`do_GET`|
|`/api/exports/`|`webapp/ledger_board.py:3661`|`do_GET`|
|`/api/exports/xlsx`|`webapp/ledger_board.py:4015`|`do_POST`|
|`/api/flight-passengers/assign`|`webapp/flight_passenger_page.py:15`|`dispatch constant`|
|`/api/flight-passengers/candidates`|`webapp/flight_passenger_page.py:15`|`dispatch constant`|
|`/api/flight-passengers/name-search`|`webapp/flight_passenger_page.py:15`|`dispatch constant`|
|`/api/imports`|`webapp/access_control.py:151`|`owner-only prefix`|
|`/api/imports`|`webapp/card_flow.py:1981`|`dispatch`|
|`/api/imports`|`webapp/card_flow.py:2080`|`dispatch`|
|`/api/imports`|`webapp/ledger_board.py:3924`|`do_POST`|
|`/api/imports/`|`webapp/card_flow.py:1982`|`dispatch`|
|`/api/imports/`|`webapp/ledger_board.py:3702`|`do_GET`|
|`/api/imports/reclassify-pending`|`webapp/card_flow.py:2009`|`dispatch`|
|`/api/imports/rules`|`webapp/card_flow.py:2053`|`dispatch`|
|`/api/imports/rules`|`webapp/card_flow.py:2131`|`dispatch`|
|`/api/income`|`webapp/access_control.py:157`|`owner-only prefix`|
|`/api/income`|`webapp/ledger_board.py:3979`|`do_POST`|
|`/api/live/state`|`webapp/ledger_board.py:2503`|`_phase7_get`|
|`/api/live/state`|`webapp/ledger_board.py:3596`|`do_GET`|
|`/api/maintenance/refund-pair/`|`webapp/card_flow.py:1980`|`dispatch`|
|`/api/maintenance/request-metrics`|`webapp/access_control.py:142`|`owner-only prefix`|
|`/api/maintenance/request-metrics`|`webapp/ledger_board.py:3448`|`do_GET`|
|`/api/ota`|`webapp/access_control.py:146`|`owner-only prefix`|
|`/api/ota`|`webapp/ota_catalog.py:1407`|`dispatch`|
|`/api/ota`|`webapp/ota_catalog.py:1437`|`dispatch`|
|`/api/ota-refresh-state`|`webapp/ota_catalog.py:1407`|`dispatch`|
|`/api/ota-refresh-state`|`webapp/ota_catalog.py:1413`|`dispatch`|
|`/api/participants`|`webapp/access_control.py:160`|`owner-only prefix`|
|`/api/participants/insurance-match`|`webapp/insurance_income_match_page.py:7`|`dispatch constant`|
|`/api/participants/link`|`webapp/participant_income_page.py:24`|`dispatch constant`|
|`/api/participants/participant`|`webapp/participant_income_page.py:25`|`dispatch constant`|
|`/api/participants/state`|`webapp/participant_income_page.py:516`|`dispatch`|
|`/api/participants/state`|`webapp/participant_income_page.py:24`|`dispatch constant`|
|`/api/participants/trip-panel`|`webapp/participant_income_page.py:506`|`dispatch`|
|`/api/participants/trip-panel`|`webapp/participant_income_page.py:24`|`dispatch constant`|
|`/api/participants/unlink`|`webapp/participant_income_page.py:25`|`dispatch constant`|
|`/api/receipts`|`webapp/receipt_review.py:690`|`dispatch`|
|`/api/receipts`|`webapp/receipt_review.py:31`|`dispatch constant`|
|`/api/receipts/edit`|`webapp/receipt_review.py:792`|`dispatch`|
|`/api/receipts/edit`|`webapp/receipt_review.py:32`|`dispatch constant`|
|`/api/receipts/group`|`webapp/receipt_review.py:785`|`dispatch`|
|`/api/receipts/group`|`webapp/receipt_review.py:34`|`dispatch constant`|
|`/api/receipts/image`|`webapp/receipt_review.py:707`|`dispatch`|
|`/api/receipts/image`|`webapp/receipt_review.py:32`|`dispatch constant`|
|`/api/receipts/learn`|`webapp/receipt_review.py:698`|`dispatch`|
|`/api/receipts/learn`|`webapp/receipt_review.py:773`|`dispatch`|
|`/api/receipts/learn`|`webapp/receipt_review.py:33`|`dispatch constant`|
|`/api/receipts/learn/delete`|`webapp/receipt_review.py:781`|`dispatch`|
|`/api/receipts/learn/delete`|`webapp/receipt_review.py:33`|`dispatch constant`|
|`/api/receipts/scan`|`webapp/receipt_review.py:783`|`dispatch`|
|`/api/receipts/scan`|`webapp/receipt_review.py:31`|`dispatch constant`|
|`/api/receipts/tsv`|`webapp/receipt_review.py:692`|`dispatch`|
|`/api/receipts/tsv`|`webapp/receipt_review.py:32`|`dispatch constant`|
|`/api/receipts/ungroup`|`webapp/receipt_review.py:790`|`dispatch`|
|`/api/receipts/ungroup`|`webapp/receipt_review.py:34`|`dispatch constant`|
|`/api/receipts/upload`|`webapp/receipt_review.py:674`|`dispatch`|
|`/api/receipts/upload`|`webapp/receipt_review.py:713`|`dispatch`|
|`/api/receipts/upload`|`webapp/receipt_review.py:32`|`dispatch constant`|
|`/api/receipts/vision`|`webapp/receipt_review.py:723`|`dispatch`|
|`/api/receipts/vision`|`webapp/receipt_review.py:32`|`dispatch constant`|
|`/api/receipts/vision/new`|`webapp/receipt_review.py:765`|`dispatch`|
|`/api/receipts/vision/new`|`webapp/receipt_review.py:33`|`dispatch constant`|
|`/api/receipts/vision/rescan`|`webapp/receipt_review.py:741`|`dispatch`|
|`/api/receipts/vision/rescan`|`webapp/receipt_review.py:33`|`dispatch constant`|
|`/api/reserve-link/plan`|`webapp/ledger_board.py:2475`|`_phase7_get`|
|`/api/reserve-link/state`|`webapp/ledger_board.py:2476`|`_phase7_get`|
|`/api/review/apply/plan`|`webapp/ledger_board.py:2483`|`_phase7_get`|
|`/api/review/guidance`|`webapp/ledger_board.py:2491`|`_phase7_get`|
|`/api/review/model`|`webapp/ledger_board.py:2491`|`_phase7_get`|
|`/api/rows`|`webapp/access_control.py:156`|`owner-only prefix`|
|`/api/rows/`|`webapp/ledger_board.py:3693`|`do_GET`|
|`/api/rows/`|`webapp/ledger_board.py:3697`|`do_GET`|
|`/api/tabs`|`webapp/ledger_board.py:3681`|`do_GET`|
|`/api/tabs/`|`webapp/ledger_board.py:3505`|`do_GET`|
|`/api/tabs/`|`webapp/ledger_board.py:3506`|`do_GET`|
|`/api/tabs/`|`webapp/ledger_board.py:3689`|`do_GET`|
|`/api/tabs/`|`webapp/ledger_board.py:3691`|`do_GET`|
|`/api/trips`|`webapp/access_control.py:155`|`owner-only prefix`|
|`/assets/fonts/`|`webapp/ledger_board.py:3627`|`do_GET`|
|`/assets/ota/`|`webapp/ledger_board.py:3617`|`do_GET`|
|`/assets/ota/`|`webapp/ledger_board.py:3620`|`do_GET`|
|`/auth/callback`|`webapp/ledger_board.py:2273`|`_auth_routes`|
|`/auth/login`|`webapp/ledger_board.py:2253`|`_auth_routes`|
|`/auth/state`|`webapp/ledger_board.py:2310`|`_auth_routes`|
|`/board`|`webapp/ledger_board.py:2560`|`_phase7_get`|
|`/board`|`webapp/ledger_board.py:3538`|`do_GET`|
|`/cards`|`webapp/card_flow.py:1981`|`dispatch`|
|`/cards`|`webapp/card_flow.py:1998`|`dispatch`|
|`/cards/all`|`webapp/access_control.py:143`|`owner-only prefix`|
|`/cards/all`|`webapp/ledger_board.py:3513`|`do_GET`|
|`/demo`|`webapp/google_demo_page.py:17`|`dispatch constant`|
|`/download`|`webapp/ledger_board.py:3658`|`do_GET`|
|`/evidence/original/`|`webapp/ledger_board.py:2544`|`_phase7_get`|
|`/evidence/preview/`|`webapp/ledger_board.py:2535`|`_phase7_get`|
|`/expense/new`|`webapp/ledger_board.py:3654`|`do_GET`|
|`/export`|`webapp/access_control.py:148`|`owner-only prefix`|
|`/export`|`webapp/ledger_board.py:3656`|`do_GET`|
|`/flight-passengers`|`webapp/flight_passenger_page.py:15`|`dispatch constant`|
|`/google-ledger/expense-reconciliation`|`webapp/sheet_expense_review.py:15`|`dispatch constant`|
|`/healthz`|`webapp/ledger_board.py:3405`|`do_GET`|
|`/import`|`webapp/access_control.py:147`|`owner-only prefix`|
|`/import`|`webapp/card_flow.py:1981`|`dispatch`|
|`/import`|`webapp/card_flow.py:2031`|`dispatch`|
|`/import`|`webapp/card_flow.py:2034`|`dispatch`|
|`/import`|`webapp/ledger_board.py:3650`|`do_GET`|
|`/income/`|`webapp/ledger_board.py:2579`|`_phase7_get`|
|`/income/`|`webapp/ledger_board.py:3672`|`do_GET`|
|`/income/new`|`webapp/ledger_board.py:3652`|`do_GET`|
|`/lineage`|`webapp/ledger_board.py:3694`|`do_GET`|
|`/lineage`|`webapp/ledger_board.py:3697`|`do_GET`|
|`/ota`|`webapp/access_control.py:145`|`owner-only prefix`|
|`/ota`|`webapp/ota_catalog.py:1407`|`dispatch`|
|`/ota/booking`|`webapp/ota_catalog.py:1407`|`dispatch`|
|`/ota/booking`|`webapp/ota_catalog.py:1420`|`dispatch`|
|`/participants`|`webapp/access_control.py:159`|`owner-only prefix`|
|`/participants`|`webapp/participant_income_page.py:24`|`dispatch constant`|
|`/participants/insurance-match`|`webapp/insurance_income_match_page.py:7`|`dispatch constant`|
|`/preview`|`webapp/card_flow.py:1967`|`dispatch`|
|`/readyz`|`webapp/ledger_board.py:3405`|`do_GET`|
|`/receipts`|`webapp/receipt_review.py:688`|`dispatch`|
|`/receipts`|`webapp/receipt_review.py:31`|`dispatch constant`|
|`/reserve-links`|`webapp/ledger_board.py:2475`|`_phase7_get`|
|`/review`|`webapp/ledger_board.py:2491`|`_phase7_get`|
|`/review`|`webapp/ledger_board.py:3531`|`do_GET`|
|`/row`|`webapp/ledger_board.py:2566`|`_phase7_get`|
|`/row`|`webapp/ledger_board.py:3637`|`do_GET`|
|`/rows`|`webapp/ledger_board.py:3689`|`do_GET`|
|`/rows`|`webapp/ledger_board.py:3691`|`do_GET`|
|`/rules`|`webapp/access_control.py:150`|`owner-only prefix`|
|`/rules`|`webapp/ledger_board.py:3675`|`do_GET`|
|`/share`|`webapp/social_preview.py:50`|`dispatch`|
|`/split`|`webapp/ledger_board.py:3672`|`do_GET`|
|`/trips`|`webapp/access_control.py:149`|`owner-only prefix`|
|`/trips`|`webapp/ledger_board.py:3699`|`do_GET`|
|`/tsv`|`webapp/ledger_board.py:3505`|`do_GET`|
|`/tsv`|`webapp/ledger_board.py:3506`|`do_GET`|
|`/versions`|`webapp/ledger_board.py:3725`|`do_GET`|

경로/접두사 고유값 124개, 파일·핸들러 참조 206개. 일반 API·자산·이전 호환 경로는 독립 메뉴로 만들지 않는다.

보조 조사 결과는 위 소스와 대조했다. 초기 외부 작업자 보고의 owner/viewer 혼합 표기, 비교 서버 경로, `/insurance-match` 별칭 주장은 운영 근거로 수락하지 않았다. 실제 경로는 `/participants/insurance-match`다.
