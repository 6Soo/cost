# 숲길여행 비용처리 자동화

최신 재개 안내는 [2026-09-27 세션 인계](docs/handoff/2026-09-27/README.md)다.
웹 장부는 `python run_candidate.py`로 합성 데이터와 함께 실행한다.
Phase 6 규칙 대화와 A/Ramp/Pretendard 화면을 포함하며 실제 AI와 운영 배포는 미완료다.

주식회사 숲길여행의 법인카드 비용처리(분류 → 장부 기록 → 시각화)를 자동화한다.

> **이어받는 세션은 [`AGENTS.md`](AGENTS.md)부터 읽을 것** — 최신 핸드오프와 작업별
> 필독 문서의 순서는 이 공통 진입점에서 관리한다.

여러 에이전트의 목표와 반복 실행 기준은 [공통 실행 규약](docs/AGENT_EXECUTION_CONTRACT.md)에,
확정된 판단과 사용자 답변 대기는 [결정 등록부](docs/DECISION_REGISTER.md)에 정리되어 있다.
의미 해시와 반복 실행 검증의 최신 결과는 [멱등 실행 추가 인계](docs/handoff/2026-09-08/IDEMPOTENCY_UPDATE.md)에 있다.

전체 실행 경로의 최신 점검과 개선 설계는
[`docs/PIPELINE_REVIEW_2026-09-07.md`](docs/PIPELINE_REVIEW_2026-09-07.md)에 있다.
보존된 v15 워크북과 v5 OTA shadow는 행수·합계 확인만으로 회계 정본으로 사용하면 안 된다.
아래 초기 설계 설명과 현재 코드·운영 상태의 차이도 이 점검 문서에서 확인한다.

최신 구현과 검증 기록은 [2026-09-08 인계](docs/handoff/2026-09-08/README.md)에 있다.
로컬 진단은 다음 명령으로 실행한다. 원본 파일을 바꾸지 않으며 외부 전기를 실행하지 않는다.

```powershell
python -m tools.pipeline_audit --root . --inventory config/pipeline_inventory.json
```

진단에서 `ok`는 실제 검사한 파일·구조 항목의 통과를 뜻한다. 전체 업무 정확성이나 게시 승인을
뜻하지 않으며, 현재 보존 자료의 감사 해시 불일치는 오류로 보고된다.

## 왜 Google Apps Script인가 (핵심 설계 결정)

- **Apps Script는 사용자의 구글 계정 권한으로 구글 서버에서 실행**된다.
  - `SpreadsheetApp.openById()` 로 관련 시트 5개(+앞으로 만들 시트)를 **추가 공유 0회**로 접근.
  - 읽기·장부 기록·셀 색칠 전부 계정 내부에서 처리 → 데이터가 밖으로 나가지 않음.
- 실행 전 해당 계정의 권한과 현재 배포 상태를 확인해야 한다. 로컬 Google Workspace
  커넥터 접근 가능 여부도 실제 읽기 호출로 확인하며, 특정 앱이나 환경 이름만으로 단정하지 않는다.

이 리포는 그 Apps Script 코드와 설계 문서의 **원본(source of truth)** 이다.

## 대상 시트

| 역할 | 스프레드시트 ID | 비고 |
|---|---|---|
| RAW 카드내역 ①| `1nYxV9UM9rMRjEhnhdc8evE2xb3z6RxgWd5f5ci6PPdE` | 카드사 다운로드분 업로드 |
| RAW 카드내역 ②| `11jjbN882fdQDcIexuzX-l0yBw02VgIna1jhnJNMkN_o` | |
| RAW 카드내역 ③| `1SiOftobiUJSxSdvBEKL9AmxgQkjzkzDjs2O_8SBoyh4` | |
| 26년 1분기 **완료** 장부 | `1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8` | 학습(정답) 자료 |
| 26년 **진행** 장부 | `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU` | 기록 대상 |

## 프로세스 (현재 → 재설계)

원래 4단계:
1. (수동) 카드사에서 사용내역 받아 RAW 시트 업로드
2. 내역을 보고 어떤 비용인지 **추론**
3. 판단 완료분을 가공해 **장부 시트에 전기**
4. RAW 시트에 **배경색**으로 상태 표기 (완료 / 매출취소 / 흰색=미분류)

재설계: **2~4단계를 한 번의 "정산 실행"으로 통합**하고 멱등(idempotent)하게.
자세한 내용은 [`docs/design.md`](docs/design.md).

## 로드맵 — 미해결 3과제는 전부 "이메일"로 수렴

법인카드 수집 API, 트립닷컴/아고다/부킹 실사용일, 네이버페이/카카오페이 내역 —
셋 다 오픈 API가 없고, 실질 해법이 전부 **이메일 파싱**이다.
→ 개별 프로젝트로 흩어지지 말고 **이메일 인제스천 계층 하나**로 통합 설계.
자세한 내용은 [`docs/roadmap.md`](docs/roadmap.md).

## 구성

```
apps-script/      운영 Google Apps Script 자동전기·메일 연동 코드
ledger/           Python 비용분류 파이프라인과 버전별 레거시 빌더
ledger/domain/    SQLite 기반 v2 도메인 모델·직접 적재·전환 게이트
ledger/tests/     v2 도메인·원천 어댑터·전환 회귀 테스트
ledger/data/      재현 입력, 레거시 정본, 생성 워크북
ledger/baselines/ v2 회귀 기준선과 전환 게이트 결과
docs/             설계·운영·비용분류 규칙·세션 인계 문서
tools/            파이프라인 빌더·읽기 전용 진단·선택적 LLM 브리지
```

현재 운영 정본과 v2 병렬 경로, 주요 진입 명령, 브랜치 정리 기준은
[`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md)에 정리되어 있다.
