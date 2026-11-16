# COST — 숲길여행 비용 관리

카드 원본을 대사하고 OTA 근거와 여행을 연결해 지출 검토·교정·XLSX 출력을 돕는다. 최종 회계 정본은 Google 시트이며 COST가 자동으로 쓰지 않는다.

[운영 장부](https://ledger.foresttour.kr/) · [카드 내역](https://ledger.foresttour.kr/import)

| 필요한 정보 | 문서 |
| --- | --- |
| 전체 문서와 역할 찾기 | [문서 지도](docs/README.md) |
| 처음 읽기·현재 정책·상세 명세 찾기 | [시작 안내](docs/COST_V3_START_HERE.md) |
| 완료한 일·남은 일·다음 작업 경계 | [현재 상태](docs/session_handoff.md) |
| 마지막 검증 릴리스·배포·복구 원칙 | [운영 기록](docs/operations.md) |
| 작업 방식·권한·검증 기준 | [작업 지침](AGENTS.md) |
| 과거 결정·검증 근거·옛 파일 찾기 | [보관함](docs/history/README.md) |

문서의 기능 명세·합성 테스트·운영 배포·실자료 수락은 서로 다른 상태다. 현재 상태를 확인한 뒤 해당 주제의 명세만 읽는다. 과거 실행 계획을 새 작업으로 다시 실행하지 않는다.

## 로컬 합성 개발

운영과 다른 데이터 경로를 사용한다. 다음은 운영 서버 실행 명령이 아니다.

```powershell
$env:WEBLEDGER_CARD_FLOW='1'
$env:WEBLEDGER_UNIFIED_DB='1'
python run_candidate.py --data-root C:\AX\cost-dev-data --port 8765 --environment local-synthetic --synthetic-sessions
```

문서만 바꾸면 문서 diff·참조를 확인하며 앱을 재배포하지 않는다.
