# COST 현재 상태 · 작업 인계

기준일 2026-11-20 KST. 확인한 main은 64743750, 운영은 ecbdb5c9다. 작업 직전에 PR head와 운영 릴리스를 다시 확인한다.

## 2026-11-20 (2) · M6 새 추출 기준 확정

- **소유자 결정(2026-11-20):** "새 기준으로 진행." 기존 기준 `7,965건 / a26d4465…`는 원 입력 사본 소실로 재현 불가이므로 **이력으로만 보존**하고 비교 base로 쓰지 않는다. 현재 결정적 추출기로 새 보호 사본 기준을 생산한다.
- **새 기준:** `7,965건 · 28,544,770바이트 · SHA-256 3c6c46f51fbaa03b6da34708c8891a940fe3f1b957138986860e5dd992b6bde1`. 같은 보호 입력에서 Python 추출 2회와 오프라인 Rust 조립 결과의 바이트가 모두 일치했고, 두 Python 매니페스트도 검증했다.
- **코드:** [PR #1072](https://github.com/6Soo/cost/pull/1072) — 기존 M6 Rust 추출기 구현을 최신 main에 재적용(충돌 3건 해소, `extract-baseline-compare` 보존, `extract-sources` 추가 전용). `--stages` 입력은 파일을 읽기 전에 기본·지정 호스트의 Board·Core·OTA Evidence·OTA Review 경로와 파일 별칭을 거부한다(`DB_IS_LIVE`).
- **검증:** 합성 파이프라인 20건 + Rust 골든 2건 + 표적 Python 85건 통과. CI 3/3(impact-checks·rust-core·windows-p2-descendant-boundary) 통과. 독립 검수는 `4cb34308`에서 차단 1건(`--stages` 라이브 경로 미검사) 지적 → `2290b8a8`에서 해소, **APPROVE**.
- **다음:** 퇴역 계획 [3단계](playbooks/m6-extractor-retirement.md)의 단위별 이식(난이도 낮은 파서부터)과 1단계 결합 해소(`core_writer`의 `periods` 의존). 이번 PR은 오프라인 검증 CLI이며 운영 스위치·Python 삭제는 하지 않았다.

## 2026-11-20 · OTA 배치 운영 반영

- PR #1070 병합과 ecbdb5c9 운영 배포를 완료했다. Board·Worker·호환 Rust 바이너리 적용과 보호 표 14개 불변을 확인했다. [운영 기록](operations.md#2026-11-20-2045-kst--ota-카드-후보-rust-배치-운영-전환)
- Linux 자격증명 시험에는 비공개 파일 모드를 적용했고 Windows 전용 M5 복구 시험은 Windows 러너에서 실행했다. 시험 파일과 검증 조건을 유지했다. 최종 CI 세 검사 통과.
- 다음 범위는 업로드 뒤 Python 재판정 경로, 저장 이용일 보완과 퇴역 절차다. 운영 DB 저장 보완은 별도다. 추출기 기준은 원 입력 사본 또는 소유자의 새 기준 결정이 필요하다.

## 2026-11-20 · OTA 규칙 압축과 Rust 후보 전환

- [#1070](https://github.com/6Soo/cost/pull/1070). 규칙·P2 호환성 5b9cfe7f, Rust 후보 배치 339b410f. 일반 외화의 전후 1일 허용과 결제대행사 표기의 당일 조건, 원문 결제일 공란, M:N과 표시용 공통기간을 보존했다. Rust CLI가 배치를 지원할 때만 후보 검색을 넘긴다. 구형 바이너리와 숲나들e·토요코인·라쿠텐 전용 조회는 Python 경로를 사용한다.
- 3분기 감사와 같은 시점의 Board·Core 사본 및 기간 근거로 카드 거래 7,349건을 감사했다. 저장 보완 대상 2,585건과 판정 변경 대상 60건을 구분했다. 격리 복원 후 decisions-only 보완에서 원장 행과 기존 저장 이용일 91건의 값이 그대로였고, 보완 2,585건·재실행 0건·미저장 0건을 확인했다. 새 이용일은 전체 검증 359건·추론 102건·미상 2,124건이며, 3분기 OTA 장부 후보와 겹치는 건 각각 149·40·47건이다. 판정 변경 대상 60건은 예행 뒤에도 남았다. 운영 화면 집계의 누락 867건·미판정 270건은 방문한 화면 범위의 별도 지표다.
- 같은 운영 사본의 이벤트 7,965건과 카드 원행 7,349건에서 운영 바이너리와 새 배치를 대조했다. 후보 진단 2,239건의 후보·탈락 사유를 포함해 결과 차이 0, 묶음 연결 결과 340건과 수동 연결 3건이 동일했다. 같은 사본에 고정 묶음은 0건이었으며 고정 묶음 경계는 합성 검사로 다뤘다. 같은 입력의 shadow-links는 OTA 7,965건과 환불 짝 486건에서 목록 밖 차이 0으로 통과했다. Python 최종 판정은 카드 업로드 뒤 갱신에도 호출된다. [Python 판정기 퇴역 절차](playbooks/core-cutover.md#ota-후보-배치와-python-연결-판정기-퇴역)를 따른다. 이용일 폴백 퇴역은 운영 저장 판정의 보완과 화면·내보내기 대조 뒤에 한다. 7,965건 고정 추출 기준은 원래 입력 재현 또는 소유자의 새 기준 결정이 필요하다.
- GitHub Rust·Windows P2 검사는 통과했다. [Linux 영향 검사](https://github.com/6Soo/cost/actions/runs/44725006671/job/136250069528)는 기준 브랜치와 같은 M5 테스트 파일에서 토큰 파일 권한 6건과 Windows 전용 taskkill 호출 1건이 실패해 #1070은 초안으로 남겼다. 운영 사본 대조와 격리 예행 집계는 D:/WebLedgerHost/data/backups/ota-rust-candidates-20261120-195941-089의 summary.json, solver-shadow-summary.json, storage-rehearsal/summary.json에 있다.
- 운영 장부는 Board·Worker가 실행 중인 2c442dbb다. 배포 증거의 릴리스 blob 불일치는 0이고 보호 표가 동일하다. 기존 브라우저 대조에서 기본 여행의 카드 지출 ID 89건과 별도 수입 탭의 Google 수입 35건을 확인했다. 참가자·보험, 항공권, 예약 연결 동선에는 차이가 남아 있다. 이번 OTA 운영 배포와 금융 적용은 미수행이다.

## 2026-11-20 · 장부 표시 기준과 Plush 화면

- 기준 `2fb41a74`. 기존 `/board`에서 레거시의 기본 여행과 분기 전환 선택지, 날짜·분류 순서, 거래처·내용 표시와 분기 지출 표시를 Plush 컴포넌트에 연결했다. 날짜 검색과 분기 지출 검색은 공통 서버 조회를 쓰며 검색 전 전체 합계를 유지한다.
- 카드 분류와 저장 스키마에는 변경이 없다. 운영 배포는 미수행이다. 참가자·보험, 항공권, 예약 연결을 장부 안에서 여는 동선은 미반영이다.
- 표적 확인 명령은 `python -B -m pytest -q -p no:cacheprovider webapp/tests/test_ledger_parity_spec_11_2_1.py webapp/tests/test_m4_parity_refund_total_scope.py`와 `npm --prefix frontend run test:run -- src/features/ledger`이다.

- 검증 결과는 장부 조회·환불·열람자 Python 검사 35건과 Plush 장부 검사 43건 통과다. 타입 검사와 빌드도 통과했다.

## 2026-11-20 (3) — 죽은 코드 퇴역과 기존 회귀 2건 수정

- **죽은 코드 퇴역:** 전수 조사로 참조 0을 확인한 13개 헬퍼·상수(−141줄)와 `ensure_ledger_schema` 래퍼. [#1064](https://github.com/6Soo/cost/pull/1064) `b8667cb9`, [#1065](https://github.com/6Soo/cost/pull/1065) `0920dc67`. #1065는 중복도 함께 정리(`COMPANY_CELL` 중복, `_esc` 사본 2개→`pages.esc`, `app`의 `replay()` 5개→`app.db.replay_scoped_request`)하고, #1062 검수 지적 O1(변환 후 저장소 쓰기→뷰 재생)을 검사로 입증했다.
- **기존 회귀 2건 수정** [#1066](https://github.com/6Soo/cost/pull/1066) `c01a5d98`:
  1. `/board` HTML이 수입 행 거래처 칸에 참가자 명부 이름(`customer_name`·`nickname`)을 실었다(`ledger_design._row_party_main`). SPEC §13 보호 경계·지연 로딩 계약 위반 → 경로 레이블로 대체.
  2. `test_ledger_apply` fixture가 `WEBLEDGER_UNIFIED_DB`를 정리하지 않아 다른 검사가 남긴 값이 `_embedded_audit` 분기를 바꿨다 → 스토어 생성 전 정리·복원.
  - 드러난 이유: `origin/main`의 impact 검사가 **PR 증거 재사용(skip)** 이라 실제 실행된 적이 없었다.
- **CI 재사용 실측(첫 사례):** main push `53204c7e`가 PR 증거를 재사용해 **1분 53초**에 종료(단계 로그에서 테스트·준비 전부 skipped, `44633965930`). 실제 실행 1회는 1분 58초 중 테스트 70초·준비 48초.
- **#1062 독립 검수 APPROVE**(차단 0). O2(apply 사이드카 재검증이 `-wal` 크기만)는 비차단 잔여.
- **남은 일:** `test_trip_ledger_presentation::test_browser_expense_table_keeps_long_party_and_service_dates_reachable`는 지출 행 기하 검사로 이번 변경 없이도 로컬 실패(15px 여유) — 브라우저 환경 의존 별건. M6 §11.1-3 고정 추출 기준 재설정은 2026-11-20 (2)에서 소유자 결정으로 해소됐다. 열린 PR은 [#1008](https://github.com/6Soo/cost/pull/1008)(draft)만. 운영 배포는 하지 않았다.

## 이번 연속 작업에서 병합한 것

- **열람자 금액 위조(차단 결함) 수정** [PR #1060](https://github.com/6Soo/cost/pull/1060) `19518d4e`. 독립 검수(SHA `e7ee3859`)의 차단 지적: `/access/rows` viewer 분기가 `int(display_amount_krw, amount_krw, 0)`로 금액을 강제 변환해, 금액 미확인 Google 수입 행(`amount_krw=None`, `amount_missing=True`)을 **0원으로 위조**했다. 같은 payload의 `confirmed`는 미확인이라 한 응답이 자기모순이었고 SPEC §11.2.1 계약 1·4 / GGL-014를 위반했다. 수정: 미확인이면 `None` 유지, `VIEWER_ROW_FIELDS`에 `amount_missing` 추가, 회귀 검사 1건(수정 없이는 `0 is None`으로 실패 확인). viewer 10 + 인접 128 passed, CI 3/3.
- **CI 증거 재사용 도구의 토큰 누출 수정** [PR #1061](https://github.com/6Soo/cost/pull/1061) `53204c7e`. artifact 다운로드의 302 redirect(서명 storage URL)로 `Authorization`이 따라가던 것을 `add_unredirected_header` + API URL 검증으로 막았다. `test_quality_checks` 60 passed(신규 검사는 수정 전 `io` import 누락으로 실패했다가 통과).
- **세 번째 저널 통합** [PR #1062](https://github.com/6Soo/cost/pull/1062) `62263509`. `source_fact_applies`를 `ledger_operation_requests`로 이동(3값 shape `legacy`/`unified`/`unified_source_facts`, `--include-source-facts` 오프라인 병합 CLI, 별도 백업 `.pre-source-facts-merge-backup`). `reserve_link_saves`는 AccessStore 계약(SPEC 16.4)이라 제외. 저널 32 + 스키마 5 = 37 passed(rebase 후 재확인), CI 3/3. 운영 DB·스키마 미접촉.
- **CI 재사용 첫 성공 실측:** main push `53204c7e`가 PR 증거를 재사용해 **1분 53초**에 끝났다(같은 PR 실행은 2~3분). 이전 main 실행 4건은 모두 재실행이었다.
- **남은 차단(소유자 결정):** M6 §11.1-3 고정 추출 기준(`7,965건 / a26d4465…`)은 입력 사본 소실로 재현 불가다. 기준 재설정은 소유자 결정 사항이라 그 전에는 M6 퇴역을 시작할 수 없다. → **해소(2026-11-20 (2)):** 소유자 "새 기준으로 진행" 결정으로 새 기준을 생산했다.
- **열린 PR:** [#1008](https://github.com/6Soo/cost/pull/1008) 정책 초안(draft, 소유자 결정 없이 병합하지 않음). 이번 작업에서 운영 배포는 하지 않았다.

## 진행 상태

| 범위 | 확인된 상태와 다음 근거 |
| --- | --- |
| 운영 | Board·Worker 실행 SHA `9fd2d4c2`. [17:55 KST 배포 증거](operations.md#2026-11-19-1755--9fd2d4c2-운영-배포). 인증 수집의 실사이트 확인은 별도다. |
| M2·P2 | M2는 [SPEC §10](SPEC.md#10-로드맵) 기준 종료. OTA와 이용기간 대상 보완 [#1036](https://github.com/6Soo/cost/pull/1036)·[#1034](https://github.com/6Soo/cost/pull/1034)·[#1042](https://github.com/6Soo/cost/pull/1042)·[#1044](https://github.com/6Soo/cost/pull/1044), 선택형 패킷 [#1012](https://github.com/6Soo/cost/pull/1012)·[#1043](https://github.com/6Soo/cost/pull/1043)은 main 병합. [#1022](https://github.com/6Soo/cost/pull/1022)의 규칙 통합도 병합됐다. 미연결 496건 중 실제 회수 수와 토큰 절감은 미측정. 기본 패킷은 전체 정책이다. |
| M3 Rust | P1 작성과 OTA·환불 연결의 Rust 운영 전환 기록이 있다. 이후 저장 판정 보완 및 고정 추출 기준 재현은 [SPEC §11.1](SPEC.md#111-rust-새-코어-m3-m6)의 종료 조건을 따른다. |
| L2·M4 장부 조회 | [#1026](https://github.com/6Soo/cost/pull/1026) 병합(`cde4077c`). 공통 조회의 운영 수락과 기존 HTML 상세·교정 퇴역은 [§11.2.1](SPEC.md#1121-장부-조회-통합)의 행·금액·권한·복귀 대조 뒤 진행한다. |
| L3·M6 장부 이관 | [#1013](https://github.com/6Soo/cost/pull/1013) 병합(`9a953e27`). 새 장부 테이블 추가의 소유자 승인과 이관 도구가 기록돼 있다. 운영 이관 및 대조 완료 근거는 확인되지 않았다. [#1030](https://github.com/6Soo/cost/pull/1030) revision 보정은 main 병합(`326d6afd`)으로 반영됐다. 원본 보존·백업 복원·행/금액/revision 대조는 [이관 계약](design/m6-ledger-merge-contract.md)과 [#1013](https://github.com/6Soo/cost/pull/1013)을 함께 본다. |
| L3·M6 추출기 | 새 기준 확정(`7,965건·28,544,770바이트·SHA-256 3c6c46f5…`) — 소유자 결정 2026-11-20. Python 2회 + Rust 바이트 일치, 매니페스트 검증. [PR #1072](https://github.com/6Soo/cost/pull/1072) 독립 검수 APPROVE(2290b8a8), CI 3/3. 구 기준 `a26d4465…`는 이력 보존·비교 제외. 남은 일: 단위별 파서 이식과 `core_writer`의 `periods` 결합 해소. [추출기 퇴역 계획](playbooks/m6-extractor-retirement.md) |
| L5·M5 운영 이전 | 합성 큐·보조 노드 예행 근거가 있다. 운영 요청량·저장/복원 비용과 제공자·과금·고객 원문 이전 결정이 남았다. [§11.3](SPEC.md#113-서버와-보조-노드-m5) |
| L4 CI·검수 | [기준 main CI](https://github.com/6Soo/cost/actions/runs/44549038076). 검증 증거 재사용과 실행 시간 계측을 우선한다. Windows·금융·보호 게이트는 [AGENTS](../AGENTS.md) 기준을 적용한다. |

## 문서 정리와 다음 검토

- L1 문서 통합 후보는 [#1041](https://github.com/6Soo/cost/pull/1041). 절차·정책·운영 기록의 역할은 [문서 지도](README.md)에서 확인한다. 이전 인계·작업판의 최신 원문은 아래 고정 링크에 있다.
- 다음 조회 작업은 #1026 병합본에서 장부 수락 조건과 남은 호환 경로를 대조한다. 장부 저장 이관은 신선 백업을 복원한 사본에서 대조한다. OTA 근거 DB는 사본 예행에서 압축할 중복과 절감량을 먼저 확인한다. [OTA 근거 압축 절차](playbooks/ota-evidence-compaction.md)
- 새 인계는 현재 진행·차단·다음 행동과 근거 링크만 갱신한다. 기존 승인 범위는 [SPEC §11.5](SPEC.md#115-m3m4m5-보완-명세)와 해당 PR의 소유자 결정에서 확인한다.

[통합 직전의 전체 인계](https://github.com/6Soo/cost/blob/a9c739e72a0f8ef806700253b48bc455e9d41dbb/docs/session_handoff.md) · [통합 직전 작업판과 승인 근거](https://github.com/6Soo/cost/blob/a9c739e72a0f8ef806700253b48bc455e9d41dbb/docs/agents/BOARD.md)
