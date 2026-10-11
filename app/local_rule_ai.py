"""Optional loopback-only interpretation. The model cannot access rows or a database."""
import json
import os
import re
import urllib.request

from app import rule_proposals


class InterpretationPending(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def enabled():
    return os.environ.get('WEBLEDGER_LOCAL_RULE_AI') == '1'


def interpret(text):
    if not enabled() or not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise InterpretationPending()
    if rule_proposals.parse(text)['kind'] == 'REJECTED_ORIGINAL_EDIT':
        raise InterpretationPending()
    schema = {'type': 'object', 'properties': {
        'scope': {'type': 'string', 'enum': ['THIS_ONLY', 'MERCHANT_RULE', 'UNKNOWN']},
        'item': {'type': 'string'}}, 'required': ['scope', 'item'], 'additionalProperties': False}
    payload = {'messages': [
        {'role': 'system', 'content': 'Extract only the requested expense category and scope. '
         'Never change amounts, dates, payment identity or trip assignments. '
         'scope THIS_ONLY means this payment; MERCHANT_RULE means same merchant. '
         'Use UNKNOWN if ambiguous. item must be the requested Korean category without spaces. '
         'Return JSON with scope and item, without commentary.'},
        {'role': 'user', 'content': text}], 'temperature': 0, 'max_tokens': 128,
        'chat_template_kwargs': {'enable_thinking': False},
        'response_format': {'type': 'json_object', 'schema': schema}}
    request = urllib.request.Request('http://127.0.0.1:8088/v1/chat/completions',
                                     data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
    try:
        # Disable inherited proxies as well as redirects. Instructions stay on this PC.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=20) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        result = json.loads(json.loads(raw)['choices'][0]['message']['content'])
        if set(result) != {'scope', 'item'} or result['scope'] not in ('THIS_ONLY', 'MERCHANT_RULE'):
            raise ValueError()
        item = result['item']
        if not isinstance(item, str) or not re.fullmatch(r'[\uac00-\ud7a3]{1,20}', item):
            raise ValueError()
        if item not in re.sub(r'\s+', '', text):
            raise ValueError()
        # The model must not broaden or narrow an explicit user-selected scope.
        repeated = bool(re.search(r'앞으로|(?:같은|동일)\s*가맹점', text))
        only = bool(re.search(r'이번만|이\s*(?:건|거래|결제)만', text))
        if repeated and only:
            raise ValueError()
        prefix = '이 가맹점은 앞으로 ' if repeated else '이 건만 '
        return prefix + item + '로 분류'
    except Exception:
        # No model output, user text, endpoint exception or source data in errors.
        raise InterpretationPending() from None
