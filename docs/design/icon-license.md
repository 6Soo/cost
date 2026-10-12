# 아이콘 출처와 라이선스 고지

작성일: 2026-10-12

## 적용 범위

COST 업무 화면의 버튼·메뉴에 쓰는 작은 선형 아이콘은 외부 요청·아이콘
폰트·전체 패키지 없이 `webapp/ui_icons.py`의 고정 목록으로만 렌더링한다.
사용자 원문이나 AI 응답을 SVG·HTML로 직접 삽입하지 않는다.

## 방향 참고와 라이선스

- 시각 방향(24px viewBox, 채움 없음, 둥근 선 끝, 2px 선)은 Lucide 선형
  아이콘의 일반적인 관례를 참고했다. 참고 문서: https://lucide.dev/guide/
- `webapp/ui_icons.py`의 경로는 COST용으로 직접 작성한 단순 도형이며
  Lucide 공식 SVG를 복사하지 않았다. 따라서 특정 Lucide 버전·커밋의
  경로와 동일하다고 주장하지 않는다.
- 방향을 참고한 원 라이선스 고지를 보존한다.
  - Lucide: ISC License — https://lucide.dev/license
  - Lucide의 Feather 기반 아이콘: MIT License — https://lucide.dev/license
- 위 고지는 참고 방향의 조건을 유지하기 위한 기록이며, COST 저장소에
  제삼자 아이콘 자산이 들어왔다는 의미가 아니다. 공식 SVG를 그대로
  포함하게 되면 해당 시점에 정확한 출처·버전(또는 커밋)과 고지를 이
  문서에 함께 기록한다.

## 렌더링 규칙

- 기본 16px, 사이드 메뉴 18px, 표 헤더 14~16px을 사용한다.
- 장식 아이콘은 `aria-hidden="true"`, `focusable="false"`이며 클릭은
  부모 버튼에 전달된다. 기존 버튼의 접근 가능한 이름을 바꾸지 않는다.
- 허용되지 않은 이름은 렌더링하지 않고 빈 문자열을 돌려준다.
