# 관리자 UI 후속 진단과 검증

- 기준: `origin/main` 0bd7a5d0, 관리자 UI 후속 변경 및 현재 작업 트리.
- 범위: 공통 셸과 장부, 카드, 지출, OTA, 여행, 영수증, 예약 연결, 항공, 계정, 검토, 내보내기 화면. 실제 고객 자료 대신 독립된 합성 서버·세션을 사용했다.
- 기준: 저장소 `AGENTS.md`, 기존 셸 토큰과 컴포넌트, Jakub Krehel의 `better-interface`, `better-accessibility`, `better-layout`, `better-writing`, `better-typography`, `better-colors`, `better-ui`, `interface-review` 실제 지침.

## 수정한 문제

| 심각도 | 발견과 조치 |
| --- | --- |
| HIGH | 어두운 테마에서 카드 링크(2.76:1), OTA 페이지 번호(3.59:1), 예약 연결 경고(2.77:1)의 텍스트 명암이 4.5:1 미만이었다. 기존 테마의 accent·muted·warning 토큰을 적용했다. |
| HIGH | OTA와 예약 연결의 모바일 표 라벨, OTA 선택 필터 값도 어두운 표면에서 읽기 어려웠다. 해당 화면과 공통 스타일의 고정 색상을 테마 토큰으로 교체했다. 두 화면의 실제 렌더링 명암 회귀 테스트를 추가했다. |
| HIGH | 카드 자료 오류와 예약 연결 오류에 복구 경로가 부족했다. 카드 화면에 다시 불러오기와 관리자 문의를, 예약 연결 오류에 문의 안내를 추가했다. 저장과 적용 요청의 처리 방식은 유지했다. |
| MEDIUM | 카드 오류 화면이 공통 본문 여백 없이 화면 가장자리에 붙었다. 기존 카드 화면의 컨테이너와 상세 표면을 재사용했다. |
| MEDIUM | 터치 장치의 hover 잔류 가능성, 테마 변경 시 transition, reduced-motion 내비게이션 이동을 공통 스타일과 테마 제어에서 수정했다. |

## 실제 화면과 테스트

- 390×844 및 1440×900: 기준과 변경 화면에서 11개 경로를 캡처했다. `quality-artifacts/admin-ui-ux/polish-*`는 카드 오류의 두 크기, OTA 및 예약 연결의 모바일 다크 테마 전후 캡처다. OTA 필터·행 캡처에는 렌더링 검사용 합성 DOM을 사용했다. 나머지 캡처와 측정 JSON은 로컬 `.local-archive/ui-audit-20261105/`에 있다.
- 320px: 접근 가능한 10개 화면에서 문서 가로 넘침이 없었고, 표시된 버튼의 이름을 점검했다. reduced-motion에서 메뉴 열기, 닫힌 상태와 Escape 닫기를 실제 브라우저로 확인했다.
- 명암: 접근 가능한 10개 화면의 밝은/어두운 테마에서 표시된 직접 텍스트의 렌더링 색상을 측정했으며 수정 후 해당 검사에서 실패가 없었다. 표 가상 요소는 OTA·예약 연결에서 별도로 측정했다. 이미지 배경·투명도 등 검사에서 제외된 텍스트가 있으므로 전체 명암 감사로 간주하지 않는다.
- `python -m pytest -q webapp/tests/test_cards_all.py webapp/tests/test_card_catalog_assets.py webapp/tests/test_ota_catalog_browser.py webapp/tests/test_reserve_link.py webapp/tests/test_reserve_link_browser.py`: 115 passed, 31 subtests passed. 이후 OTA 색상 수정의 관련 검사 7 passed, 3 subtests passed; 새 명암 및 카드 오류 회귀 검사 7 passed.
- 2026-11-05의 앞선 `better-ui` 검사: 공통 셸·카드·지출·장부 관련 62 passed, 19 subtests passed, skip 0.

## 최종 검토 및 미검증

`interface-review`는 기준 0bd7a5d0 대비 변경 전체와 공통 셸의 대표 소비 화면을 검토했다. 위 결함은 수정 후 재검증했다. 합성 환경에서 항공 화면은 기능 비활성 응답이므로 활성 항공 업무, 실제 고객 자료가 있는 모든 상세·오류 조합, 모든 권한 조합, 스크린리더 수동 검사와 물리 모바일 기기는 **미검증**이다. 전체 관리자 화면에 결함이 없다고 단정하지 않는다.
