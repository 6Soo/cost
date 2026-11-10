# 항공권 예약 요약 아이콘 정렬 수정 (2026-11-07)

상태: **구현·병합·운영 코드 배포 COMPLETE**. 운영 인증 UI 미검증: 인증된 항공권 요약 화면 접근 불가 (격리 세션; 인증 우회/로그인 정보 변경 없음). 합성 검증과 구분한다.

사용자 요청: 첨부 항공권 예약 요약의 목록 아이콘과 펼침 화살표 정렬을 수정한다. 기존 여행 장부 항공권 요약만 대상으로 한다.

## 변경과 보호 범위

- [PR #721](https://github.com/6Soo/cost/pull/721), 테스트 head `42a29c7d9f5430c1a741dfae54db3ceadfda11ec`, 운영 SHA `7c29ff3356f048aecfcdc5c1b6751a160e9acb40`.
- 공통 장식 SVG 목록/chevron을 양끝에 배치한다. 기본 marker 및 문자 chevron을 대체하고 native details/summary·포커스·최소56px을 유지한다. 펼침 상태는 회전된 정적 방향으로 표시하며 애니메이션은 추가하지 않는다.
- 목록 로드·필터·SOURCE_CHANGED 초기화는 레이블만 바꾸므로 두 아이콘이 보존된다. 좁은 폭에서 숫자를 말줄임하지 않고 전체 문구를 줄바꿈한다.
- 최신 main의 항공권 목록/선택 상세 개선을 유지해 포팅했다. 기존 root 작업 브랜치는87커밋 뒤였으며 사용자 미커밋 변경을 보존하기 위해 임시 통합 worktree를 사용했다. 이전 root 패치는 비공개 보관 후 해당 두 파일만 정리했다.
- 금융 금액/ID/분류/여행 배정/API/DB 스키마·원본/Google 최종 장부 쓰기 변경 없음.

## 요구사항과 검증

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| 좌우 아이콘 정렬 | COMPLETE | ego 동일1440/657/390/320px before/after 캡처·시각 확인 |
| 로드·자료 갱신 후 아이콘 보존 | COMPLETE | SOURCE_CHANGED/reopen 및 빈 목록 업데이트 회귀 |
| 모바일 전체 숫자·키보드 | COMPLETE | 320px 장문/Enter/Space/focus/최소높이·가로넘침0 |
| 테마·확대 | COMPLETE (합성 범위) | 밝음/어두움1440/390/320, CSS200% 넘침0; 본문 대비17.85/13.98, 아이콘7.58/5.71 |
| 영향 QA | COMPLETE | `python tools/run_quality_checks.py --base origin/main --run`:124 passed·skip0·필수브라우저6함수 전건실행·compile0 |
| 독립 UI 리뷰 | COMPLETE | 승인 fallback Luna medium, interface-review 및 도메인 검토 Approve; 승인 무료후보 실제목록 부재 |
| CI·코드 배포 | COMPLETE | PR CI42367605079 성공·main CI42367768444 성공·공식 release 증거 |
| 운영 인증 UI | NOT_VERIFIED | 운영 홈 GET에서 요약 영역이 노출되지 않았다. 실제 항공권 요약 화면 직접 수락은 미검증이며 인증 차단 원인을 확정하지 않는다. |

최초 표적 테스트1실패는 PowerShell stdin에서 새 한국어 assertion이 `???`로 변환된 테스트 작성 문제였다. UTF-8 패치로 바로잡고 최종 영향124건 전체 통과했다. 테스트를 제외하거나 skip하지 않았다. 구 기준 branch의4건 통과는 최종124건에 합산하지 않는다.

실제 OS/브라우저 자체 확대·실기기·스크린리더·번역/RTL은 미검증이다. 사용 스킬: better-interface/layout/ui/typography/colors/accessibility/writing, ui-ux-pro-max, ego-browser. 최종 독립 검토는 프로젝트의 interface-review 절차를 적용했다.

## 배포 근거

이전 `fbda50cbe01d5021ab341ed82337badb2e8c59a0` → `7c29ff3356f048aecfcdc5c1b6751a160e9acb40`. 정확한 Git `1429` blobs 불일치0, task/process SHA 일치·단일 listener·backend8751·health/ready200·보호API401·보호13표 불변. 기존 검증 릴리스와 task 복구점을 유지한 코드 전용 배포이며 별도 전체백업/마이그레이션/분류 재처리 없음. `financial_apply=NOT_RUN`.

비공개 근거 `C:/AX/cost/.local-archive/flight-summary-20261107/`: run-summary/JUnit/pytest.log, browser/browser-stress JSON, 동일폭 before/after PNG, independent-review.md, release-audit/review/deploy-evidence/production-browser JSON. 호스트 `D:/WebLedgerHost/releases/deploy-evidence-7c29ff3356f048aecfcdc5c1b6751a160e9acb40.json`. 고객 원문·운영 전체화면을 Git에 넣지 않는다. 문서 후속은 재배포하지 않는다.
