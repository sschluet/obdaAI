"""Native conversation envelopes remain inside the actual model budget."""
from copy import deepcopy

import pytest
from hub.agent_context import AgentContextLimitError
from hub.agent_native import auxiliary_parts, native_messages
from hub.agent_runtime import encode, fit_native_plan
from test_agent_native import prepared


def history(count=3):
    return [
        {'sequence': i, 'kind': 'read', 'status': 'succeeded',
         'document': {'tool': 'http', 'integration_id': 'one',
                      'arguments': {'method': 'GET', 'path': f'/api/one/{i}'}},
         'result': {'http_status': 200,
                    'body': {'version': f'2030.1.{i}', 'note': 'ä' * 3000}}}
        for i in range(1, count + 1)
    ]


def test_fit_counts_native_receipts_without_mutating_originals():
    native = prepared(history=history())
    saved = deepcopy(native)
    result, data = fit_native_plan(native, 22000, 22500)
    assert native == saved
    messages = native_messages(result.metadata)
    assert any(message['role'] == 'tool' for message in messages)
    parts = [result.instruction, encode(data),
             *(part.content for part in auxiliary_parts(result.metadata))]
    assert sum(map(len, parts)) <= 22000
    assert sum(len(part.encode()) for part in parts) + 64 * len(
        auxiliary_parts(result.metadata)) <= 22500
    assert result.original_data == native.original_data
    assert data['goal'] == native.data['goal']
    assert data['interfaces'] == native.data['interfaces']


def test_native_history_must_not_clip_mandatory_policy_to_fit():
    native = prepared(history=history())
    with pytest.raises(AgentContextLimitError):
        fit_native_plan(native, 200, 200)
