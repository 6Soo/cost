# Plush UI 릴리스 절차

새 UI는 `/ui/`와 같은 출처의 인증 API를 사용한다. `frontend/dist/`는 빌드 산출물이며 Git에 없으므로 일반 소스 패키징만으로는 화면을 배포할 수 없다. 기존 Python/Google/영수증 작성 경로와 운영 데이터는 그대로 사용한다.

1. 다른 운영 배포 담당자와 순서를 맞추고, 현재 운영 SHA를 실제 실행 작업과 배포 근거에서 확인한다. 그 SHA가 `-PreviousSha`다. 최종 후보 SHA의 영향 검사·프런트 테스트·타입 검사·빌드 및 별도 세션의 정확 SHA 독립 검수를 마친다.
2. 후보와 같은 HEAD에서 추적 프런트 변경이 없는지 확인한 뒤 `npm.cmd ci`, `npm.cmd run build`를 `frontend/`에서 실행한다. 빌드 전후 HEAD와 추적 프런트 변경을 다시 대조한다. 기존 글꼴은 서버의 `/assets/fonts/PretendardVariable.woff2`를 사용한다.
3. `D:/WebLedgerHost/releases/<후보 SHA>/`를 새로 배타적으로 생성한다. 기존 릴리스나 다른 세션의 폴더를 덮어쓰지 않는다. 후보 SHA의 `git archive`를 풀고 모든 추적 파일을 해당 SHA의 Git blob과 대조한다. 같은 빌드의 `frontend/dist/`를 이 릴리스의 같은 경로에 복사한다. 실제 고객 자료·개인 설정·개발 node_modules를 추가하지 않는다.
4. 릴리스의 `DEPLOYED_COMMIT`과 `release-audit-<SHA>.json`에 정확 SHA·추적 파일 수·blob 불일치0을 기록한다. 추가로 `frontend_build_sha`와 빌드 파일별 SHA-256을 기록하고 복사 전후 바이트 해시를 대조한다. 최종 검수 근거 파일은 후보 SHA와 일치해야 한다.
5. 기존 `tools/deploy_verified_release.ps1 -CandidateSha <후보> -PreviousSha <현재 운영> -ReviewEvidence <검수 근거> -Apply`로 전환한다. 신선 백업·복원 등 데이터 안전 게이트는 기존 배포 절차를 따른다. 이 UI를 위해 데이터 마이그레이션·금융 반영·Google 자동 쓰기를 수행하지 않는다.
6. 공식 배포 도구의 종료 코드와 실제 런타임 SHA, health/ready, 보호 표 불변 결과를 확인한다. 추가로 비인증 `/ui/`·자산·API 거부, 빌드 자산 존재·해시, 가능한 인증 범위의 화면 렌더링을 확인한다. 로그인 때문에 인증 화면 검사가 불가능하면 그 사실을 적고 익명 거부·로컬 합성 렌더링과 구분한다. 운영 자료를 합성 계정으로 읽거나 인증을 우회하지 않는다.

되돌림은 공식 배포 도구와 이전 릴리스 자산으로 수행한다. 새 UI에서 정상 저장한 교정·영수증·장부 데이터는 되돌리기 위해 삭제하지 않는다. 전환 실패나 자동 되돌림이 발생하면 최종 실제 운영 SHA를 확인하고 실패를 성공으로 보고하지 않는다. 결과는 [운영 기록](../operations.md)과 [현재 상태](../session_handoff.md)에 남긴다.
