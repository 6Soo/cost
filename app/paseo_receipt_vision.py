"""Receipt reading through local Paseo with Qwen4 Max Preview (a text-only model).

qwen4-max-preview does not accept image input, so the photo is first read by local
Windows OCR (no network, no external image transmission) and the model structures the
OCR text into review candidates. Only untrusted suggestions are returned; nothing here
writes a ledger. The caller keeps the owner/CSRF/image-ownership checks and the manual
input path, exactly as for the Claude reader. The reading rules live in the playbook's
ocr-reading-prompt section; the output contract is receipt_vision.validate_response.

The run uses `paseo run --output-schema`, whose stdout is the schema-shaped JSON result
itself. That is the answer source: the daemon's `logs --json` timeline rendering is not
reliable across versions, so it is deliberately not used.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from . import receipt_vision
from .connected_agent_provider import AgentUnavailable, _run_bounded

PROVIDER_MODEL = 'qwen-code/qwen4-max-preview(openai)'
MODEL_LABEL = 'Qwen4 Max Preview'
ENGINE = 'paseo'
# Agent startup plus a reading; the CLI wait stops just before this hard limit.
TIMEOUT_SECONDS = 240
OCR_TIMEOUT_SECONDS = 60
OCR_LANGUAGES = ('ja', 'ko')
OCR_SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'windows_receipt_ocr.ps1'
VisionUnavailable = receipt_vision.VisionUnavailable
# OCR is the model's only view of the photo: if it fails there is nothing to fall back to.
NO_FALLBACK = receipt_vision.NO_FALLBACK | {'VISION_OCR_UNAVAILABLE'}
log = logging.getLogger('cost.paseo_receipt_vision')


def enabled():
    return os.name == 'nt' and os.environ.get('WEBLEDGER_RECEIPT_VISION') == 'paseo-qwen4-max'


def _environment():
    # Run as an independent top-level agent: drop any caller Paseo context so the reading is
    # never merged into the caller's workspace/timeline, and behaves the same outside a Paseo host.
    return {key: value for key, value in os.environ.items()
            if key not in ('PASEO_AGENT_ID', 'PASEO_WORKSPACE_ID', 'PASEO_AGENT_CWD')}


def _ocr_readings(image):
    """Read the one approved photo with the local Windows OCR engine, per language.

    A language whose engine is missing or fails is skipped, not fatal. The photo never
    leaves this machine here; only the resulting text is handed to the model.
    """
    readings = {}
    for language in OCR_LANGUAGES:
        try:
            proc = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(OCR_SCRIPT),
                 '-ImagePath', str(image.resolve()), '-Language', language],
                capture_output=True, timeout=OCR_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode or len(proc.stdout) > 256 * 1024:
            continue
        try:
            result = json.loads(proc.stdout.decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            continue
        text = result.get('text')
        if isinstance(text, str) and text.strip():
            readings[language] = text.strip()
    if not readings:
        raise VisionUnavailable('VISION_OCR_UNAVAILABLE')
    return readings


def _paseo_command():
    """node + the Paseo CLI entry, so a multi-line prompt is never re-parsed by a .cmd shim."""
    node = os.environ.get('WEBLEDGER_NODE_EXE', '').strip() or shutil.which('node')
    if not node:
        return None
    cli = os.environ.get('WEBLEDGER_PASEO_CLI', '').strip()
    if not cli:
        appdata = os.environ.get('APPDATA')
        if appdata:
            candidate = Path(appdata) / 'npm' / 'node_modules' / '@getpaseo' / 'cli' / 'bin' / 'paseo'
            if candidate.is_file():
                cli = str(candidate)
    if cli and Path(cli).is_file():
        return [node, '--disable-warning=DEP0040', cli]
    return None


def _schema_text():
    return json.dumps(json.loads(receipt_vision.SCHEMA_PATH.read_text(encoding='utf-8')), separators=(',', ':'))


def _prompt(readings, guidance, lesson, schema):
    parts = [receipt_vision.playbook_prompt(start='ocr-reading-prompt:start', end='ocr-reading-prompt:end')]
    parts.append('Schema: ' + schema)
    if lesson:
        parts.append(receipt_vision.LESSON_INSTRUCTION)
    if guidance:
        parts.append(guidance)
    for language, text in readings.items():
        label = 'Japanese' if language == 'ja' else 'Korean'
        parts.append(f'OCR reading ({label} engine):\n{text}')
    return '\n\n'.join(parts)


def _raise_run_error(proc):
    text = ((proc.stdout or b'') + (proc.stderr or b'')).decode('utf-8', errors='replace')
    raise VisionUnavailable(receipt_vision._classify(text))


def _stderr_workspace(proc):
    match = re.search(r'Created workspace (wks_[0-9A-Za-z]+)',
                      (proc.stderr or b'').decode('utf-8', errors='replace'))
    return match.group(1) if match else None


def _cleanup(run, command, workspace_id, *, cwd, env):
    """Best-effort: archiving the one-shot workspace also archives its agent. Never fatal."""
    if not workspace_id:
        return
    try:
        run(command + ['workspace', 'archive', workspace_id], cwd=cwd, env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired, AgentUnavailable):
        pass


def _parse_answer(answer):
    answer = answer.strip()
    if answer.startswith('```'):
        answer = re.sub(r'^```(?:json)?\s*', '', answer, flags=re.I)
        answer = re.sub(r'\s*```$', '', answer).strip()
    match = re.search(r'\{.*\}', answer, flags=re.S)
    if match:
        answer = match.group(0)
    try:
        result = json.loads(answer)
    except (ValueError, UnicodeError):
        raise VisionUnavailable('VISION_RESPONSE_INVALID') from None
    if not isinstance(result, dict) or 'receipts' not in result:
        raise VisionUnavailable('VISION_RESPONSE_INVALID')
    return result


def recognize(image, *, runner=None, guidance=None, lesson=False, ocr=None):
    """No image leaves the machine; the model reads local OCR text only and returns candidates."""
    if not enabled():
        raise VisionUnavailable('VISION_DISABLED')
    image = Path(image)
    if not image.is_file() or not 0 < image.stat().st_size <= receipt_vision.MAX_BYTES:
        raise VisionUnavailable('VISION_IMAGE_INVALID')
    data = image.read_bytes()
    receipt_vision._media_type(data)
    image_hash = hashlib.sha256(data).hexdigest()
    readings = (ocr or _ocr_readings)(image)
    schema = _schema_text()
    prompt = _prompt(readings, guidance, lesson, schema)
    command = _paseo_command()
    if command is None:
        raise VisionUnavailable('VISION_PASEO_NOT_FOUND')
    run = runner or _run_bounded
    env = _environment()
    # ignore_cleanup_errors: the daemon can still hold the empty cwd briefly after archiving.
    with tempfile.TemporaryDirectory(prefix='cost-paseo-vision-', ignore_cleanup_errors=True) as tmp:
        run_command = command + ['run',
                                 '--provider', PROVIDER_MODEL,
                                 '--mode', 'plan',
                                 '--new-workspace', 'local',
                                 '--title', 'COST receipt reading',
                                 '--output-schema', schema,
                                 '--json',
                                 '--wait-timeout', f'{TIMEOUT_SECONDS - 20}s',
                                 '--cwd', tmp,
                                 '--', prompt]
        try:
            proc = run(run_command, cwd=tmp, env=env, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise VisionUnavailable('VISION_TIMEOUT') from None
        except AgentUnavailable as error:
            raise VisionUnavailable('VISION_RESPONSE_TOO_LARGE' if error.code == 'AGENT_RESPONSE_TOO_LARGE'
                                    else 'VISION_EXECUTION_FAILED') from None
        except OSError:
            raise VisionUnavailable('VISION_EXECUTION_FAILED') from None
        workspace_id = _stderr_workspace(proc)
        try:
            if proc.returncode:
                _raise_run_error(proc)
            answer = proc.stdout.decode('utf-8-sig')
        finally:
            _cleanup(run, command, workspace_id, cwd=tmp, env=env)
    parsed = _parse_answer(answer)
    result = receipt_vision.validate_response(parsed, image_hash=image_hash, model=PROVIDER_MODEL, lesson=lesson)
    result['engine'] = ENGINE
    result['label'] = MODEL_LABEL
    return result


def recognize_with_fallback(image, *, runner=None, guidance=None, lesson=False, ocr=None, fallback_ocr=None):
    """Paseo first; a model failure, limit or timeout falls back to Windows OCR once, with the reason kept."""
    run_id = uuid.uuid4().hex[:12]
    try:
        result = recognize(image, runner=runner, guidance=guidance, lesson=lesson, ocr=ocr)
    except VisionUnavailable as error:
        if error.code in NO_FALLBACK:
            raise
        log.warning('receipt reading %s: paseo failed with %s, using Windows OCR', run_id, error.code)
        result = receipt_vision.ocr_fallback(image, error.code, ocr=fallback_ocr)
        result['attempts'] = [{'model': PROVIDER_MODEL, 'result': error.code}, {'model': 'windows-ocr', 'result': 'OK'}]
        return result
    result['attempts'] = [{'model': PROVIDER_MODEL, 'result': 'OK'}]
    return result
