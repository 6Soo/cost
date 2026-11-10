# 여행 장부 이용일 경고 조사 (2026-11-09)

상태: **조사 COMPLETE / 표시 보완 코드 검증 PARTIAL / 병합·운영 배포 NOT_RUN**.

사용자 요청의 대상은 여행 장부의 `이용일 확인 필요`와 `이용일 미확인`이다. 이전 카드 내역의 `날짜 확인 필요 757건→0건` 보고는 이 요구의 완료 근거가 아니다.

## 실제 대상과 조사 근거

인증된 ego-browser TaskSpace 9에서 `/trips`의 여행별 장부 링크 68개를 수집하고, 동일 세션의 GET으로 68개 모두 읽었다. 실제 렌더링된 지출 2,860행 중 숙박비 경고 353행, 항공료 경고 49행을 확인했다. DB 공란 618행을 화면 경고 수로 대체하지 않았다. 고객 원문·예약번호·화면·행별 조사 자료는 Git에 넣지 않았다.

| 숙박비 경고의 조사 분류 | 행 수 |
| --- | ---: |
| 예약 자료의 기간을 표시 코드로 보완 가능한 후보 | 73 |
| 금액·외화 대조 또는 예약만 존재하는 후보이며 결제 연결 미성립 | 237 |
| 연결된 예약 원본에 이용기간 없음 | 19 |
| 취소·환불 성격의 카드 원행 | 16 |
| 코어 연결·후보 없음 | 4 |
| 연결된 기간의 보호 조건·충돌 | 3 |
| 취소·보류 예약 | 1 |
| 합계 | 353 |

73행은 **보관된 worker 입력에 대한 읽기 전용 코드 비교 결과**이며 운영에서 해결된 건수가 아니다. 새 경로는 71행을 추가 보완하며, 2행은 기존 경로도 보완 가능한 상태지만 화면에서 경고가 남아 있었다. 당시 보관 worker는 4,139 events, 운영 persisted snapshot은 4,200 results로 세대가 완전히 같지 않아, 최신 운영 상태에서 동일 수의 감소를 확정할 수 없다. 갱신 중 근거를 최신 사실로 쓰도록 보호를 완화하지 않았다.

항공료 49행은 모두 저장된 예약번호가 비어 있다. 이 중 정상 구매 4행은 설명 속 번호에 대응하는 항공 일정 자료가 있지만 저장된 예약 관계가 아니고, 정상 구매 39행은 해당 경로에서도 사용 가능한 일정이 없다. 나머지 6행은 취소·환불 카드다. 설명 문자열만으로 예약 관계를 만들거나 결제일을 이용일로 바꾸지 않았다.

## 변경과 보존

`webapp/ledger_stay_evidence.py`에 표시 전용 경로를 추가했다. 기존 코어의 `MATCHED_GROUP` M:N 연결에서 모든 관련 예약 관측의 기간이 완전하고 같을 때, 그리고 코어가 개별 연결을 확인했으나 예약 항목 메타데이터만 비어 있을 때 이용기간을 보완한다. 기존 화면의 `추론` 표시를 재사용한다.

금융용 `card_matches`·`ledger_metadata`, 금액·원행·예약 관계·여행 귀속·Google 쓰기와 운영 DB는 변경하지 않았다. 단순 순서 배분, 취소·환불·충돌·stale/변경 원본·불완전/서로 다른 기간·수동 빈 값 교정·다른 저장 예약번호는 보호한다. M:N 표시 보완으로 개별 결제 검증을 주장하지 않는다.

코드 커밋: `221849f10f80b24e482a58cf2cfa8902ad56c2c2` (기준 `d960646ba6302b49b376b406dff18b189bafc996`).

## 실제 검사와 남은 조건

- 표적 `test_ledger_stay_evidence.py` + `test_ledger_display_updates.py`: **71 passed**.
- 독립 검토자 `2d40ad4f-2eab-4c5e-bf0c-ccff68282294`: 정확 코드 SHA APPROVE, 별도 64 passed 및 합성 보호 검사. Paseo runtimeInfo에서 실제 `gpt-6.1-sol / medium` 확인. 검토자 자신의 보고에서는 모델 정보를 독립 확인할 수 없다고 적었으며, 이를 감독자가 runtimeInfo로 별도 검증했다.
- 영향 검사 `python tools/run_quality_checks.py --base origin/main --run`: **245 passed, 1 failed, skip 0, compile PASS**. 전체 통과 아님.
- 실패는 `webapp/tests/test_toyoko_reconciliation.py::test_mail_core_card_ota_views_share_reservation_candidates_and_preserve_decision` 85행의 기존 `card_catalog.render_html` 예약번호 기대다. 이 호환 화면은 `/cards/all` 링크만 반환한다. 변경 모듈을 기준 커밋의 원문으로 메모리에 교체한 별도 프로세스에서도 같은 실패를 재현했다. 영향 없는 실패를 범위 밖 수정하거나 검사를 제외하지 않았다.
- 합성 원본·수정 HTML을 실제 ego-browser로 1440/390/320px에서 각각 렌더링·스크린샷 확인. `이용일 확인 필요`→`07.05–07.07 · 2박 · 추론`, 가로 넘침 없음. 화면 색상·레이아웃·제어 변경 없음. 실운영 수정 후 화면, 다크 테마, 스크린리더 음성·실제 확대는 미검증이다.
- `better-interface/layout/ui/typography/colors/accessibility/writing`을 읽고 변경 범위의 증거·문구·기존 표기 재사용 원칙을 적용했다. `interface-review`는 설치된 스킬 목록에 없어 실행했다고 주장하지 않는다. 독립 검토는 코드 범위이며 전체 UI 승인으로 확대하지 않는다.

**배포 조건:** 실제 영향 검사 실패를 CI 인프라 예외로 통과 처리하지 않는다. 현재 코드 병합·운영 배포·서버 재시작·금융 적용은 실행하지 않았다. 현재 운영 SHA는 조사 당시 `d96f08809b8201238e8399d053140ab20e3a91fc`다.

다음 단계는 위 기존 검사 실패의 별도 처리 범위를 확정하고 실제 실패를 해결한 뒤, 현재 main 기준 영향 검사·정확 SHA 검수→정상 병합→공식 단일 작성자 배포→같은 68개 장부의 경고 재집계다. 운영에 없는 날짜를 채우거나 고객에게 모든 경고를 직접 입력하라고 넘기는 것으로 대체하지 않는다.

비공개 증거: `C:/AX/cost/.local-archive/service-date-investigation-20261109/`의 `summary.json`, `warning-inventory-private.json`(402행 상태), `rendered-private.json`, `independent-review.md`, `visual-checks.json`, `baseline-test.py`. 실제 재개 명령은 같은 디렉터리의 `CHECKPOINT.md`에 남긴다.
