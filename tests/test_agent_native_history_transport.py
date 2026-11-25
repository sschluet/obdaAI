"""Native historical calls/results are real messages and fully permissioned input."""
import asyncio
import hashlib
import json
from copy import deepcopy

import httpx
import pytest
from hub import agent_native
from hub.agent_native import NativeCallError
from hub.policy import ContextPart
from test_agent_native import http_binding, prepared
from test_agent_native_transport import adapter, event, execution_fixture, fragment

pytest_plugins = ['test_agent_capability_runtime']


def history(identifier='one'):
    return [{
        'sequence': 1, 'kind': 'read', 'status': 'succeeded',
        'document': {'tool': 'http', 'integration_id': identifier,
                     'arguments': {'method': 'GET', 'path': '/api/one/config'}},
        'result': {'http_status': 200, 'effect_verified': False,
                   'body': {'version': 'SYNTHETIC_PRIVATE_VERSION', 'safe_mode': False,
                            'zero': 0, 'optional': None}},
    }]


def value():
    source = prepared(history=history())
    return agent_native.with_history(source, source.data)[0]


def rehash(metadata):
    metadata['messages_sha256'] = hashlib.sha256(json.dumps(
        metadata['messages'], ensure_ascii=False, separators=(',', ':'), sort_keys=True,
    ).encode()).hexdigest()


def stream(provider):
    async def run():
        return [piece async for piece in provider.stream([
            ContextPart(content='Synthetic system policy', source_id='policy', revision=1),
            ContextPart(content='Synthetic current state', source_id='state', revision=1),
        ], ['system', 'user'], external=False, grants=[])]
    return asyncio.run(run())


def history_adapter(monkeypatch, tmp_path):
    response = httpx.Response(200, text=event(fragment(
        'finish_run', '{"message":"Synthetic observed version retained."}')) + 'data: [DONE]\n\n')
    provider, _, requests = adapter(monkeypatch, tmp_path, response)
    source = value()
    provider.local_native_plan = source.metadata
    return provider, source, requests


def test_actual_http_messages_have_ordered_call_result_pairs_with_matching_ids_and_full_aux_egress(
    monkeypatch, tmp_path,
):
    provider, source, requests = history_adapter(monkeypatch, tmp_path)
    original = deepcopy(source.metadata)
    checked = []
    from hub import providers
    real_check = providers.check_egress

    def check(parts, **kwargs):
        checked.append(deepcopy(parts))
        return real_check(parts, **kwargs)

    monkeypatch.setattr(providers, 'check_egress', check)
    output = stream(provider)
    assert json.loads(output[0])['kind'] == 'finish'
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    messages = body['messages']
    assert [message['role'] for message in messages] == ['system', 'user', 'assistant', 'tool']
    assert messages[0]['content'] == 'Synthetic system policy'
    assert messages[1]['content'] == 'Synthetic current state'
    call = messages[2]['tool_calls'][0]
    assert call['function']['name'] == http_binding(source)
    assert messages[3]['tool_call_id'] == call['id']
    assert 'SYNTHETIC_PRIVATE_VERSION' in messages[3]['content']
    assert body['tools'] == source.metadata['tools']
    assert len(checked) >= 2  # Both before capacity and immediately before POST.
    for parts in checked:
        assert len(parts) == 4
        assert all(str(part.label) == 'LOCAL_ONLY' for part in parts)
        assert json.loads(parts[2].content) == body['tools']
        assert json.loads(parts[3].content) == messages[2:]
    assert source.metadata == original


def test_native_history_is_deepcopied_and_does_not_change_schema_binding_hash():
    source = value()
    messages = agent_native.native_messages(source.metadata)
    assert source.metadata['sha256'] == prepared().metadata['sha256']
    messages[1]['content'] = 'Changed external copy'
    assert agent_native.native_messages(source.metadata)[1]['content'] != 'Changed external copy'
    parts = agent_native.auxiliary_parts(source.metadata)
    chars, size = agent_native.metadata_size(source.metadata)
    assert len(parts) == 2 and chars == sum(len(part.content) for part in parts)
    assert size == sum(len(part.content.encode()) for part in parts)


@pytest.mark.parametrize('tamper', [
    'hash', 'role', 'pair', 'unknown_name', 'scope', 'missing_result',
])
def test_tampered_or_unbound_history_never_reaches_http(monkeypatch, tmp_path, tamper):
    provider, source, requests = history_adapter(monkeypatch, tmp_path)
    metadata = deepcopy(source.metadata)
    if tamper == 'hash':
        metadata['messages'][1]['content'] = 'SENSITIVE_TAMPER'
    elif tamper == 'role':
        metadata['messages'][0]['role'] = 'system'
    elif tamper == 'pair':
        metadata['messages'][1]['tool_call_id'] = 'SENSITIVE_WRONG_PAIR'
    elif tamper == 'unknown_name':
        metadata['messages'][0]['tool_calls'][0]['function']['name'] = 'SENSITIVE_UNKNOWN'
    elif tamper == 'scope':
        metadata['messages'][0]['tool_calls'][0]['function']['arguments'] = json.dumps({
            'arguments': {'method': 'GET', 'path': '/not-authorized'},
        })
    else:
        metadata['messages'].pop()
    if tamper != 'hash':
        rehash(metadata)
    provider.local_native_plan = metadata
    with pytest.raises(NativeCallError) as caught:
        stream(provider)
    assert 'SENSITIVE_' not in str(caught.value)
    assert not requests


def test_history_is_revalidated_after_capacity_wait_before_any_http(monkeypatch, tmp_path):
    provider, _, requests = history_adapter(monkeypatch, tmp_path)
    real_messages = agent_native.native_messages
    after_wait = False
    calls = []

    def validate(metadata):
        calls.append(after_wait)
        if after_wait:
            metadata['messages'][1]['content'] = 'SENSITIVE_CHANGED_AFTER_WAIT'
        return real_messages(metadata)

    monkeypatch.setattr(agent_native, 'native_messages', validate)

    async def run():
        nonlocal after_wait
        await provider.local_slot.acquire()
        task = asyncio.create_task(anext(provider.stream([
            ContextPart(content='Synthetic', source_id='state', revision=1),
        ], ['user'], external=False, grants=[])))
        await asyncio.sleep(0)
        assert calls and not any(calls)
        after_wait = True
        provider.local_slot.release()
        with pytest.raises(NativeCallError):
            await task

    asyncio.run(run())
    assert any(calls) and not requests


def inject_history(monkeypatch):
    original = agent_native.prepare

    def prepare(instruction, data):
        document = deepcopy(data)
        target = document['interfaces'][0]['integration_id']
        document['history'] = history(target)
        document['history'][0]['document']['arguments']['path'] = '/api/config'
        source = original(instruction, document)
        return agent_native.with_history(source, source.data)[0]

    monkeypatch.setattr(agent_native, 'prepare', prepare)


def test_execution_counts_both_aux_parts_and_history_bytes_in_effective_output(
    ha, monkeypatch, tmp_path,
):
    inject_history(monkeypatch)
    result, requests, _, _, _ = execution_fixture(ha, monkeypatch, tmp_path)
    assert result.status == 'succeeded', result.error
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert [message['role'] for message in body['messages']] == [
        'system', 'user', 'assistant', 'tool']
    assert body['max_tokens'] == 1500
    trace = json.loads(result.routing_trace)['native_context']
    assert trace['auxiliary_parts'] == 2
    assert trace['auxiliary_utf8_bytes'] == sum(len(json.dumps(
        value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
    ).encode()) for value in (body['tools'], body['messages'][2:]))


@pytest.mark.parametrize('budget', ['chars', 'utf8'])
def test_history_that_exceeds_provider_budget_is_blocked_without_http(
    ha, monkeypatch, tmp_path, budget,
):
    inject_history(monkeypatch)
    from hub import execution
    from hub.db import ProviderConfig, Run
    real_execute = execution.execute_run
    checked = []

    async def run(factory, cfg, provider, run_id):
        with factory() as db:
            current = db.get(Run, run_id)
            snapshot = json.loads(current.context_snapshot)
            base = [ContextPart.model_validate(part) for part in snapshot['parts']]
            auxiliary = agent_native.auxiliary_parts(snapshot['agent_generation']['native_plan'])
            assert len(auxiliary) == 2
            row = db.get(ProviderConfig, 'local-default')
            config = json.loads(row.config)
            if budget == 'chars':
                without_history = sum(len(part.content) for part in [*base, auxiliary[0]])
                config['context_chars'] = without_history + len(auxiliary[1].content) - 1
                assert config['context_chars'] > without_history
            else:
                without_history = sum(len(part.content.encode()) + 64
                                      for part in [*base, auxiliary[0]]) + 4096
                config['context_tokens'] = without_history + min(1024, config['output_tokens'])
            checked.append(True)
            row.config = json.dumps(config)
            db.commit()
        await real_execute(factory, cfg, provider, run_id)

    monkeypatch.setattr(execution, 'execute_run', run)
    result, requests, _, _, _ = execution_fixture(ha, monkeypatch, tmp_path)
    assert checked and result.status == 'failed' and not requests
    assert 'Kontext' in result.error


def test_history_keeps_provider_revocation_check_after_real_queue_wait(ha, monkeypatch, tmp_path):
    inject_history(monkeypatch)
    result, requests, _, _, _ = execution_fixture(
        ha, monkeypatch, tmp_path, revoke_after_wait='revision')
    assert result.status == 'failed' and not requests
