# M5 요청량 계측

제공자 규모 산정([SPEC §11.3](../SPEC.md#113-서버와-보조-노드-m5))용 내용 없는 HTTP 요청 수 계측은 명시 opt-in이다. 켜면 Board가 `<data-root>/metrics/http-<포트>.json`에 고정 라우트 ID·메서드·상태 등급·바이트 합계·시간 버킷만 누적한다. URL 원문·사용자·헤더·본문은 기록하지 않으며, 기본 실행은 계측 파일을 만들지 않는다.

- 켜기: 공식 설치기를 기존 작업 인자 그대로에 `-RequestMetrics`만 더해 다시 실행한다(`tools/install_web_ledger_startup.ps1 -Install …`). 전달 경로는 러너 `-RequestMetrics` → 런처 `--request-metrics` → `run_candidate --request-metrics`이며 Board 자식에만 적용되고 터널·항목 페이지에는 가지 않는다. 배포 도구의 SHA 전환은 이 스위치를 보존한다.
- 끄기: 같은 설치기를 `-RequestMetrics` 없이 다시 실행하고 Board를 재시작한다. 이미 쌓인 집계 파일은 지우지 않는다.
- 조회: `tools/http_request_metrics_summary.py`가 집계만 읽는다. 실제 작업 등록·재시작은 소유자 결정이며 저장소 작업에서 수행하지 않는다.
