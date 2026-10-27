# Runtime catalog R0 (RF-005 / RF-109)

상태: R0 PARTIAL / 정적 후보 도구 / 운영 의존성 미확인. RF-005 실제 릴리스·복구 계약의 완료가 아니다.

`tools/runtime_dependency_catalog.py`는 Git 추적된 Python·PowerShell·cmd/bat·XML 소스 중 tools, app, webapp, tests와 알려진 루트 런처 후보만 정적으로 읽습니다. 모듈 import, 프로세스 실행, 스케줄러 조회, 운영 경로 탐색, 환경/시크릿 값 출력은 하지 않습니다. 출력은 JSON 또는 `--format summary`이며 출처는 파일 경로와 줄 번호만 포함합니다.

이 도구는 `TEST_FIXTURE`, `HISTORICAL`, `UNKNOWN`을 반환합니다. `ACTIVE_SAFE_READ`/`ACTIVE_WRITE_GUARDED` 승격은 실제 호출과 보호 근거가 검증된 이후의 작업입니다. R0에서는 주석·문자열·프로세스/쓰기 호출 표식만으로 ACTIVE를 부여하지 않습니다. 각 항목은 confidence와 근거 설명, 정적 참조 위치, OPEN_QUESTION을 제공합니다. 상대 import는 패키지와 import level을 기준으로 해결하며 parse/read 오류는 원문 없는 diagnostics와 exit2로 반환합니다. 참조 줄은 무표시로 절단하지 않습니다. script 경로 문자열은 추적 후보와 정확히 일치하는 경로만 찾으므로 동적·절대 경로 호출은 미확인입니다.

실행: `python tools/runtime_dependency_catalog.py --format summary`

검증: `python -m pytest tests/test_runtime_dependency_catalog.py -q` 8 passed. CLI summary는 추적 후보616개를 분류했고 exit0이었다. 상대 import·외부 root·주석/process marker의 ACTIVE 오분류 방지·원문 sentinel 비출력·읽기/구문 오류·참조 전체 보존을 합성 입력으로 확인했다. 실제 운영 호출 관계·권한 게이트는 확인하지 않았다.

남은 질문:
- 운영 Windows scheduler, launcher, deploy 및 rollback에서 실제 호출되는 추적 스크립트와 인자 계약은 무엇인가?
- 쓰기 가능 도구의 권한, 백업, 복구 게이트를 어떤 증거로 확인할 것인가?
- 현재 worktree의 baseline SHA는 `0b9ebf4afe067e2844745f5526606a7f2087ba39`; 운영 SHA는 확인하지 않았으며 이 R0 도구는 런타임 변경이나 배포를 수행하지 않는다.
