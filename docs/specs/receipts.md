# 영수증 기능

**상세 계약·참고 자료.** 아래 절의 작성 시점별 구현/배포 표시는 현재 상태가 아니다. 최신 사용자 정책과 현재 상태를 먼저 확인하고 필요한 절만 읽는다.

[시작 안내](../COST_V3_START_HERE.md) · [현재 상태](../session_handoff.md) · [운영 기록](../operations.md)

## 내용

- [COST 영수증 Muse Spark Contributor Free 연결](#src-docs-receipt-muse-opencode-md)

---

<a id="src-docs-receipt-muse-opencode-md"></a>

## receipt-muse-opencode

통합 전 경로: `docs/receipt-muse-opencode.md`

<a id="src-docs-receipt-muse-opencode-md--cost-영수증-muse-spark-contributor-free-연결"></a>
### COST 영수증 Muse Spark Contributor Free 연결

> **독립 영수증 기능의 당시 실험·대체 모델 설정 기록.** [COST V3 단일 개발 진입점](../COST_V3_START_HERE.md)에서 별도 기능으로 분류했다. `integration/cost-final`은 현재 V3 기준 브랜치가 아니며 모델 이름·무료 과금·CLI 제공 여부를 현재 사실로 단정하지 않는다. 해당 기능 요청 시 실제 코드/모델 가용성/개인정보 전송 동의를 새로 확인하고, V3 매칭 R0~R6를 막지 않는다.


> 구현은 `integration/cost-final`의 비운영 코드이며, 실제 Windows OpenCode 호출·운영 배포 검증 전까지 완료로 간주하지 않는다.

<a id="src-docs-receipt-muse-opencode-md--제품-동작"></a>
#### 제품 동작

1. 사용자가 영수증 작업 화면의 **여행 선택**에서 이번 영수증의 여행을 직접 지정한다. AI는 여행명을 추론하지 않는다.
2. A4 사진(JPEG/PNG)을 저장한 다음 **Muse로 영수증 자동 찾기**를 누른다.
3. COST가 파일을 Windows OpenCode CLI에 첨부하고 고정 모델 `opencode/muse-spark-1.3-contributor-free`로 보낸다.
4. AI는 서로 다른 실물 영수증/승선권마다 정규화된 좌표·상호·날짜·금액·통화·결제수단의 **미확정 후보**만 반환한다.
5. 원본 이미지 위 영역을 눈으로 확인하고 후보를 선택해 수동 수정 및 등록한다. 한 번 분석한 다수 후보를 검토하는 동안에는 자동 재호출하지 않는다.
6. 같은 업체·날짜·금액이어도 **같은 종이에 서로 다른 위치의 승선권은 자동 병합하지 않는다**.
7. 실제 한 결제로 묶을 경우, 같은 여행·날짜·업체·통화·결제수단·확정 분류의 **확정된 비용 후보**를 선택해 묶는다. 개별 원본과 금액은 남고 TSV는 합산 행 하나로 나온다. 묶음 해제도 가능하다.
8. 법인카드 영수증은 이미 기록된 카드 매입 거래와 대사하고 추가 지출로 이중 기록하지 않는다. JPY 현금/개인카드는 기존 ×10, KRW는 원화 그대로다.

<a id="src-docs-receipt-muse-opencode-md--windows-pc에서-수행할-검증-및-활성화"></a>
#### Windows PC에서 수행할 검증 및 활성화

- 현재 사용 중인 OpenCode CLI 버전 및 인증 계정부터 확인한다.
- `opencode models --refresh`와 `opencode models --verbose`로 **정확한 모델 ID 및 무료 가격**을 확인한다.
- OpenCode의 자동 충전·유료 모델 폴백·타 모델 사용 설정이 없음을 확인한다. 0원 조건을 보증할 수 없으면 활성화하지 않는다.
- 메모리/컨텍스트가 분리된 해당 OpenCode의 `run --format json --file <실제 이미지>` 이미지 첨부와 응답 이벤트 형식을, 승인된 테스트 페이지로 실측한다. 대화형 IDE용 기본 빌드 에이전트를 사용하지 않는다.
- 서버 실행 환경에 `WEBLEDGER_RECEIPT_VISION=opencode-muse-free`를 주입해야 영수증 페이지에 새 버튼이 노출된다. 글로벌 사용자 쉘에 설정하는 것만으로 Windows 예약 작업의 서비스 프로세스에 전달된다고 가정하지 않는다.
- 초기에는 운영 서비스로 전송하지 말고 격리된 Windows 실행 환경과 합성 자료에서 검증한다.
- 테스트: `python -m pytest -q tests/card_pipeline/test_opencode_receipt_vision.py webapp/tests/test_receipt_muse_grouping.py` 및 기존 영수증·중복 보호 인접 테스트. 실제 6개 샘플의 누락/영역/합계는 별도 검증한다.
- 운영 변경 시 기존 영수증 저장소, SQLite 장부, 카드 수집기, Cloudflare Tunnel, Google 원본과 현재 Windows 작업트리를 보존한다.

<a id="src-docs-receipt-muse-opencode-md--데이터-전송보안"></a>
#### 데이터 전송·보안

사용자가 회사 영수증의 Muse Contributor Free 외부 전송 및 모델 학습 이용 조건을 명시 승인했다. 별도 API 키 없이 **PC에서 기존 OpenCode 인증을 이용**한다. 추론은 로컬이 아닌 클라우드에서 이뤄진다.

- 전송은 owner의 명시적 AI 분석 버튼을 누를 때만 수행한다.
- 승인된 원본 사진 하나만 전달하며 모델은 별도의 임시 작업 디렉터리 안에서 실행된다.
- 고정된 `receipt-readonly` 에이전트의 `permission: {'*':'deny'}`로 파일 읽기/수정, shell, 웹·MCP 도구 호출을 모두 차단한다. 첨부된 이미지 내용에 있는 지시를 운영 명령으로 취급하지 않는다.
- 모델 출력은 비용 확정·카드 결제·Google 수정 명령이 아니라 **검증할 데이터**다.
- 기존 CSRF/owner 인증 및 저장 사진 소유 확인을 통과한 요청만 모델을 호출한다.
- 서비스가 실패하거나 빈 결과를 반환하면 수동 입력 경로를 유지한다. **유료 모델에 자동 재시도하지 않는다.**
- 무료 모델은 기간 한정이며, 계정/플랜 설정에 따라 비용이 생길 수 있으므로 현재 요금표와 계정 설정을 확인한 뒤에만 켠다.

<a id="src-docs-receipt-muse-opencode-md--현재-한계"></a>
#### 현재 한계

- 현재 AI는 **영수증별 영역 위치와 값 제안**을 반환한다. 상호·날짜·금액이 불명확하면 사람에게 확인을 요청한다.
- PDF 파일 직접 업로드/렌더링과 영수증 영역 자체를 편집하는 드래그 핸들은 이번 변경에 포함되지 않았다. 현재는 각 박스 좌표 입력으로 보정 가능하다.
- 이미지 여러 장은 개별 페이지로 저장·분석한다. 여러 페이지를 한 번에 묶는 배치 작업은 후속이다.
- Windows에서 모델의 실제 이미지 입력 성공·응답 품질·지연·무료 사용량은 아직 실측되지 않았다.
