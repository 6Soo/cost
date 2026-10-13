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
import threading
import time

MODEL = 'opencode/muse-spark-1.3-contributor-free'
SPACE_BUNNY = 'opencode/space-bunny-free'
INKLING = 'openrouter/thinkingmachines/inkling:free'
MODEL_LABELS = {MODEL: 'Muse', SPACE_BUNNY: 'Space Bunny', INKLING: 'Inkling Free'}
# Waiting time before a model that hit a limit or an outage is tried again, in seconds.
COOLDOWN = {'VISION_RATE_LIMITED': 300, 'VISION_PROVIDER_UNAVAILABLE': 60, 'VISION_EXECUTION_FAILED': 60}
NETWORK_WORDS = ('fetch failed', 'econnreset', 'etimedout', 'econnrefused', 'socket', 'overloaded', 'unavailable', 'timed out')
MAX_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
TIMEOUT_SECONDS = 120
SCHEMA = '{"receipts":[{"merchant":null,"date":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"note":null}]}'
AGENT_INSTRUCTION = ('You read one attached receipt image and answer with JSON only, using exactly this schema and no other keys: '
                     + SCHEMA + '. The image is already in the message. Never call tools, never look for files or instructions.')
LESSON_INSTRUCTION = ('사용자가 지적한 인식 오류를 바탕으로 영수증을 다시 분석하라. 실제로 새로 발견한 영수증이 있다면, '
                      '처음에 놓친 유형을 다음 분석에서 더 잘 확인하기 위한 짧고 일반적인 인식 지침을 "lesson" 필드에 한 문장으로 작성하라. '
                      '실제 이미지와 사용자 피드백으로 뒷받침되지 않는 원인은 추측하지 마라. 날짜, 금액, 상호, 개인정보는 쓰지 마라. '
                      '유용한 지침을 만들 수 없다면 null을 반환하라.')
AGENT_INSTRUCTION_LESSON = AGENT_INSTRUCTION.replace('and no other keys:', 'plus the optional top-level key "lesson", and no other keys:')
PROMPT = f'''Output format: a single JSON object, nothing else. No markdown, no code fence, no explanation.
Schema: {SCHEMA}
The page image is already attached to this message. Do not call any tool; answer from the attached image only.
The page may contain several Japanese/Korean receipts, ferry or boarding tickets, handwriting and stamps,
overlapping or rotated slips. One receipts entry per physical receipt or ticket, even identical-priced tickets.
Write merchant as printed in the original language (Korean, Japanese or English). Do not translate it.
date as YYYY-MM-DD. amount is the paid total as an integer (not subtotal, tax, tendered or change).
currency is JPY or KRW. payment is cash, private_card, corporate_card or null.
Use null for anything unreadable. Never guess a date, amount or payment method.
Do not create entries from advertisements or blank areas. Do not combine tickets.'''


class VisionUnavailable(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


def enabled():
    return os.name == 'nt' and os.environ.get('WEBLEDGER_RECEIPT_VISION') == 'opencode-muse-free'


def _image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff') and data.rstrip().endswith(b'\xff\xd9'):
        return '.jpg'
    raise VisionUnavailable('VISION_IMAGE_REQUIRED')


def _provider_error(event):
    """Names the provider failure. Only a limit, an outage or a network fault may move on to another model."""
    error = event.get('error') if isinstance(event.get('error'), dict) else {}
    data = error.get('data') if isinstance(error.get('data'), dict) else {}
    status = data.get('statusCode')
    message = str(data.get('message') or error.get('name') or '').lower()
    if status in (401, 403):
        # An authorisation or policy refusal is never routed around.
        raise VisionUnavailable('VISION_PROVIDER_ERROR')
    headers = data.get('responseHeaders') if isinstance(data.get('responseHeaders'), dict) else {}
    retry = str(headers.get('retry-after') or '').strip()
    if status == 429 or any(word in message for word in ('rate limit', 'usage limit', 'quota')):
        raise VisionUnavailable('VISION_RATE_LIMITED', int(retry) if retry.isdigit() else None)
    if status in (500, 502, 503, 504) or any(word in message for word in NETWORK_WORDS):
        raise VisionUnavailable('VISION_PROVIDER_UNAVAILABLE')
    raise VisionUnavailable('VISION_PROVIDER_ERROR')


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
                _provider_error(event)
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
        if not isinstance(result, dict) or set(result) - {'lesson'} not in ({'receipts'}, {'documents'}):
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
        return None  # only this field is lost; the rest of the entry is still a candidate
    return value.strip() or None


_DATE_SEPARATED = re.compile(r'^(\d{4})[/.](\d{1,2})[/.](\d{1,2})(?:\s+\d{1,2}:\d{2})?$')
PAYMENT_VALUES = ('cash', 'private_card', 'corporate_card')


TOP_LEVEL_ALIASES = {'documents': 'receipts', 'receipts': 'receipts'}
ITEM_ALIASES = {'merchant': 'merchant', 'store': 'merchant', 'shop': 'merchant',
                'date': 'date', 'datetime': 'date', 'receipt_date': 'date',
                'amount': 'amount', 'total_amount': 'amount', 'total': 'amount',
                'currency': 'currency', 'payment': 'payment', 'payment_method': 'payment',
                'category_hint': 'category_hint', 'note': 'note'}
CANONICAL_ITEM_KEYS = ('merchant', 'date', 'amount', 'currency', 'payment', 'category_hint', 'note')


def _canonical_item(item):
    """Rename known synonym keys to the schema keys; unknown keys are dropped, values are not changed."""
    renamed = {}
    for key, value in item.items():
        target = ITEM_ALIASES.get(str(key).strip().lower())
        if target is not None and target not in renamed:
            renamed[target] = value
    return {key: renamed.get(key) for key in CANONICAL_ITEM_KEYS}


def _normalized_item(item):
    """Deterministic clean-up of what the model wrote; anything still unclear becomes null, never a guess."""
    item = _canonical_item(item)
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


def _valid_date(value):
    if value is None:
        return None
    try:
        return value if datetime.date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _valid_amount(value):
    if isinstance(value, str) and value.replace(',', '').strip().isdigit():
        value = int(value.replace(',', '').strip())
    if type(value) is int and 0 < value <= 1_000_000_000:
        return value
    return None


def validate_response(result, *, image_hash, model=MODEL, lesson=False):
    """Each entry stands alone: a field that is not clear becomes null on that entry, the other entries are kept."""
    if 'receipts' not in result and 'documents' in result:
        result = dict(result, receipts=result['documents'])
    receipts = result.get('receipts')
    if not isinstance(receipts, list) or len(receipts) > 50:
        raise VisionUnavailable('VISION_RESPONSE_INVALID')
    rows = []
    seen = {}
    for item in receipts:
        if not isinstance(item, dict):
            continue
        item = _normalized_item(item)
        merchant = _string(item['merchant'])
        date = _valid_date(_string(item['date'], 10))
        amount = _valid_amount(item['amount'])
        # An entry with no merchant, date or amount is not a reading; it is dropped, never shown as a candidate.
        if merchant is None and date is None and amount is None:
            continue
        currency = item['currency'] if item['currency'] in ('JPY', 'KRW') else None
        payment = item['payment'] if item['payment'] in PAYMENT_VALUES else None
        content = json.dumps([merchant, date, amount, currency, payment], ensure_ascii=False)
        # Identical tickets stay separate: the k-th copy of one reading gets its own id; list order does not matter.
        occurrence = seen.get(content, 0)
        seen[content] = occurrence + 1
        rid = hashlib.sha256(json.dumps([image_hash, content, occurrence]).encode()).hexdigest()[:24]
        rows.append({'id': rid, 'merchant': merchant, 'date': date, 'amount': amount,
                     'currency': currency, 'payment': payment,
                     'category_hint': _string(item['category_hint'], 60),
                     'note': _string(item['note'], 240), 'requires_review': True})
    out = {'receipts': rows, 'source_sha256': image_hash, 'model': model,
           'confirmed': False, 'trip_inferred': False}
    if lesson:
        # A lesson is optional and never decides whether the receipts are valid.
        text = result.get('lesson')
        out['lesson'] = text.strip()[:200] if isinstance(text, str) and text.strip() else None
    return out


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


def recognize(image, *, runner=None, guidance=None, model=MODEL, lesson=False):
    """No direct model API, no paid fallback, no model-accessible tools. guidance is plain text added to the prompt."""
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
                     'mode':'primary','model':model,'prompt':AGENT_INSTRUCTION_LESSON if lesson else AGENT_INSTRUCTION,'permission':{'*':'ask'}}},
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
        command = [executable,'run','--pure','--model',model,'--agent','receipt-readonly',
                   '--title','COST receipt reading (free)',
                   '--format','json',f'--file={attachment}','--',_prompt(guidance, lesson)]
        try:
            proc = (runner or _run_bounded)(command,cwd=str(root),env=environment)
        except (OSError,subprocess.TimeoutExpired):
            raise VisionUnavailable('VISION_EXECUTION_FAILED') from None
        if proc.returncode:
            parse_events(proc.stdout)  # raises the named provider error when the output carries one
            raise VisionUnavailable('VISION_PROVIDER_UNAVAILABLE')
        parsed = parse_events(proc.stdout)
    return validate_response(parsed, image_hash=hashlib.sha256(data).hexdigest(), model=model, lesson=lesson)


def _prompt(guidance, lesson):
    parts = [PROMPT]
    if lesson:
        parts.append(LESSON_INSTRUCTION)
    if guidance:
        parts.append(guidance)
    return '\n'.join(parts)


_COOLING = {}
_COOL_LOCK = threading.Lock()


def inkling_enabled() -> bool:
    """Inkling sends the photo to OpenRouter. It is used only after the owner approves that and OpenRouter is connected."""
    if os.environ.get('WEBLEDGER_RECEIPT_INKLING') != 'approved':
        return False
    if os.environ.get('OPENROUTER_API_KEY'):
        return True
    try:
        auth = json.loads((Path.home() / '.local' / 'share' / 'opencode' / 'auth.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(auth, dict) and 'openrouter' in auth


def chain():
    models = [MODEL, SPACE_BUNNY]
    if inkling_enabled():
        models.append(INKLING)
    return models


def _cooling(model, now):
    with _COOL_LOCK:
        return _COOLING.get(model, 0) > now


def _cool(model, code, retry_after, now):
    seconds = COOLDOWN[code]
    if code == 'VISION_RATE_LIMITED' and retry_after:
        seconds = min(max(int(retry_after), 30), 1800)
    with _COOL_LOCK:
        _COOLING[model] = now + seconds


def recognize_with_fallback(image, *, runner=None, guidance=None, clock=time.monotonic, lesson=False):
    """Muse first; a limit or outage moves to the next free model, once per model per request.
    A normal answer, even an empty one, ends the chain. Anything else is refused, not routed around."""
    attempts = []
    for model in chain():
        now = clock()
        if _cooling(model, now):
            attempts.append({'model': model, 'result': 'COOLING'})
            continue
        try:
            result = recognize(image, runner=runner, guidance=guidance, model=model, lesson=lesson)
        except VisionUnavailable as error:
            if error.code not in COOLDOWN:
                raise
            _cool(model, error.code, error.retry_after, clock())
            attempts.append({'model': model, 'result': error.code})
            continue
        attempts.append({'model': model, 'result': 'OK'})
        result['label'] = MODEL_LABELS.get(model, model)
        result['attempts'] = attempts
        return result
    raise VisionUnavailable('VISION_ALL_MODELS_UNAVAILABLE')
