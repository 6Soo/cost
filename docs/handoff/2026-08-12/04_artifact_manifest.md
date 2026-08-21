# 산출물·검증 manifest

## 최신 후보 보고서

- 루트: `/tmp/cost-gate-current-20260812c`
- 보고서: `/tmp/cost-gate-current-20260812c/artifacts/3cecbeb869ef4ef6a3fc80e3530b2d1a-ae4a57abdbed/gate_report.json`
- run id: `3cecbeb869ef4ef6a3fc80e3530b2d1a`
- `passed`: `false`
- `code_commit`: `243fb8240eddbbcd71133c0788f8561064c5a2e4`
- `code_bundle_sha256`: `60b68249b00fd49587539bf76e5c0de8046a77392a7b1fb7a313fc31c78ee692`
- `candidate_semantic_sha256`: `ae4a57abdbed9992ba7e598629083b72c760641d377d4d54b700d92a06d2c651`
- `gate_report_sha256`: `43d14609bfb5d4720498de2d5ff7c221eb3865699635ce7ea8bfe1471dd8b980`
- `input_manifest_sha256`: `655bf26d06fb7e19e68307d9e626d93dfd846e79472b78b25cb495f48ec5d838`
- `parser_version`: `direct-source-v5`
- `schema_version`: `p07-direct-v3`
- `format_version`: `2`

## HAN equality package

- manifest: `/tmp/cost-gate-current-20260812c/han-equality/manifest.json`
- `applied=false`
- `authority_status=unattested`
- `posting_status=blocked`
- package set SHA256: `6769eab91f4125d3ae49b8520b8159518ebfbf9e2433ce7bd089395dd8cad91d`
- candidate master rows: 5,328
- private mapping rows: 2,188

이 경로는 임시 산출물이며 민감한 원장 값이 포함될 수 있다. 저장소에 복사·커밋하지
않고, 필요한 경우 동일 명령으로 재생성한다.

## 테스트 기록

```text
python3 -m py_compile ...                         PASS
python3 -m unittest -v ...                        106 tests, OK
git diff --check                                  PASS
independent Sol high final review                VERDICT: PASS
```

전체 후보 실행은 Gate6 `direct_baseline_unavailable` 때문에 fail-closed로 끝났다. 이
실패를 지우거나 전체 PASS로 재명명하지 않는다.
