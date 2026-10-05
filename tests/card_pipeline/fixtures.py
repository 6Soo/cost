# -*- coding: utf-8 -*-
"""Synthetic card files and a temporary database for the pipeline tests.

Nothing here is a customer file. Every sheet is built in memory by the fixtures
below, and every database is a temporary directory.
"""

from __future__ import annotations

import io

from openpyxl import Workbook

# The Korean headers a domestic card sheet actually uses.
DOMESTIC_HEADERS = ["카드사", "카드번호", "카드종류", "구분", "가맹점", "이용금액",
                    "외화금액", "외화코드", "원화금액", "승인일", "매입일",
                    "승인번호", "취소여부", "상태"]

# The English headers a foreign card sheet uses.
FOREIGN_HEADERS = ["Issuer", "Card No", "Card Type", "Type", "Merchant",
                   "Amount", "Foreign Amount", "Currency", "Amount KRW",
                   "Date", "Post Date", "Authorization Code", "Cancel", "Status"]

TRANSACTION_FIELDS = ["Issuer", "Card No", "Card Type", "Type", "Merchant",
                      "Amount", "Foreign Amount", "Currency", "Amount KRW",
                      "Date", "Post Date", "Authorization Code", "Cancel", "Status"]


def _cell(value):
    return value


def make_xlsx(rows, headers=DOMESTIC_HEADERS, *, headered=True) -> bytes:
    """A real .xlsx, not a CSV with an xlsx name."""
    workbook = Workbook()
    sheet = workbook.active
    if headered:
        sheet.append(list(headers))
    for row in rows:
        sheet.append([_cell(v) for v in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def make_csv(rows, headers=DOMESTIC_HEADERS, *, headered=True) -> bytes:
    """A UTF-8 with BOM CSV, the other shape a card upload arrives as."""
    import csv
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    if headered:
        writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def domestic_row(*, merchant, amount, approval, date="2026-04-09",
                 posting="2026-04-11", kind="승인", issuer="합성카드",
                 card="****-****-****-1234", card_kind="신용", cancel="",
                 status="정상", foreign_amount=None, currency="",
                 krw_amount=None):
    return [issuer, card, card_kind, kind, merchant, amount,
            "" if foreign_amount is None else foreign_amount, currency,
            "" if krw_amount is None else krw_amount, date, posting,
            approval, cancel, status]


def foreign_row(*, merchant, amount, approval, date="2026-04-09",
                posting="2026-04-11", kind="PURCHASE", issuer="SYNTHETIC BANK",
                card="****1234", card_kind="CREDIT", cancel="", status="OK",
                currency="USD", krw_amount=13500):
    return [issuer, card, card_kind, kind, merchant, amount,
            amount, currency, krw_amount, date, posting, approval, cancel, status]


# A headerless corporate export: the F-style layout the reference code reads.
CORP_F_HEADERS = None


def corp_row(*, date="20260409", card="합성카드1234", merchant="합성식당",
             kind="식당", amount=12000, approval="123456(654321)", status="정상",
             index=2):
    """19 columns, F/E-style, with the cells the profile claims in place."""
    row = [None] * 19
    row[0] = date          # 매입일
    row[1] = date          # 승인일
    row[2] = "카드사"
    row[5] = "1234"        # 카드 뒤 4자리
    row[7] = merchant
    row[8] = kind
    row[10] = "원화"
    row[11] = amount
    row[12] = 0
    row[15] = approval
    row[16] = status
    return row