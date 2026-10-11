import io
import json
from unittest.mock import patch

import pytest

from app import local_rule_ai as ai


def test_model_cannot_return_original_mutations_or_ambiguous_scope():
    for output in ({'scope': 'UNKNOWN', 'item': '식비'}, {'scope': 'THIS_ONLY', 'item': '식비', 'amount': 1},
                   {'scope': 'THIS_ONLY', 'item': '<script>'}):
        response = io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(output)}}]}).encode())
        with patch.dict(ai.os.environ, {'WEBLEDGER_LOCAL_RULE_AI': '1'}), \
                patch.object(ai.urllib.request.OpenerDirector, 'open', return_value=response), \
                pytest.raises(ai.InterpretationPending):
            ai.interpret('합성 요청')


def test_interpretation_produces_only_reviewable_deterministic_instruction():
    # Even when the model gets scope wrong, explicit same-merchant scope wins.
    output = {'scope': 'THIS_ONLY', 'item': '현지잡비'}
    response = io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(output)}}]}).encode())
    with patch.dict(ai.os.environ, {'WEBLEDGER_LOCAL_RULE_AI': '1'}), \
            patch.object(ai.urllib.request.OpenerDirector, 'open', return_value=response) as call:
        canonical = ai.interpret('이 편의점 결제는 식비가 아니라 현지잡비야. 앞으로 같은 가맹점은 그렇게 분류해 줘.')
    assert canonical == '이 가맹점은 앞으로 현지잡비로 분류'
    assert call.call_args.args[0].full_url == 'http://127.0.0.1:8088/v1/chat/completions'
    assert ai.rule_proposals.parse(canonical)['kind'] == 'MERCHANT_RULE'


def test_source_edit_never_reaches_model():
    with patch.dict(ai.os.environ, {'WEBLEDGER_LOCAL_RULE_AI': '1'}), \
            patch.object(ai.urllib.request, 'build_opener') as opener, pytest.raises(ai.InterpretationPending):
        ai.interpret('금액을 변경해 줘')
    opener.assert_not_called()
