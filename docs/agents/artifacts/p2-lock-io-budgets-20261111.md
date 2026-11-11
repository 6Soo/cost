# P2 잠금·I/O 장애 수정과 운영 밖 검증

기준 SHA `455a723df84f3a6b07d1a087641f16dd86d61f1a`(P2 소스는 `83d87f88`과 동일), 비교 장애 릴리스 `bd4646a1`. 작업자 코드 `3a7363fcd12966fcdc473328e4fce024ae7a2f36` 이후 독립검수 지적을 고친 관리자 최종 코드 **`11945b2f51e9e33374c98ec692d44a1345000b6d`**를 검증했다. 운영 자료·실제 모델·배포는 사용하지 않았다. 아래 결과는 합성 provider 검증이다.

## 확인한 원인과 한계

- 구 버전은 sweep 전체가 active_writer로 감싸져 조립·모델 호출까지 route 잠금을 유지했다. 조립·신선도 재조립은 runtime/board 잠금도 유지했다. 당시 운영의 live stack·잠금별 보유 시간은 수집하지 않았다.
- bd는 조립 내부 enable/window 검사 없이 전체 소스를 읽었다. 83은 로더 전후 검사를 추가했지만 로더 내부를 중단하지 못했다. 호출 예약은 초기 조립 뒤이므로 예약0은 조립 미완료·선정 없음·게이트·사전 오류 등 여러 경로와 양립한다. **운영 호출0의 직접 원인은 유일하게 확정할 수 없다.**
- 합성 초기 whole-word posting 색인에서 메모리 증가와 120초 시간 초과를 포착했다. 최종 코드는 숫자 및 필요한 문자열의 bitmap 색인으로 대체했다. 이는 합성 병목의 직접 근거이며 과거 운영 원인 확정으로 해석하지 않는다.

## 수정

- P1 준비·예약·반영만 짧은 writer 구간에 두고, P2 조립·추가 조회·모델 호출·신선도 재조립은 route/runtime/board 쓰기 잠금 밖의 읽기 연결에서 수행한다. off/창 밖에서는 P2 조립·근거 조회0이며 P1 선저장은 유지한다.
- 조립 전에 회차 최대50건과 첫 묶음 고유50건 잔여량을 적용한다. 다른 live claim도 잔여량에서 센다. 추가 조회 최대2회는 유지한다.
- 변경 메타데이터와 숫자·요청 문자열 색인을 재사용한다. 같은 회차의 거래별 누적 읽기2GiB·누적 근거 작업시간120초, 회차 읽기3GiB·전체180초 상한이다. 추가 조회·신선도 재조립·실패도 거래별 예산에서 차감하고 새 회차에서만 초기화한다. 파일1MiB 블록, JSON파일64MiB, 레코드 UTF-8 8MiB 상한과 SQLite VM/행·압축 해제 검사를 적용한다. 초과 시 부분 근거를 성공으로 반영하지 않는다.
- 읽기·색인 구축·조회·소유 모델 프로세스에서 off/stop/창 종료를 확인한다. 반영 직전 거래·정책·등록 소스와 Windows ChangeTime 등을 대조한다. 같은 크기·mtime 복원 편집 거부 회귀를 포함한다. 원문·수동교정·정확연결·환불 보호를 유지한다.
- P2 uncached 메일 revision을 P1 전역 body cache에 등록하지 않아 색인 교체 뒤에도 이전 원문을 붙잡는 경로를 막았다. P1 기본 독자 동작은 유지한다.

## 관리자 직접 검사

- 표적7파일: **102 passed**, 16.64초.
- `python tools/run_quality_checks.py --base origin/main --run`: 30파일, **680 passed·3 failed·4 subtests passed·skip0**, 149.15초. compile 통과, 전체 검사는 실패다.
- 실패3건은 `webapp/tests/test_expense_cleanup.py`의 `test_the_primary_menu_has_one_expense_cleanup_entry_and_no_rail_unassigned_section`, `test_cleanup_cards_hide_per_row_ai_inputs_and_protect_held_rows`, `test_cleanup_shows_reason_counts_without_hiding_unposted_expenses`다. 정확 기준455a723d에서 같은3건을 직접 실행해 **3 failed**를 재현했다. 기존 실패를 고치거나 테스트를 약화하지 않았다.
- 작업자가 새로 쓴 P1 cache 미등록 회귀의 본문 기대는 기존 body_text의 선행 개행에 정렬했다. 기존 보호 테스트 기대를 바꾼 것이 아니다. 이전 WIP의 잠금 실패·시간 초과·중단 측정은 과거 근거이며 최종 통과 근거로 쓰지 않는다.
- 기존 `test_p2_assembly_budget.py`는 매 snapshot 재읽기 기대를 색인 재사용 계약에 맞춰 바꾸고, 실제 파일 변경 시 재읽기·신선도 거부 검사를 강화했다. 독립 검수도 이 변경을 계약 정렬로 확인했다. 첫 최종검수 b85b56c8은 거래별 예산 재설정 지적1건으로 CHANGES_REQUESTED였다. 관리자11945b2f는 누적 예산과 읽기/시간 초과 회귀2건을 추가했으며 재검수 대상이다.

## 규모 실측

같은 합성 후보2,000건·메일9,174건·저장소 **1,100,346,849 bytes**를 재사용한다. 각 명령은 새 합성 장부 사본과 cold 프로세스에서3회 sweep하며, 완료 색인만 다음 sweep에서 재사용한다. `python tools/p2_scale_measure.py measure --root <보존 fixture> --mode off|on --label <새 이름> --sweeps 3`으로 재현한다. 기존 label은 덮어쓰지 않는다.

작업자 최종3a7363fc: off 1.200초·프로세스읽기3,507,757 bytes·근거/조립/호출0. on 132.412초·프로세스읽기1,122,007,986 bytes·조립50·호출3·반영50, route최대보유0.3725초·경쟁DB쓰기최대대기0.0019초다.

관리자 최종11945b2f 직접 실측은 다음과 같다. 두 실행 모두 exit0이다.

| 항목 | off | on |
| --- | ---: | ---: |
| 3회 총 소요(초) | 0.892 | 106.812 |
| 프로세스 논리 읽기(bytes) | 3,506,878 | 1,122,002,698 |
| 근거 읽기: 1/2/3회(bytes) | 0 / 0 / 0 | 1,100,582,022 / 0 / 0 |
| 고유 조립 / 선정(select) | 0 / 0 | 50 / 50 |
| 합성 호출 / 반영 대상 | 0 / 0 | 3 / 50 |
| route 최대 보유(초) | 0.2629 | 0.2642 |
| runtime / board 최대 보유(초) | 0.2624 / 0.2623 | 0.2638 / 0.2637 |
| 경쟁 프로세스 route 최대 대기(초) | 0.6066 | 0.3027 |
| 경쟁 프로세스 DB 쓰기 최대 대기(초) | 0.0023 | 0.0016 |

on 각 sweep은71.969/22.579/12.083초이며, 계측된 조립6지점과 호출3지점의 route/runtime/board 소유·DB쓰기트랜잭션은 모두false다. off의 P1 준비 읽기까지0이라는 뜻은 아니다. 별도 프로세스의 BEGIN IMMEDIATE/ROLLBACK 대기로 DB쓰기 가용성을 확인했으며 모든 SQLite 내부 잠금의 정확 보유시간 계측으로 해석하지 않는다.

수치는 물리 디스크 읽기와 구분한 Windows 프로세스 논리 읽기량이며 동시 프로세스 내 읽기도 보수적으로 예산에 포함한다. 운영 P1 평상 기준선으로 해석하지 않는다. 합성 도구의 여행 유효성 seam·합성 provider는 실제 구독 모델·예약 Worker·실사이트 가동 검증과 구분한다.

## 증거와 남은 승인

비공개 근거: 작업자 worktree의 `.local-archive/p2-scale-20261111/runs/manager-off-cumulative`, `manager-on-cumulative`와 관리자 `.local-archive/manager-p2-resume-20261111/`의 `target-11945b2f.json`, `impact-11945b2f/`, `baseline-455a723d.xml`. 이전 측정 final-off/on-v6·manager-off/on-final도 보존했다. 기존 QA파일3개는 별도 사본과 해시 대조 뒤 원래 위치에 복원했다.

별도 gpt-6.1-sol / medium이67755cfee4ba968e88da94256bf94183d4450e23를 APPROVE했다. 누적예산 지적 해소·신규회귀2건 직접2pass/1.18초·수치JSON 일치·기존 보호를 확인했다. 이후 승인상태 문서3개 추가분도 최종SHA로 재확인해 #804댓글에 남긴다. Fable에게 보고하고 중단하며 운영965bca05 유지, 승인 전 P2/main/wave3 배포·고객 실행 금지다. 운영 호출0의 역사적 직접 원인 확정은 위 한계를 유지한다.
