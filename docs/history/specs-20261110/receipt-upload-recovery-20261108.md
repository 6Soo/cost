# 영수증 업로드 응답 유실 복구 (2026-11-08)

상태: **구현·검증·PR #733 병합 및 PR #735 통합 운영 반영 COMPLETE**. 운영 SHA `d043892777dc50d1e61d3478440f4148719fd39f`.

사용자 요청: 다량 업로드한 영수증의 행방과 업로드 페이지·처리 경로를 조사한 뒤 `수정해`. 서버 저장 후 응답이 끊기면 브라우저가 실패·재시도만 남기는 경로를 수정했다. 과거 사용자가 올린 파일의 실제 복구나 당시 누락 원인의 확정은 이 수정의 검증 결과가 아니다.

## 변경과 수락

| 항목 | 상태·근거 |
| --- | --- |
| 사진·PDF 저장 결과 복구 | COMPLETE. 실제 전송 바이트의 SHA256과 소유자 보호 `/api/receipts` 저장 목록을 대조한다. PDF 페이지·원본 선택·직접 입력·미리보기를 복원한다. |
| 일괄 업로드·미저장·조회 오류 | COMPLETE. 저장을 확인하지 못하면 재시도를 유지하고 다음 파일을 처리한다. 저장 확인 GET은 15초 제한·캐시 미사용이며 자동 재전송하지 않는다. |
| 응답 본문 유실 | COMPLETE. 기존 업로드 120초 제한을 헤더뿐 아니라 본문 읽기까지 유지한다. 200 응답의 잘린 JSON·중단된 본문도 저장 SHA를 확인한다. |
| 변환 이미지·Safari 오류 형식 | COMPLETE(합성). 브라우저 변환 후 실제 전송 바이트를 사용하며 `TypeError('Load failed')`도 처리한다. 실제 HEIC·iPhone/Safari는 미검증이다. |
| 새로고침·기존 동선 | COMPLETE(합성). 저장 파일명·PDF 페이지 재조회, 직접 입력과 키보드 포커스 유지. 저장 성공은 분석·지출 등록 완료를 뜻하지 않는다. |
| 보호 경계 | COMPLETE(검사). 서버 저장/API/CSRF·소유자 계약 변경 없음. 자동 AI 분석·금융 등록·원본 수정·Google 쓰기 추가 없음. |
| 고객 과거 업로드 파일 | UNVERIFIED. 실제 고객 원본을 복구했다고 보고하지 않는다. |
| 운영 반영 | COMPLETE. PR735 통합 릴리스 `d043892777dc50d1e61d3478440f4148719fd39f`로 단일 배포. 통합 QA1166+133·skip0·browser72/72, runtime SHA·보호13표 불변·health/ready200·보호API401 및 인증 영수증 GET 업로드 입력 확인. 고객 과거 원본의 실제 복구나 업로드 POST는 실행하지 않음. |

## 검증과 병합

- 제품 검수 HEAD `859e74837fc40a5f2a1bbae9c7ac36060efa569d`, [PR #733](https://github.com/6Soo/cost/pull/733) 병합 SHA `6ddbc7ef9feb796e444704a87ab7733cde8a8e82`. 두 트리 `ff989b20c0af38c7eb484c3ebb42a57a53a70629` 동일, diff 0. 변경 파일은 `webapp/receipt_review.py`, `webapp/tests/test_receipt_page_flow.py` 둘뿐이다. root의 카드·금융·미배포 로컬 변경은 포함하지 않았다.
- `python tools/run_quality_checks.py --base origin/main --run`: **307 passed +32 subtests, skip0, browser37/37, compile PASS**. 데이터 보호·영수증·권한·환불·OTA exact/manual·여행 배정·Google TSV 경계를 포함했다. 초기 인계 수정은 catch의 변수 범위 오류로 복구 검사 red였으며 수정 후 재검증했다. 본문 유실 후속 전 306+30 근거와 최종 307+32는 중복이므로 합산하지 않는다.
- 실제 감독자 `gpt-6.1-sol / medium` 최종 HEAD APPROVE, 독립 `gpt-6-luna / medium` UI·정확성 APPROVE. [검수 댓글](https://github.com/6Soo/cost/pull/733#issuecomment-6712367660).
- GitHub run `42408750254` / job `128512087070`은 결제 실패/지출 한도 annotation으로 **steps0, 실행 전 차단**. 2026-11-07 사용자 승인 Sol medium 이상 최종 SHA 검수 예외를 적용했다. CI는 failure이며 녹색으로 보고하지 않는다. 로컬 보호 검사 실패를 우회하지 않았다. 검수 근거 파일 인코딩 오류를 UTF-8로 교정해 최종 댓글·파일에 보존했다.

## UI 근거와 남은 수락

실제 `better-interface`, `better-layout`, `better-ui`, `better-typography`, `better-colors`, `better-accessibility`, `better-writing`, `interface-review` 지침과 `ui-ux-pro-max` 오류 복구 검색을 적용했다. 독립 리뷰는 읽기 전용이며 별도 실행 검증으로 꾸미지 않는다.

ego-browser 합성 390/1440px 동일 크기 전후: 응답 유실 뒤 기존 실패/재시도 → 저장 결과 복구됨, 불필요한 재시도 없음. 320/390/1440px 가로 넘침 없음. 키보드 직접 입력·올바른 원본 미리보기·가맹점 포커스 확인. 기존 polite live region과 native button을 유지했다. 다크 테마 시도는 실제 색을 바꾸지 못했으므로 미검증으로 기록한다. 실제 200% 확대·스크린리더·물리기기·고객 업로드·운영 인증 화면도 미검증이다.

비공개 근거: `C:/AX/cost/.local-archive/receipt-recovery-20261108/`의 `run-summary.json`, `pytest.log`, `junit.xml`, `primary-review.json`, `interface-review.md`, `browser.json`, `ui-evidence.json`, 동일 크기 전후 PNG, CI job/annotation, `checkpoint.json`. 합성 fixture 서버·브라우저 작업은 종료했다. 별도 배포 준비 스크립트는 실행하지 않았다.

통합 배포 결과는 [현재 상태](../../session_handoff.md)와 [운영 기록](../../operations.md), 비공개 `.local-archive/uncommitted-release-20261108/deploy-evidence.json`에 기록했다. 원래 영수증 검증 근거와 upstream blob을 보존했고 별도 영수증 배포는 하지 않았다. 실제 고객의 과거 파일 복구·실제 기기/Safari·스크린리더 수락은 여전히 미검증이다. 이 문서-only 후속 때문에 재배포하지 않는다.
