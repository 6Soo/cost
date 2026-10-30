# 열린 PR와 실제 남은 개발 구현 실행 · 2026-10-30

- 최신 사용자 지시: 열린 PR를 확인하고 미구현 개발사항을 여러 Luna low, ANUS free auto1개, OpenRouter free1개에 위임해 구현한다.
- 현재 main `fc1e2022095387d1def02e2e7f8197456142481f`. [PR384](https://github.com/6Soo/cost/pull/384)의 [GEMN-01~05](google-expense-mn-reconciliation-20261030.md)를 구현하고 [PR385](https://github.com/6Soo/cost/pull/385)의 카드 UI를 검증·보완한다. 과거 완료 기능을 재구현하지 않는다.
- GEMN-01/03: 실제 여행·Google 원천/세대/수입·지출 구분·오류를 검증하는 read-only 서비스. GEMN-02: 여행+signed KRW 금액 그룹 순수 계산. GEMN-04:900px 이상 PC 상태 열·그룹 원행 상세. GEMN-05:합성/보호/실제 읽기 전용 수락. 기존 SDD1:1·복사/TSV·원본/수동/금융 연결은 변경하지 않는다.
- 카드 UI는 CSS 변경만으로 완료로 보지 않고 필터·펼침·페이징·테마·좁은 폭·200% 확대·키보드와 관련 보호를 확인한다. 일반 코드의 검증 후 정상 PR/main·고정 SHA 배포를 진행한다.
- 기존 미결의 코드 부족과 실제 외부 의존을 구분해 남은 개발만 보완한다. 메일 열거 완료·실제 참가 DB/영수증·원결제 증거·실기기 등은 사실을 만들거나 보호를 낮춰 완료시키지 않는다. Travel INS PR2는 오래된 전체 diff를 검토하고, 신규 클라우드·과금·시크릿·실가입 변경 없이 처리 가능한 코드 범위만 판단한다.
- 작성권은 작업자 계약/큐에 분리한다. 사용자 기본 작업 사본·미추적 파일·stash를 보존하고 작업자 운영 자료/비밀/원문 접근과 재귀 위임을 금지한다. Google 최종 장부 자동 쓰기와 카드 수집/업로드 보류를 유지한다.
- 실제 작업자·커밋·검사·차단·다음 행동은 `C:/AX/cost/.local-archive/open-pr-development-20261030/queue.json`에 유지한다. 현재 통합 workspace `wks_a8cde23592aa8fd3`, 완료 후 공식 archive한다.
