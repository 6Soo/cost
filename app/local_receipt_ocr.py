"""Read an already stored image with Windows OCR, without network or accounting writes."""
from __future__ import annotations

import datetime
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import threading

_LOCK = threading.Lock()
PDF_PAGE_LIMIT = 10
PDF_LIMIT = 5 * 1024 * 1024
PDF_PAGE_IMAGE_LIMIT = 4 * 1024 * 1024


class OcrError(Exception):
    pass


def enabled():
    return os.name == 'nt' and os.environ.get('WEBLEDGER_RECEIPT_OCR') == 'windows'


def recognize(image: Path, language: str = 'ja') -> dict:
    if language not in ('ja', 'ko'):
        raise OcrError('OCR_LANGUAGE_INVALID')
    if not enabled():
        raise OcrError('OCR_UNAVAILABLE')
    if not _LOCK.acquire(blocking=False):
        raise OcrError('OCR_BUSY')
    try:
        script = Path(__file__).resolve().parents[1] / 'tools/windows_receipt_ocr.ps1'
        process = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
             '-ImagePath', str(image.resolve()), '-Language', language],
            capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if process.returncode or len(process.stdout) > 256 * 1024:
            raise OcrError('OCR_FAILED')
        result = json.loads(process.stdout.decode('utf-8-sig'))
        if not isinstance(result.get('text'), str) or not result['text'].strip():
            raise OcrError('OCR_TEXT_EMPTY')
        lines = [{'text': line['text'], 'top': line['top']} for line in result.get('lines') or []
                 if isinstance(line, dict) and isinstance(line.get('text'), str)
                 and type(line.get('top')) in (int, float)][:200]
        return {**result, 'lines': lines, 'suggestions': suggestions(result['text'], language),
                'requires_review': True}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
        raise OcrError('OCR_FAILED') from None
    finally:
        _LOCK.release()


def recognize_pdf(pdf: Path, language: str = 'ja') -> dict:
    """Render/OCR a bounded PDF locally. Return page images for existing receipt review."""
    if language not in ('ja', 'ko'):
        raise OcrError('OCR_LANGUAGE_INVALID')
    try:
        size = pdf.stat().st_size
        if not 8 <= size <= PDF_LIMIT or not pdf.read_bytes().startswith(b'%PDF-'):
            raise OcrError('PDF_INVALID')
    except OcrError:
        raise
    except OSError:
        raise OcrError('PDF_INVALID') from None
    if not enabled():
        raise OcrError('OCR_UNAVAILABLE')
    if not _LOCK.acquire(blocking=False):
        raise OcrError('OCR_BUSY')
    try:
        script = Path(__file__).resolve().parents[1] / 'tools/windows_receipt_ocr.ps1'
        process = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
             '-PdfPath', str(pdf.resolve()), '-Language', language],
            capture_output=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if process.returncode or len(process.stdout) > 48 * 1024 * 1024:
            raise OcrError('OCR_FAILED')
        result = json.loads(process.stdout.decode('utf-8-sig'))
        pages = result.get('pages')
        if not isinstance(pages, list) or not 1 <= len(pages) <= PDF_PAGE_LIMIT:
            raise OcrError('PDF_PAGE_LIMIT')
        clean = []
        for number, page in enumerate(pages, 1):
            if not isinstance(page, dict) or page.get('page') != number or not isinstance(page.get('text'), str):
                raise OcrError('OCR_FAILED')
            image = base64.b64decode(page.get('png', ''), validate=True)
            if len(image) > PDF_PAGE_IMAGE_LIMIT or not image.startswith(b'\x89PNG\r\n\x1a\n'):
                raise OcrError('OCR_FAILED')
            clean.append({'page': number, 'text': page['text'], 'image': image,
                          'suggestions': suggestions(page['text'], language), 'requires_review': True})
        return {'pages': clean, 'requires_review': True}
    except OcrError:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
        raise OcrError('OCR_FAILED') from None
    finally:
        _LOCK.release()


def suggestions(text: str, language: str) -> dict:
    """Only unambiguous dates and Japanese labelled totals; never guess payment."""
    dates = set()
    for year, month, day in re.findall(r'(20\d{2})\s*[./\-\u5e74]\s*(\d{1,2})\s*[./\-\u6708]\s*(\d{1,2})', text):
        try:
            dates.add(datetime.date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass
    result = {'date': next(iter(dates))} if len(dates) == 1 else {}
    if language == 'ja':
        totals = set()
        for line in text.splitlines():
            compact = re.sub(r'\s+', '', line)
            if '\u5408\u8a08' not in compact or any(word in compact for word in ('\u5c0f\u8a08', '\u7a0e', '\u5272\u5f15')):
                continue
            values = re.findall(r'(?<!\d)(\d[\d,]*)(?!\d)', compact)
            if len(values) == 1:
                value = int(values[0].replace(',', ''))
                if value > 0:
                    totals.add(value)
        if len(totals) == 1:
            result['total_jpy'] = next(iter(totals))
    return result
