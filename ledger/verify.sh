#!/bin/bash
# Fast Track(2026-07-24, 사용자 지시 "4번 적용"): 로직만 검증한다 — 워크북·rev·LibreOffice
# 재계산은 전혀 안 건드린다. 전체 체인(20~30분)과 달리 수 초 내 끝난다.
# 로직 수정 후에는 항상 이것부터 돌리고, 실제로 사용자에게 파일을 전달할 때만
# build_workbook_v76.py 이후 전체 체인(무겁다)을 돈다.
set -e
cd "$(dirname "$0")"
echo "[1/4] build_v13_trip.py"
python3 build_v13_trip.py
echo "[2/4] fix_v14.py"
python3 fix_v14.py
echo "[3/4] patch_v14.py"
python3 patch_v14.py
echo "[4/4] test_regression.py"
python3 test_regression.py
