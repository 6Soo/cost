# Runtime catalog R0 (RF-005 / RF-109)

상태: CODE_WRITTEN / 표적 테스트 실행 전 / 운영 의존성 미확인

`tools/runtime_dependency_catalog.py`는 Git 추적된 Python·PowerShell·cmd/bat·XML 소스 중 tools, app, webapp, tests와 알려진 루트 런처 후보만 정적으로 읽습니다. 모듈 import, 프로세스 실행, 스케줄러 조회, 운영 경로 탐색, 환경/시크릿 값 출력은 하지 않습니다. 출력은 JSON 또는 `--format summary`이며 출처는 파일 경로와 줄 번호만 포함합니다.

분류는 `ACTIVE_SAFE_READ`, `ACTIVE_WRITE_GUARDED`, `TEST_FIXTURE`, `HISTORICAL`, `UNKNOWN`을 사용합니다. R0 증거만으로 운영 호출을 확인할 수 없어 엔트리포인트 이름만으로 ACTIVE를 부여하지 않으며, 실질적인 운영 스크립트는 추가 호출 근거 확인 전 `UNKNOWN`입니다. 정적 쓰기/배포 표식은 guarded 범주 후보를 표시할 뿐, 실제 보호 절차의 검증을 의미하지 않습니다. 각 항목은 confidence와 근거 설명, 정적 참조 위치, OPEN_QUESTION을 제공합니다.

실행: `python tools/runtime_dependency_catalog.py --format summary`

남은 질문:
- 운영 Windows scheduler, launcher, deploy 및 rollback에서 실제 호출되는 추적 스크립트와 인자 계약은 무엇인가?
- 쓰기 가능 도구의 권한, 백업, 복구 게이트를 어떤 증거로 확인할 것인가?
- 현재 worktree의 baseline SHA는 `0b9ebf4afe067e2844745f5526606a7f2087ba39`; 운영 SHA는 확인하지 않았으며 이 R0 도구는 런타임 변경이나 배포를 수행하지 않는다.
