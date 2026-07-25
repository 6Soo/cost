# 숲길여행 비용처리 자동화

주식회사 숲길여행의 법인카드 비용처리(분류 → 장부 기록 → 시각화)를 자동화한다.

> **이어받는 세션은 [`AGENTS.md`](AGENTS.md)부터 읽을 것** — 최신 핸드오프와 작업별
> 필독 문서의 순서는 이 공통 진입점에서 관리한다.

## 왜 Google Apps Script인가 (핵심 설계 결정)

- 이 자동화 코드가 도는 환경에서는 **구글(`docs.google.com`) 접근이 정책상 차단**돼 있다.
  즉 외부 샌드박스/서버에서 시트로 손을 뻗는 방식은 불가능·비효율.
- 대신 **Apps Script는 사용자(김주형 이사)의 구글 계정 권한으로 구글 서버에서 실행**된다.
  - `SpreadsheetApp.openById()` 로 관련 시트 5개(+앞으로 만들 시트)를 **추가 공유 0회**로 접근.
  - 읽기·장부 기록·셀 색칠 전부 계정 내부에서 처리 → 데이터가 밖으로 나가지 않음.
- 결론: **"시트를 누구에게 공유"하는 문제가 아니라, "계정 안에서 도는 스크립트"** 구조.
  권한 부여 클릭이 0번인 것이 이 방식의 최대 장점.

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
tools/            외부 LLM을 직접 호출하는 선택적 브리지
```

현재 운영 정본과 v2 병렬 경로, 주요 진입 명령, 브랜치 정리 기준은
[`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md)에 정리되어 있다.
