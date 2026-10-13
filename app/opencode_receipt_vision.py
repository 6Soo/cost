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
AGENT_INSTRUCTION = ('You read one attached receipt image and answer with JSON only, using exactly this schema and no other keys: '
                     '{"receipts":[{"box":[x0,y0,x1,y1],"merchant":null,"date":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"note":null}]}. '
                     'The image is already in the message. Never call tools, never look for files or instructions.')
PROMPT = '''Output format: a single JSON object, nothing else. No markdown, no code fence, no explanation.
Schema: {"receipts":[{"box":[x0,y0,x1,y1],"merchant":null,"date":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"note":null}]}
The page image is already attached to this message. Do not call any tool; answer from the attached image only.
The page may contain several Japanese/Korean receipts, ferry or boarding tickets, handwriting and stamps,
overlapping or rotated slips. One receipts entry per physical receipt or ticket, even identical-priced tickets.
box = [x0,y0,x1,y1] in 0..1 relative to the whole page (use pixel coordinates if you cannot normalize).
date as YYYY-MM-DD. amount is the paid total as an integer (not subtotal, tax, tendered or change).
currency is JPY or KRW. payment is cash, private_card, corporate_card or null.
Use null for anything unreadable. Never guess a date, amount or payment method.
Do not create entries from advertisements or blank areas. Do not combine tickets.'''


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
        if not isinstance(result, dict) or set(result) not in ({'receipts'}, {'documents'}):
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


def image_size(data):
    """Width and height from the PNG or JPEG header alone; None when they cannot be read."""
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    if data.startswith(b'\xff\xd8'):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                return None
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(data[index + 7:index + 9], 'big'), int.from_bytes(data[index + 5:index + 7], 'big')
            index += 2 + int.from_bytes(data[index + 2:index + 4], 'big')
    return None


_DATE_SEPARATED = re.compile(r'^(\d{4})[/.](\d{1,2})[/.](\d{1,2})(?:\s+\d{1,2}:\d{2})?$')
PAYMENT_VALUES = ('cash', 'private_card', 'corporate_card')


TOP_LEVEL_ALIASES = {'documents': 'receipts', 'receipts': 'receipts'}
ITEM_ALIASES = {'merchant': 'merchant', 'store': 'merchant', 'shop': 'merchant',
                'date': 'date', 'datetime': 'date', 'receipt_date': 'date',
                'amount': 'amount', 'total_amount': 'amount', 'total': 'amount',
                'currency': 'currency', 'payment': 'payment', 'payment_method': 'payment',
                'box': 'box', 'bbox': 'box', 'region': 'box',
                'category_hint': 'category_hint', 'note': 'note'}
CANONICAL_ITEM_KEYS = ('box', 'merchant', 'date', 'amount', 'currency', 'payment', 'category_hint', 'note')


def _canonical_item(item):
    """Rename known synonym keys to the schema keys; unknown keys are dropped, values are not changed."""
    renamed = {}
    for key, value in item.items():
        target = ITEM_ALIASES.get(str(key).strip().lower())
        if target is not None and target not in renamed:
            renamed[target] = value
    return {key: renamed.get(key) for key in CANONICAL_ITEM_KEYS}


def _normalized_item(item, size):
    """Deterministic clean-up of what the model wrote; anything still unclear becomes null, never a guess."""
    item = _canonical_item(item)
    box = item.get('box')
    if isinstance(box, list) and len(box) == 4 and any(type(x) in (int, float) and x > 1 for x in box):
        if size is None:
            return item
        width, height = size
        if not width or not height:
            return item
        item['box'] = [box[0] / width, box[1] / height, box[2] / width, box[3] / height]
    date = item.get('date')
    if isinstance(date, str):
        match = _DATE_SEPARATED.match(date.strip())
        if match:
            try:
                item['date'] = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                item['date'] = None
    payment = item.get('payment')
    if isinstance(payment, str):
        item['payment'] = payment.strip().lower() if payment.strip().lower() in PAYMENT_VALUES else None
    currency = item.get('currency')
    if isinstance(currency, str):
        item['currency'] = currency.strip().upper() if currency.strip().upper() in ('JPY', 'KRW') else None
    return item


def validate_response(result, *, image_hash, size=None):
    if 'receipts' not in result and 'documents' in result:
        result = dict(result, receipts=result['documents'])
    receipts = result.get('receipts')
    if isinstance(receipts, list):
        receipts = [_normalized_item(item, size) if isinstance(item, dict) else item for item in receipts]
        # An entry with no merchant, date or amount is not a reading; it is dropped, never shown as a candidate.
        receipts = [item for item in receipts if not (isinstance(item, dict)
                    and item.get('merchant') is None and item.get('date') is None and item.get('amount') is None)]
        result = dict(result, receipts=receipts)
    if not isinstance(receipts, list) or len(receipts) > 50:
        raise VisionUnavailable('VISION_RESPONSE_INVALID')
    rows = []
    for i, item in enumerate(receipts):
        if not isinstance(item, dict) or set(item) != {
                'box','merchant','date','amount','currency','payment','category_hint','note'}:
            raise VisionUnavailable('VISION_FIELD_INVALID')
        box = item['box']
        # No region at all is unknown, and the candidate still waits for review. A malformed region is refused.
        if box is not None and (not isinstance(box, list) or len(box) != 4
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
        if isinstance(amount, str) and amount.replace(',', '').strip().isdigit():
            amount = int(amount.replace(',', '').strip())
        if amount is not None and (type(amount) is not int or amount <= 0 or amount > 1_000_000_000):
            raise VisionUnavailable('VISION_TOTAL_INVALID')
        currency, payment = item['currency'], item['payment']
        if currency not in ('JPY','KRW',None):
            raise VisionUnavailable('VISION_CURRENCY_INVALID')
        if payment not in ('cash','private_card','corporate_card',None):
            raise VisionUnavailable('VISION_PAYMENT_INVALID')
        box = [round(float(x),5) for x in box] if box is not None else None
        # OCR amounts/merchant names can be corrected; source position identifies a slip.
        rid = hashlib.sha256(json.dumps([image_hash,i,box],separators=(',',':')).encode()).hexdigest()[:24]
        rows.append({'id':rid,'box':box,'merchant':merchant,'date':date,
                     'amount':amount,'currency':currency,'payment':payment,
                     'category_hint':_string(item['category_hint'],60),
                     'note':_string(item['note'],240),'requires_review':True})
    return {'receipts':rows,'source_sha256':image_hash,'model':MODEL,
            'confirmed':False,'trip_inferred':False}


def _run_bounded(command, *, cwd, env):
    """Run OpenCode with no stdin, and stop its whole process tree at the time limit.

    On Windows the npm command is a shim: killing only the shim leaves the real process holding
    the output pipes, so a plain subprocess.run would wait forever. The tree is stopped instead.
    """
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'] if os.name == 'nt'
                       else ['kill','-9',str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _opencode_executable():
    """The OpenCode command: an explicit path, then PATH, then the npm global install folder only."""
    configured = os.environ.get('WEBLEDGER_OPENCODE_EXE', '').strip()
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which('opencode')
    if found:
        return found
    appdata = os.environ.get('APPDATA')
    if appdata and (Path(appdata)/'npm'/'opencode.cmd').is_file():
        return str(Path(appdata)/'npm'/'opencode.cmd')
    return None


def recognize(image, *, runner=None):
    """No direct model API, no paid fallback, no model-accessible tools."""
    if not enabled():
        raise VisionUnavailable('VISION_DISABLED')
    image = Path(image)
    if not image.is_file() or not 0 < image.stat().st_size <= MAX_BYTES:
        raise VisionUnavailable('VISION_IMAGE_INVALID')
    data = image.read_bytes()
    ext = _image_extension(data)
    executable = _opencode_executable()
    if executable is None:
        raise VisionUnavailable('VISION_OPENCODE_NOT_FOUND')
    with tempfile.TemporaryDirectory(prefix='cost-vision-') as temporary:
        root = Path(temporary)
        attachment = root / ('receipt'+ext)
        attachment.write_bytes(data)
        # 'ask' keeps the tool list the model expects. A tool request is refused automatically:
        # nothing is approved and nothing runs. 'deny' for every tool made the free tier answer 403.
        config = {'$schema':'https://opencode.ai/config.json',
                  'agent':{'receipt-readonly':{'description':'Receipt reading, tools need approval',
                     'mode':'primary','model':MODEL,'prompt':AGENT_INSTRUCTION,'permission':{'*':'ask'}}},
                  'permission':{'*':'ask'}}
        (root/'opencode.json').write_text(json.dumps(config),encoding='utf-8')
        # An isolated configuration directory: the user's global OpenCode config, its MCP servers
        # and its other provider keys are not loaded into this call.
        isolated = root/'config'
        (isolated/'opencode').mkdir(parents=True)
        (isolated/'opencode'/'opencode.json').write_text(json.dumps(config),encoding='utf-8')
        environment = dict(os.environ, XDG_CONFIG_HOME=str(isolated))
        # --file is an array option: it must not sit directly before the prompt, or the prompt
        # is read as a second file. --pure keeps external plugins and MCP servers out of the call.
        command = [executable,'run','--pure','--model',MODEL,'--agent','receipt-readonly',
                   '--title','COST receipt reading (free)',
                   '--format','json',f'--file={attachment}','--',PROMPT]
        try:
            proc = (runner or _run_bounded)(command,cwd=str(root),env=environment)
        except (OSError,subprocess.TimeoutExpired):
            raise VisionUnavailable('VISION_EXECUTION_FAILED') from None
        if proc.returncode:
            raise VisionUnavailable('VISION_PROVIDER_ERROR')
        parsed = parse_events(proc.stdout)
    return validate_response(parsed,image_hash=hashlib.sha256(data).hexdigest(),size=image_size(data))
