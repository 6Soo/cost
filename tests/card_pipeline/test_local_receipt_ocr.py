import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import local_receipt_ocr as ocr


def test_suggestions_never_guess_payment_or_krw_conversion():
    text = 'SYNTHETIC\n2026/10/12\n\u5408\u8a08 1,234\n\u5c0f\u8a08 1,000\n\u7a0e 234'
    assert ocr.suggestions(text, 'ja') == {'date': '2026-10-12', 'total_jpy': 1234}
    assert ocr.suggestions(text, 'ko') == {'date': '2026-10-12'}
    assert ocr.suggestions(text + '\n\u5408\u8a08 500\n2026/10/13', 'ja') == {}


def test_disabled_and_unsupported_languages_fail_without_process():
    with patch.dict(os.environ, {}, clear=True), patch.object(ocr.subprocess, 'run') as run:
        with pytest.raises(ocr.OcrError):
            ocr.recognize(Path('unused'), 'ja')
        with pytest.raises(ocr.OcrError):
            ocr.recognize(Path('unused'), 'xx')
        run.assert_not_called()


def test_pdf_recognition_is_disabled_until_local_windows_ocr_is_enabled(tmp_path):
    pdf = tmp_path / 'synthetic.pdf'
    pdf.write_bytes(b'%PDF-1.4 synthetic')
    with patch.dict(os.environ, {}, clear=True), patch.object(ocr.subprocess, 'run') as run:
        with pytest.raises(ocr.OcrError):
            ocr.recognize_pdf(pdf)
        run.assert_not_called()


def test_real_windows_engine_reads_synthetic_image(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows OCR integration')
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (800, 400), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 40)
    draw.text((30, 30), 'SYNTHETIC RECEIPT\n2026/10/12\n\u5408\u8a08 1234', fill='black', font=font)
    path = tmp_path / 'synthetic.png'
    image.save(path)
    with patch.dict(os.environ, {'WEBLEDGER_RECEIPT_OCR': 'windows'}):
        result = ocr.recognize(path)
    assert 'SYNTHETIC' in result['text']
    assert result['suggestions']['date'] == '2026-10-12'
    assert result['requires_review'] is True


def test_real_windows_engine_renders_and_reads_synthetic_pdf(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows OCR integration')
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (800, 400), 'white')
    ImageDraw.Draw(image).text((30, 30), 'SYNTHETIC RECEIPT\n2026/10/12', fill='black',
                               font=ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 40))
    path = tmp_path / 'synthetic.pdf'
    image.save(path, 'PDF')
    with patch.dict(os.environ, {'WEBLEDGER_RECEIPT_OCR': 'windows'}):
        result = ocr.recognize_pdf(path)
    assert result['requires_review'] is True
    assert len(result['pages']) == 1
    assert result['pages'][0]['image'].startswith(b'\x89PNG\r\n\x1a\n')
    assert 'SYNTHETIC' in result['pages'][0]['text']
    assert result['pages'][0]['suggestions']['date'] == '2026-10-12'
