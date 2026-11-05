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


def test_saved_upload_name_and_duplicate_are_recovered_without_changing_original(tmp_path):
    store = tmp_path / 'receipts.json'
    first = rr.store_uploaded(store, PNG, kind='image', name='<합성>.png')
    second = rr.store_uploaded(store, PNG, kind='image', name='another.png')
    assert first['duplicate'] is False and second['duplicate'] is True
    data = rr.load(store)
    assert data['uploads'] == [{'kind': 'image', 'sha256': first['sha256'], 'name': '<합성>.png'}]
    assert rr.image_bytes(store, first['sha256']) == PNG
    page = rr.render_html(data, csrf='test')
    assert '&lt;합성&gt;.png' in page
    assert '<합성>.png' not in page


def test_retry_after_upload_metadata_write_failure_keeps_original(tmp_path):
    from unittest.mock import patch
    store = tmp_path / 'receipts.json'
    save = rr._save
    calls = []

    def fail_metadata(path, data):
        calls.append(1)
        if len(calls) == 2:
            raise OSError('synthetic write failure')
        save(path, data)

    with patch.object(rr, '_save', side_effect=fail_metadata):
        with pytest.raises(rr.ReceiptStoreError):
            rr.store_uploaded(store, PNG, kind='image', name='fixture.png')
    sha = hashlib.sha256(PNG).hexdigest()
    assert rr.image_bytes(store, sha) == PNG
    assert rr.load(store)['uploads'] == []
    retry = rr.store_uploaded(store, PNG, kind='image', name='fixture.png')
    assert retry['duplicate'] is True
    assert rr.load(store)['uploads'][0]['sha256'] == sha


@pytest.mark.parametrize('kind', ['empty', 'bad_header', 'oversized'])
def test_invalid_or_oversized_pdf_is_rejected_before_render(tmp_path, kind):
    from unittest.mock import patch
    body = {'empty': b'', 'bad_header': b'%PD', 'oversized': b'%PDF-' + b'x' * (5 * 1024 * 1024)}[kind]
    with patch.object(rr.local_receipt_ocr, 'recognize_pdf') as recognize:
        with pytest.raises(ValueError):
            rr.store_pdf(tmp_path / 'receipts.json', body)
        recognize.assert_not_called()
