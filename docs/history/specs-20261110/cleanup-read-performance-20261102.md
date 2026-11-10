# 지출 정리·환불 읽기 성능 개선 (2026-11-02)

사용자 요청: 코드를 검토해 발견한 병목을 최적화하고, 가능하면 Rust를 적용한다. 이번 범위는 실제 측정에서 확인한 지출 정리 조회와 동일 금액 환불 후보 탐색이다. 금융 분류·원본·링크 정책·기장·Google·스키마는 변경하지 않는다.

- 완료 조건: 동일 입력 전체 출력 동등, 원본/수동/중복/환불 보호 검사, 전후 중앙값, 정상 PR/main 병합, 이전 검증 SHA 보존 배포와 최소 운영 수락.
- 기준 `61188520`, 구현 `c82d86b7`·검사 보완 `2e3a6935`, 병합 후보 `114af50de6f1a28f19186d9b3cc35c89a92c1be4`, PR #498.
- 읽기 전용 운영 측정 3.181초 중 SQLite execute 1.979초, 동일금액 추론 함수 0.407초. SQL 상관 OR 재조회는 SQLite의 문장별 IN 집합으로 바꾸고 SQL NULL을 기존 EXISTS와 동일하게 취급한다. 구매 후보는 발급사·끝4·정확 금액으로 묶고 원본 오류/사용중/요청 밖 후보는 유일성 검사에서 제외하지 않는다.
- 운영 DB 동일 입력·워밍 후5회 중앙값: 지출 목록·건수·필터 읽기 묶음2.235→0.514초(4.35배), 환불 분석0.625→0.248초(2.52배). 원결제 링크486건 전체/지출 결과 동일·읽기 쓰기0. HTTP 지연·첫 화면·전체 서비스 개선율로 표현하지 않는다.
- 합성5,000구매/500취소·5회 중앙값: 완료 조건조회6.589→0.170초(38.80배), 환불0.656→0.040초(16.47배), 전체출력 동일·쓰기0. 실제 데이터 결과와 별도다. `python tools/benchmark_cleanup_refunds.py --baseline 61188520 --purchases 5000 --repeats 5`로 재현한다.
- Rust는 이번에 도입하지 않았다. 저장소의 Rust 프로젝트/호스트 도구체인이 없고, 주 병목이 이미 네이티브 SQLite의 반복 조회와 후보 전체 순회였다. 언어 경계·Windows 빌드/배포를 추가하기 전에 SQL/자료구조 변경만으로 위 이득을 확인했다.
- 검사: 환불/분류·원본·권한144 passed, NULL/SQL동등성/지출정리/유지보수40 passed, 원승인/해외환불47 passed. 비어 있지 않은 NULL 경계 fixture 보완4 passed는40에 포함된 검사의 후속 재실행이며 합산하지 않는다. 전체 회귀는 국소 읽기 변경으로 미실행이다.
- 근거는 Git 제외 `.local-archive/read-performance-20261102/`의 profile.txt·real-differential.json·synthetic-benchmark.json·initial-tests.xml·sql-tests.xml·foreign-protection.xml·null-equivalence-final.xml·release-audit.json·review.json이다. 고객 원문·ID·개별 링크는 보고서/Git에 넣지 않는다.

## 운영 수락

2026-11-02 COMPLETE. PR #498 main 병합 및 고정운영 `114af50de6f1a28f19186d9b3cc35c89a92c1be4`, 이전 검증 `e95a82392be716f488e1175d8ed621c2ac6cd8ec`. 배포1,262blobs불일치0·단일loopback·task/processSHA·health/ready200·보호API401/403·금융13표내용/스키마불변PASS. 코드 전용으로 검증된 이전 릴리스와 task 복구점을 보존하고 전체 DB백업/복원은 반복하지 않았다. 금융/분류/여행/장부/Google/원본/스키마 쓰기0.

인증 ego-browser의 실제 지출 정리에서 처리필요1건, 분류완료 GAMSGO 제외, 원결제 미연결 아고다 취소 유지 확인. TaskSpace13 종료. 앞선 UI 작성자의 명시handoff 후 직렬 배포하고 종료 후 후속 작성자에게 호스트/gate 권한 해제 통지했다.

요청 미결/차단0. 다음 기능 명령 없음. 문서 후속으로 추가 배포/재시작하지 않는다.
