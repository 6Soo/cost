"""합성 Google 장부 워크북 픽스처.

옛 /google-ledger 브라우저 화면은 6c0a5e38(ROUTES=())로 폐지됐다. 라우트 거부·
비공개 데이터 미노출·쓰기 금지는 test_google_viewer_http의
test_retired_google_ledger_routes_return_404_without_private_data_or_writes가
검사한다. 이 모듈은 다른 검사가 쓰는 워크북 픽스처만 남긴다.
"""

import datetime as dt
import io

import openpyxl

from app import google_authority as ga

INCOME = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
EXPENSE = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]
NOW = dt.datetime(2026, 10, 11, 9, 0, tzinfo=ga.KST)


def empty_workbook():
    book = openpyxl.Workbook()
    book.active.title = 'Synthetic template'
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def workbook(title, income, expense):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(title)
    for col, label in zip("BCDEFGH", INCOME):
        ws[f"{col}5"] = label
    ws["B6"], ws["C6"], ws["D6"], ws["H6"] = dt.date(2027, 2, 6), income[0], income[1], income[2]
    ws["C8"] = "=sum(H6:H6)"
    ws["B10"] = "지출 내용"
    for col, label in zip("BCDEFGH", EXPENSE):
        ws[f"{col}11"] = label
    ws["B12"], ws["C12"], ws["D12"], ws["E12"], ws["F12"], ws["G12"], ws["H12"] = (
        dt.date(2027, 2, 7), expense[0], expense[1], "2027-02-07", "RESV-9", "카드", expense[2])
    ws["C13"] = "=SUM(H12:H12)"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()