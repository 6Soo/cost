# 작업판

## 진행 중

| ID | 작업 | 명세 절 | 작업자 | 브랜치 | 상태 | 통과 조건 |
| --- | --- | --- | --- | --- | --- | --- |
| INC-P2 | 읽기 과다·준비 응답 장애의 승인된 롤백 | §13·Fable 장애 복구 지시 | 관리자 `c89bbda2` | `docs/p2-pilot-stop-20261111` | 06:13:42 KST 운영 `965bca05` 롤백 완료. health/ready 정상·데이터 불변. 읽기량 감소 실측, 평상 기준선 미검증 | 5DB SQLite 백업/별도복원 PASS, Board/Worker/listener SHA 일치, 8751/8790 health/ready200·401, 보호13표·원본/수동/관련14표 불변, P2/fulloff. 두10초 읽기5.54MB/s·395B/s, +15분 실측117.42MB/s·5.36MB/s(재상승 1구간). [장애 기록](../operations.md) |
| A | 최신 결정·위임 규칙 반영 문서 | §9·§12.2·§14·부록 A, 규칙집 LINK-018 | 기존 작업자 `cc9881e3` 완료·archive | `docs/decisions-20261111-a` | COMPLETE — #795 병합 `6c160d54` | 통합 문서 링크·diff PASS, 최종 sol medium 검수, 배포 없음 |
| B | 운영 읽기 전용 M1 기준선 | §10 M1 | sol high `05fe4b33` 완료·archive | `ops/m1-baseline-20261111` | COMPLETE — #795 병합 `6c160d54`, 관리자 실제 재현 exit 0 | 최종 코드 영향 92 passed·skip0, 가드9 passed, mode=ro 집계 재현·원문 출력 없음 |
| D1 | Windows P2 조사·도구 없는 어댑터 결정 | §6.2·§6.3·§6.6 | sol high `90a8007b` 조사 완료·archive | `research/p2-isolation-20261111` → #796 | COMPLETE — 문서 병합 `1ad1364d`, stdin 직접 주입 승인 | 최종 `5e78bf06` sol medium 승인·문서 검사 통과. probe 제외, OS 격리 수락 아님. 실제 도구 미실행·예약 Worker 완료는 D5 검증 |
| A-R | 공식 Google 7열 세무 전달 양식 검토 의견 | §9 | 관리자 | `integration/decisions-m1-20261111` | COMPLETE — #795 병합 `6c160d54` | 양식 변경 없이 1쪽 이내, 확인 사실과 제안 구분 |
| C | wave3 #799 병합 완료, 배포는 P2 수정과 함께 | §14 #4 / Fable 최신 위임 | 최신 main 통합 검증 완료·최종 SHA 판정은 PR 댓글 | `ui/wave3-20261110`, 검사 코드 `9d4e9913` + 후속 문서 보충 | 고정 SHA 159파일 2317pass/33fail, 전 실패 동일 main 재현·신규0; compile/guard 정상·skip0·브라우저누락0 | ego 390/1440 밝음/어두움 36+복사4, 제외행 같은페이지 펼침/접힘·복사; 실제 상세200·실자료·실기기 등 미검증. CI 결제차단. 병합/배포 없음 |
| D2~D4 | 사건 직접 주입·실행/보호 검증·전체 탐지 | §6.2~§6.6 | Terra high `23fcdce5`, 관리자 검수 | `feat/p2-tool-free-runtime-20261111` → #797 | 병합 완료/운영 롤백 — `bd4646a1`의 읽기·준비 장애로 06:13:42 KST `965bca05` 복구. P2 재배포 금지 | 기존 합성·표적·독립검수 근거 보존. 운영 규모 off/on 읽기·소요·잠금 실측과 Fable 승인 전 완료로 재가동하지 않음 |
| E1 | OTA 3곳 조회 수집 스크립트 | §7 | sol high `92cc66bd`, 관리자 검수 | `integration/ota-collection-release-20261111` → #798 | COMPLETE — 구현·합성검수 범위, 병합 `a050d65f` | 최종 a11d5ea8 독립 sol medium APPROVE·Node52·영향84pass/skip0. 원본/importer 유지·manifest 식별값0. 실사이트·예약등록·운영수집 미실행 |
| E2 | 국민 기업카드 수집 스크립트 | §7 | EXAONE high `60d8fb44` 완료·archive | `feat/kb-card-collection-script-20261111` → #803, `4b4d5aad` | 구현 완료·PR 열림. 관리자가 Node 6묶음 exit0·pytest 1 passed 재실행, 운영 경로·식별값 grep 0. sol 최종 SHA 검수 전, 병합 안 함 | 복구 판단 후 같은 작업자 재개. 수집·합성 검증까지, 실제 인증·다운로드·운영 DB 접근 금지. 실제 Page seam 합성 회귀·최종 SHA 검수·관리자 수락 필요 |
| E3 | 하나·기업 로그인 방식·조회 경로 조사 | §7 | EXAONE `34c94c0f` 조사 종료·archive | `research/card-login-paths-20261111` → #800 | PARTIAL로 닫음 — 최종 `729b3a89`의 [조사 보고서](artifacts/card-login-paths-20261111.md)를 `0308eed3`에 원문 보존 병합 | 사용자 로그인 세션에서 로그인 수단·실제 조회 조건/기간/양식 확인 필요. 추가 공개 조사 없음. 보고서의 추가 조사 제안은 현재 실행 지시가 아님 |

## 대기

독립 작업은 별도 worktree에서 수행한다. BOARD 작성자는 관리자 한 명이며 작업자는 결과를 보고한다.

| ID | 작업 | 명세 절 | 선행 작업 | 등급(틀리면 비싼가) |
| --- | --- | --- | --- | --- |
| D5 | 합성 검증·배포·첫 약 50건 후 Fable 보고 | §6.8 | D2~D4·합성·배포 COMPLETE | 첫 묶음 미완료 — 05:04~05:59:19 KST 제어55분 제한 종료, 호출/고유/처리0. finally off·fullfalse·원본/수동/관련14표 불변. 성공률/표본 산출불가. [종료 보고서](artifacts/p2-first-batch-20261111.md). 야간 밖 재실행·전체확대 금지 |
| D5-FIX | 근거 조립·실행 예산·쓰기 잠금 장애의 근본 해결 | §6.2~§6.6 | `integration/p2-lock-io-resume-20261111` 코드 `11945b2f`, [draft #804](https://github.com/6Soo/cost/pull/804) 최종 문서 SHA·독립검수는 PR 기록 | 첫 독립검수의 건당누적예산 지적1건 수정·재검증 완료, 재검수/Fable 승인 게이트 유지. 관리자 표적102pass·영향680pass/기존3fail/skip0(정확455a723d 동일3실패). 합성2000건·1.100GB off0.892초/근거0, on106.812초/조립50·합성3호출·50반영, route최대0.2642초·경쟁DB대기최대0.0016초. 운영 직접 원인 확정 불가. [검증 보고서](artifacts/p2-lock-io-budgets-20261111.md) |
| GAP | CODE_GAPS 중 P2 연결 밖 항목 | §10 M2 | D 경로 범위 확정 | 증상별 패치 금지, 후속 배정 |

## 완료

| ID | 작업 | 병합 SHA | 검수 | 날짜 |
| --- | --- | --- | --- | --- |
| | | | | |

## 모델 기록

- 2026-11-11 P-1: sol 작업자 `5d9252a6`의 메일 묶음 스트리밍은 실제 해시 성능과 숫자 청크 경계로 두 번 반려되어, 숫자 경계 수정은 terra medium `bdf4e97e`로 이관했다. sol 전체를 제외한 결정은 아니다. 독립 sol 검수 `7c4d5d88`는 `fde1615b`를 숫자 경계 결함으로 반려했다. 미수정 상태의 승인·병합·배포는 하지 않는다.

모델을 뺐을 때만 적는다(관리자 지침 §4).

| 날짜 | 모델 | 이유 |
| --- | --- | --- |
| | | |

공급자 확인(2026-11-11): 구성 프로필 0개. 사용자 결정으로 Luna 신규 배정·오류 후 재실행을 중단한다(Codex 사용량 공유). 기존 A는 완료됐다. EXAONE은 `opencode/exaone/k-exaone_v2.5`(high 지원, input/output 0), ANUS는 `anus/anus/free`(high 지원) 목록 확인. 구현은 EXAONE 여러 개와 ANUS 1개, 운영 폴더·금융 보호·최종 검수는 sol/terra만 맡는다. EXAONE 2개를 E1/E2에 실행했고 ANUS 1개를 E3에 배정했다. EXAONE 품질은 구현/검사 완료 전이라 미확정이다. ANUS는 재개 지시 뒤에도 도구 실행·산출물 없이 종료해 E3를 EXAONE으로 이관한다(실행 환경과 모델 중 어느 원인인지는 미확정, 모델 전체 제외 결정은 아님). 무료 작업자는 고객 자료·운영 폴더 없이 코드·합성 작업만 수행한다. 한도/호출 실패는 품질 반려로 세지 않는다.

## 최고 관리자에게 올린 일

| 날짜 | 내용 | 상태 |
| --- | --- | --- |
| 2026-11-11 | D1 격리 조사 후 대안 결정 요청 | 해결 — Fable이 도구 없는 어댑터와 SPEC §6.2·§6.3·§6.6 개정 승인. 보고서만 통합, probe 제외, D2~D5 진행 |
| 2026-11-11 | D5-FIX #804: 첫독립검수 건당누적예산 지적 수정11945b2f. 표적102pass/영향680pass·기존3fail, 합성2000건·1.100GB off근거0/on106.812초·50반영·route최대0.2642초. 운영 호출0의 역사적 직접원인은 자료부족으로 미확정 | 최종 재검수 결과와 함께 Fable에게 보고할 사항. 운영965유지·승인 전 배포금지. E2/C 미착수 |

이전 기록: [BOARD-through-20261112](../history/BOARD-through-20261112.md)
