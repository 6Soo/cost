# Reserve 저장 일정 재개 기록

상태: `PARTIAL_HANDOFF`. 운영 일정 조회와 구현은 미완료다. 기존 검증 manifest는
당시 스냅샷으로 보존하며 이 문서 작성 뒤의 문서 해시를 소급해 반영하지 않는다.

## 복원한 작업

사용자는 `reserve 레포에 여행일 시작과 끝을 저장해온 자료`와 진행 기록을 찾아
재개하도록 요청했다. 실제 경로는 `C:\AX\reservation`이다.

- 공급자: `src/lib/scheduleExport.ts`, `scripts/export-schedule.ts`.
- 소비자: `ledger/domain/reservation_schedule_export.py`,
  `tools/import_reservation_schedule.py`.
- 날짜는 저장된 `tours.depart_date`와 `return_date`에서 가져온다.
  기존 export는 종료일 포함 의미를 기록한다. 결제일이나 원문 재파싱으로 보완하지 않는다.
- [8월 26일 인계](../2026-08-26/README.md)는 운영 연결값 형식 오류로 실제 export가
  중단됐음을 명시한다. 기존 3행 demo export와 smoke DB는 계속 격리 자료다.
- [8월 25일 대화](../2026-08-25/paseo_bdf58685_full_transcript.md)에서 댓글 10개 기준,
  운영진 게시판 이동 이후에도 기존 여행·활동 증거 삭제 금지, 후속 구현 요청을 확인했다.
  단순히 게시글이 현재 안 보인다는 이유로 여행을 제거하지 않는다.

## 이번 실측

- Cost 테스트: `python -m pytest ledger/tests/test_reservation_schedule_export.py -q --tb=short`
  결과 10 passed. 운영 DB는 사용하지 않았다.
- 합성 일정 두 행을 메모리 DB에 import한 뒤 행 순서만 역전해 재실행했다.
  최초 inserted=9, 역순 inserted=3, export digest 불일치. 날짜 권위가 세 개 더 생긴다는
  뜻은 아니며 export와 lineage 감사 행의 중복이다. 기존 단일 입력 반복 테스트만으로는
  순서 불변성을 보장하지 못한다.
- 기존 CLI는 `getDb()`를 호출한다. 이 함수는 `initSchema()` 및 필요시 DDL·백필을
  실행하므로 읽기 전용 export로 사용하면 안 된다. 이번에는 해당 CLI를 운영에 실행하지 않았다.
- Vercel CLI의 실제 `whoami` 및 프로젝트 목록 조회 성공. 대상 프로젝트는 `reservation`.
  production env pull은 두 Turso 변수를 `[SENSITIVE]`로 반환했다. 로컬 기존 URL도
  유효한 libsql/https scheme이 아니었다. 보호된 값을 우회하지 않았다.
  내려받은 임시 env 파일은 값 출력 없이 검사 후 삭제했다. 기존 `.env.local`은 보존했다.
- 사용자에게 채팅으로 비밀값을 보내지 않고 로컬 연결값을 설정하도록 요청했다.

## 구현 모델 실행 결과

사용자 지정 `codex/gpt-reserve`, `thinkingOptionId=max`로 실제 작업을 위임했다.
에이전트 `3327ee4e-12c3-4635-873a-d343e349ed11`은 시작 즉시 사용량 한도 오류로
종료됐다. 도구가 표시한 재시도 시점은 `Sep 14th, 2026 5:49 PM`이며 시간대는
확인되지 않았다. 작업 활동은 요청과 오류 두 항목뿐이며 파일 변경은 없었다.
다른 모델로 자동 전환하지 않았다.

## 다음 실행자가 할 일

1. 사용자가 지정한 구현 모델의 가용성 또는 대체 모델 지시를 확인한다.
2. export CLI에서 앱 DB 초기화 경로를 제거한다. 직접 libsql client와 읽기 전용
   transaction을 사용하고 모든 성공·실패 경로에서 연결을 닫는다.
   운영 URL과 옵션을 연결 전에 검사하며 오류에 비밀값을 포함하지 않는다.
3. 출력은 기존 파일을 덮어쓰지 않고 완성된 문서만 배타적으로 게시한다.
   합성 client로 DDL 미호출, 읽기 transaction, 실패 정리, 출력 충돌을 검증한다.
4. 공급자와 소비자의 행 순서 정규화를 함께 설계한다. 기존 v2 digest를 조용히 바꾸지
   말고 버전·이전 증거 호환·다중 행 공통 fixture·반복 import 검증을 포함한다.
5. source_datanum과 원문 fallback이 서로 다른 게시글을 지목할 수 있는 기존 SQL을
   확인한다. 저장 날짜와 원문 hash의 존재만으로 모든 source 연결이 증명됐다고 보지 않는다.
6. 실제 연결값이 설정된 뒤 개인정보 없는 일정만 새로운 export 파일로 읽는다.
   원본 운영 DB를 수정하거나 로컬 demo DB로 폴백하지 않는다.
7. 새 격리 cost DB에서 검증·두 번 import·권위 로더 검증을 수행하고,
   현재 cost trip code와 Reserve 식별자의 명시적 대응을 확인한다.
   날짜가 같다는 이유만으로 서로 다른 여행 코드를 합치지 않는다.
8. 일정 겹침 정책은 기존 원천과 수동 결정부터 대조한다. 재개 요청을 일반 tie-break
   승인으로 해석하지 않는다. 운영 전기·배포 완료로 기록하지 않는다.

이번 재개에서 두 저장소의 기존 미커밋 코드와 운영 자료는 변경하지 않았다.
문서에 발견 내용과 정확한 중단 원인을 추가했다.
