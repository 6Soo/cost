# 확정 여행 종료일 근거 개정

`tools/revise_trip_schedule.py`는 소유자가 확정한 종료일을 기존 일정 증거 구조에 기록한다. 여행별 예외를 동기화 코드에 넣지 않는다. DB·Google·거래 판정에는 접근하지 않는다. 운영 적용은 별도 승인된 단일 작성자가 수행한다. PR #841 작업에서는 운영 미리보기만 수행했다.

## 입력·미리보기

비공개 JSON 파일에 `trip_code`, `ends_on`(ISO 날짜), `rule_id`, `decided_on`, `reason` 문자열을 기록한다. 근거 없는 추론으로 일정을 만들지 않는다. 기존 authoritative 여행의 종료일만 바꾸며 여행 신원·시작일·연도·지역은 유지한다.

```powershell
python tools/revise_trip_schedule.py --authority <trip-authority.json> --evidence-root <evidence-folder> --change <private-change.json>
```

기본은 읽기 전용 미리보기다. 출력한 여행·이전/새 종료일·`before_sha256`을 검수한다. 화순 입력은 TRIP-098의 2026-11-13 결정을 근거로 종료일 2026-08-26을 지정한다. 기존 8/23~25 답변은 삭제하지 않는다.

## 적용·원복

```powershell
python tools/revise_trip_schedule.py --authority <trip-authority.json> --evidence-root <evidence-folder> --change <private-change.json> --expected-sha256 <preview-before-sha256> --receipt <new-private-receipt-folder> --apply
python tools/revise_trip_schedule.py --authority <trip-authority.json> --rollback <receipt-folder>
python tools/revise_trip_schedule.py --authority <trip-authority.json> --rollback <receipt-folder> --apply
```

적용은 새 receipt 폴더에 원본/새 authority의 정확한 바이트를 보관하고 각각 파싱·원본 바이트 대조로 복원 사본을 확인한 뒤 진행한다. 새 owner-schedule 증거에는 원래 일정 레코드 전체와 새 결정의 규칙·결정일·이유를 남긴다. active authority는 기존 스키마의 여행별 단일 레코드를 교체한다. 이전 레코드는 새 증거의 `basis.supersedes`와 receipt에, 기존 authority 전체는 `authority.before.json`에 보존한다. 기존 증거는 수정하지 않는다. 증거를 먼저 저장하고 authority는 마지막에 원자 교체한다. 다른 여행 레코드는 그대로다.

미리보기 SHA나 적용 직전 원본이 달라지면 중단한다. 동시 유지보수는 배타적 `.revision.lock`으로 막는다. 원복은 receipt의 파일 해시·대상 경로·현재 authority가 적용 직후 값인지 확인한 뒤 원본 바이트를 복원한다. 이후 변경을 덮어쓰지 않으며 새 증거도 삭제하지 않는다. 강제 종료로 lock이 남으면 작성자 종료와 원본/새 SHA부터 확인한다. 자동 lock 제거는 없다. `applied.json`이 없어도 manifest와 현재 SHA로 교체 여부를 확인하고 같은 원복 경로를 쓸 수 있다.

근거 개정과 종료일 동기화는 별도 단계다. 이후 일반 동기화가 Google 명시 종료일과 새 확정 일정이 일치할 때 `save_trip_meta`로 종료일만 갱신한다. 재판정과 `trip_tabs.source_sha256` 직접 수정은 하지 않는다. 사본·receipt·원문 근거는 비공개로 보존하고 Git/PR에 넣지 않는다.

## 읽기 실패 처리

원본 동기화는 선택적 후처리 실패가 독립 작업을 막지 않게 한다(`tools/google_authority_sync.py`의 demo refresh 예외 분리). 이에 맞춰 `import_trips`는 경고 로그 `TRIP_SCHEDULE_UNAVAILABLE`와 결과 `schedule_unavailable`을 남기고 기존 여행의 종료일 갱신만 건너뛴다. 새 여행 생성·자동 연결은 계속 가능하다. 근거를 못 읽었다고 보호 없는 종료일 갱신을 허용하지 않는다.
