"""Multimodal receipt extraction via user-installed OpenCode (model pinned to Free).

Only returns untrusted review suggestions. Does not change a ledger or use tools.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

MODEL = 'opencode/muse-spark-1.3-contributor-free'
MAX_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
TIMEOUT_SECONDS = 120
PROMPT = '''Read ONLY the attached page image. It may contain multiple Japanese/Korean
receipts, ferry tickets, handwriting, stamps, overlapping and rotated slips.
Return exactly ONE JSON object and no commentary or Markdown:
{"receipts":[{"box":[x0,y0,x1,y1],"merchant":null,"date":null,"amount":null,
"currency":null,"payment":null,"category_hint":null,"note":null}]}
Each physical receipt/ticket must have its OWN region, including identical-priced tickets.
Box coordinates must be numbers in [0,1] relative to the WHOLE attached page.
Rotate mentally as necessary. Distinguish paid total from subtotal, tax, tendered and change.
Never assume a payment method or date from a trip title. If unknown, use null, not a guess.
Payment is cash, private_card, corporate_card or null; currency is JPY, KRW or null.
Do not create expenses from advertisements, notes, blank backing pages or ticket stubs
that do not establish a payment. Preserve uncertain evidence using nulls and a short note.
Do not combine tickets; a user may later group selected tickets in the accounting UI.
Never call tools, change files, or write to any ledger.'''


class VisionUnavailable(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def enabled():
    return os.name == 'nt' and os.environ.get('WEBLEDGER_RECEIPT_VISION') == 'opencode-muse-free'


def _image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff') and data.rstrip().endswith(b'\xff\xd9'):
        return '.jpg'
    raise VisionUnavailable('VISION_IMAGE_REQUIRED')


def parse_events(raw):
    if len(raw) > MAX_OUTPUT_BYTES:
        raise VisionUnavailable('VISION_RESPONSE_TOO_LARGE')
    try:
        lines = raw.decode('utf-8-sig').splitlines()
        texts = []
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError()
            if event.get('type') == 'error':
                raise VisionUnavailable('VISION_PROVIDER_ERROR')
            if event.get('type') == 'text':
                part = event.get('part')
                if (isinstance(part, dict) and part.get('type') == 'text'
                        and isinstance(part.get('text'), str) and not part.get('synthetic')
                        and not (part.get('metadata') or {}).get('compaction_continue')):
                    texts.append(part['text'])
        answer = '\n'.join(texts).strip()
        if answer.startswith(chr(96) * 3):
            answer = re.sub('^' + chr(96) * 3 + '(?:json)?', '', answer, flags=re.I)
            answer = re.sub(chr(96) * 3 + '$', '', answer.strip()).strip()
        result = json.loads(answer)
        if not isinstance(result, dict) or set(result) != {'receipts'}:
            raise ValueError()
        return result
    except VisionUnavailable:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise VisionUnavailable('VISION_RESPONSE_INVALID') from None


def _string(value, max_length=120):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise VisionUnavailable('VISION_FIELD_INVALID')
    return value.strip() or None


def validate_response(result, *, image_hash):
    receipts = result.get('receipts')
    if not isinstance(receipts, list) or len(receipts) > 50:
        raise VisionUnavailable('VISION_RESPONSE_INVALID')
    rows = []
    for i, item in enumerate(receipts):
        if not isinstance(item, dict) or set(item) != {
                'box','merchant','date','amount','currency','payment','category_hint','note'}:
            raise VisionUnavailable('VISION_FIELD_INVALID')
        box = item['box']
        if (not isinstance(box, list) or len(box) != 4
                or any(type(x) not in (int,float) or x < 0 or x > 1 for x in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise VisionUnavailable('VISION_BOX_INVALID')
        merchant = _string(item['merchant'])
        date = _string(item['date'], 10)
        if date is not None:
            try:
                if datetime.date.fromisoformat(date).isoformat() != date:
                    raise ValueError()
            except ValueError:
                raise VisionUnavailable('VISION_DATE_INVALID') from None
        amount = item['amount']
        if amount is not None and (type(amount) is not int or amount <= 0 or amount > 1_000_000_000):
            raise VisionUnavailable('VISION_TOTAL_INVALID')
        currency, payment = item['currency'], item['payment']
        if currency not in ('JPY','KRW',None):
            raise VisionUnavailable('VISION_CURRENCY_INVALID')
        if payment not in ('cash','private_card','corporate_card',None):
            raise VisionUnavailable('VISION_PAYMENT_INVALID')
        box = [round(float(x),5) for x in box]
        # OCR amounts/merchant names can be corrected; source position identifies a slip.
        rid = hashlib.sha256(json.dumps([image_hash,i,box],separators=(',',':')).encode()).hexdigest()[:24]
        rows.append({'id':rid,'box':box,'merchant':merchant,'date':date,
                     'amount':amount,'currency':currency,'payment':payment,
                     'category_hint':_string(item['category_hint'],60),
                     'note':_string(item['note'],240),'requires_review':True})
    return {'receipts':rows,'source_sha256':image_hash,'model':MODEL,
            'confirmed':False,'trip_inferred':False}


def recognize(image, *, runner=None):
    """No direct model API, no paid fallback, no model-accessible tools."""
    if not enabled():
        raise VisionUnavailable('VISION_DISABLED')
    image = Path(image)
    if not image.is_file() or not 0 < image.stat().st_size <= MAX_BYTES:
        raise VisionUnavailable('VISION_IMAGE_INVALID')
    data = image.read_bytes()
    ext = _image_extension(data)
    executable = shutil.which('opencode')
    if executable is None:
        raise VisionUnavailable('VISION_OPENCODE_NOT_FOUND')
    with tempfile.TemporaryDirectory(prefix='cost-vision-') as temporary:
        root = Path(temporary)
        attachment = root / ('receipt'+ext)
        attachment.write_bytes(data)
        config = {'$schema':'https://opencode.ai/config.json',
                  'agent':{'receipt-readonly':{'description':'Receipt reading, no tools',
                     'mode':'primary','model':MODEL,'permission':{'*':'deny'}}},
                  'permission':{'*':'deny'}}
        (root/'opencode.json').write_text(json.dumps(config),encoding='utf-8')
        command = [executable,'run','--model',MODEL,'--agent','receipt-readonly',
                   '--title','COST receipt reading (free)',
                   '--format','json','--file',str(attachment),PROMPT]
        try:
            proc = (runner or subprocess.run)(command,cwd=str(root),capture_output=True,
                        timeout=TIMEOUT_SECONDS,check=False,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired):
            raise VisionUnavailable('VISION_EXECUTION_FAILED') from None
        if proc.returncode:
            raise VisionUnavailable('VISION_PROVIDER_ERROR')
        parsed = parse_events(proc.stdout)
    return validate_response(parsed,image_hash=hashlib.sha256(data).hexdigest())
