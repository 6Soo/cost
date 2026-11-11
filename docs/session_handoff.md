## 2026-11-12 B 근거 도달률 측정·기간 가드 완료 — 모델 호출·운영 변경 없음

- 기존 색인 10,013건(종류 집계는 mail_directory 원천 연결 13,557행)에서 금액 필드 10,013건, 통화 222건, 예약번호 패턴 1,494건, 이용기간 패턴 289건을 읽기 전용으로 집계했다.
- 재선정 후보 148건의 조건별 도달률: T1 정확 금액·통화 32건, T1∪T2 75건, T1∪T2∪T3 75건, T1~T4 전체 합집합 75건, 무근거 73건이다. 무근거는 `nice` 색인은 있으나 조건 불일치 57건, 공급자 색인 자체 없음 17건(other 15·기타 2)으로 나뉜다. 상세는 `evidence-reachability.json`이다.
- P2 결과 가드를 추가했다. 인용 발췌에 서비스 날짜가 글자로 없으면 기간을 비우고, 근거가 0건이면 기존 여행 유지·기간 미확인·낮은 확신만 허용한다. 날짜 표기 정규화와 네 가지 회귀 테스트를 포함해 표적 테스트 54건이 통과했다.
- 옛 거래 685건은 여행 `0206_하쿠산`(2027-02-06~02-09)에 붙어 있었고 카드일 범위는 2025-07-21~2025-11-25, 승인일 685건 모두 없음, 금액 합계 145,589,412원(약 14,558.9만원)이다. 읽기 전용 `board_rows`에 표시 0건·여행 귀속 0건으로 화면·합계·지출내용 복사 투영에 나타나지 않았다. 원본 카드 자료는 열지 않았다.
## 2026-11-12 P1 운영 등록 완료·2층 재선정 오프라인 판정 COMPLETE — 반영·배포 없음

- 승인된 211개 P1 규칙을 인증된 `/api/imports/rules` 경로로 등록했다. API 성공 211건, 읽기 전용 active 규칙 990개(기존 779+신규 211), `rule.created` 감사 211건, 등록 구간의 비규칙 변경 0건이다. 367건 항목 일치 367/367, 수동·기록·닫힌 분기 변경 0, Google 0이다. 근거는 `p1-registration-verify.json`이다.
- B 대상에서 카드일(승인일, 없으면 매입일)이 2026-04-01 이전인 행을 제외했다. 승인일 없는 2025년 매입 685건은 전부 `trip-c03c66308638`, 장부 기록 0건, 1층 367건 중 140건이었다. 자동 교정하지 않았다.
- 재선정 후보 148건에서 금액 상위 10건과 결정적 무작위 10건을 선택했다. 근거는 정확 금액·통화 또는 공급자+금액 조건만 허용했고, 사건별 후보 여행 enum·허용 항목 enum·evidence_refs 스키마를 사용했다.
- sol 호출 20건, JSON 스키마 응답 20/20, 의미 검증 11/20, 여행 변경 0건, 이용기간 신규 입력 13건, 기존 항목 유지 1건, 근거 첨부 2/20(10%)이다. 의미 검증 실패는 근거 ID 불일치와 근거 없는 확신 등 9건이며 운영 반영·배포는 0건이다. 입력 총량·추정 토큰과 표는 `../.local-archive/p2-layer2-20261112-rerun/summary.json`, `table.md`에 있다.
## 2026-11-12 P1 재검증 PASS·P2 2층 20건 오프라인 판정 COMPLETE — 운영 반영 없음

- `unclassified`↔빈 `display_tab_id`를 동일한 표시 탭 없음으로 처리하는 비교 조건을 추가했다. 동일 `trip_id`, 장부 미기록, 수동 결정 아님을 모두 확인한 1건만 정규화로 인정했다. 규칙 효과는 `item`만이며 여행 귀속을 쓰지 않는다. 사본 재검증은 규칙 211개·367행·충돌 0, 신규 영향 56건, 보호 변경 0, 표시 정규화 1건, 위반 0건으로 PASS했다.
- 2층 대상은 열린 분기 후보 833건(금액 상위 10 + 결정적 무작위 10)으로 고정했다. 14:36 백업의 OTA 근거 10,013건을 한 번 스트리밍 해제해 발췌 색인(SQLite 131,461,120 bytes, 118,837,496 bytes 읽기, 16.78초)을 만들었다.
- `gpt-6.1-sol` 실제 도구 없는 호출 20건이 모두 JSON 스키마 응답으로 완료됐다. 결과는 미리보기 파일에만 저장했고 반영·운영 쓰기·Google 쓰기·배포는 0건이다. 20건 중 항목 변경 20건, 근거 미검출 8건, 허용 항목명과 다른 출력 13건을 관찰했다. 허용 항목명 정규화와 근거 없는 고확신 출력이 오판 위험 유형이다.
- 결과: [layer2-summary.json](../.local-archive/p2-layer2-20261112/layer2-summary.json), [layer2-table.md](../.local-archive/p2-layer2-20261112/layer2-table.md), [a-final.json](../.local-archive/p2-layer2-20261112/a-final.json). 운영 등록은 하지 않는다.
## 2026-11-12 P1 규칙 승격 사본 검증 STOP — 운영 반영 없음

- 중단된 후속 작업을 재개해 `tools/p2_rules/rehearsal.py`를 수정했다. 기존 활성 규칙과 211개 신규 규칙을 각각 명시적으로 주입해 역사적 재분류와 신규 규칙 영향을 분리했다.
- 대상은 이미 반영된 367건이며, 신규 규칙 표 211개·367행·충돌 0건이다. 사본 검증 결과 신규 규칙 추가 영향은 56건, 항목 변경 0건, 수동·기록·닫힌 분기 보호 변경 0건이다.
- 단, 1건에서 `display_tab_id`가 `unclassified`에서 빈 값으로 바뀌어 여행 귀속 불변 조건을 위반했다. 식별자는 SHA-256만 `.local-archive/p2-layer2-20261112/rehearsal-stop.json`에 기록했다. 규칙 등록은 하지 않았다.
- 운영 DB 쓰기 0건, Google 쓰기 0건, 배포 0건이다. 표적 테스트 49건 통과. 2층 20건 오프라인 판정은 P1 보호 조건이 해소될 때까지 실행하지 않는다.
- 다음 작업은 표시 탭 보호 경로를 별도 서버 작업으로 수정·검수한 뒤 동일 사본 검증을 재실행하는 것이다.
# 현재 상태

## 2026-11-12 P2 1층 367건 반영 COMPLETE — #809·wave3 단일 배포 완료

- **현재 지시 완료:** 잘못된 `webapp` 상대 import를 서버 `app` import로 고치고 실제 tuple 조회도 수정했다. [#809](https://github.com/6Soo/cost/pull/809) 최종 `7ca80c966f1acde7d66219109690d049991e0f99`는 독립 `gpt-6.1-sol / medium` APPROVE, 검수자 직접 릴리스 HTTP1 passed/13.39초다. wave3 #799를 포함한 병합·운영 SHA는 `8644e873514367a21a181f3e39c1a2028d5ab024`, 이전 운영은 `68fbe0dd`다. 공식 배포1회·롤백0, 1646파일/blob불일치0·Board/Worker SHA 일치·보호13표 불변·backend8751/unpaused 확인. CI job130615412341는 결제한도 미시작(step0)이며 최종 검수 근거를 PR에 기록했다.
- **검사 사실:** 기존 app 직접 호출 검사는 HTTP handler의 lazy import와 실제 LedgerStore tuple 연결을 실행하지 않아 놓쳤다. 새 검사는 Git archive로 임시 릴리스를 만들고 별도 `python -I`/비운영 임의 포트의 실제 HTTP에서 owner·CSRF 거부, preview 무변경, apply·장부/화면/감사·재전송 무변경을 확인한다. 영향 검사는699 passed/8 failed/35 subtests/skip0·compile/data guard PASS·지정 브라우저5검사 실행이며, 실패8건 모두 정확한 e5e7bb5f main에서도 원 테스트로 재현했다. 전체 QA는 FAILED로 유지하며 기존 테스트를 고치지 않았다.
- **배포 수락:** 00:26:12~00:41:12 KST의30초 간격 ready31회 모두200, 직후0.132초/5분1.335초/15분0.006초·최대7.016초. 운영 owner/CSRF 미리보기20건200·쓰기0 확인 후 반영 단계로 넘어갔다. 익명 브라우저 주요7주소401, CSS/JS는 별도 HTTP URL이 없어 실제 파일 내용의 인라인 포함으로 확인했고 폰트/아이콘200이다. 로그인 화면 시각 검사는 사용자 영역이다.
- **신선 복구·사본:** 짧은 읽기1.112초로 전체2852건·귀속 불일치109건을 다시 확인했다. 변경 후보368중1건 제외 후367건(기록227/미기록140)의 변경 전 세 행 전체를 보존했다. 사본20·50×6·47건의 적용/재전송/파일복원은 전부 일치, 불변 실패0이다. 전체 운영 DB의 새 사본은 만들지 않았다.
- **운영 반영367건 완료:** owner 인증·CSRF·요청ID·미리보기 digest 검증 API로20→50×6→47건,8묶음 모두 검증 PASS. `ai_inference`·근거·실행 정보·변경 전 감사 이력, 기존 장부/화면 동반 변경, 금액·귀속·원문·ID·수동/비대상·금융 보호 불변을367건 전체에서 확인했다. 되돌리기0·Google0·P1등록0·2층 실행0이다.
- **표시 검증의 오탐 보존:** 첫20건의 private 검증기가 출처에 `AI` 문자를 기대했으나 승인된 wave3의 상세 라벨은 `ai_inference`도 `자동`으로 표시한다. 독립 검수 후 실제 데이터 실패와 구분했고, 첫20건 모두 읽기 API의 거래 식별·항목·AI_INFERRED·정확한 제공자/모델/run_id/근거를 추가 대조해 통과했다. 최초 라벨 실패와 읽기15초 지연 기록을 숨기거나 테스트를 바꾸지 않았다. 마지막3건 실제 화면에서 근거를 펼쳐 AI 실행 정보 가시성까지 확인했다. 출처 라벨 자체는 여전히 `자동`이다.
- **종료 상태:** 00:54:20 KST ready200/0.045초, Board/Worker8644e873, P2/full=false. [분기 검수 목록](agents/artifacts/p2-open-quarter-attribution-review-20261112.md)에109건의 여행별 분포를 남겼고, 개별 거래 식별자는 비공개 해시만 보존한다. 아래 이전 차단/진행 기록은 이력이다. P1 규칙은 별도 작업자의 함수 검수 뒤 후속 지시를 기다리며 지금 등록하지 않는다.
- 비공개 근거 `.local-archive/p2-import-fix-20261112/`의 `final-summary.json`, `deploy-evidence.json`, `review.json`, `readyz-monitor.jsonl`, `monitor-result.json`, `anonymous-browser-smoke.json`, `runtime-final.json`, `apply367/{target-before.json,quarterly-review.json,prepare-summary.json,apply-batch-*.json,verify-batch-*.json,api-origin-batch-0.json,pilot-gate-resolution.json,ui-three.json}`. 코드 완료 SHA8644e873, 종료 기록은 이 문서의 최신 로컬 커밋이다. 현재 승인 범위의 남은 검사/차단 없음. 기존 사용자 QA3파일은 해시 일치 복원했고 미추적 파일을 보존했다.

| 옛 항목 | 새 항목별 실제 반영 건수 |
| --- | --- |
| 기타경비 | 교통비1, 수수료2, 식비1, 입장료1, 주차비1, 항공료1 (합7) |
| 현지경비 | 교통비39, 렌터카26, 숙박비27, 식비161, 입장료43, 주유비11, 주차비10, 통신비9, 통행료24, 항공료10 (합360) |

## 2026-11-12 P2 서버 진입점 수정 — wave3 통합·검증 진행

- 현재 지시는 Fable의 ImportError 수정→릴리스 HTTP 검사→wave3 포함 단일배포→367건 반영→P1 등록 없이 보고다. 이전 추가배포 금지는 이 후속 승인으로 대체됐다. #799는 `e5e7bb5f551db5ce69365c2bc10899f12863d416`로 병합됐고 이 main을 통합했다.
- 실제 운영 릴리스에는 `app/classification_correction.py`가 존재하며 `webapp/classification_correction.py`는 없다. 운영 로그가 잘못된 상대 import를 확인한다. launcher는 checkout을 sys.path 앞에 삽입하며 같은 운영 venv의 격리 probe에서도 app 모듈 경로/잘못된 webapp 모듈 부재를 확인했다(실행 중 프로세스 내부를 직접 조회한 것은 아님).
- 서버 진입점을 `from app import classification_correction`으로 수정했다. 새 HTTP 검사가 추가로 드러낸 trip_tabs tuple 인덱싱도 cursor.description을 사용해 고쳤다. 연결 row_factory와 금융/수동/열린 분기 보호는 바꾸지 않았다. 서버가 tools를 import하지 않는다.
- 새 `webapp/tests/test_p2_release_http.py`는 기존 git archive 절차로 HEAD를 임시 릴리스에 풀고 별도 `python -I`에서 애플리케이션 sys.path를 그 릴리스로 한정한다. 실제 서버의 비운영 임의 포트에서 owner 인증/CSRF 거부, preview200·무변경, apply200·장부/화면/감사, 재전송 무변경을 확인한다. wave3 통합 전/후 각각1 passed다. 기존 검사가 놓친 이유는 app 서비스를 직접 호출해 HTTP handler의 lazy import와 LedgerStore의 tuple 연결을 실행하지 않았기 때문이다.
- 영향 검사 코드 `2e224894`: 42파일707건, **699 passed/8 failed/35 subtests/skip0**, compile·추적 원본 guard 통과, 지정 브라우저5검사 실행·누락0. 실패8건 모두 정확한 기준 main `e5e7bb5f`의 별도 추출본에서 원 테스트 그대로 재현했다(8failed/errors0/skip0). 신규·미대조 실패0이며 전체 QA 통과로 표시하지 않는다. 기존 테스트·기대값은 바꾸지 않았다. 새 릴리스 HTTP 검사1건은 통과했다. 이후 `1de1b466`은 상태 문서만 추가했다. 기존 사용자 QA3파일은 해시 일치로 복원했다.
- 최종 검수·새 PR·공식배포·직후/5분/15분 ready·367건 신선 사본검사/반영은 아직 남았다. 비공개 재개점 `.local-archive/p2-import-fix-20261112/checkpoint.md`, 검사/기준 대조는 같은 폴더의 `quality/`, `baseline-comparison.json`, `baseline-failures.xml`이다. 고객 복구 파일과 QA 미추적 파일은 보존한다.

## 2026-11-12 wave3 #799 — 최신 main 통합 재검증 완료 (이 worktree 전용)

- **후속 #803 통합:** main `0281e90fa1e536b3a1d715c1a65033065121bec0`을 추가 통합했다. 변경은 국민 수집 전용 tools/tests, 영향 매핑과 문서이며 기존 app/webapp·UI·CSS·JS·159파일 테스트·quality 실행기는 동일하다. 위 159파일 검사·같은 main 실패 대조·합성 화면 근거를 재사용하고 `7188e202` 이후 변경 영향만 추가 검사한다. 추가 검사 결과와 이 통합의 최종 SHA 검수는 PR 최종 댓글을 정본으로 한다. 두 번째 문서 충돌도 양쪽 기록을 보존했다.

- **범위:** PR #799의 병합 검토 준비만 수행했다. 병합·운영 배포는 하지 않았다. 아래 이전 wave3 결과와 P2 기록은 이력이다.
- **검사 코드 SHA:** `9d4e99130708ed28a0d971c87ee508866a7a86ca`, 동일 main 비교 SHA `68fbe0ddb3543f96bfe5a7d1fc74ea737465b1a8`. 주요 UI 소스·CSS·JS는 이전 승인 `8a74e562`와 동일하며 통합 충돌은 인계 문서 한 곳의 양쪽 기록을 보존해 해소했다.
- **영향 검사:** `python tools/run_quality_checks.py --base origin/main --run`의 실행 경로를 파일별 3개 프로세스로 나눠 끝까지 기록했다. 깨끗한 고정 코드 SHA에서 159/159파일, **2317 passed / 33 failed / errors·skip·0건 파일·누락 브라우저 검사 0**, compile·추적 원본 guard 정상이다. 모든 파일의 실행 전후 HEAD가 같다.
- **실패 대조:** 실패 33건 모두 동일 main의 원 테스트에서 재현했다. 신규·미대조 실패 0. 전체 QA 통과로 표현하지 않는다. 이번 재개에서는 코드·테스트 변경이 없으며, 앞선 허용 정적/폐지 문구 단언 변경 목록과 복원한 행동 검사는 PR 본문에 유지한다.
- **화면:** 통합 코드에서 ego-browser 한 TaskSpace를 생성·캡처·종료한 390/1440 × 밝음/어두움 36화면과 복사 제외 내역 4상태를 확인했다. 가로 넘침 0, 제외 2행 같은 페이지 펼침·접힘·URL 유지와 합성 1행 45,000원 TSV 복사를 확인했다. 실제 카드 상세 200 응답·실자료·실기기·스크린리더·운영 인증 화면·320px 전체 화면·전 화면 대비/접근 이름 전수 검사는 미검증이다.
- **독립 검수:** 기존 `gpt-6.1-sol / medium` 검수자는 통합 diff에 추가 차단 결함이 없음을 확인했다. 이 상태 문서 보충 뒤 최종 SHA 판정은 PR 모델·SHA·판정 댓글을 정본으로 한다. 이전 SHA의 APPROVE를 새 SHA 승인으로 대체하지 않는다.
- **CI 차단:** run 43041722774/job 130594960713은 결제·지출 한도로 steps 0에서 시작하지 못했다. CI 통과가 아니다.
- **근거·다음:** `.local-archive/wave3-20261111/merged/`의 summary/comparison-summary/progress/combined.xml·파일별 JUnit/로그와 verified-*.json/png. 기존 미추적 QA 3개 파일을 보존했다. 최종 문서 커밋·push → 동일 독립 검수자의 최종 SHA 판정 → PR 댓글·Fable 보고. 그 뒤 병합 여부는 Fable이 결정한다.

## 2026-11-11 wave3 #799 — 병합 검토 준비 (이 worktree 전용)

- **범위:** `ui/wave3-20261110`, [PR #799](https://github.com/6Soo/cost/pull/799). Fable 지시에 따라 main 통합·검사·화면 확인·독립 검수까지만 수행하며 병합·운영 배포는 하지 않는다. 아래 P2 이력은 이번 작업 지시가 아니다.
- **완료 코드:** main `57c28ce973d3637b35a80c179c4b9c849aec93ac`가 합쳐진 `0daa3e13`에서 재개해 `86180b7ef3238619da3529cb6448330fac60f0a2`로 모바일 항목별 묶기·소계·원 날짜순 복원, 저장 상태 HTML 속성, 규칙 대화의 원래 여행 복귀, 영수증 화살표 넘침, 카드 오류 화면 거래 탭을 복구했다. 이 절을 추가한 커밋에는 규칙 대화의 닫힘·규칙 미생성 분기도 같은 여행으로 돌아가도록 하는 보충과 정적 URL 단언 1개가 포함된다. 최종 HEAD·독립 검수 판정은 PR의 모델·SHA·판정 댓글이 정본이다.
- **영향 검사 원 기록:** HEAD 메타데이터는 `86180b7e`로 고정하고 `run_quality_checks.main(['--base','origin/main','--run'])`의 pytest 실행만 파일별 2개 프로세스로 나눠 159/159파일·고유 JUnit testcase 2,343건을 끝까지 기록했다. 실행 중 규칙 복귀 링크 소스·정적 단언 2파일 보충이 작업 트리에 들어갔으므로 전체가 깨끗한 동일 소스 SHA 검사였다고 표현하지 않는다. 이 보충의 영향 대상은 최종 커밋에서 다시 검사한다. 원 결과는 2,309 passed / 34 failed / errors·skip·0건 파일·누락 브라우저 검사 0, compile·원본 추적 guard PASS다. 원 실패를 지우거나 전체 QA가 녹색이라고 보고하지 않는다.
- **실패 대조:** 같은 main SHA의 원 테스트 파일로 32개 고유 실패를 재현했다. OTA 실제 어댑터 1건은 main 표적 반복 3회째 동일 라디오 선택 timeout으로 재현한 기존 간헐 실패다(wave3 수정 없이 재검사 PASS도 보존). 나머지 1건은 규칙 복귀의 정적 `href='/board'` 단언으로, `href='/board?tab=T2026_01'`로 정렬 후 파일 6 passed. 보충을 적용한 유효 집계는 2,310 passed / 기존 실패 33(간헐 1 포함) / 신규 실패 0이다. 보충 커밋 뒤 동일 영향 선택기의 변경분 검사 결과는 PR 최종 검증 기록에서 확인한다.
- **검사 보호 복원:** 강제 goto·직접 dialog.close로 우회했던 실제 목록 복귀/저장 메모/닫기 클릭, 320·390 카드 상세 로딩·펼침·접힘·동일 URL·넘침, 작업 메뉴 Enter, 예약 iframe 현재 여행, OTA 실제 메뉴 이동, 영수증 펼침 후 넘침, 마감 필터, 현재 여행 viewer 허용 목록을 복원했다. 금액·원문·부호·ID·수동 교정·CSRF·동시 수정 보호 단언을 완화하지 않았다. 추가 기대값 정렬은 위 URL 1단언(b 유형)이며 PR 본문에 기재한다.
- **화면:** 합성 포트 8821(정식 모듈 실행)·8822/8823(합성 seed 추가)을 사용했다. 최종 코드의 ego-browser TaskSpace 22는 한 스크립트에서 생성·36개 대표 화면(홈·여행·장부·카드·OTA·영수증·수기 지출·환불·관리, 390/1440, 밝음/어두움)·복사 제외 내역 4개를 캡처한 뒤 종료했다. 가로 넘침 0. 제외 2행을 같은 페이지에서 펼치고 접었고 복사 TSV는 합성 식당 1건 45,000원이었다. 카드 원본 없는 제외 행의 404 대체 안내를 확인했으며 실제 카드 상세 200 응답·실자료·실기기·스크린리더·운영 인증 화면·320px 전체 화면·전 화면 대비/접근 이름 전수 측정은 이번 캡처에서 검증하지 않았다. 동작 회귀는 별도 pytest 근거와 구분한다.
- **근거:** 비공개 `.local-archive/wave3-20261111/final/`의 plan/progress/combined.xml/summary.json, 파일별 JUnit·log·exit, main 비교 기록, `ota-main-02.log`, `verified-render-results.json`, `verified-copy-results.json`, `dialog-link-recheck.xml`. 초기 중단·실패 로그와 기존 `quality-artifacts/` 미추적 3개 파일은 보존한다.
- **외부 차단·다음:** GitHub run 42907382198/job 130148811660은 결제·지출 한도 때문에 steps 0으로 시작하지 못했다. 이를 CI 통과로 표시하지 않는다. Fable이 최종 SHA 댓글의 sol medium 독립 판정을 보고 병합 여부를 결정한다. 운영 변경·고객 원본 접근·Google 쓰기는 없으며 운영 배포는 이 세션 범위 밖이다.
## 2026-11-12 P2 단계 2 — 귀속 불일치 제외 완료 / 서버 미리보기 API 오류로 반영 차단

- 도구 완료 커밋은 [PR #808](https://github.com/6Soo/cost/pull/808)의 병합 `befe868a444dbbae3d14feb1e8bb388e48575780`이다. 최종 `d60e4b200d8e53c767e0947aae182a5062417e1a`를 독립 `gpt-6.1-sol / medium`이 APPROVE했고 표적24건을 직접 재실행했다. CI job130607692586는 결제 한도로 시작되지 않아(step0) 승인 예외를 적용했으며 모델·SHA·판정·근거는 PR 댓글에 남겼다. 추가배포는 없다. 이 종료 기록은 로컬 커밋으로 보존한다.
- Fable 후속 지시로 사본 불변 실패 1건을 제외했다. 열린 분기 전체 2,852건에서 거래와 장부의 `trip_id` 또는 `display_tab_id` 불일치는 109건이다. 선정 단계와 미리보기에서 항상 제외하며, 이번 368후보 중 해당하는 건은 1건이다. 분기 검수 목록은 비공개 `run367/quarterly-review.json`에 해시만 보존한다.
- 나머지 367건(기록227·미기록140)을 신선 읽기 전용 조회(0.502초)로 준비했다. 사본20·50×6·47건 적용/재전송/파일복원 전부 통과, 불변 실패0·복원367일치다. 기존 중단 근거는 덮어쓰지 않았다.
- **BLOCKED:** 첫20건의 운영 `/api/p2-batch/corrections/preview`가 HTTP502를 반환한다. 운영 `68fbe0dd`의 `webapp/ledger_board.py:4720`이 `from . import classification_correction`에서 ImportError를 낸 것이 운영 로그로 확인됐다. 실제 모듈은 `app/classification_correction.py`다. 서버 변경·추가배포 금지 지시로 서버 코드는 수정하지 않았다. apply API는 미호출이며 운영 반영0·되돌리기0·Google0·P1등록0·2층0이다. 바뀐 거래가 없어 화면3건 확인도 미실행이다.
- API 실패 뒤 후보367건 전체 변경 전 값 일치, 비대상 거래/장부/화면 지문 및 보호13표 구성의 불변 조건 통과(그중 변경 허용3표도 이번에는 불변). 2026-11-12 00:05:27 KST `/readyz` 200/0.110초. 배포SHA68fbe0dd·P2 off는 직전 확인 근거이며 이번에 예약 작업을 다시 조회하지 않았다.
- 도구 표적24 passed, 최신main0281e90f 기준 영향 검사52 passed/skip0·compile/data guard PASS다. 기존 사용자 QA3파일은 해시 일치로 복원했다. 최종 SHA 독립 검수·PR 결과는 해당 PR에 기록한다. 비공개 근거 `.local-archive/p2-stage2-deploy/run367/{prepare-summary.json,target-before.json,scope-summary.json,quarterly-review.json,verify-batch--1.json,api-stop.json,quality/run-summary.json}`. 고객 원문·기존 QA 미추적 파일은 보존한다.
- 다음 서버 변경 때 수정할 항목 두 가지: P2 API의 잘못된 import, 항목만 바꾸는 요청에서 장부 여행 귀속까지 동기화하는 동작. 반영 재개에는 이 API 오류를 해결하는 별도 서버 변경·배포 지시가 필요하다. 이후 신선 값/미리보기/사본검증을 다시 하고 첫20건부터 시작한다. 최종 항목 전환은 없음(운영0건)이다.

## 2026-11-11 P2 단계 2 — #807 배포 완료, 사본 불변 검증으로 반영 전 중단

- 현재 승인 범위는 Fable의 단계 2 후속 지시다. #807은 최종 `0de29030902e7923ca345a224e9b45bbfb425b79`의 독립 `gpt-6.1-sol / high` APPROVE 후 `68fbe0ddb3543f96bfe5a7d1fc74ea737465b1a8`로 병합·공식 배포됐다. 이전 운영은 `8b116b98`다. 기존 표적 검사 44 passed/skip0·compile PASS 근거를 재사용했으며 이번 재개에서 코드·테스트는 바꾸지 않았다.
- 정리 결과 가맹점 212곳·변경 후보 368건이다. 명시적 기록 행 옵션의 신선 읽기 전용 preview는 368건 통과/보호 제외 0건(기록 228·미기록 140)이지만, **반영 가능 완료 판정은 아니다**. 과거 기본 옵션의 140 통과/228 제외와 구분한다.
- 운영 DB의 짧은 읽기(0.793초)로 후보의 거래·장부·화면 행 전체 변경 전 값을 `.local-archive/p2-stage2-deploy/target-before.json`에 보존했다. 전체 사본은 만들지 않고 메모리 사본에서 20·50×6·48건 적용/요청 재전송/파일 기반 복원을 검증했다. 368건 복원은 모두 일치했다.
- **중단:** 사본 1건에서 `ledger_entries.trip_id`와 `display_tab_id`가 항목 교정과 함께 변했다. 거래와 장부의 기존 귀속이 달라 저장 경로가 장부 귀속까지 동기화하기 때문이다. 여행 불변 조건 위반이므로 지시대로 첫 20건 운영 반영 전에 멈췄다. 운영 반영 0·운영 되돌리기 0·Google 쓰기 0·P1 등록 0·2층 실행 0이다. 개별 식별자는 비공개 근거에만 있다.
- 운영 대상 368건의 세 행 전체와 관련 14개 테이블 지문은 준비 시점 대비 불변이다. 배포 직후 보호13표 불변은 배포 근거이며 이번 중단 확인과 구분한다. Board·Worker 예약 작업은 68fbe0dd, route8752/unpaused, card-flow의 P2/full=false다.
- 준비 응답: 기존 5분 표본10회와 이후16회는 모두200. 한도로 15분 관찰 루프가 끊겼고 이를 연속 관찰 완료로 표시하지 않는다. 재개 23:52:28 KST 200/0.221초, 배포15분 이후 23:53:57 KST 200/0.168초를 별도 기록했다. 새 실패·롤백 조건은 없었다.
- 비공개 근거: `.local-archive/p2-stage2-deploy/{deploy-evidence.json,review.json,prepare-summary.json,simulation-problems.json,stop-verification.json,readyz-resume.jsonl}`. 최근 검증된 전체 백업은 `D:/WebLedgerHost/data/backups/p2-staged-20261111T143601/`, 복원 검증 사본은 같은 시각의 `data/restore-verification/` 하위다. 원본과 사용자 QA 미추적 파일은 보존했다.
- 다음은 Fable의 중단 보고 후 지시다. 문제 행을 조용히 제외하거나 여행 귀속을 자동 수정하지 않는다. 재개한다면 해당 장부 귀속 충돌의 처리 범위를 정한 뒤 신선 변경 전 값/미리보기/불변 검증을 다시 하고 첫20건부터 시작한다. 기록만을 위한 새 PR·재배포는 하지 않는다. 이 종료 기록의 커밋은 `git log -1 --oneline -- docs/session_handoff.md`로 확인한다.
## 2026-11-11 수집 스크립트 마무리 — #803 (P2 작업과 별도)

- 2026-11-12 재개: main `68fbe0dd`를 병합한 `92689b71`의 영향 검사는 **250 passed / 1 failed / skip0**, compile·data guard 통과다. 실패는 `tests/test_p2_lock_io_regression.py::test_split_prompts_count_all_assembled_cases_toward_first_fifty`의 `40 != 30`이며, 정확한 기준 main `68fbe0dd`의 독립 추출본에서도 동일 실패를 재현했다(관련 코드·테스트 diff 없음). 전체 QA 통과로 표시하지 않으며 P2 코드·기존 테스트는 변경하지 않았다. 국민50·OTA52 합성 검사를 재실행해 모두 통과했다. 근거는 `.local-archive/collection-resume/`의 `impact-92689b71.{json,log}`, `baseline-split.xml`, `collection-targeted.xml`이다. 이 기록을 포함한 최종 SHA의 별도 sol medium 검수와 병합 결과·병합 SHA는 [PR #803](https://github.com/6Soo/cost/pull/803)에 기록한다. 운영 배포는 없다.
- Fable의 이번 지시 범위는 E1/E2/E3 수집 코드·절차서·독립 검수·병합이며 운영 배포/고객 자료/로그인/운영 DB 접근은 제외한다. 주 작업 폴더와 wave3 worktree를 변경하지 않았다.
- E2 구현 커밋 `3c385d44`(기본 보완 `64ee1926`): 기본 Page 연결의 다운로드 대기/저장, 선택자 읽기·소스별 설정, 조회 뒤 관측, 주의사항 창, 실 XLS 파서/화면 건수 대조, 이전 manifest SHA 중복 검사와 `importBoundary=NOT_RUN`을 구현했다. 최종 인계 커밋은 이 절을 포함한 #803 head다.
- 검증: 국민 Node49·OTA Node52 표적 통과/skip0 후 launcher 합성 회귀 1건 추가 통과(국민 총50). 영향 검사 `python tools/run_quality_checks.py --base origin/main --run`은 구현 `3c385d44`에서 **244 passed / skip0**, compile·data guard 통과. 초기에는 outDir 호환 회귀와 P2의 `40 != 30`이 발생했고, outDir 회귀 수정 뒤 전체 재실행 통과했다. 기준 `57c28ce9`에서도 같은 영향 대상(국민 제외) 243 passed, 해당 P2 단독도 통과했다. P2 실패를 재현 가능한 기존 실패로 단정하지 않는다. 기존 테스트는 변경하지 않았다.
- E1은 #798 병합 `a050d65f`로 main에 있음. Trip 목록 `online.trip.com` 허용 및 API별 정확 origin/path 검사, 교환·위조 URL 거부 합성 회귀를 확인했다. OTA 제품 코드 추가 수정 없음.
- 실화면 확인: [국민 6항목](playbooks/card-downloads.md#실제-화면-확인-필요), [OTA 8항목](playbooks/ota-portal-collection.md#실제-화면-확인-필요). [하나·기업 조사 결과·미확인 사항](playbooks/card-login-research-20261111.md)은 기존 보고서 원문 사본이다.
- 남은 단계: 최종 head의 별도 `gpt-6.1-sol / medium` 이상 검수·PR 댓글 → 승인 시 병합. 실제 국민 화면·로그인·다운로드/DB 행 중복 리허설/가져오기, OTA 실사이트 수집·Booking 상세/변수 템플릿은 이번 완료 범위 밖이다. 운영 서버 호출 경로 변경·배포 없음. 기존 미추적 `.kb1`~`.kb4` 보존.

## 2026-11-11 P2 일괄 판정 단계 1 — 대상 확정·제안 생성 완료

- Fable이 일반 항목 1,258건·가맹점 585곳을 확정했고 서버 밖 도구로 제안을 생성했다. 운영 DB 읽기는 약 0.3초의 일관 조회 후 연결 종료이며 운영 DB 쓰기·새 전체 사본·배포·Google 사용은 없다. 완료 결과는 아래 작업판 및 이 문서의 후속 절에 기록했다.
- 날짜 수치 정정: 앞선 경계 이전 775건에는 빈 이용일이 포함됐다. 실제 이용일 경계 이전은 90건, 이용일이 없고 매입일만 이전인 건은 685건이다. 대상은 여행 귀속 기준이므로 1,258건·585곳으로 동일하다.
- 저장된 표시행 기준 화면 이용일 경고 함수 집계는 전체 441건·보호 제외 후 273건이다. 서버 메모리에만 있는 OTA 파생 근거는 읽지 않은 **상한치**다. 실시간 화면 건수 일치는 미검증이다. 닫힌 여행 12건은 여행별 건수만 작업판의 분기 검수 목록에 남기며 자동 교정하지 않는다.
- 재개 정보와 고객 자료 경로는 [작업판](agents/BOARD.md) 맨 위에 있다. 과거 대상 재정의 대기 기록은 현재 Fable 지시로 대체됐고, 과거 시범을 재실행하지 않는다.

## 2026-11-11 P2 일괄 판정 단계 0 — 대상 증가 보고 지점

- Fable의 새 두 층 일괄 판정 지시를 읽고 운영 `board.sqlite`를 `mode=ro`·`query_only`로 집계했다. 시작일 2026-06-30 이후 여행 48개, 귀속 기준 구매 2,852건(열린 여행 2,564 + 분기 기타비용 288). 수동 제외 282, 추가 금융/원본 보호 제외 163, 남은 2,407건이다.
- 일반 항목 1,258건·가맹점 585곳으로 예상 약 900건·450곳보다 약 40%·30% 많아, 지시된 즉시 보고·중단 지점에 도달했다. OTA·항공 추론 342건(기존 공급자 식별 함수 기준), 경계 이전 카드일의 열린 여행 구매 775건, 경계 이후 카드일의 닫힌 여행 구매 12건. 이용기간 미확인 수는 미집계이므로 단계 0은 미완료다.
- 비공개 근거 `.local-archive/p2-batch-20261111/{stage0.py,stage0-counts.json}`. 원문 출력·모델 호출·DB 쓰기·새 전체 사본·배포·운영 포트·Google 사용 없음. 기존 미추적 QA 파일/검수 메모와 이전 백업은 보존했다. 이번 체크포인트 커밋은 `git log -1 --oneline -- docs/session_handoff.md`로 확인한다. 코드 PR과 최종 SHA 검수는 아직 없다.
- 재개: Fable의 대상 증가 확인 → 거래별 보호 조회를 짧은 집계/메모리 처리로 교체 → 표시 근거 기반 이용기간 미확인 집계 → 단계 1 도구·합성 테스트·실제 sol 제안·문서 통합·독립 검수. 상세는 [작업판](agents/BOARD.md) 맨 위다. 단계 1·2와 운영 반영을 실행하지 않았다.

## 2026-11-11 최신 중단 — P2 대상 재정의 대기

Fable 지시에 따라 P-1·P-2 코드 수정·실측·모델 호출·백업 시도를 중단했다. 운영 P2는 비활성으로 유지하고 #803·wave3도 새 지시 전에는 시작하지 않는다. 보존 코드 브랜치는 `fix/p2-offline-assembly-20261111`, WIP 커밋은 `c34cd008a59b40bfd62cc61cc34082482993d24c`(로컬), 중단 전 코드는 `3eb5fe42e0feaa7231f85dbbf4eebe9b04c357cf`다. 실제 모델 호출·미리보기·반영은 0이다. 새 입력 예산·규칙 선택·선별 조회 요구는 구현하지 않았다. 고객 자료·임시 파일의 위치와 중단 전 기술 검증은 [작업판](agents/BOARD.md) 맨 위 절에 남겼다. 재개는 작업판의 "재개 정보" 맨 위에 있는 대상 선정 사실과 Fable의 다음 지시를 따른다. 문서 브랜치 `docs/p2-target-redefinition-stop-20261111`는 푸시만 하고 병합은 다음 문서 PR에 묶는다. 아래 실행 계획은 재개 승인이 아니다.

## 2026-11-11 최신 재개 — 오프라인 검증 전환

최신 실행 지시는 [작업판](agents/BOARD.md) 맨 위 절이다. 운영 `8b116b98`의 P2는 재승인 전까지 비활성으로 유지한다. 기존 결과 문서는 #806의 별도 sol medium 최종 검수 뒤 `57c28ce9`로 병합했다. 현재 브랜치는 `fix/p2-offline-assembly-20261111`다. 새 운영 API 백업은 준비 응답 지연으로 중단했고 생성한 부분 사본을 제거했다. 기존 14:36 API 백업을 읽기 전용으로 재사용하여 같은 탐지 순서 200건 모두 준비·보호 검사 통과를 확인했다. 첫 건은 메일 묶음 압축 2,570,172바이트/해제 19,229,366바이트가 `p2_source_io.unpack:202`의 8MiB 해제 제한에 걸려 조립 실패했다. 본문 발췌보다 앞선 경로다. 별도 작업자 `5d9252a6`가 분리 작업 폴더에서 원본 해시·충돌 보호를 보존하는 스트리밍을 구현 중이다. 관리자 근거는 `.local-archive/p2-offline-20261111/`의 `assembly-before.json`, `eligibility-200.json`, `backup-attempt2.json`~`backup-attempt5.json`이다. 새 백업 미완료는 최고 관리자에게 알렸으며 모델 호출·반영·운영 변경은 없다. 다음은 작업자 커밋 통합→같은 200건 조립·읽기량/시간 재측정→통과 때 실제 sol 20건 미리보기→보고·중단이다. 아래 절은 기존 시범의 이력이다.

## 2026-11-11 #805 재개 결과 — 5건 시범 중단, P2 off 유지

- **COMPLETE(수정·배포):** 전체 원문 충돌/base64 보존·포털 중첩 판정 필드 projection을 최종 `aee08a8b`의 별도 `gpt-6.1-sol / medium` APPROVE 후 #805로 병합했다. 운영 완료 커밋은 `8b116b98ccbacdc49c702e370031be2da45f5ef9`다. 공식 배포 도구 exit0, 릴리스1570파일/blob불일치0, Board·Worker·listener SHA 일치/backend8751, health/ready200·비인증API401·보호13표 불변이다. 사전 SQLite API 신선백업5DB와 별도복원 quick_check/schema/행수 검증 PASS(공식 도구의 BackupProducts 스위치는 별도 미사용).
- **검증:** 표적17 passed. 최종 코드8279f6ad 영향602 passed/1 failed/4 subtests/skip0·204.24초, compile PASS. 실패는 `test_split_prompts_count_all_assembled_cases_toward_first_fifty`의40 !=30이며 정확 운영기준5248d129에서도31 passed/동일1 failed로 재현했다. 테스트·기대값 불변, 전체 QA PASS 아님. 최종 문서 SHA aee08a8b 검수·병합 트리 동일 확인. CI 최종 head job130346428325는 결제 한도로 시작되지 않았다. 기존 사용자 QA3파일은 SHA256 확인 후 복원했다.
- **COMPLETE(P2 off 관찰):** 14:42:02~14:57:27 KST,15분 창+종료측정925.255초. ready32회 모두200, P2 호출0/대상0/실행이벤트0, 보호지문 불변, route sampled unavailable 최대0.8924초다.
- **FAILED(5건 운영 수락):** 14:57:49~15:02:12 KST,262.379초에 gateway8790 ready15.006초 timeout으로 즉시자동off. 후보3075/선정5/조립시작5·완료0/근거읽기시도2/모델시도0·성공0·실패0/preview0/반영0(각 회차 최댓값). `P2_SOURCE_RECORD_TOO_LARGE` 조립 실패가 두 회차에 기록됐다. 원본 레코드 중 어느 구조가 상한을 넘었는지는 이번 시범으로 확정하지 않았다. route최대18.133초는 중단선78.477초 이내였으며 직접 중단 조건은 ready timeout이다.
- **안전 종료:** 보호지문 불변, 진행중 모델호출0, P2/full=false, route8751 unpaused. 종료 후 health/ready는8751 200/200(0.110/8.896초),8790 200/200(0.008/0.013초)이다. 원본·수동교정·Google 변경 없음. 50건·전체확대·E2·wave3·세 번째 재시범은 실행하지 않았다.
- **미검증:** 운영에서 조립 완료·모델 입력이0건이므로 메일 절단 비율과 절단 후 예약번호/금액/날짜 구간 보존율은 측정할 수 없다. 합성 tail 구간 보호 검사는 통과했지만 운영 증거로 대체하지 않는다. dcbe4894의2000건/1.100GB/245.09초/합성3호출50반영은 메일 전용 합성 근거이며 포털 운영 수락이 아니다.
- **다음:** 승인된 중단 보고 지점에 도달해 Fable에 보고하고 멈춘다. 운영은8b116b98/P2 off 유지. 추가 원인 수정·재시범은 후속 지시에서 판단한다. 비공개 근거 `.local-archive/p2-staged-resume-20261111/`의 `resume805-deploy/`, `resume805-off15m/result.json`, `resume805-pilot5/{result,stage-summary,post-ready}.json`, `resume805-final-{summary.json,pytest.log,junit.xml}`, `resume-baseline-split.json`. 정확한 재개 확인 명령은 `Get-Content -LiteralPath .local-archive/p2-staged-resume-20261111/resume805-pilot5/stage-summary.json -Encoding UTF8`다. 이번 종료 기록은 로컬 커밋으로 보존하며 기록만을 위한 새 문서 PR·재배포를 만들지 않는다.

## 2026-11-11 #805 중단 작업 재개 — 최종 검수 준비

- 현재 작업은 #805의 근거 크기 수정과 승인된 단계별 재시범뿐이다. 전체 반영·E2·wave3는 실행하지 않는다. 운영 읽기전용 확인: P2/full=false, route8752 unpaused.
- 전체 메일로 원본 충돌을 검사한 뒤 P2 조립 경계에서만 20KiB 관련 구간을 발췌한다. 포털은 실제 `_read_records`의 중첩 `payload_json`에서 판정 필드와 price_components만 선택하며 raw 자료는 검색·출력하지 않는다. 실제 SQLite loader 합성·원본 불변·잘못된 JSON 보호 포함 표적17 passed.
- `dcbe4894` 규모 합성: 후보2000·근거1,100,346,849B·메일9174, 245.09초·고유조립50·합성모델3호출/50건·반영50, 근거읽기 첫1,102,565,348B/이후0. 조립은 route/runtime/board/DB쓰기 잠금 밖, 경쟁 DB쓰기 최대대기0.0079초. 실제 모델 호출이나 운영 반영 증거는 아니다.
- 영향검사 `dcbe4894`: 599 passed/1 failed/4 subtests. 실패는 `test_split_prompts_count_all_assembled_cases_toward_first_fifty`(40 != 30); 정확 운영 기준5248d129에서도 동일 1 failed/31 passed로 재현했다. 검사와 기대값은 고치지 않았다. 전체 통과로 표시하지 않는다. 최종8279f6ad 영향검사602 passed/동일1 failed/4 subtests/skip0·204.24초이며 py_compile 통과. 정확 기준 실패 근거는 resume-baseline-split.json이다. 최종 SHA 별도 sol medium 승인 전 병합/배포 없음.
- 기존 큰 합성의 provider0은 실행기 미구성이 아니라 base64 clipping의 ValueError였다. 이전5건의 route unavailable 5.096초는 P2 off 기준선 최대39.238초 안이다. 재시범 중단선은78.477초이며 ready 연속2실패·보호변화·preview없는 반영 시 즉시 off다. 조립 뒤 모델시도0이면50건으로 가지 않는다.
- 비공개 증거: `.local-archive/p2-staged-resume-20261111/`의 `resume-large-on.log`, `resume-impact-final.log`, `review805-resume.md`, `checkpoint.md`. 다음은 최종 영향검사→별도 sol medium 최종SHA 승인→#805 병합→공식 P2 off 배포→15분 관찰→5건10분→실제호출/안전 확인 시50건60분→보고·중단이다.

## 2026-11-11 단계별 P2 재배포 조건부 승인 — 단계0 진행

- 최신 Fable 지시는 #804의 단계별 계수를 보강·최종 sol medium 재검수한 뒤 P2 off 배포/15분 관찰 → 최대5건/10분 → 호출이 실제 발생하고 안전 조건을 만족하면 최대50건/60분 시범 → 보고·중단이다. 기존 승인 대기 기록은 이 후속 승인으로 대체한다. 전체 약2,100건, E2 #803, wave3 #799는 이번 보고 전 실행하지 않는다.
- 재개 실측: 운영 Board/Worker 예약 작업은965bca058a74a54bf69bc4d70a0d05f8997786c3, route8751/paused=false, P2/full_rollout=false다. 8751 ready200/1.016초,8790 ready200/0.260초, 비운영8752 listener없음. 같은Board PID2460의 연속10초×2 읽기 증가는0과55,107,598bytes(약5.35MB/s)다. Win32_Process.ReadTransferCount이며 물리디스크 읽기와 구분한다.
- 단계0 PENDING: 회차 상관ID/단계별 진행·최종계수,5건 상한/절대마감 보호를 운영 밖 구현·합성검증 중. 기존QA3파일·미소유8805·기존worktree를 보존한다. 단계1/2/3은 미실행, 운영 코드·고객 판정 변경 없음.
- 비공개 체크포인트 `.local-archive/p2-staged-resume-20261111/`; 다음은 계측 수정본 관리자 표적·영향검사→최종SHA 독립검수→#804 병합→신선백업·복원/보호13표→공식배포다. 배포 때 PreviousSha는 다시 실제 운영과 대조한다.

- 단계0 관리자 검증: 표적147pass/21.66초, 영향31파일702pass/기존3fail/4subtests/skip0·141.17초(기준455a723d 동일실패근거 유지). 계측 추가 후 같은2000건/1,100,346,849bytes 합성 off0.773초/P2근거조립호출0; on106.138초/고유50조립·합성3호출·50반영/근거첫1,100,591,362bytes 이후0·경쟁DB쓰기최대0.0012초. 실제모델/운영판정 미실행이며 최종SHA 독립검수 전이다. 기존QA3파일은 원해시로 복원했다.

## 2026-11-11 후속 PR #805 — 독립 검수 대기

- 큰 근거 처리·운영 분포·route 기준선 수정은 `f6d8b89c4e64606da09f3cd8d2ea01475398a203`에 반영했고 PR #805를 열었다. 표적149·영향596(+4 subtests) 모두 통과, skip0이다.
- 별도 `gpt-6.1-sol / medium` 독립 검수는 두 번 모델 용량 오류로 시작되지 않았다. 이 게이트를 우회하지 않으므로 #805 병합·배포·재시범은 보류한다.
- 운영 `5248d129`, P2/full off, route8752 unpaused, ready200, 보호13표 불변을 유지한다. 50건 단계와 전체 반영은 실행하지 않는다.
## 2026-11-11 P2 근거 크기·route 기준선 조사 — 재시범 전

- 운영은 `5248d129`·P2 off·full rollout off·route8752 unpaused를 유지한다. 이전 5건 시범 중단은 유지하며 재배포/재시범은 새 PR의 독립 검수 전 실행하지 않는다.
- 운영 읽기전용 크기 분포(원문 미출력): 메일 10,085건, 중앙값45,610B·p95 208,995B·최대425,242B. 포털 `ota_raw_entries` 최초78,720건은 length(TEXT) 집계였다. UTF-8 바이트 재집계79,288건(수집 증가), 중앙값/p95 86B·최대3,955,511B다. 포털 raw payload는 조립 대상에서 제외하고 판정 필드 allowlist만 쓴다.
- 최초 수정의 payload clipping은 독립 검수에서 반려됐다. 최종 수정은 전체 메일로 충돌을 비교한 뒤 evidence 조립 경계에서만 정리·발췌한다(메일 본문20KiB, 전체 evidence24KiB·전체 prompt256KiB 상한). 포털 evidence는 booking/service/status/payment/card/lifecycle 등 판정 필드만 포함한다. source record가 상한을 넘었다는 이유만으로 전체 사건을 실패시키지 않는다. 신규·기존 표적 149 passed, skip0.
- 기존 큰 레코드 합성 `staged-large-on`의 성공 해석을 철회한다. 로그는 `ai_retry:ValueError=50`, provider0·반영0이며 조립3은 `Repository.select` 진입 수다. on 실행기는 합성 provider를 주입하므로 호출 미구성이 아니다. 이전 메일 payload clipping이 base64 뒤에 한글 생략 표시를 붙여 decode에서 `ValueError`를 내는 경로를 합성 재현했다. 최종 SHA의 재측정은 최신 재개 절에 기록한다.
- P2 off route 잠금 30분 기준선: 비차단 probe17,934회·unavailable run246, 최대39.238초·p95 11.971초·중앙값6.223초. 따라서 다음 시범의 route 중단 기준은 `max(2×39.238,15)=78.477초`다. 기준선은 route/config 쓰기 없이 측정했으며 probe의 one-byte 획득은 즉시 해제한다.
- M1의 2,113 후보와 현재 시범 3,075 후보 차이는 detection SQL 변경이 아니라 운영 DB 상태가 M1 이후 변한 결과로 기록한다. 현재 읽기전용 집계 base3269, source_general3269, refund·board/manual 보호를 적용한 시범 후보3075다.
## 2026-11-11 단계별 시범 결과 — 5건 단계에서 중단

- `5248d129b713f70210f5dc64e83f85574566042e`를 공식 `tools/deploy_verified_release.ps1`로 `965bca05`에서 배포했다. Board/Worker SHA와 listener는 5248d129, backend8752, route unpaused, health/ready200, 비인증 API401, 보호13표 불변이다. 첫 시도는 릴리스 파일 누락으로 `RELEASE_AUDIT_FAILED` 안전중단했고 운영은 바뀌지 않았으며, Git blob 재구성·audit0 후 재시도했다.
- P2 off 15분 관찰: ready8752/8790 30회 모두200, 호출·대상·예약0, 보호지문 불변, P2 off 유지. Board ReadTransferCount 표본은 5분 1.94MB/s·946.5MB/s, 15분 0·1.31GB/s로 변동해 기존 재계산 경로와 구분한다.
- 최대5건 시범은 route 잠금 샘플 연속 unavailable 5.096초로 즉시 중단했다. P2는 자동 off, full rollout false, route unpaused, ready8752 200/2.821초·8790 200/0.027초, 보호13표 PASS다.
- 시범 계수: 후보3075, 선정5, 조립시작5·완료0, source_read_attempts2, 모델시도0·반환성공0·실패0, preview0·반영0. `P2_SOURCE_RECORD_TOO_LARGE`로 호출 예약 outcome unavailable, 최종 호출0/대상0 집계와 구분해 기록한다. route 중단 조건이 먼저 발생했으므로 50건 단계로 진행하지 않는다.
- 결과 근거 `.local-archive/p2-staged-resume-20261111/off-15m/result.json`, `pilot-5/result.json`, `deploy-exit.json`, `deploy-evidence/`. 전체 미해결 건·E2·wave3는 실행하지 않았다. 다음은 Fable의 원인 수정·재시범 승인 판단이다.
## 2026-11-11 최종 독립검수 완료 — #804 Fable 승인 대기

- 별도 `gpt-6.1-sol / medium`이67755cfee4ba968e88da94256bf94183d4450e23를 APPROVE했다. 지적된 누적예산 수정·신규회귀2pass·관리자102pass/영향680pass·기존3fail/규모실측을 확인했다. 이후 변경은 승인상태를 기록하는 문서3개뿐이며 최종문서SHA도 재확인해 #804댓글에 남긴다.
- 완료 코드11945b2f, 문서#802 병합455a723d, 후속draft [#804](https://github.com/6Soo/cost/pull/804)는 병합·배포하지 않았다. 이 지시의 보고시점에 도달해 Fable에게 최종보고하고 멈춘다. 다음은 Fable의 운영재개 승인 판단이다. 역사적 운영호출0의 직접원인 확정은 여전히 불가, 운영965유지·E2/C미착수·기존QA/미소유프로세스보존이다.

## 2026-11-11 10:31 P2 최종 수정·재검증 — draft #804

- 첫 독립sol medium 검수(b85b56c8)는 건당예산이 추가조회마다 초기화되는 지적1건으로 반려됐다. 관리자11945b2f가 회차 내 거래별 누적읽기·누적근거작업시간과 실패차감을 보존하고 회귀2건을 추가했다. 최종 문서SHA·재검수 결과는 [#804](https://github.com/6Soo/cost/pull/804) 댓글로 기록한다.
- 관리자 직접 표적102pass/16.64초. 영향30파일680pass/기존3fail/4subtests/skip0/149.15초. 3fail은 정확455a723d에서 동일재현한 기존ID이며 전체검사 통과 아님이다.
- 같은2000건·1,100,346,849bytes 합성으로11945b2f off/on exit0: off0.892초/P2근거·조립·호출0, on106.812초/합성3호출·50반영/근거첫1,100,582,022이후0/route최대보유0.2642초·경쟁DB쓰기최대대기0.0016초. 자세한 수치·제약은 [검증 보고서](agents/artifacts/p2-lock-io-budgets-20261111.md)에 있다.
- 운영965bca05 유지, PR병합·배포·고객/실모델·Google 쓰기 없음이다. 기존QA3파일은 복원했다. 다음은 최종SHA 별도sol medium 재검수→결과PR기록→Fable보고·중단이다. 운영호출0의 역사적 직접원인 확정은 여전히 불가, 승인 전 P2/main/wave3 배포금지다. E2 #803·wave3 #799는 이후순서로 남긴다.

## 2026-11-11 10:18 D5-FIX 관리자 직접 검증 — 독립검수와 Fable 승인 게이트

- #802 문서는 최종f5c8756f의 별도sol medium APPROVE 후455a723d로 병합했다. 배포 없음이다. P2 작업자 최종3a7363fc를 `integration/p2-lock-io-resume-20261111`에 통합한 코드 커밋은ba799241다. 이후 문서 커밋을 포함한 최종SHA·독립검수는 후속PR에서 확인한다.
- 관리자가 표적100pass, 영향30파일678pass/3fail/4subtests/skip0, 정확한 기준455a723d의 같은3fail을 직접 실행했다. 전체QA 통과는 아니다. 테스트 약화·고객자료·운영DB·실제모델·Google 쓰기는 없다.
- 후보2000건/근거1,100,346,849 bytes로 직접 off/on 실측: off1.279초·P2근거/조립/호출0, on155.292초·합성3호출/50반영·근거첫1,100,586,772 bytes 이후0·route최대보유0.3553초·경쟁DB쓰기대기최대0.0051초. 세부 조건·한계·재현 명령은 [검증 보고서](agents/artifacts/p2-lock-io-budgets-20261111.md)에 있다.
- 작업자 capacity 오류 뒤 관리자가 저장 상태에서 이어받았다. Claude 전환 없음. 기존QA3파일은 복원했고 baseline worktree도83d87f88로 복귀했다. 기존worktree·미소유8805를 보존했다.
- 다음은 별도sol medium 이상의 최종SHA·실측 검수 → PR기록 → Fable 최종보고·중단이다. 운영965bca05 유지, Fable 승인 전 배포·고객P2 재실행 금지. 운영 호출0 직접원인은 과거 live stack 부재로 유일확정 불가다. E2 #803과wave3 #799는 그 뒤 순서이며 지금 시작하지 않는다.

## 2026-11-11 09:30 관리자 재개 — 운영965 유지·문서 최종 검수부터

- #802 최종 `f5c8756f`를 별도 `gpt-6.1-sol / medium`이 APPROVE했고 `455a723d`로 병합했다. CI는 결제 한도로 steps0, 문서 링크·diff PASS, 테스트·배포 없음이다. 후속 관리자 기록 브랜치는 `docs/manager-p2-resume-20261111`이며 D5-FIX 기존 worktree에서 별도 sol high가 구현·합성 검증을 진행 중이다.
- 예약 `24cfe08a` 원문과 최신 작업판·PR·8개 worktree를 대조했다. 09:02 예약 실패 원인은 Codex 구버전의 gpt-6.1-sol 미지원 HTTP400이며 한도 오류로 단정하지 않는다. 그 실행은 archived/closed이고 해당 시각 커밋·작업판 변경 흔적은 없다.
- 운영 Board PID2460 checkout 및 Board/Worker 예약 작업 SHA는 `965bca058a74a54bf69bc4d70a0d05f8997786c3`, route8751/paused=false다. 8751·8790 healthz/readyz 네 경로200을 읽기 전용으로 확인했다. 읽기량·고객 DB·보호 지문은 이번 상태 대조에서 재측정하지 않았다.
- #802 장애 기록·작업판 문서의 최종 SHA 독립 sol medium 검수 후 병합이 다음 작업이다. 이어 기존 D5-FIX `27dacf23`에서 운영 밖 수정·규모 합성 실측·독립 검수까지 수행하고 Fable에 보고한다. 승인 전 P2/main/wave3 배포는 금지다.
- 기존 미추적 QA 3파일과 worktree를 보존했다. 8805 PID19544는 소유 미확인으로 유지했다. 재개 근거와 정확한 순서는 [작업판](agents/BOARD.md#재개-정보)에 기록했다.

## 2026-11-11 06:18 운영 장애 복구 — 965bca05 롤백, 읽기 기준선 미검증

- Fable의 명시적 장애 복구 지시를 실행했다. `83d87f88` 배포와 그 소유 Prepared 작업을 전환 전에 취소하고, 5DB SQLite backup API·별도 복원·quick_check/스키마/행수 동등을 확인했다. 지정된 구 Board PID34256은 `WebLedger-Board` 예약 작업의 중지로 종료하고 잠금 비파괴 해제를 확인했다. 같은 SHA/P2off 재시작 뒤 공식 도구로 **06:13:42 KST `965bca058a74a54bf69bc4d70a0d05f8997786c3` 롤백 완료**다. 다음 배포의 PreviousSha는 `965bca05`다.
- Board·Worker·listener SHA 일치, backend8751/Gateway8790 health/ready200·비로그인401, 보호13표·원본7,336·수동교정 대상255·관련14표 지문 불변, P2/fullrollout off를 확인했다. 데이터 변경·금융/Google 쓰기는 없다. Gateway와 route lock 파일 삭제·우회·다른 프로젝트 프로세스 조작은 하지 않았다.
- **읽기량 평상 기준선은 미검증**이다. 06:14:47~06:15:08 새 Board PID2460의 두10초 구간은 약123.3MB/s·355.4MB/s여서 Fable에 즉시 수치 보고했다. 후속06:15:41~06:16:01은 약5.35MB/s·0B/s, 06:17:19~06:17:40은 약5.54MB/s·395B/s로 감소했다. 시작 후 준비 작업 여부와 평상 기준선은 미확정이다. 준비 실패 실측06:03:54부터 응답 정상 확인06:13:42까지 최소9분48초, 실제 장애 시작/읽기량 종료는 미확정이다.
- **P2 재배포·재실행 금지**다. Fable이 지정한 off 시 조립/조회0, 회차50건 제한, 조립/모델 호출의 route·DB 쓰기 잠금 분리, 색인/읽기·시간 예산, 시범 창 종료 시 진행 회차 중단을 운영 밖에서 해결한다. 후보2,000건 이상·근거1GB 이상 합성 off/on 읽기량·소요·잠금 실측과 독립 검수 및 Fable 승인을 받기 전 `83d87f88`을 운영에 다시 올리지 않는다.
- C #799는 최종 시각 수락 차단 그대로, E2 `60d8fb44`는 운영 복구 지시로 파일을 보존한 채 일시중지 응답을 받았다. 복구 완료 판단 이후 같은 작업자를 재개하며 중복 배정하지 않는다. 완료 A/B/A-R/D1/E1을 다시 실행하지 않는다.
- 상세 운영 사실은 [운영 장애 기록](operations.md), 비공개 증거는 `.local-archive/manager-resume-20261111/incident-rollback/`와 `resume-c89bbda2.md`에 있다. 코드 롤백 완료와 성능 복구 미확인을 구분한다.

## 2026-11-11 06:07 재개 — 첫 P2 제한 실행 종료·보완 배포 잠금 대기

- 관리자 `c89bbda2`는 원 A~E 및 Fable 후속 결정을 인계 기록으로 대조했다. 완료 A/B/A-R/D1/D2~D4/E1을 재실행하지 않는다. 문서 #800은 `0308eed3`, P2 조립 보완 #801은 `83d87f88416924a5ec377e988a82b778d9f956a2`로 병합됐다. 루트의 기존 미추적 QA 3파일은 보존한다.
- D5 첫 제한 제어는 **05:59:19 KST, `pilot_watch_deadline`으로 종료**됐다. 약 55분 3초 동안 호출 예약0·고유사건0·처리0, 성공률과 근거 표본은 산출 불가다. `finally` 비활성화·전체확대 false, 원본7,336·수동교정 대상255·관련 보호14표 지문 불변을 확인했다. [첫 묶음 보고서](agents/artifacts/p2-first-batch-20261111.md)에 결과와 한계를 기록했다. 첫50 완료와 M2 완료를 선언하지 않는다.
- D5-FIX 최종 `83d87f88`은 독립 `gpt-6.1-sol / medium` 소스·문서 APPROVE다. 합성 신규8·관리자53 통과, 영향413통과/기존3실패·skip0을 보존한다. 준비한 Git 원본1,562개·blob 불일치0이며 P2 비활성 상태로 공식 배포를 시작했다. **06:07 KST 현재 배포는 전환 전 `gateway_route.py pause`의 route lock 획득 대기**다. 후보 Prepared의 health/ready 200만 확인했고 운영 route는 기존 `bd4646a1`/8752다. 완료 증거가 없으므로 보완 배포 성공으로 쓰지 않는다. 단일 원본 로더 선점 취소·전체 조립 강제 시간 제한과 실제 지연 해결은 미검증이다.
- 구 Board는 기존 제한 제어가 재시작한 프로세스이며 읽기량 증가를 관측했다. 구 `sweep_once()`가 P2 조립까지 writer lock을 유지하는 구조를 확인했지만 실제 lock holder/live stack은 미측정이다. route lock 우회·강제 프로세스 종료는 하지 않고 Fable에 운영 복구 판단을 올렸다. 야간 종료 후 고객 재실행·전체확대는 하지 않았다.
- C 최종 `e1219d9b`는 push·관리자227통과·독립 코드승인까지 완료, [#799](https://github.com/6Soo/cost/pull/799)는 draft다. 승인된 TaskSpace1 소실로 최종390/1440 시각 수락이 BLOCKED며 새 공간 생성·병합·배포를 하지 않는다. 기존 전체 검사 실패 기록은 그대로다.
- E2는 기존 EXAONE `60d8fb44`가 같은 worktree에서 구현·합성 검사를 계속한다. 화면 요약 정규화·조회 후 snapshot 신선도 등 중간 발견을 전달했으며 최종 SHA 수락 전이다. E3 조사 원문은 #800에 병합했고 사용자 로그인 세션의 실제 조회 조건 확인이 남은 PARTIAL이다.
- 비공개 근거는 `.local-archive/manager-resume-20261111/`의 `p2-release/pilot-after.json`, `p2-assembly-release/`, `review-83d87f88-release.md`, `resume-c89bbda2.md`다. 실행 중 공식 배포 exec session `33495`의 종료·runtime/protection 근거를 먼저 확인하고 E2 결과 수락을 계속한다. 배포 전후 통지는 같은 레포의 최고 관리자와 기존 E2 작업자에게 한다.

## 2026-11-11 05:40 재개 — C 최종 코드 승인·D5 조립 지연 조사

- 관리자 `e154dd1c`는 원 A~E 지시와 Fable 후속 결정 6개를 인계 원문에서 직접 복구했다. 완료 A/B/A-R/D1/D2~D4/E1은 재실행하지 않는다. 루트 브랜치는 `docs/p2-first-batch-report-20261111`, 기존 완료 커밋 `1312f813`, 운영은 `bd4646a1`다.
- C 최종 `e1219d9bab9b0ff7122b6aef6fb24c0c855c72e7`을 정상 push했다. 이용일 원문 부재 단정·UNLINKED 설명·예약 추론 표시의 신규 30건 회귀를 복원했다. 관리자 직접 변경 영향 **227 passed**, failures/errors/skipped 0, 실행 전후 SHA 일치다. 작업자 최종 표적 55 passed와 복구 231 passed·59 passed + 18 subtests도 보존했다. 독립 세션 `f90a202d`의 최종 소스 판정은 **APPROVE**, 실제 런타임 `gpt-6.1-sol / medium`은 Paseo metadata로 확인했다. [초안 PR #799](https://github.com/6Soo/cost/pull/799)에 SHA·근거를 갱신했다.
- C의 과거 실패 기록은 유지한다. `3340b0fb` 149파일은 2,143 pass/34 fail(기존32/신규2), `fe399e42` 추가48파일은 1,089 pass/39 fail(정확 main `a050d65f` 대조 기존9/신규30), 둘 다 skip0이다. 최종 변경 영향 통과를 새 전체 QA 통과로 바꾸지 않는다. CI는 결제 한도로 steps0이다. 최종 390/1440 실제 시각 수락은 승인 TaskSpace1 소실로 **BLOCKED**, 새 공간은 만들지 않으며 병합·배포는 미실행이다.
- D5는 05:39 KST에도 호출 예약0·고유사건0, 작업 대상20건이다. 기존 관리자 소유 제어가 계속 실행되며 예산60회·고유50건·야간 종료·finally off를 유지한다. 성공률·표본·종료·보호 대조는 아직 없다. 원문을 출력하지 않고 프로세스 CPU/읽기 증가만 관찰했다. 반복 전체 근거 읽기와 조립 후 시간 제한 확인 경로는 코드에서 찾았으나 live stack으로 원인을 확정하지 않았다. 별도 Terra `f4e9ebbc`가 `fix/p2-case-assembly-budget-20261111`에서 합성 재현·최소 보완 중이며 운영 제어와 고객 자료에는 접근하지 않는다. 제어 lock 중에는 배포하지 않는다.
- E2는 기존 EXAONE `60d8fb44`가 기본 ego 연결·조회기간/공간 전달·실제 조회·0건 판독을 보완한다. 관리자 수락·최종 SHA 독립검수는 남았다. E3 최종 `729b3a89`의 [조사 보고서](agents/artifacts/card-login-paths-20261111.md)를 문서 통합에 준비했다. **PARTIAL 종료**와 사용자 로그인 세션 확인 필요 상태를 유지하며 추가 공개 조사는 하지 않는다.
- 비공개 체크포인트: `.local-archive/manager-resume-20261111/resume-e154dd1c.md`. 다음은 D5 종료·보호 대조 확인, D5-FIX 합성 결과 검수, E2 직접 수락이다. 고객 첫50 완료·전체확대·C 배포를 완료로 쓰지 않는다.

## 2026-11-11 재개 검수 — C 보호 복구·합성 공간 소실·E2 실행 경계 보완

- 관리자 후속 `44fc0d1d`는 원래 A~E와 Fable 후속 승인을 인계 원문에서 복구했다. 완료 A/B/A-R/D1/D2~D4/E1을 재실행하지 않는다. 운영 SHA는 아래의 `bd4646a1` 그대로다.
- C 현재 작성자는 `969d191d`이며 최종 후보는 `fe399e42a7b35fb74b74c7f9deef306a66d513e6`다. 최신 main `a050d65f`를 충돌 없이 병합했고, 수입 연결의 실제 탭 조작·취소 불변·Enter POST 1회·정확 ID·연결 건수 단언과 환불/증빙의 원 기준 비교를 복구했다. 작업자 표적 55건·복구 16건 통과, 추가 영향 48파일 및 관리자 수락 검사는 진행 중이다. 기존 `3340b0fb` 전체 검사(149파일·2,143 pass/34 fail·기존32/신규2·skip0)는 실패 근거로 보존한다.
- **C 최종 렌더링 수락은 BLOCKED**다. 05:15 KST에 승인된 ego-browser TaskSpace 1 재개가 `task space not found: 1`로 실패했다. Fable의 "이 공간도 사라지면 추가 생성하지 않는다" 지시에 따라 새 공간을 만들지 않는다. 기존 3340의 390/1440 캡처는 남지만 최종 후보의 새 렌더링·수락은 미검증이다. 운영 배포를 완료로 쓰지 않는다.
- E2는 1차 독립 사전검수에서 실제 ego 연결을 외부 모듈에 맡긴 경계, CLI TaskSpace 이름 전파, 조회 기간 입력·조회 실행, 화면 0건 처리의 누락을 확인해 같은 EXAONE 작업자가 보완한다. 실사이트·고객·운영 접근은 금지한 채 실제 Page API와 같은 합성 표면으로 검사한다. 완성된 수집기로 수락하지 않았다.
- D5 제어는 05:04 KST 시작 후 계속 실행 중이다. 05:21 KST 호출 예약 0건, 작업 대상 20건이며 성공률·종료·보호 전후 대조는 아직 미확정이다. 전체 실행은 비활성이며 일일60회·고유50건·야간 종료·finally 비활성화를 유지한다. 배포 lock은 제어가 소유한다.
- 완료 E1/D 작업 공간의 비공개 증거와 원래 미추적 QA 파일은 `.local-archive/manager-resume-20261111/completed-workspace-evidence/`에 파일별 SHA-256 대조로 보존한 뒤 공식 archive했다. D 디렉터리는 제거됐고 E1 디렉터리는 공식 도구가 유지했다. 브랜치·완료 커밋은 남겼다. 이전 문서의 D worktree 경로 근거는 이 보존 사본을 사용한다.

## 2026-11-11 P2 코드 운영 배포·OTA 수집 스크립트 병합

- **현재 운영 SHA는 `bd4646a1b4c1d0b6acf11af886e4f86dfe3ea64c`**([PR #797](https://github.com/6Soo/cost/pull/797))다. 공식 배포 도구로 2026-11-11 04:56 KST에 전환했고 Board·Worker 예약 작업과 실제 listener의 SHA를 확인했다. health/ready 200·비인증 API 401·보호 13표 불변이다. 이전 운영은 `965bca05`이며 다음 배포의 `-PreviousSha`는 `bd4646a1`이다.
- 배포 전 **5개 DB·45개 파일의 신선 백업과 별도 복원 대조**를 완료했다. 모든 DB 테이블·열, 원본 파일 해시, review binding이 일치하고 운영 상태는 불변이다. 최초 백업 실패 기록은 보존한다. 게이트웨이 상태 파일의 동시 갱신을 막은 v2 검증은 04:51:58 KST 완료됐다. continuous code 배포는 `BackupProducts`를 사용하지 않았으며 별도 복원 검증 근거로 구분한다.
- P2는 비활성 상태로 배포했다. startup 조건상 Worker가 생성되지 않아 독립 sol medium 검수를 통과한 제어로 같은 배포의 Board 예약 작업만 재시작했다. 05:04 KST에 **첫 50건 제한 실행을 시작**했고 gateway drain·재시작 ready·route resume을 확인했다. 고유 사건 50건·호출 예산 60회·야간 시간·한도/인증 오류 종료와 finally 비활성화·전후 보호 비교를 유지한다. 첫 50건 완료는 아직 아니며 전체 실행은 금지한다.
- OTA 수집 코드 [PR #798](https://github.com/6Soo/cost/pull/798)은 `a050d65f045c07c8469883bc95a211939222e82e`로 병합했다. 최종 `a11d5ea8` 독립 gpt-6.1-sol medium APPROVE, 표적 Node wrapper 1건(내부 52건)과 최종 영향 84건·실패/오류/skip 0·compile 0을 확인했다. CI는 steps 0의 결제 한도 차단이며 녹색으로 보고하지 않는다. 원본 importer 구조를 보존하고 manifest에서 원본 파일명·예약번호를 제외했다. 실사이트 수집·예약 등록·운영 DB 가져오기는 실행하지 않았다. 운영은 여전히 P2의 `bd4646a1`이다.
- C `3340b0fb` 고정 검사는 149파일 전부 완료됐다. 고유 2,177건 중 2,143 passed·34 failed·skip 0이며 신규 실패 2건(390 닫기 selector·font token)이 있어 통과가 아니다. 후속 `d40b2c64`가 이 결과를 보존하고 신규 실패와 수입 연결 보호 단언을 복구한다. E2는 기존 `60d8fb44`가 실제 ego entry와 합성 완주를 보완 중이다. E3는 로그인 세션 확인이 남은 PARTIAL이다. A/B/A-R/D1 완료 항목은 재실행하지 않는다.
- 비공개 근거: `.local-archive/manager-resume-20261111/resume-453dc562.md`, `p2-release/`, `ota-integration-final/`. 기존 미추적 QA 파일 3개는 원래 해시로 복원했다. 고객 원문·식별자를 Git에 포함하지 않는다.

## 2026-11-11 재개 검수 — D 예약 합성 통과·C/E1 수정 요구

- D 최종 후보 `be3a3090dadd2d0b882d6211677af8016df9f68b`는 독립 `gpt-6.1-sol` medium 소스 검수 APPROVE, 관리자 직접 P2 표적 검사 **70 passed**다. 최종 영향 검사는 895 실행·892 통과·기준선 UI 실패 3·skip 0이며 실패 상태 자체를 통과로 바꾸지 않는다. 같은 base `1ad1364d` 대조 근거를 최종 병합 기록에 포함한다.
- D5 별도 예약 작업 V2는 실제 **LastTaskResult 0**(2026-11-11 04:24:15 KST), 합성 1건의 판정·교정 이력 저장을 확인했다. CLI 1회·도구 이벤트 0·원문 불변·금융 쓰기 0, 소요 22,416ms다. 원 JSONL 재생과 OS 격리는 실측하지 않았다. 최초 실패 결과는 보존한다. 고객 첫 50건·운영 배포는 아직 미실행이며, 신선 백업·복원 확인과 안전 배포 뒤에만 진행한다.
- C `3340b0fb`의 고정 149파일 영향 검사는 기존 소유 wrapper에서 계속된다. 재개 시 45/149의 실패 16개 JUnit node는 모두 기준선 실패로 보고됐다. 독립 검수에서 `test_participant_income.py`의 취소 불변·Enter 1회 POST·고정 ID·연결 개수 단언 삭제를 발견해 REQUEST_CHANGES다. 전체 검사 완료 후 동작·보호 단언과 실제 사용자 탭 전환을 복구하고 새 SHA를 검수한다. 기존 합성 TaskSpace 1을 재사용하며 390/1440 실제 여행 장부 캡처를 추가했다.
- E1 `536739a8`의 관리자 직접 Node 48건과 작업자 영향 QA 84건은 통과했으나, 독립 검수에서 요약 manifest 파일명에 예약번호가 들어가는 결함으로 반려했다. 같은 작업자 `92cc66bd`가 파일 목록만 제외한 `c7b0112a`와 신규 회귀 RED 4 → GREEN 4를 보고했으며 최종 검사·재검수 전이다. 원본 detail 파일명과 importer 계약은 보존한다.
- 기존 C 작업자는 `db482a8c`, E1은 `92cc66bd`, E2는 `60d8fb44`로 이어졌다. E3는 사용자 로그인 세션 확인이 남은 PARTIAL이다. 완료 A/B/A-R/D1은 재실행하지 않는다. 비공개 재개 근거는 `.local-archive/manager-resume-20261111/resume-reconciliation-20261111.md`에 있다.

## 2026-11-11 C 최종 회귀 수정·D 예약 합성 검증 실패 분석

- C는 `4db0d3a0` 뒤 실제 일괄 편집의 두 번째 행·Shift 선택과 모바일 홈 말줄임 회귀를 Terra high `6fc69ce8`가 수정 중이다. 관련 회귀 24 passed·2 subtests는 작업자 보고이며, 관리자도 8804 합성 홈 390/1440에서 여행명·기간을 직접 확인했다. 최종 고정 SHA의 전체 영향 검사·독립 검수·병합·배포는 아직 남았다. 이전 전체 149파일 검사는 16파일 뒤 안전 종료됐으며 통과로 취급하지 않는다.
- D2~D4는 Terra high `23fcdce5`가 최종화한다. `4da058fb` 영향 검사는 725 passed·기존 UI 3 failed·별도 OTA 종료 오류 1건으로 실패했다. 소유한 대사 자식 프로세스의 취소 누락을 합성 재현해 고친 뒤 최신 main을 병합한 `53f1f40b`는 독립 코드 검수 APPROVE이며 최종 영향 검사는 진행 중이다. 실제 오류와 같은 원인이었는지는 확정하지 않았다.
- D5는 운영과 같은 계정·로그온 유형의 **별도 관리자 소유 예약 작업에서 합성 1건을 한 번 실행**했다. 판정·이력 저장, 호출 예약 1건과 동일 실행 ID, 원본 불변·금융 쓰기 0을 확인했지만 하네스의 프로세스 관측 단언이 실패해 작업 종료 코드 1이다. 사후 읽기 전용 검증은 exit 0·합성 DB 해시 불변이다. Windows Popen 감사 인자의 실행 파일 값이 `None`이어서 필터가 놓치는 현상은 실제 bounded runner와 무해한 자식 프로세스로 재현했다. 첫 실행 실패를 성공으로 바꾸지 않으며, 관측 보완과 최종 코드에서의 예약 검증이 남았다. 고객 첫 50건·운영 배포는 아직 실행하지 않았다.
- E1은 `10a2ee67`의 관리자 직접 영향 검사 84 passed·skip 0 뒤 독립 검수에서 경로 이탈 저장 가능성·Trip 페이지네이션·실패 한도·로그인 중단 결함이 발견됐다. 같은 작업 두 차례 반려로 sol high `a4320a9d`에게 기존 worktree를 인계했다. E2는 기존 EXAONE이 합성 구현을 진행 중이다. E3는 PARTIAL로 닫고 사용자 로그인 세션에서 실제 조회 조건을 확인해야 한다.
- A·B·세무 양식 유지 검토는 #795 병합 `6c160d54`, D1 도구 없는 어댑터 결정 문서는 #796 병합 `1ad1364d`로 완료했다. 실행 정본은 SPEC §6이며 OS 격리를 안전 근거로 삼지 않는다. 아래 작업자·SHA·검사 진행 기록은 이 절과 작업판의 최신 상태를 우선한다.

## 2026-11-11 도구 없는 P2 결정 반영·D2~D4 구현·C 기준선 비교 (이력)

- D1 결정 문서는 [PR #796](https://github.com/6Soo/cost/pull/796), 병합 `1ad1364d35ab7bcba2e99797bb3d1b09dd5b6902`로 반영했다. 최종 `5e78bf06` 독립 sol medium 승인, 문서 검사·승인 트리 동등 확인, CI 결제 한도 시작 차단 근거가 있다. D1 조사 worktree는 커밋·브랜치를 보존하고 공식 archive했다. 이 문서 변경은 배포하지 않았다.
- C 후보 `f0cd5fc0`를 관리자 통합 `d1589f82`로 합쳤다. 관리자가 같은 main에서 통과하던 45개 회귀 nodeID를 직접 실행해 **45 passed·2 subtests·skip 0**, exit 0을 확인했다. 알려진 테마 버튼의 추가 접근성 수정과 최종 영향 검사·독립 검수·배포는 남아 있으므로 C 완료는 아니다. 파일별 기준선 비교·모바일 여행 목록 수정과 정적 단언 예외 목록은 작업판에 있다.
- D 합성 스키마 `39cdbe64`와 repository fixture 정합 수정 `df078a2b`는 관리자 직접 검사 **9 passed**, diff check를 통과해 본체에 전달했다. 첫 50건 제한이 P1 선게시까지 막던 경로·P2 이용기간의 실제 표시 연결·Windows 자식 프로세스 Job 편입 경쟁 조건을 사전 검수에서 찾아 수정 중이다. 초기 영향 검사 385 passed·3 failed는 같은 main에서도 재현됐다는 작업자 보고이며 최종 수락 전이다.

- **현재 실행 기준:** Fable이 D1 대안으로 도구 없는 어댑터를 승인했다. Worker가 사건·근거 원문·규칙·스키마를 stdin/프롬프트로 직접 넣고, 모델은 빈 임시 cwd에서 JSON만 낸다. 직접 Codex read-only/never가 기본이며 검증된 대체만 등록한다. OS 격리 검증을 안전 근거로 삼지 않는다. [SPEC §6](SPEC.md#6-p2-런타임), [실행 계획](superpowers/plans/2026-11-11-p2-tool-free-runtime.md), [D1 보고서와 후속 결정](agents/artifacts/p2-isolation-20261111.md)을 함께 본다. probe 도구는 통합하지 않는다.
- D2~D4는 sol high `0d6af74c`가 `feat/p2-tool-free-runtime-20261111`에서 구현한다. D2 `08421e98`·합성 7 passed는 작업자 보고이며 관리자 수락 전이다. 스키마·픽스처만 EXAONE high `f9fa4608`에게 별도 배정했다. 고객 원문·운영 자료는 아직 실행하지 않았다. D5는 실제 예약 Worker 맥락의 합성 검증·최종 SHA 독립 검수·안전 배포 뒤 첫 약 50건에서 멈춰 보고한다. 전체 미해결 건 실행은 승인되지 않았다.
- C 소유 PowerShell 검사는 끝까지 완료됐으며 2,001 passed·82 failed다. 같은 main `7aa6c418`에서 실패 nodeID를 파일별 대조하고 새 회귀를 수정 중이다. 작성자는 sol high `0fc54139`, 관리자는 검수·통합·배포를 맡는다. 폐지된 대기·보류 문구를 강제하는 테스트는 Fable 승인으로 해당 기대 문구만 바꾸며 나머지 동등성·보호 검사는 유지한다. 390/1440 실제 렌더링과 새 실패 0·최종 검수·배포는 남아 있다.
- E1/E2는 실제 활동과 코드·합성 테스트 산출물을 확인했으며 구현이 진행 중이다. 결과 수령 뒤 관리자가 통과 조건을 실행한다. E3는 PARTIAL로 닫고 **사용자 로그인 세션에서 확인 필요** 항목만 남겼다. 로그인 수단·실제 조회 조건/기간/양식은 NOT_VERIFIED다.
- A·B·세무 7열 유지 검토는 #795 병합 `6c160d54`로 완료됐고 Fable이 확인했다. 현재 문서 변경은 배포하지 않는다. 이전의 D1 차단·D2 미착수·C 실행 중 기록은 아래 이력이며 최신 상태는 이 절과 [작업판](agents/BOARD.md)이다.

## 2026-11-11 A·B 병합 완료와 E3 후속 조사 수령

- A·B·Google 7열 검토는 [PR #795](https://github.com/6Soo/cost/pull/795), 병합 `6c160d5405b2cc40adfcd78e8f0a5450193132cf`로 완료했다. 승인 최종 `3127b6db`와 병합 트리 차이 0, 독립 sol medium 승인·CI 결제/한도 시작 차단·코드 영향 92 passed·가드 9 passed 근거를 PR에 남겼다. 관리자 M1 읽기 전용 재현도 exit 0이며 입력 지문 불변을 확인했다. 운영 표시 세대는 미검증이다. 완료된 A·B worktree는 안전 확인 뒤 공식 archive했다.
- E3는 `research/card-login-paths-20261111`의 `729b3a89`(선행 `6cd43469`·`cfd94b32`)에 보존했다. 공개 안내 조사 후에도 하나·기업의 로그인 수단·실제 조회 조건·기간·양식은 NOT_VERIFIED여서 PARTIAL이다. 문서 diff·인용 경로를 확인하고 기업 파서 참조만 정정했다. 미통합이며, 수집 준비 완료나 M2 완료로 취급하지 않는다.
- 다음 통합은 `integration/wave3-collection-20261111`에서 관리한다. C의 실행 중 QA 결과와 같은 main SHA의 실패 비교, 별도 모바일 여행 목록 수정 검수, E1/E2 결과 검수가 남았다. D1 격리 미검증으로 고객 원문 P2·첫 50건은 차단한다. 이번 조사 수령에 운영 코드 테스트·배포·Google 쓰기는 실행하지 않았다. 상세 다음 명령은 비공개 `.local-archive/manager-resume-20261111/continuation-checkpoint.md`에 있다.

## 2026-11-11 A·B 통합과 P2 격리 차단 — 관리자 실행 상태

- 사용자 결정 문서 `b002c7fe`는 통합 커밋 `d63d1b57`, M1 기준선 `f3703981`·`096a1039`는 통합 `ef90643f`·`8c878048`에 있다. 최종 검수와 병합 근거는 [PR #795](https://github.com/6Soo/cost/pull/795)에 남긴다. 현재 병합 여부와 최종 SHA는 이 PR의 기록을 확인한다.
- M1 수치·정의·재현 명령은 [운영 기록](operations.md#2026-11-11-m1-읽기-전용-기준선)에 있다. 카드 7,336건, 내부 미기록 3,792건(비삭제 여행 3,759건), 현재 입력으로 재현한 이용일 미확인 147행이다. 저장 판정 미충족 정상 구매 0건은 M2 정책 완료를 뜻하지 않는다. 실제 운영 프로세스의 표시 세대·카드사 다운로드 시각·Booking 수집 시각은 검증되지 않았다.
- [세무 전달 양식 검토](agents/tax-ledger-review-20261111.md): 현재 Google 7열을 유지한다. 증빙 종류·부가세 구분·승인/환불 관계·행에서 원본으로의 추적성을 기존 기장 방식과 대조할 검토 의견만 남겼다. 양식 변경·별도 세무 산출물은 구현하지 않았다.
- D1 조사는 `research/p2-isolation-20261111`의 `5469f5a5`(도구 `5ffc135f`)에 보존했다. Codex 정책 거부·DPAPI 시작 실패, Claude 권한 대기 때문에 모델 경로의 합성 본문이 실행되지 않았다. 격리 수락과 실제 예약 작업은 미검증이며 고객 원문 P2·첫 50건은 실행하지 않는다. 조사 도구의 영향 QA도 `UNKNOWN_IMPACT:1`로 미통과라 #795에 통합하지 않았다. §6.6 복구/대안 범위는 최고 관리자에게 올린다.
- C는 `40c20e8e`에서 영향 QA를 재실행 중이다. 이전 실행은 36% 로그만 남고 프로세스·최종 결과가 없어 중단으로 기록했다. 같은 main 비교·390/1440 렌더링·최종 검수·병합·배포는 남아 있다. [작업판](agents/BOARD.md)에 실행 ID·증거 경로를 남겼다.
- Luna 신규 배정을 중단했고 기존 A는 끝났다. EXAONE high 2개가 E1(OTA 조회)·E2(국민카드 수집)를 별도 worktree에서 구현 중이다. 무료 모델의 고객 자료·운영 폴더·로그인 세션 접근은 금지했다. ANUS 1개도 E3(하나·기업 카드 공개 안내·코드 조사)에 배정했으나 두 차례 산출물 없이 종료돼 같은 worktree의 작업을 EXAONE으로 넘긴다. 원인을 모델 품질로 단정하거나 모델 전체를 제외하지 않았다. 완료 검사 전 EXAONE 품질을 확정하지 않는다.
- 운영 앱 기동·DB/원문/Google 쓰기·원본 교정·배포는 이번 A·B 통합에서 실행하지 않는다. 다음은 #795 최종 SHA 검수·병합 확인, C 회귀 비교, E1/E2 결과 검증이다. M2 D2~D5는 격리 차단과 독립 구현을 구분해 계속 관리하며, 전체 미해결 건 반영 승인은 없다.
- 재개 관리자 `daebb5d1`는 A~E 원래 지시를 복구하고 통합 `f7996137`의 독립 sol medium 승인 및 CI 결제·한도 시작 차단을 확인했다. 이후 인계 변경은 실행 상태만 기록한다. M1·C의 이전 프로세스는 최종 결과 없이 종료돼 01:35:12에 관리자 소유 실행으로 다시 시작했으며, 종료 근거·정확한 다음 명령은 [작업판 재개 정보](agents/BOARD.md#재개-정보)와 비공개 `.local-archive/manager-resume-20261111/continuation-checkpoint.md`에 있다. C 장부·카드·여행·영수증의 1440/390 합성 캡처를 직접 확인했지만 모바일 여행 목록 말줄임·실제 복사·main 실패 비교·최종 검수·배포는 남아 있다. 기존 E1~E3 작업자를 재사용하며 고객·운영 접근 금지를 유지했다.
- 관리자 M1 재현은 01:48:24 KST exit 0으로 완료됐다. 카드 7,336·내부 미기록 3,792·현재 입력 표시 미확인 147행이 기존 기준선과 일치하고 입력 지문 불변을 확인했다. 운영 표시 세대는 미검증이다. E3 정적 보고 `6cd43469`는 핵심 로그인·조회 경로 미확인으로 PARTIAL이며 공개 안내 조사 후속을 배정했다. C·D·E 전체 완료나 배포로 확대 해석하지 않는다. A/B의 실제 병합 SHA는 [PR #795](https://github.com/6Soo/cost/pull/795)에서 확인한다.

## 2026-11-11 통합 명세·판정 규칙집 확정, 증상별 패치 동결 — 현재 정본(작업 방향)

- **정본 교체:** 실행 정본은 [통합 명세](SPEC.md)와 [판정 규칙집](DECISION_POLICY.md)(+`docs/policy/`)이다. `docs/history/`(과거 명세는 `docs/history/specs-20261110/`)는 근거 기록이다. [작업 지침](../AGENTS.md)은 한 쪽으로 줄였다.
- **현재 단계: M1 기준선·M2 P2 연결 착수 승인.** 이번 문서 변경은 M0 실행 정본과 현재 상태를 갱신한다. 코드·운영은 바뀌지 않았다. 아래 절들의 운영 SHA와 배포 기록은 그대로 유효하다.
- **증상별 패치 동결(통합 명세 §12.1):** 공급자별 파서 수정, 이용일 경고 수치를 쫓는 수정, 기록만을 위한 문서 PR을 하지 않는다. 예외는 운영 장애와 로드맵 작업이다. 아래 절의 "남은 반복 원인(다음 작업)" 목록(이스타·ANA·Volotea 파서 등)은 **파서 패치로 하지 않고** M2에서 P2가 원문을 읽어 판정한다.
- **사용자 결정 요지(2026-11-10~11):**
  - 처리 흐름에 사용자 확인 단계가 없다. 사용자는 분기마다 검수하고 교정한다. Google 붙여넣기는 수작업으로 유지한다.
  - P2는 운영 Worker가 Paseo로 `codex/gpt-6.1-sol`(기본)·`claude/opus`(대체)를 부르고 고객 원문을 줄 수 있다.
  - Codex 사용량 공유 때문에 Luna 작업자 사용을 중단했다. 현재 구현 작업자는 exaone 여러 개와 ANUS Free Auto 1개이며, 필요하면 terra·sol 일부를 쓴다.
  - 순서는 현 시스템에 P2 연결(M2) → 그 뒤 Rust·React·클라우드.
  - 필요한 산출물은 여행별 손익, 세무·증빙 자료, 직원·가이드 지출 정산이다. 세무 자료는 분기 검수 후 빠짐없이 채운 Google 지출표 그대로이며, 내부 회계 양식이기도 하다(Q1·Q2 전달 완료, 양식 변경 금지). 직원·가이드 정산은 M2 이후 정의를 제안하고 지금은 구현하지 않는다.
  - OTA 연결은 가맹점·정확 금액에 카드 끝자리 또는 결제일이 더 맞으면 성립하며 상호 유일성을 요구하지 않는다(LINK-002). 캐시·포인트 비용도 카드 거래와 같은 귀속 절차를 따른다(ITEM-019).
  - LINK-018은 2026-11-11 확정됐다. `ui/wave3-20261110`은 재검증 후 배포가 승인됐으며 M1·M2 착수도 승인됐다.
  - 전체 결정은 통합 명세 부록 A에 있다.
- **다음 작업:**
  1. (완료) 과거 명세 112개와 인계 문서를 `docs/history/specs-20261110/`로 내렸다. 절차서 두 개는 `docs/playbooks/`로 옮겼다.
  2. M1 기준선: 판정 상태·주체별 건수 등을 [운영 기록](operations.md)에 남긴다(운영 DB는 읽기 전용).
  3. M2 작업을 [작업판](agents/BOARD.md)에 올린다. 첫 작업은 Windows에서 에이전트 CLI의 사건 폴더 격리 확인이다(통합 명세 §6.6).
- **사용자 확인 대기:** 없음. LINK-018, 세무 자료, `ui/wave3-20261110`의 재검증 후 배포, M1·M2 착수 결정은 반영했다. 직원·가이드 정산 정의는 M2 이후 제안하며 현재 구현하지 않는다.
- **코드와 규칙이 다른 곳 24건**은 [목록](policy/CODE_GAPS.md)에 있다. M2에서 정리한다. 코드를 읽어 찾은 것이며 실행해 재현하지는 않았다.
- **규칙집을 만든 방법과 한계**는 규칙집 §8에 있다. 영역별 규칙 754개는 추출·묶기 에이전트(`gpt-6.1-sol` high)의 산출을 표본 확인한 것이다.

## 2026-11-10 밤 이용일 경고 미확인 98행 원본 대조·교정 — 현재 정본(장부 이용일)

- **운영:** `965bca058a74a54bf69bc4d70a0d05f8997786c3`([#790](https://github.com/6Soo/cost/pull/790)·[#791](https://github.com/6Soo/cost/pull/791), 2026-11-10T11:07Z, 이전 `374462fe`). blob 불일치0·보호13표 불변·worker_switched=true. 다음 코드 배포는 `-PreviousSha 965bca05…`. OTA `PARSER_VERSION` 17로 스냅샷 재계산(약 11분) 후 반영.
- **경고:** 154 → 145(데이터 교정) → **132**(배포 후). 남은 항목은 숙박비 90·항공료 39·렌터카 3.
- **원본으로 교정한 데이터(인증 저장 API, 사유는 원본 메일·카드 이용일):**
  - 여행 배정:
    - 직접 결제 호텔 8건(10/14 일회성 복구 도구의 '공급자 지역 근접' 추론 오배정): 카메노이 4·플라자 게이힌 → 0704_야마가타, APA 니가타 2 → 0630_오제, 호텔 하쿠바 → 0620_묘코
    - Volotea·DISCOVERCARS → 유럽
    - 아시아나 2건 → 0722_가루이자와·1104_아오모리
  - 항목: KT엠모바일 → 통신비, 인천공항공사 16,000원 → 교통비(4/23 종료 여행 동률 → 0417_아오모리), 케이밴코리아 단기렌트 → 렌터카.
- **코드:**
  - #790: 현장 결제를 여행 시작 전날까지 인정하고, 렌터카 중개사는 예약 채널로 본다.
  - #791:
    - 결제일·끝4자리 없는 아시아나 발권 메일은 아시아나 가맹점의 같은 금액 카드와 1:1일 때만 표시한다.
    - 에어비앤비 확정 메일을 예약 이벤트로 읽고, 카드 가맹점 `AIRBNB * 코드`로 숙박일을 표시한다.
    - Klook 렌터카의 픽업·반납일을 읽는다.
  - 모두 표시 전용이며, 금융 링크·여행·Google 쓰기는 바꾸지 않는다.
- **보호해서 바꾸지 않은 사용자 결정(사용자 확인 필요):**
  - 이스타항공_ARS 2건(49,100·59,100원)과 차지비 533원이 `user_decision`으로 숙박비다. 원본상 항공권·EV 충전이다.
  - 공항 ATM 현금 인출 966,203원이 `user_exception`으로 항공료다.
  - JTB 5,165,600원은 11/2 소유자 저장(1015_오제·숙박비)이 최신이다(메일상 10/17–10/18 단체 숙박).
- **과거 장부 재사용 배정으로 보류:** APA 4/26 2건(0417_아오모리, 카드일은 0424_알펜루트 기간)·쇼나이 호텔 6/26(0620_묘코, 카드일은 0625_아키타 기간)·요코테 플라자 7/7(6/28 숙박 예약 있음, 판단 보류).
- **남은 반복 원인(다음 작업):**
  - 이스타·ANA·Volotea·DISCOVERCARS 메일 파서가 없다(각 1건 안팎).
  - 고투게이트 10건은 결제 메일에 운항일이 없다(일정표 메일 수집 필요).
  - skyticket 3건은 취소 참조 충돌로 보류 중이고, 엔화 결제 메일 형식은 파서가 읽지 못한다.
  - 산림휴양시설 NICE 다수는 메일에 이용일이 없다.
  - Rakuten 4/19 104,350×9는 원본이 없다.
- **근거 자료(비공개):** `.local-archive/warning-98-20261110/`(대상 98행, luna xhigh 원본 대조 결과 flight/lodging-evidence — 위임 결과는 표본 재확인 후 사용, 숙박 쪽은 현장결제 예약을 놓쳐 신뢰도 낮음).

## 2026-11-10 저녁 브랜치·작업공간 통합 정리 + UI/UX 재설계 진행 현황 — 현재 정본

- **운영:** `965bca058a74a54bf69bc4d70a0d05f8997786c3`(맨 위 절, 2026-11-10T11:07Z, 이전 `374462fe`). 다음 코드 배포는 `-PreviousSha 965bca05…`로 하고, 배포 전후로 같은 날 배포한 다른 cost 세션들(cost-48·cost-82·cost-a2)에 알린다. 운영 포트 8790/8751/8752는 미리보기에 쓰지 않는다(`tools/run_synthetic_preview.py`가 거부한다).
- **UI/UX 재설계([명세](history/specs-20261110/uiux-full-audit-redesign-20261110.md)) 진행 상태:**
  - **운영 반영:** PR-1(HIGH 즉시 수정)과 PR-2 기반(토큰·컴포넌트·오류 화면)은 [#779](https://github.com/6Soo/cost/pull/779)로 병합, `9ad0a454`부터 운영에 있다(UXA-01~08·10).
  - **미병합·미검증(원격 `ui/wave3-20261110`, `68ab82ba`, main 대비 58커밋):** PR-2 전수 토큰 치환, PR-3 앱 셸·내비(사이드바 진행 중 여행·하단 탭·더보기 시트·브레드크럼), PR-4 여행 장부(정산 단계·탭·서랍), PR-5 거래 허브, PR-6 홈·여행 목록·영수증·관리, PR-7 문구·셸 다듬기, 장부 'Google 장부용 복사' 영역 재설계(사실 목록·제외 거래별 사유·같은 페이지 상세 펼침), 기존 테스트 정렬. 이 브랜치의 마지막 전체 QA(`bcc88cce`, main `f786ffcf` 기준)는 1881 passed/128 failed였고 그중 **main에서는 통과하는 새 실패 69건**이 있었다. 이후 기능 회귀 5건(예시 자료 표시·`/rules` 404·업로드 복구 문구 등)을 고치고 나머지 61건 정리(테스트 정렬·셸 정리)를 병합했으나 **병합 후 재검증은 끝내지 못했다.**
  - **다음 실행(이 순서):** ① `git switch ui/wave3-20261110 && git merge origin/main` ② `python tools/run_quality_checks.py --base origin/main --run` ③ 실패 ID를 같은 main SHA 기준 worktree에서 재실행해 '새 실패 0' 확인(기준 main에도 있는 실패는 기존 실패로 분리) ④ PR 생성 → `codex gpt-6.1-sol medium` 최종 SHA 검수(CI 결제 한도 예외) → 병합 → 공식 `deploy_verified_release.ps1` 배포.
  - **작업 중 확인한 함정:** Windows에서 미리보기 서버가 운영 포트에 중복 바인딩된다(04:00–04:06 사고, 가드 추가). 셸이 페이지 `<main>`에 id를 덧붙이면 페이지 고유 id 규칙이 사라진다(셸에서 보존). `.page-body a.btn` 리셋이 `.btn.primary`를 이겨 주 버튼이 흰 상자가 된다(복원 규칙). 사이트 셸 JS가 '상세'·'관리' 등 문구의 링크에 아이콘을 자동으로 붙이므로 좁은 버튼은 `data-no-action-icon`을 쓴다.
- **정리 결과:** 병합 완료된 로컬 브랜치 33개·원격 브랜치 21개와 임시 worktree(`cost-ui-*`, `cost-w3-before`, `cost-base-check`, `cost-process-20261109`, Paseo UI 워크스페이스 12개)를 제거했다. 삭제 전 모두 main 또는 `ui/wave3-20261110`에 커밋이 포함됐는지(남은 커밋 0)와 미커밋 변경 0을 확인했다. 메인 체크아웃 `C:/AX/cost`는 `main`(`374462fe`)으로 옮겼다.
- **보존한 미병합 브랜치(병합 승인 아님):** `ui/wave3-20261110`(위), `fix/flight-passenger-names-20261108`(11커밋, 오래된 기준), `fix/skyticket-overseas-purchase-dates-20261109`(8커밋, PR #765는 CLOSED, 로컬 전용이던 1커밋 `d50e76f2`를 원격에 보존), `fix/mobile-income-single-line-20261109`(1커밋, 원격에 새로 보존). 다른 세션의 열린 PR [#788](https://github.com/6Soo/cost/pull/788)과 그 worktree `C:/AX/cost-wt-trip`은 건드리지 않았다.

## 2026-11-10 Trip.com 사전승인 반영·Gmail 수집 복구 — 현재 정본(OTA·Gmail)

- **운영:** `374462fe922a67b53758d7e1d8bb46c5e4eedaf6`([#787](https://github.com/6Soo/cost/pull/787) Trip 주문·카드 사전승인 근거), 이전 `998dd461`. blob 불일치0·보호13표 불변·worker_switched=true.
- **Trip 반영:** 사용자가 알려 준 이메일 인증번호로 예약 계정 로그인 → 호텔 주문 상세 502건을 `trip-api-v1`로 수입(백업 `D:/WebLedgerHost/data/backups/ota-evidence-before-trip-api-20261110.sqlite`). 현장결제 호텔의 카드 사전승인은 장부에서 `MM.DD–MM.DD 사전승인`/`사전승인(취소)`와 환불 상태로 표시. 장부 경고 175 → **154**(Trip 38→17).
- **확인 필요(금융):** 사전승인은 체크아웃 후 환불되는 보증금인데 카드 명세에 환불 행이 들어온 것은 일부뿐이라, 현재 숙박비 합계에 환불된 보증금이 포함돼 있다. 금액·분류는 자동으로 바꾸지 않았다 — 환불이 찍힌 카드 명세 업로드 또는 사전승인 행 처리 결정 필요.
- **Gmail 수집 장애·복구:** 17:06 KST부터 수집 토큰 갱신이 400으로 실패(OAuth 앱 "테스트 중" 상태의 7일 만료). 사용자 지시로 ego lite에서 재인증하고, Google 인증 플랫폼(프로젝트 `exemplary-vista-312906`) 브랜딩에 홈페이지·개인정보처리방침 링크(`foresttour.kr`)를 넣어 **프로덕션으로 게시**한 뒤 다시 재인증(18:17 KST). 수동 1회 수집 정상(신규 11건). 이전 토큰은 `secrets/gmail-collector-token.{expired,testing}-20261110.json`.

## 2026-11-10 OTA 포털 직접 조사·자동 보강 — 당시 정본(최신은 위 절)

- **운영:** `998dd46100a8bd11304532f741e15f162fd9c3c6`([#784](https://github.com/6Soo/cost/pull/784)), 이전 `895a412e`([#783](https://github.com/6Soo/cost/pull/783)+[#781](https://github.com/6Soo/cost/pull/781)) ← `9ad0a454`. 두 배포 모두 blob 불일치0·보호13표 불변·worker_switched=true·Gateway 유지. 다른 세션(UI/UX)과 배포 순서를 메시지로 조율했다.
- **사용자 지시:** Agoda·Trip.com·Booking.com을 ego lite로 직접 조사하고 자동 보강 방법과 이후 수집 절차를 문서화. 절차·결과 정본: [OTA 포털 직접 수집 절차](playbooks/ota-portal-collection.md). AGENTS.md의 Agoda 수집 규칙을 이 결정으로 갱신했다.
- **자동 보강:** Agoda 예약 상세 API 응답을 `agoda-api-v1` 포털 근거로 읽는 파서·수입 도구(#783)와 동일 객실 묶음 표시 규칙(#784). 운영 저장소에 1,418건 수입(백업 `D:/WebLedgerHost/data/backups/ota-evidence-before-agoda-api-20261110.sqlite`). 장부 경고 182 → **175**(Agoda 35→28).
- **장부 교정:** Booking.com에서 산 항공권 2건(카드 가맹점 `Booking.com`+숫자)이 국내여행 숙박비로 들어가 있어 항목 `항공료`·해당 해외여행으로 이동(근거: Booking 여행 페이지). 카드 행 이용일은 화면에서 직접 고칠 수 없어 날짜는 미표시로 남는다.
- **Trip.com(사용자가 알려 준 이메일 인증번호로 예약 계정 로그인 후 조사):** 주문 1,002건·호텔 상세 502건. Trip "숙박비" 경고 38행 중 23행은 현장결제 호텔의 **카드 사전승인**(대부분 체크아웃 후 환불 완료)으로 실제 숙박비가 아니다. 자동 반영(사전승인 표시·환불 짝)은 후속 구현.
- **차단·후속:** Booking 숙소 결제의 정확 대사(숙소 통화 금액)와 Booking 항공권 출발일 파서, 취소 예약 결제의 "취소된 예약" 표시, 남은 Agoda(다른 계정 추정) 15행은 후속.

## 2026-11-10 장부 이용일 경고 근본 원인 수정·성능 회복 — 당시 정본(최신은 위 절)

- **운영:** Board·Worker는 `9ad0a454ae323cb6ee61c2a4827dca3bf34caa15`(아래 PR과 다른 세션의 UI 1차 #779 포함)로 공식 단일 코드 배포됐다. 이번 작업의 배포 순서: 2ef58a92 → 4151d805 → 7334f1ae → cee973fb → 086acc67 → 094e52c9 → f5758929 → 9ad0a454(이전 검증 복구점 f5758929). 9ad0a454는 다른 세션(UI/UX)과 조율해 이 세션이 단일 작성자로 배포했다. 각 배포: tracked blob mismatch0, health/ready200, 보호 API401, 보호13표 전후 불변, `worker_switched=true`(이 절의 2ef58a92 이후 배포 기준). 근거: `D:/WebLedgerHost/releases/deploy-evidence-<SHA>.json`, `continuous-switch-<SHA>.json`, 비공개 `.local-archive/service-date-row-audit-20261109/deploy-<SHA8>/`.
- **병합 PR(모두 독립 `codex/gpt-6.1-sol`·`medium` 최종 SHA APPROVE, 호스팅 CI는 결제 한도로 미시작=NOT_GREEN, 2026-11-07 예외):**
  - [#772](https://github.com/6Soo/cost/pull/772) 장부 이용일 인덱스를 스냅숏 세대당 1회 계산(운영 규모 257.6s→약 8s, 결과 동일 325쌍).
  - [#774](https://github.com/6Soo/cost/pull/774) 렌더당 `board_rows` 1회 스캔(`display_tab_id` 무인덱스로 탭 55개 각각 전체 스캔하던 1.2s→0.04s), 커밋된 부분환불 분석을 변경(total_changes/data_version) 전까지 재사용(페이지당 0.68s). 운영 실측: 여행 장부 3.5–9s(잠금 대기 p50 1.2s·p95 52s) → **약 1s**(p50 0.003ms·p95 0.2s). 영향 QA 483 passed/10 failed — 10건(`test_card_flow_browser.py` 9, `test_read_scope_and_probe.py::test_store_lock_wait_is_recorded_for_real_http_request` 1)은 **기준 main에서 동일 재현되는 기존 실패**로 별도 과제.
  - [#775](https://github.com/6Soo/cost/pull/775) ① OTA 재계산(5–9분, 잦은 `SOURCE_CHANGED_DURING_RECONCILIATION` 실패) 동안 장부 OTA 이용일이 전부 사라지던 결함 → 마지막 완결 세대를 화면 표시용으로 유지(쓰기·연결 경로는 계속 fresh 요구). ② 여행 기간 안의 직접 가맹점 숙박·렌터카 카드 결제는 `MM.DD 현장 결제`로 카드 이용일 기준임을 표시(예약·PG·국내 여행사·마켓·ARS 채널 제외, 숙박 일수 추론 없음).
  - [#776](https://github.com/6Soo/cost/pull/776) ① 기간 없는 Booking.com 결제 이벤트가 같은 예약번호의 유일한 유효 예약 기간을 표시(낡은 링크·digest 불일치·취소/환불 관측이 하나라도 있으면 보류). ② **어드벤처코리아(skyticket) 736,240원 근본 원인**: 실제 원본 본문이 CRLF라 `합계` 줄 정규식이 금액을 못 읽음 → 줄 끝 정규화(운영 원본 재추출로 금액·출발/귀국일 복구 확인).
  - [#777](https://github.com/6Soo/cost/pull/777) 4월 이후 숙박을 그 전에 예약한 확정 메일 미수집(예: 4월 중순 숙박의 Booking 확정 메일이 1월 초 수신) → 일일 과거 대조에 2025-04-01~2026-04-01 **공급사 발신 메일만** 보충 창 추가. 첫 운영 실행에서 보충 대상이 5,073건(미보유 4,848건, 1건 약 0.76–1.5초)이라 작업 제한 1800초에 걸려 진행분을 모두 잃는 결함을 발견 → [#778](https://github.com/6Soo/cost/pull/778) 200건 묶음 원자 저장·강제 종료 임시 파일 정리. 이후 매시간 실행마다 이어 받아 2026-11-10 06:29 KST에 완료(`history-reconciliation.json`: `supplier_after 2025-04-01`, 대조 9,259건, 마지막 실행 848건 추가, 통합 저장소 가져오기 완료). 이후 정상 실행은 미보유분만 받으므로 3–4분에 끝난다.
  - [#782](https://github.com/6Soo/cost/pull/782) 재기동 직후 완결 세대가 없을 때 메일 보충 등으로 입력이 바뀌면 재계산 결과를 매번 버려 장부 이용일이 장시간 비던 결함(경고 222→377) → 첫 세대만 입력이 바뀌어도 메모리에 표시용으로 게시(fresh 아님·디스크/콜백 게시 없음·즉시 재계산). 운영에서 `refresh_done … outdated_by` 확인.
  - [#780](https://github.com/6Soo/cost/pull/780) 이용일 근거가 없는 환불·취소(음수) 행은 경고 대신 `취소·환불`로 표시(이미 날짜가 있는 행·양수 행·내보내기/Google 복사 경로 영향 없음).
- **장부 교정(인증 UI 저장, 수동 교정 이력 보존):** 어드벤처코리아 카드 3행 항목 `여행상품비→항공료`. 전액 환불·취소된 Rakuten 예약 1건은 환불 탭으로 이동(이용일 미표시가 정상).
- **장부 이용일 경고(인증 ego-browser 68여행·2,859행 전수, fresh 스냅숏 기준):** 최초 519 → 440 → 344 → **222**(cee973fb) → **183**(9ad0a454, 2026-11-09T20:4xZ, 숙박비 138·항공료 40·렌터카 5). 보충 완료·OTA 재계산(2026-11-10T02:44Z) 뒤 최종 **182**(숙박비 137·항공료 40·렌터카 5). 보충으로 직접 해소된 행은 1건(Booking은 #776으로 이미 27→12)이며, 나머지는 아래 원인별 잔여다. 재계산 창과 겹친 집계(425)는 원인①의 증상이었다.
- **남은 경고 원인(코드로 단정 불가·수집 공백):** Agoda 35(확정 메일이 이 메일함에 오지 않고 포털 수집은 10/21이 마지막 — 전용 Paseo IAB 수집 필요), Trip 38(같은 금액 카드 2장↔예약 2건 등 카드별 대응 근거 없음·예약 근거 없음), Booking 11(같은 예약번호의 어떤 메일에도 숙박 기간 없음), 나머지 98 중 숲나들e/산림휴양시설 약 20(사전 예약 결제, 이용일 원문 없음), 결제일이 여행 기간 밖인 직접 결제 16, 항공 직접/고투게이트 등 35(예약 확정서 미수집 또는 확정서에 일정 없음), 취소·환불된 skyticket 예약 3건은 날짜 미표시가 정상. 행·예약 식별자는 비공개 `.local-archive/service-date-row-audit-20261109/`에만 둔다.
- **프로세스 점검 결과:** 운영 상시 프로세스는 Board 1(Gateway 8790→8751/8752)·Worker 1(mail-collect 매시 30분 약 1.5–3.5분, review-source·roster·google-authority 감시). OTA 스냅숏 재계산은 Board 안에서 60초마다 입력 지문(원천 약 1.2GB SHA-256 2회)을 계산하고 입력 변경 시 5–9분 재계산한다. 원본 내용 기반 지문은 기존 계약(크기·시각 같아도 내용 변경 감지) 때문에 유지했다. 재기동 직후에는 디스크에 공개 요약만 있어 첫 재계산 완료(약 7–15분)까지 OTA 이용일이 비어 보인다 — 후속 과제.
- **Gateway:** `WebLedger-Gateway` 작업은 `releases/f7ff4ec4…/tools/ledger_gateway.py`를 실행한다. 이후 `ledger_gateway.py` 변경이 없어(diff 0) 동작상 문제는 없으나, 7일 보존 정리에서 이 릴리스 폴더는 실행 중 자산으로 보존해야 한다.
- **운영 장애 1건(복구 완료):** 2026-11-10 04:00–04:06 KST 다른 Claude 세션의 합성 미리보기(`run_synthetic_preview --port 8790`)가 운영 Gateway 포트를 차지하고 운영 Gateway(PID 9964)가 종료돼 공개 장부 인증 요청이 401이었다. 미리보기 프로세스만 종료하고 `WebLedger-Gateway` 작업을 재시작해 복구(Gateway PID 19504, 인증 장부 200). 해당 세션에 운영 포트(8790/8751/8752) 사용 금지를 전달했고 확인 답신을 받았다. healthz는 미리보기도 200이라 인증 GET으로 확인해야 한다.
- **미검증/후속:** 재기동 직후 OTA 이용일 공백, 재계산 실패 원인 입력 성분 미확정, 기존 실패 테스트 10건, 실기기·스크린리더.

## 2026-11-09 작업공간 통합 정리 — 당시 정본(최신은 위 2026-11-10 절)

- **코드 기준:** `origin/main`은 [PR #763](https://github.com/6Soo/cost/pull/763) 병합 `00499a52`(코드 트리는 검수 SHA `2723125a`와 동일)다. 작성 시점(2026-11-09 오후)에 열린 PR은 이 정리 PR([#764](https://github.com/6Soo/cost/pull/764))과 다른 담당의 코드 PR [#765](https://github.com/6Soo/cost/pull/765)(skyticket 해외 구매 메일·항공료 일수)뿐이다. 호스팅 CI는 결제 한도로 시작되지 못해 녹색이 아니며, 2026-11-07 승인 예외(`sol medium` 이상의 최종 SHA 독립 검수)로 병합했다.
- **운영 기준:** Board task는 `d67a1312d6e592648db0ed6ea95e49ff5aa9d053`(PR #764 병합, #763 코드 포함)로 단일 코드 배포됐다(이전 `c202fe6e`). 1,459 blobs mismatch0·health/ready200·보호 API401·보호13표 불변. 상세는 [운영 기록](operations.md) 맨 위 절이다. 아래 11월 9일 절의 배포 전 표현은 당시 상태다.
- **정리 결과:** 병합 완료된 로컬·원격 브랜치와 임시 worktree 6곳(`cost-copy-docs`, `cost-copy-qa`, `cost-release-date`, Paseo 2곳, 기준선 사본), 오래된 stash 7개를 제거했다. 미커밋 변경·미추적 스크립트·stash 내용은 삭제하지 않고 비공개 `C:/AX/cost/.local-archive/cleanup-20261109/`에 patch·zip·목록으로 보관했다(복원 방법: patch는 `git apply`, 미추적은 zip/폴더 복사).
- **보존한 미병합 작업(병합 승인 아님):** (1) `fix/flight-passenger-names-20261108`(원격 유지, 11커밋): 항공 탑승객 한글 표기·공유 숙박 기간 근거·카드 레거시 날짜 등. 이 중 `5e14e8d2`는 main에 이미 반영됐고 나머지는 오래된 기준(`91dbc581`)에서 갈라져 main 변경과 겹치므로 영향 QA 없이 병합하지 않는다. (2) `fix/mobile-income-single-line-20261109`(로컬 전용, 1커밋): 모바일 수입 연결 상태 한 줄 CSS와 worktree의 미커밋 CSS/테스트 변경(patch 보관). 두 브랜치는 `unmerged-branches.bundle`로도 보관했다. 둘 다 별도 검증된 PR로만 병합한다.
- **진행 중인 별도 작업:** 이용일 경고 402행 개별 조사·어드벤처코리아 항공료 표시는 다른 담당이 `C:/AX/cost`에서 계속 진행한다. 그 작업의 미커밋 코드 변경은 이번 정리 대상에서 제외했고 `fix/ota-rental-source-period-20261109` 로컬 브랜치도 그 작업이 쓰므로 삭제하지 않았다.
- **여전히 미검증:** 인증 운영 화면(`AUTH_UI_BLOCKED`)의 카드 진입 성능·복사 붙여넣기·68장부 이용일 경고 감소, 실기기/Safari/스크린리더. 완료로 보고하지 않는다.
- **문서 구조:** 이 문서와 [운영 기록](operations.md)에는 2026-11-08 이후 절과 운영 절차만 남겼다. 2026-11-07 이전 인계는 [이전 인계](history/session_handoff-through-20261107.md), 운영 기록은 [운영 기록 10/28~11/07](history/operations-20261028-20261107.md)과 [10/27까지](history/operations-through-20261027.md)에 원문 그대로 있다. 과거 ACTIVE/READY/대기 표시는 새 개발 과제가 아니다.
## 2026-11-09 이용일 근본 원인 수정 배포 / 원문 개별 조사는 계속

- 최신 실행 지시: **단순 연결에 그치지 않고 원문 조사에서 근본 원인을 찾을 때마다 코드 수정·회귀 검증**. 전체 402행의 개별 원문 조사·교정은 진행 중이다. 아래 과거의 `조사 완료`·Draft·미배포 설명은 당시 상태이며 현재 전체 완료 근거가 아니다.
- [PR #762](https://github.com/6Soo/cost/pull/762), 검수 코드 `7a2b126a063d8032bcba18b5d9b60bc7636ae866`, 운영 `c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a`. 항공 확정서 일정이 결제 문맥에 전달되지 않던 결함, 일반 예약 파서에 가려진 명시 완료 환불, 예약번호 공란인 기존 카드의 검증된 항공 날짜 표시를 수정했다. 환불 처리 중·예정·부정·요청 표현의 잘못된 완료 판정도 독립 검토에서 재현·수정했다.
- 최종 영향 QA **697 passed +47 subtests, skip0, compile PASS**. 독립 최종 SHA 검수 **210 passed / APPROVE**, 추가 부정11·완료5 파이프라인 PASS. Paseo runtimeInfo로 검수자의 `codex/gpt-6.1-sol`·`medium` 확인. 호스팅 run42555491219/job128960134984는 Billing/spending limit·steps0 시작 불가였으며 CI 녹색이 아니다. 기존 2026-11-07 승인 예외와 정확 SHA/로컬 QA로 병합했다.
- 공식 단일 코드 배포: 1,454 blobs mismatch0, task/process/runtime SHA 일치, Gateway8790→loopback8751·listener1·health/ready200·보호 API401·보호13표 전후 불변. 이전 검증 운영 d96f0880 복구점 보존. 기존 #759/#761 병합 코드도 이 배포에 포함됐다. 금융/Google/원문/여행 배정 쓰기·마이그레이션·대량 재처리0.
- 실제 보존 원문을 배포 릴리스의 호스트 Python으로 재추출해 항공 일정·완료 환불의 금액/일정 복구 확인. PC1440/모바일390 합성 before/after 날짜 표시·넘침0, 독립 코드/화면 검수. **인증 운영 68장부의 경고 감소·전체 402행 해소·실기기/스크린리더는 미검증**이며 완료로 보고하지 않는다.
- 다음 개별 원문에서 렌터카의 새 제목·통화 접두 선결제액·인수/반납일 추출 누락을 재현해 별도 코드 수정 중이다. `parser16`에서 유일한 정수 KRW 온라인 선결제액만 읽고 실패·미완료·예정은 결제 완료로 승격하지 않는다. 렌터카 기간을 박수 대신 인수·반납일로 표시한다.
- 라쿠텐은 인증 예약 확인서의 예약 ID와 공급자 예약 번호를 구분하고 기간·예약일·할인 후 예약금액·카드 끝자리를 보존한다. 공급자·예약일·원금액·끝자리가 일치하면 읽기 전용 기간 추론에만 사용한다. `paid_on=None`·`payment_event_id=None`·`RESERVATION_ONLY`, 수수료 포함 KRW 청구액의 금융 비교 계약 유지. 공급자 목록 누락과 일반 결제 확정 UI의 오표시도 수정 중이다. 실제 보존 원문의 두 사례 재추출 PASS·금융 쓰기0. 이 후속은 아직 최종 SHA 검수·병합·배포 전이다.
- 최신 상세 체크포인트는 비공개 `.local-archive/service-date-row-audit-20261109/individual-investigation-checkpoint.md`; 고객 원문·식별자는 Git/PR에 포함하지 않는다. 기존 ego-browser TaskSpace10이 없어 실시간 브라우저 재개는 사용자 응답 대기이며 저장된 원문 조사와 코드 수정은 계속한다.
- 배포 근거: `D:/WebLedgerHost/releases/deploy-evidence-c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a.json`, 비공개 `deploy-flight-refund-c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a/`. 문서만의 후속으로 재배포하지 않는다.

## 2026-11-09 여행 장부 이용일 경고 — 초기 조사·Draft 당시 기록

- 최신 요청 `이용일 확인필요라고 떠있는건들 조사`의 대상은 카드 목록 날짜 경고가 아닌 여행 장부다. 인증 ego-browser GET으로 여행68개·지출2860행을 전수 확인해 숙박비353행/항공료49행 경고를 조사했다. [원인별 집계·수정·검증 한계](history/specs-20261110/ledger-service-date-investigation-20261109.md).
- [Draft PR #759](https://github.com/6Soo/cost/pull/759), 코드 SHA `221849f10f80b24e482a58cf2cfa8902ad56c2c2`: M:N 동일 이용기간과 항목 메타데이터 누락의 표시 보완. 표적71pass·독립64pass/정확SHA 코드APPROVE·합성1440/390/320 전후 넘침0. 금융·원본·예약 연결·여행 배정·Google 쓰기 없음.
- **필수 영향 QA245pass/1fail·skip0·compilePASS**. 기존 `test_toyoko_reconciliation.py`85행이 호환 링크 화면에 예약번호를 기대하며 기준 모듈에서도 실패한다. 테스트 제외나 범위 밖 수정 없음. 실제 실패에 CI 인프라 예외를 적용하지 않았으며 병합·배포·재시작 미실행이다.
- 보관 worker 입력 기준73행은 표시 보완 후보(새 경로71행 추가)지만 운영 snapshot과 세대가 달라 운영 해결 건수로 주장하지 않는다. 나머지 원인과 항공료49행도 개별 조사 기록에 보존했다. 운영은 조사 당시 `d96f08809b8201238e8399d053140ab20e3a91fc`이며 이전 카드 날짜0건 보고는 이 요구의 완료 근거가 아니다.
- 정확한 재개점: 비공개 `C:/AX/cost/.local-archive/service-date-investigation-20261109/CHECKPOINT.md`. 기존 검사 실패 별도 처리→필수 영향QA→최종SHA검수/정상병합→공식 단일배포→같은68장부 실제감소 수락이 남았다. 배포 보호 경계 유지.

## 2026-11-09 산림치유원 NICE 메일 — 운영 수집 전환·누락 원문 복구 완료

- [PR #752](https://github.com/6Soo/cost/pull/752)의 수집·파서 수정은 통합 운영 SHA `d96f08809b8201238e8399d053140ab20e3a91fc`에 포함되어 있다. 제품 검수 HEAD `d337121f45335a3fdd1486afb97e7ad53ba1d1d8` 영향 QA411 passed·skip0·compile PASS·필수 브라우저1/1, 독립 gpt-6.1-sol/medium 승인 근거를 유지한다. CI는 결제/사용 한도의 steps0 차단으로 녹색이 아니었다.
- 통합 배포와 최종 보호13표 구간 종료·잠금 해제 통지를 받은 뒤 전용 자료 복구 구간을 실행했다. 기존 hourly 수집의 정상 종료를 기다려 MailCollect working directory를 구43907dd에서 d96 고정 릴리스로 전환했다. 실행파일·인자·인증 파일을 보존했고 작업은 Enabled/Ready로 복구했다.
- 인증 Gmail API로 정확30개 ID 집합과 원본 payload digest30/30을 재검증했다. OTA 백업과 별도 복원본의 내용/무결성 동등성을 확인한 뒤 기존 원문을 덮어쓰지 않고 **누락30건을 원자 추가**했다. 기존 원문/원본 blob/원본 entry 행 해시 보존, 반복 import 쓰기0, 수집 watermark 불변, 금융 보호13표 불변 PASS. 금융 원행·수동 결정·환급 확정·Google 최종 장부 쓰기는 하지 않았다.
- 실제 운영 d96 모듈로 읽기 수락: 복구 원문30/30 존재·이벤트30개·0원 오인식0, 대상 7월 결제11건 중 취소 안내6건을 대조해 잔여5건 확인. 은행 환급 완료나 예약 유지 확정으로 승격하지 않는다. Gateway health/ready200·보호 API401 확인, 서버 재배포/재시작은 하지 않았다.
- **최신 사용자 지시: 숙박일 추가 질문 없이 지리적으로 가까운 기존 여행에 배정한다.** 진안고원산림치유원은 전북 진안/호남권이므로 해당 7월 거래는 기존 `1115_호남` 여행에 귀속 완료다. 운영 읽기 검사에서 원결제·취소가 같은 여행에 code_inference/classified로 귀속되고 미배정0임을 확인했다. 이미 올바른 귀속이라 금융·수동 이력을 다시 쓰지 않았다. 과거 숙박일을 필수 사용자 사실로 둔 차단은 철회하며 여행 귀속을 미완료로 되돌리지 않는다. 실제 이용일이나 예약 유지를 창작하지 않는다. 인증 고객 화면의 독립 시각 수락은 미실행이며 이 귀속 확인과 구분한다.
- 비공개 실제 근거는 `C:/AX/cost/.local-archive/forest-receipts-20261108/`의 source-recovery-evidence.json, post-recovery-acceptance.json, mail-task-release-evidence.json과 checkpoint.md다. 백업/별도 복원본은 `D:/WebLedgerHost/data/backups/forest-mail-20261108T201146Z/`에 보존했다. 아래 이전 복구 대기 문구는 실행 전 역사 기록이며 현재 복구 상태가 아니다. 이 문서 전용 후속은 재배포하지 않는다.

## 2026-11-09 여행 지출 실제 복사·Job 수명주기·OTA 메모리 — 운영 수락 완료

- 최신 사용자 `해결을 해`의 운영 복사 오류를 해결했다. 준비된 TSV를 먼저 선택해 동기 복사를 시도하고 선택적 비동기 클립보드 응답은 1.5초로 제한한다. 응답이 없거나 거부되면 원문 선택·재복사 경로와 활성 버튼을 유지한다. 요청 안에서만 행 조회를 재사용하며 원본 검증·Google 대조·기존 7열/중복 제외 계약을 유지한다. Google 최종 장부 쓰기는 실행하지 않았다.
- 최종 운영 SHA **`d96f08809b8201238e8399d053140ab20e3a91fc`**, 이전 검증 `db7ce9954bcdd4e9a858035e99d23c683ec82349`. [복사 #751](https://github.com/6Soo/cost/pull/751), [수명주기 #754](https://github.com/6Soo/cost/pull/754), [OTA 메모리 #756](https://github.com/6Soo/cost/pull/756), [종료 경합·복귀 보호 #757](https://github.com/6Soo/cost/pull/757)를 포함한다. 최종 main tree는 검수 `3d859e9c0d1195b69b03ebbcb6a8fb11fa62ec4a`와 동일하다. 원문 복구 #752와 날짜 #755의 기존 병합도 보존했다.
- 정확한 소스별 영향 검사: 복사 **425 passed +85 subtests·필수 browser43/43**, OTA **424 passed +4 subtests·browser10/10**, 합본 교차 **23 passed**, 배포 종료 보호 **100 passed**. 각 검사 skip0·compile PASS이며 서로 중복된 검사를 합산한 고유 검사 수로 표시하지 않는다. 폐기된 제안 UI/분류 대기 기대는 현행 DEST 검사로 대체하고 API 권한·금융 원본·원자성·멱등성 보호는 유지했다. 초기 red 결과는 별도로 보존했다.
- 실제 독립 `gpt-6.1-sol / medium`이 후보·합본·정확 main SHA를 검수해 승인했다. CI run42516114312/job128839384202(copy union), run42515451899/job128837348189(OTA), run42517410150/job128843348971(종료 보호)는 각 정확 SHA에서 runner0/steps0 결제·사용 한도 미시작이다. **CI는 NOT_GREEN**이며 2026-11-07 사용자 승인 예외를 적용했다. 실행된 검사 실패를 예외로 통과시키지 않았다.
- **인증 운영 native 수락 PASS:** ego-browser의 실제 1440px·390px에서 각각 **17행·7열** 준비 값과 OS Ctrl+V 결과가 정확히 일치했다. 버튼 활성 복귀·오류 없음·페이지 넘침0, 키보드 실행을 확인했다. 복사부터 붙여넣기 비교까지 각각 2,728ms·2,828ms인 단일 표본이며 이전 다른 여행/상태의 지연과 같은 입력 성능 비교라고 주장하지 않는다. 동일 크기 운영 전후 캡처와 합성 1440/390/320·두 테마 전후·예외 상태 근거를 보존했다. 고객 원문/화면은 비공개 산출물에만 둔다. TaskSpace0을 마치고 사용자 결과 탭은 유지했다.
- 공식 코드 전용 배포: **1,453 tracked blobs mismatch0**, task/process/runtime SHA 일치, Gateway8790→loopback8752·listener1·health/ready200·보호 API401. fresh 보호13표 전후 불변과 운영 재기동/복사 뒤 최종 불변을 확인했고 단일 작성자 잠금을 해제했다. 실제 운영 stop/start 두 회차에서 이전 프로세스14개가 매번 전부 종료되고 새 소유자1개가 유지됐다. Running 중 추가 시작도 같은 소유자를 유지했다. 자식 crash/descendant kill/mutex 재사용·경쟁은 별도의 실제 Windows 합성 Job 검사로 검증했으며 운영 자식을 의도적으로 crash한 것은 아니다.
- 첫 후보 `c2f7bdd7`의 전환은 **FAILED**였고 이전 db7 서비스·ready200·보호13표 불변으로 복구했다. 기존 도구가 첫 예외를 가려 실제 최초 원인은 미확정이다. 합성으로 확인한 stale TCP/CIM 조회, 검증 직후 PID 종료, 후보 cleanup 오류의 복귀 건너뜀, 실패 기록 쓰기의 복귀 차단을 수정해 새 불변 릴리스 d96을 배포했다. 실패 c2를 수정하거나 성공으로 재분류하지 않았다. unknown/reused PID 종료 금지는 유지한다.
- OTA 동일 합성 입력80개·4범위320관측에서 본문 보존320→80, catalog peak private503,541,760→450,428,928 bytes, reconcile507,183,104→453,758,976 bytes(약11%)이며 결과/원본 해시가 동일했다. catalog wall time은 단일 표본에서 개선되지 않았다. [재현 명세](history/specs-20261110/ota-mail-load-lifetime-20261109.md). 운영 warm 중 private1,826.7MiB(db7)→1,019.3MiB(d96), warm 완료 후296.9MiB·10프로세스·소유자1·CPU0.015625초/12.6256초로 수렴했다. 이는 같은 입력을 통제한 운영 효과율이나 장기 누수 완치 증명이 아니며 venv 부모/자식 쌍을 중복 보드로 세지 않는다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d96f08809b8201238e8399d053140ab20e3a91fc.json`; 비공개 `.local-archive/copy-paste-resume-20261109/`의 `production-copy-acceptance.json`, `release-d96f0880/`, `runtime-before.json`, `runtime-after.json`, `runtime-after-warm.json`; 합성 계측은 `.local-archive/webledger-root-20261109/`. PC 담당에게 A–F 최종 결과를, 원문 복구 담당에게 최종 SHA·after13 PASS·lock release를 전달했다. 원문30건 복구는 그 담당의 별도 승인 구간이며 이번 코드 배포의 완료 범위로 꾸미지 않는다.
- 남은 필수 복사/배포 작업은 없다. 실기기/Safari·스크린리더 음성·실제200% 확대와 장시간 운영 누수 검증은 미실행이다. 이 후속 문서 변경으로 코드 검사·재배포·서버 재시작을 반복하지 않는다. 아래 11월8일 AUTH_UI_BLOCKED 기록은 당시 이력이며 현재 복사 수락 상태를 대체하지 않는다.

## 2026-11-09 산림치유원 NICE 메일 — 코드 병합 완료 / 운영 복구 대기

- 사용자 요청은 메일 조사에서 발견한 문제 전체 해결이다. [PR #752](https://github.com/6Soo/cost/pull/752), 검수 SHA `d337121f45335a3fdd1486afb97e7ad53ba1d1d8`, 정상 main 병합 `25d41ff933a35fc42122e2d4da6264a6a6f4a45f`(동일 tree). Windows/CloudMail 검색의 산림치유원 누락, NICE 취소금액·취소요청일시 파싱을 교정하고 수수료와 결제금액 구분 및 과거 forest-only 복구 경로를 검증했다. 금융 원행·수동 결정·환급 확정·Google 최종 장부는 변경하지 않았다.
- 정확 검수 SHA의 영향 QA **411 passed, skip0, compile PASS, 필수 브라우저1/1**. 독립 실제 `gpt-6.1-sol / medium`은 제품 HIGH/MEDIUM 결함 없음·CI 예외 병합 승인을 기록했다. CI42492278382/job128767045020은 billing/spending-limit으로 steps0에서 차단됐으며 녹색 CI가 아니다.
- 대상 누락 원문30건은 인증 Gmail 읽기와 정확 ID 집합·원본 payload digest 재열람30/30으로 확인했다. 보관소 추가 복구·운영 배포·예약 작업 변경은 **미실행**이다. 과거 `pg_mail_index.json`은 운영 입력이 아니며 고객 자료를 Git에서 수작업으로 덮어쓰지 않는다.
- 실제 운영 Windows Job/mutex 감독기 정식 통합과 단일 배포 순서를 조정 중이다. 기존 기동 보호를 제거하거나 구 배포 경로로 우회하지 않는다. 통합 코드 배포의 보호13표 전후 확인 종료 후 MailCollect의 구버전 working directory를 검증 릴리스로 고정한다. 그 뒤 별도 자료 복구 보호 구간에서 OTA 백업·별도 복원 동등성·단일 작성자·기존 원문 불변·반복0쓰기·watermark 불변을 확인해30건만 추가한다.
- 실제 숙박일은 보관자료와 별도 예약메일 검색에서 근거를 찾지 못해 사용자에게 필수 사실을 질문한 상태다. 결제일/주문번호를 숙박일/예약번호로 만들지 않는다. 코드 병합을 실자료 복구·은행 환급·예약 유지·이용일 확정 완료로 보고하지 않는다.
- 비공개 인계: `C:/AX/cost/.local-archive/forest-receipts-20261108/checkpoint.md`에 QA/JUnit·독립 검수·원본 동등성 manifest·복구/사후 수락 명령을 보존했다. 임시 작업공간은 후속 운영 복구에 사용 중이며 루트의 다른 작업·미추적 파일은 보존했다. 이 상태 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-08 여행 지출 복사 포커스 오류 복구 — 당시 운영 배포 / 후속 복사 수락으로 대체 예정

- [PR #749](https://github.com/6Soo/cost/pull/749) 운영 SHA `068de5da50611255dd4ef23d12f2a8272fe4b616`, 검수 코드 `4cc5ac3699948c828885fd46d84597e842618a71`와 webapp/tests tree 동일. 이전 운영 SHA `e1c60ad037eb6651d68058ea90ac57327e64ce20`. 아래 #744의 포커스 복원만으로 해결되지 않던 `Document is not focused` 오류에 대한 후속이다.
- 두 클립보드 API가 모두 거부해도 전체 TSV를 선택된 읽기 전용 입력에 남기고 직접 복사하거나 새 클릭으로 재시도할 수 있다. 재시도는 서버 재조회 없이 준비된 내용을 사용하고 성공 여부를 실제 결과대로 표시한다. 제외된 거래의 일자·가맹점·금액·상세 링크도 같은 최신 GET 응답에서 갱신한다. Google 대조·복사 대상 규칙, API 계약과 금융 처리는 변경하지 않았다.
- 정확한 코드 SHA의 영향 QA **305 passed +69 subtests, skip0, 필수 browser22/22, compile PASS**. TSV 경계 추가10건 통과. 실제 독립 `gpt-6.1-sol / medium` 최종 APPROVE 및 HIGH/MEDIUM 없음. CI run42473632476/job128709986234는 결제/사용한도 annotation·steps0 시작 차단으로 녹색이 아니며 2026-11-07 사용자 승인 예외를 적용했다.
- 합성 ego1440/390/320 동일 크기 전후·실제 운영 테마 초기화와 두 테마·키보드·페이지 넘침0 확인. 두 API 강제 거부 뒤 선택 텍스트 보존, 새 클릭 재시도 뒤 native Ctrl+V 내용 일치, TSV GET1회·POST0 확인. 실제 측정 안내문 대비 light7.5777/dark5.7053 이상. 초기 테마 적용이 잘못된 캡처는 근거에서 제외하고 재생성했다.
- 공식 보호 배포 증거: 1,447 tracked blobs mismatch0, runtime SHA verified, listener1·backend8752, health/ready200·보호 API3개401, 보호13표 전후 불변, financial_apply NOT_RUN. 완료 시각 2026-11-08 23:04 KST. 코드 전용 배포로 원본/금융/Google 쓰기·재처리·마이그레이션 없음. 중단 후 증거를 확인했으므로 재배포하지 않았다.
- **AUTH_UI_BLOCKED:** 재개 시 이전 인증 TaskSpace18이 `task space not found: 18`로 없어 운영 화면의 최종 복사→native 붙여넣기 해시 비교와 운영1440/390 캡처는 실행하지 못했다. 위 합성 검증을 인증 운영 수락으로 대체하지 않는다. 실기기/Safari·스크린리더 음성·실제200%확대·RTL도 미검증이다. 남은 작업은 허가된 인증 ego 세션에서 운영 GET/복사·붙여넣기 일치와 화면 확인이며 코드 재구현·재배포는 필요 없다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-068de5da50611255dd4ef23d12f2a8272fe4b616.json`, 비공개 `.local-archive/expense-copy-actionable-20261108/`의 deploy-evidence/release-audit/quality-final/junit-final/deploy-review 및 ego 결과. 고객 원문은 추적 문서에 포함하지 않는다. 후속 문서 전용 변경은 코드 검사·배포·서버 재시작을 반복하지 않는다.

## 2026-11-08 수집 현황·빈 기간 업로드 UX — 운영 완료

- 최신 요청 “제발 의도에맞게 UX UI 좀 신경쓰라고”의 대상은 카드 수집 기간 확인→빈 기간 자료 업로드 흐름이다. 빈 기간이 있는 카드사를 먼저 보여주고 날짜 옆에 `이 기간 업로드`를 배치했다. 네 개 집계 타일·반복 계산 설명을 없애고 카드사별 기간을 짧은 목록으로, 업로드 파일은 모든 기간 요약 아래 한곳의 접힌 목록으로 정리했다. 파일 처리 결과 접근은 유지한다.
- [PR #747](https://github.com/6Soo/cost/pull/747), 운영 SHA `e1c60ad037eb6651d68058ea90ac57327e64ce20`, 검증 코드 `e905a0d6a8324f048ce249197e447e65113d15e8`와 tree 동일. 영향 검사 **238 passed +70 subtests·skip0·browser20/20·compile PASS**, 실제 독립 `gpt-6.1-sol / medium` 정확한 운영 SHA 코드·interface-review APPROVE. CI run42469738253은 결제/사용한도 steps0 시작 실패로 녹색이 아니며 기존2026-11-07 승인 예외를 적용했다.
- 합성 예외 상태 및 **인증 운영 화면** 전후1440/390, 운영1440/390/320·두 테마·파일23개 접힘/키보드 펼침·Enter 업로드의 기간 맥락/파일 입력 포커스·넘침0 PASS. 운영 GET200·카드사3/파일23/공백1 및 기간/공백 projection SHA-256이 배포 전후 동일하다. 실측 라벨 대비17.0629/9.8968, 업로드5.3097/7.6095. 고객 원문과 화면은 비공개 증거에만 보존한다.
- 공식 단일 코드 전용 배포:1,446 blobs mismatch0·task/process/runtime SHA 일치·Gateway8790→loopback8751·health/ready200·보호 API401·보호13표 불변·financial_apply NOT_RUN. 단일 작성자 잠금을 기다린 뒤 정상 전환했다. 원본/금융/Google 쓰기·실제 업로드 POST·재처리·스키마 변경 없음. 이전 검증 릴리스/task XML을 복구점으로 보존했다.
- 호스트 `D:/WebLedgerHost/releases/deploy-evidence-e1c60ad037eb6651d68058ea90ac57327e64ce20.json`, 비공개 `.local-archive/coverage-intent-ux-20261108/`의 QA·리뷰·ego-final·production-after·보호 snapshot이 근거다. 남은 필수 작업 없음. 실기기/Safari·스크린리더 음성·실제 브라우저200%확대·RTL은 미검증이다. 후속 문서만으로 검사·배포·재시작을 반복하지 않는다.

## 2026-11-08 파일별 기본 조회기간·파일 사이 공백 교정 — 운영 완료

- 최신 사용자 결정: 거래일자는 자료의 조회기간 공백을 메우는 근거다. **한 파일의 최초~최종 거래일 전체**를 기본 조회기간으로 삼고 내부 무거래일은 공백으로 세지 않는다. 같은 카드사의 모든 카드 파일 범위를 합친 뒤 파일 사이 빈 구간만 표시한다. 아래 #742와 과거 거래일별 공백 계산을 이 기준이 대체한다. [현행 계약](history/specs-20261110/card-transaction-date-gaps-20261108.md).
- [PR #745](https://github.com/6Soo/cost/pull/745), 운영 SHA `a0d257c45fef1767d25d5269bbac0007c22e4f2e`, 검증 코드 `20df129ec70f29d2c298cc9179edb7afa2e14580`와 tree 동일. 영향 QA **236 passed +70 subtests, skip0, 필수 browser19/19, compile PASS**. 독립 실제 `gpt-6.1-sol / medium` 정확한 병합 SHA APPROVE. CI는 steps0 결제/사용한도 차단으로 녹색이 아니며 기존 승인 예외를 적용했다.
- ego 합성 전후1440/390/320에서 넘침0, 내부 빈 날짜 제외·파일사이 공백1·같은 카드사 다른 카드 파일로 해소 후0, 빈자료·오류 복구·키보드 포커스·업로드 맥락 확인. 인증 운영 고객 화면·실기기/Safari·스크린리더 음성·실제 브라우저200%확대·RTL은 미검증이다.
- 공식 고정 SHA 배포: 1,445 blobs mismatch0, task/process/runtime SHA 일치, Gateway8790→loopback8752, health/ready200, 영향 coverage API/화면과 보호 API401, 보호13표 전후 불변, `financial_apply=NOT_RUN`. 고객 원본·DB/금융/Google 쓰기·재처리·마이그레이션 없음. 호스트 증거 `D:/WebLedgerHost/releases/deploy-evidence-a0d257c45fef1767d25d5269bbac0007c22e4f2e.json`, 비공개 `.local-archive/card-file-span-20261108/`. 후속 문서 변경은 재배포하지 않는다.

## 2026-11-08 Google 장부 지출내용 복사 대조·클립보드 오류 — 운영 완료

- PR #744 병합·운영 SHA `aa7d6a648118c907421e32234ca3837cc11c42a9`, 이전 실제 runtime `8341f266531a389a406eb8ce6486759366f03e87`. `Google 장부 일치`는 이미 대조된 `MATCHED_MANUAL`/`MATCHED_EXISTING`, `Google 대조 보류`는 `REVIEW_CONFLICT`로 안전한 단일 Google 행을 확정하지 못한 후보다. 보류 사유별 펼침 정보를 추가했고 `NEW_EXPENSE`만 복사한다.
- 클립보드 문서 포커스 오류에 버튼 포커스 복원과 textarea 선택 fallback을 추가했다. 표적 `19 passed·skip0`, health/ready200, 보호 API401, 보호13표 불변, `financial_apply=NOT_RUN`. Google 최종 장부 쓰기와 고객 원본·금융 데이터 변경은 없었다.
- 배포 evidence는 `D:/WebLedgerHost/releases/deploy-evidence-aa7d6a648118c907421e32234ca3837cc11c42a9.json`, 상세 근거는 `.local-archive/google-expense-copy-fix-20261108/`다. impact-checks는 billing/infrastructure steps0으로 녹색이 아니며 이를 성공으로 보고하지 않는다.

## 2026-11-08 카드사별 거래일자 합집합 공백 — 운영 완료

- PR #742 병합·운영 SHA `8341f266531a389a406eb8ce6486759366f03e87`. 같은 카드사의 모든 카드 거래일자를 합집합해 카드사별 조회기간과 공백을 계산한다.
- 커버리지 표적 49 passed·skip0, blob mismatch0, health/ready200, 보호 API401, 보호13표 불변, 금융 적용 미실행. 배포 evidence는 `D:/WebLedgerHost/releases/deploy-evidence-8341f266531a389a406eb8ce6486759366f03e87.json`이다.

## 2026-11-08 여행 장부 독립 메뉴 제거 — 운영 완료

- PR #740 병합·운영 SHA `43f49f91ecdd189c962e094f4bc671e76a72b86f`. 전역 `여행 장부` 메뉴를 제거하고 `여행 관리`에서 여행을 선택하는 구조로 바꿨다. `/board` 기능은 유지한다.
- 표적 42 passed·skip0, 브라우저 2 passed·9 subtests. 공식 배포 evidence는 `D:/WebLedgerHost/releases/deploy-evidence-43f49f91ecdd189c962e094f4bc671e76a72b86f.json`이며 보호13표 불변·health/ready200·보호 API401·금융 적용 미실행이다.

## 2026-11-08 카드 최종 귀속·P3 작업 기능 폐지 — 운영 완료

- PR #737 병합 SHA와 운영 SHA는 `e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd`다. 카드 P3 작업함·분류 대기 UI/답변 경로를 폐지하고 실제 여행 또는 결제일·매입일 기준 기타비용 귀속을 적용했다.
- 121 passed·skip0, compileall/diff-check PASS. 공식 배포는 이전 실제 runtime `d043892777dc50d1e61d3478440f4148719fd39f`에서 전환했으며 blob mismatch0·health/ready200·보호 API401·보호13표 불변·financial_apply NOT_RUN이다. GitHub impact-checks는 steps0 billing 차단으로 녹색이 아니며 승인 예외 근거를 보존했다.
- 배포 증거는 `D:/WebLedgerHost/releases/deploy-evidence-e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd.json` 및 `.local-archive/card-destination-ux-20261108/`에 있다. 고객 원본/Google/금융 쓰기와 스키마 변경은 실행하지 않았다.

## 2026-11-08 카드 최종 귀속·P3 작업 기능 폐지 — IMPLEMENTING

- 최신 사용자 지시: UX/UI 최우선으로 미배정/확인필요/처리필요/미분류와 관련 P3 기능·UI 잔재를 삭제하고 P1/P2 이후 여행 또는 결제일 분기 기타비용으로 종결한다. [단일 실행 정본](history/specs-20261110/card-destination-only-ux-20261108.md).
- 이전 #735 통합은 11월8일04:24 KST 별도 사용자 원문을 수집하지 못해 과거 작업함 유지 계약으로 제거 변경을 제외했다. 코드 배포·보호 검사는 성공했지만 최신 제품 계약 수락은 미완료였다. 이번 변경은 그 요구 누락을 교정한다. 기존 보호13표·원본·수동교정·환불·권한은 유지한다.
- 현재 브랜치 `fix/card-destination-ux-20261108`, 기준 `d6d22a94415da70f83c88d770067775675b79ca9`. 구현·합성 전후·표적/영향 QA·독립 검수·단일 배포를 수행 중이며 아직 완료를 주장하지 않는다.

## 2026-11-08 미커밋 전체 검토·통합 운영 배포 — 기술 배포 COMPLETE / 최신 제품 계약 누락은 위 후속 참조

- 사용자 `미커밋 변경사항까지 모두 검토해서 배포`와 `모두 확인해서 메인으로 병합 운영배포해` 범위. [PR #735](https://github.com/6Soo/cost/pull/735), 검수 HEAD `1ee5c6983f11e59bb1a2b52f3df90f1eab487165`, 운영 SHA `d043892777dc50d1e61d3478440f4148719fd39f`. [28파일 판정·수락 기록](history/specs-20261110/review-all-uncommitted-release-20261108.md). 원래 로컬8커밋의 이력과 미커밋25·미추적3파일을 모두 검토했다. 유효 변경은 통합하고 원본/권한/환불 보호 제거는 제외·보존했다. 영수증 PR733도 같은 SHA로 운영 반영했다.
- 어드벤처코리아 항공료, 여행 관리 단일 집계, 모바일 수입/보험/금액, 실제 OPEN 사용자 작업, 행별 지출 복사, 정상 구매의 유효한 결제 분기 fallback을 반영했다. 조회 실패를 0건으로 숨기지 않고 정상 P1/P2를 사용자 업무로 만들지 않는다. 메일 캐시의 disabled-gate 의존성과 짧은 보험 문구에서 긴 날짜/이름이 겹치는 결함도 수정했다.
- 최종 Windows 영향 QA **1166 passed +133 subtests, skip0, 필수 브라우저 72/72, compile PASS**. 초기6실패와 모바일 겹침 red는 보존했고 최종 고정SHA에서 교정 후 통과했다. 독립 실제 `gpt-6.1-sol / medium` 정확SHA 승인·interface-review Approve. CI42411351988/job128519990700은 결제/사용 한도로 steps0에서 차단돼 기존 승인 예외를 적용했으며 CI 녹색으로 보고하지 않는다.
- 공식 SHA 고정 git archive·tracked blob mismatch0, 단일 배포 lock·PREVIEW/APPLY 완료. 이전 `d97158484d17f974668dafffafdb1a7b462a7249`에서 전환했고 runtime/task/process SHA 일치, loopback backend, health/ready200·보호 API401·보호 테이블13개 불변을 확인했다. 운영 분류/여행 교정·재처리·원본/금융/Google 쓰기·마이그레이션은 실행하지 않았다.
- 인증 GET 수락: 카드·여행·영수증 영향 화면 main/heading 및 coverage API200 확인. 고객 원본 파일 확인 POST는 실행하지 않았다. 합성 1440/390/320 동일크기 전후 및 짧은 보험 stress에서 페이지 넘침0·텍스트 행 침범0, 키보드 포커스와 light7.5777:1/dark5.7053:1 대비 확인. 전체 고객 화면 시각 수락·실제 기기·스크린리더 음성·RTL/OS확대는 미검증이다. 과거 고객 영수증 파일을 복구했다고 주장하지 않는다.
- root main은 보존 stash `484adc3acd41374568e1ac39e4f18d4d0d2a8b60` 생성 후 정상 fast-forward했다. 기존 stash6개와 원본28파일 snapshot은 모두 보존했다. 비공개 근거 `.local-archive/uncommitted-release-20261108/` 및 `.local-archive/all-main-review-20261108/`. 이 후속 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-08 영수증 업로드 응답 유실 복구 — 통합 운영 반영 COMPLETE

- 사용자 다량 영수증 업로드 경로 조사 후 `수정해` 범위. [수락·검증 기록](history/specs-20261110/receipt-upload-recovery-20261108.md). [PR #733](https://github.com/6Soo/cost/pull/733) 병합 `6ddbc7ef9feb796e444704a87ab7733cde8a8e82`, 검수 HEAD `859e74837fc40a5f2a1bbae9c7ac36060efa569d`와 tree 동일. 사진/PDF 실제 전송 SHA로 저장 결과를 복구하고 본문 유실·Safari 형식 오류·일괄 처리·재시도를 보완했다. 고객의 과거 파일을 실제 복구한 것으로 보고하지 않는다.
- 최종 Windows 영향 **307 passed +32 subtests, skip0, browser37/37, compile PASS**. 실제 Sol medium 최종 SHA APPROVE·독립 Luna medium APPROVE. CI42408750254/job128512087070은 결제/사용 한도로 steps0 차단되어 기존 사용자 승인 예외를 적용했고 녹색으로 보고하지 않는다. 합성 ego390/1440 동일 크기 전후·320/390/1440 넘침0·키보드 직접 입력/미리보기 확인; 고객 업로드·실기기/Safari·스크린리더·200% 실제 확대·다크 테마 미검증.
- **운영 반영 COMPLETE:** PR735 통합 릴리스 `d043892777dc50d1e61d3478440f4148719fd39f`에 포함해 단일 작성자로 배포했다. 통합 QA1166+133·skip0·browser72 및 보호13표 불변·health/ready200·보호API401·인증 `/receipts` GET 화면의 업로드 입력 확인. 고객 과거 파일의 실제 복구/업로드 POST는 실행하지 않았다. 상세는 위 통합 배포 기록이며 영수증만 별도 재배포하지 않는다.

## 2026-11-08 남은 작업공간 4곳 통합·정리

- 사용자 후속 `4곳도 진행해` 범위: root·card-coverage·pr683·pr685의 변경 판정 및 통합/정리. [판정·검증·보존 계약](history/specs-20261110/remaining-workspace-integration-20261108.md). root 수입표는 #723, 카드 대안들은 #713/714/717로 대체됐으며 초기 queue 누락=0 fallback은 최신 오류 계약과 충돌해 제외했다.
- pr683의 유효한 오류 메뉴 문구를 접근성 이름과 통일했다. 첫 영향 검사에서 발견된 PC 사이드바11px 넘침을 해당 문구 전용 줄바꿈으로 수정했다. 제품 SHA `ea80f7d90a3fda526e9f36d16adf725ac27fd29f`: 298개 검사·skip0·필수 브라우저21개 전건실행·compile 통과. 표적14+2subtests 통과. 합성1440/390/320·두테마·키보드 진입/포커스·CSS200%·대비17.06 확인. 실제 운영 UI/물리기기/스크린리더/번역·RTL 미검증.
- 별도 실제 `gpt-6.1-sol / medium` 제품 검수 APPROVE. 문서 후속 최종 SHA별 판정과 병합 상태는 PR 댓글/merge 기록으로 확정한다. CI 인프라 차단 예외는 최신 사용자 승인대로 적용하고 실제 실패를 녹색으로 간주하지 않는다.
- 모든 파일/미추적·무시 파일·Git 이력의 복구 사본 및 SHA256 대조 후 세 임시 worktree를 정리하고 기본 root main 하나를 남기는 범위다. stash6개 보존. 실제 정리 영수증과 최종 SHA는 비공개 `.local-archive/remaining-four-20261108/summary.json`에 기록한다. 아래의 4곳 보존 설명은 이번 통합 전 스냅샷이다.
- 이번 요청의 운영 배포/서버 재시작·DB/원본/금융/Google 쓰기0. 기존 미배포·미검증 수락을 그대로 유지한다.

## 2026-11-08 카드 내역 거래일자 공백 전환

최신 요청과 수락 계약: [거래일자 공백 전환](history/specs-20261110/card-transaction-date-gaps-20261108.md). 조회기간 기반 대시보드를 폐기하고 실제 거래일 사이 공백으로 전환한다. PR #731 병합 및 운영 SHA `d97158484d17f974668dafffafdb1a7b462a7249` 배포 완료. 최종 영향 QA503+100 subtests, skip0/browser35, Sol medium 검수 PASS. health/ready200·보호API401·보호13표 불변. 인증 운영 API·DOM으로23파일/27표시그룹/515공백 및 구 폼0 확인; 전체 고객 화면 시각 수락은 미검증이다. 실제 작업 근거는 운영 기록에 보존하며 문서-only 후속은 재배포하지 않는다. 기존 main의 다른 로컬 커밋8개는 별도 보존한다.
## 2026-11-11 P2 1층 가맹점 일괄 판정 — 제안 생성 완료

- 승인된 서버 밖 단계 1을 `fix/p2-batch-open-quarter-20261111`에서 완료했다. 운영 `board.sqlite`는 `mode=ro` 짧은 조회만 했고 연결을 닫았다. 대상은 열린 여행 48개(0630 포함)와 2026년 3분기 이후 분기 기타비용으로, 일반 항목 1,258건·정규화 가맹점 585곳이다.
- `gpt-6.1-sol` 도구 없는 실행기로 45곳씩 13개 묶음을 처리했다. `.local-archive/p2-batch-20261111/summary.json` 기준 224곳·403건 변경 제안, 220곳 기존 항목 유지, 낮은 확신 358곳, 13회 성공 호출(재시도 오류 기록 2회), 총 모델 시간 1,054.452초·입력 221,213토큰·출력 40,979토큰이다. `proposals.jsonl`은 585행이며 각 가맹점 ID가 정확히 한 번 나온다.
- 출력 결속·커버리지·개인 식별자 비노출 무결성 검사 PASS, 단계 관련 pytest **32 passed, skip0**. 운영 DB·금융 원본·Google·P1 규칙·기존 분류 반영·배포·2층 근거 판정은 실행하지 않았다. 낮은 확신과 기존 유지 결과는 자동 반영하지 않으며 Fable 보고 후 별도 승인이 필요하다.
- 재개 중 일시 오류는 `failures.json`에 보존했다. 완료 근거는 `.local-archive/p2-batch-20261111/`(고객 원문·제안 표본 포함 비공개)이며 Git·PR에는 넣지 않는다. 현재 작업은 Fable 보고 대기다.

## 2026-11-11 P2 단계 2 — 정리·읽기 전용 미리보기에서 보호로 중단

- Fable 지시에 따라 모델 재호출 없이 항목 대응표와 가맹점 표기 묶음 다수결을 코드화했다. `대중교통→교통비`, 시설 이용이 확인되는 `이용료→입장료`, 편의점·시설 이용이 아닌 이용료·운영 장부에 없는 항목은 기존 유지, 동률은 유지다.
- 정리된 결과는 `normalized-proposals.jsonl`·`normalized-summary.json`에 보존했다. 변경 후보 368건 중 기존 교정 경로의 읽기 전용 미리보기 통과 140건, `CORRECTION_PROTECTED` 제외 228건이다. 제외된 228건은 기록된 장부 행과 화면 행이 모두 있어 현재 AI 교정 보호가 걸렸다.
- 보호를 우회하거나 운영 DB를 쓰지 않았다. 변경 전 값은 `before-state.json`에 있고, 가장 최근 검증 전체 백업(14:36) 위치는 기존 작업판 기록을 따른다. 서버 코드 변경이 필요하면 그 사실을 보고하고 반영을 멈춘다.
- 단계 2 코드·테스트·문서 PR을 준비 중이다. 앞서 `gpt-6.1-terra` 세션은 이전 P2 기술 작업의 별도 검증으로 한 번 생성됐으며, 이번 검수용 외 추가 에이전트는 만들지 않는다.
- PR #807을 열었지만 요청된 별도 `gpt-6.1-sol / medium` 검수 에이전트가 두 차례 모델 용량 초과로 시작하지 못했다. 검수·승인 전에는 병합하지 않으며, 서버 코드 변경 필요 여부도 그 검수 뒤 판단한다.




