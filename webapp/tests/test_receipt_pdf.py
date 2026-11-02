import hashlib
import json

import pytest

from webapp import receipt_review as rr
from webapp.tests.test_receipt_review import PNG


def test_pdf_original_is_preserved_and_page_candidates_are_idempotent(tmp_path):
    store = tmp_path / 'receipts.json'
    pdf = b'%PDF-1.7 synthetic fixture; never a customer document'
    rendered = {'pages': [
        {'page': 1, 'text': 'SYNTHETIC PAGE ONE', 'image': PNG, 'suggestions': {'date': '2026-10-12'}},
        {'page': 2, 'text': 'SYNTHETIC PAGE TWO', 'image': PNG, 'suggestions': {}},
    ], 'requires_review': True}
    calls = []

    def recognize(path, language):
        calls.append((path, language))
        return rendered

    from unittest.mock import patch
    with patch.object(rr.local_receipt_ocr, 'recognize_pdf', side_effect=recognize):
        first = rr.store_pdf(store, pdf)
        original_path = rr._pdfs_dir(store) / (hashlib.sha256(pdf).hexdigest() + '.pdf')
        assert original_path.read_bytes() == pdf
        assert first['bytes'] == len(pdf)
        assert len(first['pages']) == 2
        assert first['pages'][0] == first['pages'][1]  # same rendered image remains content-addressed
        assert first['page_text'] == ['SYNTHETIC PAGE ONE', 'SYNTHETIC PAGE TWO']
        assert first['suggestions'][0] == {'date': '2026-10-12'}
        assert rr.store_pdf(store, pdf) == first

    assert len(calls) == 1
    data = json.loads(store.read_text(encoding='utf-8'))
    assert data['candidates'] == []  # OCR never registers a cost
    assert data['images'] == [first['pages'][0]]
    assert len(data['pdfs']) == 1


@pytest.mark.parametrize('kind', ['empty', 'bad_header', 'oversized'])
def test_invalid_or_oversized_pdf_is_rejected_before_render(tmp_path, kind):
    from unittest.mock import patch
    body = {'empty': b'', 'bad_header': b'%PD', 'oversized': b'%PDF-' + b'x' * (5 * 1024 * 1024)}[kind]
    with patch.object(rr.local_receipt_ocr, 'recognize_pdf') as recognize:
        with pytest.raises(ValueError):
            rr.store_pdf(tmp_path / 'receipts.json', body)
        recognize.assert_not_called()
