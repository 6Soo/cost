# 2026-08-29 세션 작업 결과 요약 (1페이지)

## 완료된 5개 작업

| # | 작업 | 산출물 |
|---|------|--------|
| 1-A | `manual_tab_schedule_authority.py` 0416 수정 (체크아웃 -1 제거) | `0413_나가센도` 04/15 → 04/16, 28건 일괄 +1일 |
| 1-B | `trip_schedule_authority_v3.json` 48건 보강 | trips.json 8건 + Q1 11건 + 5월_유럽/부산 보정 |
| 1-C | 매칭 tie-break 3단계 (체크인=시작일 우선) | 06/16→레분토, 07/08→아키타 등 9건 자동 해결 |
| 1-D | HI Design 수동 부산 귀속 | `0501_부산` 05/01 → 04/29 확장 |
| 1-E | 정식 OTA 파이프라인 부분 적용 | 84 → **103 links**, 78 bound_unique |

## 최종 매칭 결과

| 상태 | 08-26 (84건) | **08-29 (103건)** | 변화 |
|------|-------------|------------------|------|
| bound_unique | 59 | **78** | +19 |
| authority_missing | 25 | 25 | 동일 |
| 총액 (KRW) | 13,850,872 | **20,885,284** | +7,034,412 |

## 정식 OTA 파이프라인의 한계

- `project_verified_lodging_decisions`의 `TRIP_MERCHANT_CONTRACTS`가 KBD/KBO/HAN/CORP의
  **Trip.com 패턴만** 등록
- Booking.com(190건), KLOOK(16건), AIRBNB(6건), Rakuten Travel(10건) 자동 매칭 불가
- `prepare_external_lodging_facts`는 24 active fact 만들었으나 매칭 단계에서 0 authority
- `build_links_from_verified.py`로 target_code 기반 직접 매칭으로 우회 (24→21, 87.5% 성공)

## 핵심 산출물 SHA-256

| 파일 | SHA-256 |
|------|---------|
| `trip_schedule_authority_v3.json` | `a1927d256ced782c8bcc39f5bb8bdca0ff523438514a576ac200e9c994d50bd3` |
| `agoda-card-link-candidate-v5-20260826.sqlite` | `120b6579390336a314329697359d394b6cebe19c0a6ee79ae37e9a95d5d24263` |
| `agoda-card-accounting-draft-v5-ota-extended.sqlite` | `9cfcd472060e0fffd6e68152552e27590fa3cd20accc5080c5e1f1bc55254ec3` |

## 미배정 25건 (모두 2025년 또는 2026년 1-2월)

authority v3가 2026-04-04부터 시작하므로 자동 매칭 불가. 다음 세션 작업:
- 2025년 권위 추가 (23건) 또는 2025년 결제 terminal 분리
- 2026년 1~2월 권위 확인 (2건)

## 다음 세션 우선순위

1. **미배정 25건 처리** (2025년 권위 추가)
2. **`project_verified_lodging_decisions` 한계 극복** (Booking.com/KLOOK TRIP_MERCHANT_CONTRACTS 확장)
3. **`v5-ota-extended` journal shadow 생성** (현재 미생성)
4. **2025-08-26 직전 회계 draft와 정합성 비교**
5. **수기장부 1,379건 / OTA 1,720건 대사** (P6 단계 잔여)

## 금지·보존

- `agoda-card-link-candidate-v5-20260826.backup-84links.sqlite` 보존 (84 links 원본)
- 회계 전기·외부 게시·배포는 이번 세션에서도 수행하지 않음
- v5 candidate DB 재생성 금지 (103 links + 1,742 non_agoda 메일 소실 위험)
