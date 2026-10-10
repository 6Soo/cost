"""Regenerates the synthetic .xls fixtures. Needs `xlwt`, which is not a runtime dependency."""
from pathlib import Path

import xlwt

DATA = Path(__file__).parent / "data"
KB = ['매입일', '승인일', '승인시간', '부서번호', '부서명', '카드번호', '이용자명', '가맹점명', '업종명', '결제방법',
      '할부개월수', '승인금액', '부가세', '승인구분', '승인방식', '승인번호', '상태', '과세유형', '가맹점상태',
      '가맹점번호', '가맹점사업자등록번호', '대표자성명', '가맹점주소', '가맹점전화번호']
ROWS = [
    ['2026.10.02', '2026.10.01', '14:13:41', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', '합성편의점',
     '편의점', '일시불', 0.0, 12000.0, 0.0, '국내', 'IC', '71000001', '정상', '과세', '정상', '1', '1', '홍', '서울', '02'],
    ['2026.10.02', '2026.10.01', '15:00:00', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', '합성식당',
     '일반음식점', '일시불', 0.0, 45000.0, 0.0, '국내', 'IC', '71000002', '정상', '과세', '정상', '2', '2', '홍', '서울', '02'],
    ['2026.10.03', '2026.10.02', '09:30:10', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', '합성식당',
     '일반음식점', '일시불', 0.0, -45000.0, 0.0, '국내', 'IC', '71000002', '취소', '과세', '정상', '2', '2', '홍', '서울', '02'],
]


def save(path, headers, data):
    book = xlwt.Workbook(encoding='utf-8')
    sheet = book.add_sheet('Sheet1')
    for column, header in enumerate(headers):
        sheet.write(0, column, header)
    for index, row in enumerate(data, 1):
        for column, value in enumerate(row):
            sheet.write(index, column, value)
    book.save(str(path))


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    save(DATA / "kb-domestic-acquired-synthetic.xls", KB, ROWS)
    approval_headers = [h for h in KB if h != '매입일']
    approval_rows = [[v for h, v in zip(KB, row) if h != '매입일'] for row in ROWS]
    save(DATA / "kb-approval-synthetic.xls", approval_headers, approval_rows)
