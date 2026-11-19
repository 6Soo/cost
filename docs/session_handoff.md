# COST 현재 상태 · 작업 인계

기준일 2026-11-19 KST. 확인한 main은 `a9c739e7`, 운영은 `9fd2d4c2`다. 작업 직전에 PR head와 운영 릴리스를 다시 확인한다.

## 진행 상태

| 범위 | 확인된 상태와 다음 근거 |
| --- | --- |
| 운영 | Board·Worker 실행 SHA `9fd2d4c2`. [17:55 KST 배포 증거](operations.md#2026-11-19-1755--9fd2d4c2-운영-배포). 인증 수집의 실사이트 확인은 별도다. |
| M2·P2 | M2는 [SPEC §10](SPEC.md#10-로드맵) 기준 종료. OTA와 이용기간 대상 보완 [#1036](https://github.com/6Soo/cost/pull/1036)·[#1034](https://github.com/6Soo/cost/pull/1034)·[#1042](https://github.com/6Soo/cost/pull/1042)·[#1044](https://github.com/6Soo/cost/pull/1044), 선택형 패킷 [#1012](https://github.com/6Soo/cost/pull/1012)·[#1043](https://github.com/6Soo/cost/pull/1043)은 main 병합. [#1022](https://github.com/6Soo/cost/pull/1022)의 규칙 통합도 병합됐다. 미연결 496건 중 실제 회수 수와 토큰 절감은 미측정. 기본 패킷은 전체 정책이다. |
| M3 Rust | P1 작성과 OTA·환불 연결의 Rust 운영 전환 기록이 있다. 이후 저장 판정 보완 및 고정 추출 기준 재현은 [SPEC §11.1](SPEC.md#111-rust-새-코어-m3-m6)의 종료 조건을 따른다. |
| L2·M4 장부 조회 | [#1026](https://github.com/6Soo/cost/pull/1026) 병합(`cde4077c`). 공통 조회의 운영 수락과 기존 HTML 상세·교정 퇴역은 [§11.2.1](SPEC.md#1121-장부-조회-통합)의 행·금액·권한·복귀 대조 뒤 진행한다. |
| L3·M6 장부 이관 | [#1013](https://github.com/6Soo/cost/pull/1013) 병합(`9a953e27`). 새 장부 테이블 추가의 소유자 승인과 이관 도구가 기록돼 있다. 운영 이관 및 대조 완료 근거는 확인되지 않았다. [#1030](https://github.com/6Soo/cost/pull/1030) revision 보정은 열린 초안이다. 원본 보존·백업 복원·행/금액/revision 대조는 [이관 계약](design/m6-ledger-merge-contract.md)과 [#1013](https://github.com/6Soo/cost/pull/1013)을 함께 본다. |
| L3·M6 추출기 | 기존 7,965건의 고정 기준은 입력 사본이 없어 현재 재현할 수 없다. 기준 재설정 결정, 호출자·브리지·롤백 대조가 퇴역에 선행한다. [추출기 퇴역 계획](playbooks/m6-extractor-retirement.md) |
| L5·M5 운영 이전 | 합성 큐·보조 노드 예행 근거가 있다. 운영 요청량·저장/복원 비용과 제공자·과금·고객 원문 이전 결정이 남았다. [§11.3](SPEC.md#113-서버와-보조-노드-m5) |
| L4 CI·검수 | [기준 main CI](https://github.com/6Soo/cost/actions/runs/44544980268). 검증 증거 재사용과 실행 시간 계측을 우선한다. Windows·금융·보호 게이트는 [AGENTS](../AGENTS.md) 기준을 적용한다. |

## 문서 정리와 다음 검토

- L1 문서 통합 후보는 [#1041](https://github.com/6Soo/cost/pull/1041). 절차·정책·운영 기록의 역할은 [문서 지도](README.md)에서 확인한다. 이전 인계·작업판의 최신 원문은 아래 고정 링크에 있다.
- 다음 조회 작업은 #1026 병합본에서 장부 수락 조건과 남은 호환 경로를 대조한다. 장부 저장 이관은 신선 백업을 복원한 사본에서 대조한다. OTA 근거 DB는 사본 예행에서 압축할 중복과 절감량을 먼저 확인한다. [OTA 근거 압축 절차](playbooks/ota-evidence-compaction.md)
- 새 인계는 현재 진행·차단·다음 행동과 근거 링크만 갱신한다. 기존 승인 범위는 [SPEC §11.5](SPEC.md#115-m3m4m5-보완-명세)와 해당 PR의 소유자 결정에서 확인한다.

[통합 직전의 전체 인계](https://github.com/6Soo/cost/blob/a9c739e72a0f8ef806700253b48bc455e9d41dbb/docs/session_handoff.md) · [통합 직전 작업판과 승인 근거](https://github.com/6Soo/cost/blob/a9c739e72a0f8ef806700253b48bc455e9d41dbb/docs/agents/BOARD.md)
