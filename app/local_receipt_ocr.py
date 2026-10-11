"""Read an already stored image with Windows OCR, without network or accounting writes."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import threading

_LOCK = threading.Lock()


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
        return {**result, 'suggestions': suggestions(result['text'], language),
                'requires_review': True}
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
