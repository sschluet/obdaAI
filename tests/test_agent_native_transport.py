"""Actual local adapter SSE protocol, with synthetic transport and real native codec."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from hub.agent_native import NativeProtocolUnavailable
from hub.config import Settings
from hub.policy import ContextPart
from hub.providers import AnswerLimitReached, Providers
from test_agent_native import http_binding, prepared

pytest_plugins = ["test_agent_capability_runtime"]


def event(delta=None, finish=None):
    return 'data: ' + json.dumps({
        'choices': [{'delta': delta or {}, 'finish_reason': finish}],
    }) + '\n\n'


def fragment(name='', arguments='', index=0):
    return {'tool_calls': [{'index': index, 'type': 'function',
                            'function': {'name': name, 'arguments': arguments}}]}


def adapter(monkeypatch, tmp_path, response):
    requests = []
    original = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(Providers, '_target',
                        lambda *args: ('http://127.0.0.1/v1/chat/completions',
                                       {'Host': 'synthetic.local'}, {}, 'synthetic-key'))
    provider = Providers(Settings(local_model='synthetic-model', source_dir=str(tmp_path),
                                  local_max_tokens=777, local_disable_thinking=True))
    value = prepared()
    provider.local_native_plan = value.metadata
    return provider, value, requests


def collect(provider, *, external=False):
    async def run():
        return [value async for value in provider.stream(
            [ContextPart(content='Synthetic private context', source_id='synthetic', revision=1)],
            ['user'], external=external, grants=[])]
    return asyncio.run(run())


def test_split_function_arguments_yield_one_valid_canonical_decision_and_respect_settings(
    monkeypatch, tmp_path,
):
    value = prepared()
    name = http_binding(value)
    lines = event({'content': 'Untrusted natural prose ignored.'})
    lines += event(fragment(name[:5], '{"parameters":{"method":"GET",'))
    lines += event(fragment(name[5:], '"path":"/api/one/states"}}'))
    lines += event({}, 'tool_calls') + 'data: [DONE]\n\n'
    provider, _, requests = adapter(monkeypatch, tmp_path, httpx.Response(200, text=lines))
    output = collect(provider)
    assert len(output) == 1
    decision = json.loads(output[0])
    assert decision['tool'] == 'http' and decision['integration_id'] == 'one'
    assert decision['arguments'] == {'method': 'GET', 'path': '/api/one/states'}
    body = json.loads(requests[0].content)
    assert body['tools'] == provider.local_native_plan['tools'] and body['tool_choice'] == 'auto'
    assert 'response_format' not in body and 'temperature' not in body
    assert body['model'] == 'synthetic-model' and body['max_tokens'] == 777
    assert body['enable_thinking'] is False
    assert requests[0].headers['Authorization'] == 'Bearer synthetic-key'


@pytest.mark.parametrize('natural', ['', 'Please confirm all updates before execution.'])
def test_complete_stream_without_native_call_is_not_a_natural_language_answer(
    monkeypatch, tmp_path, natural,
):
    provider, _, requests = adapter(monkeypatch, tmp_path, httpx.Response(
        200, text=event({'content': natural}) + event() + 'data: [DONE]\n\n'))
    assert json.loads(collect(provider)[0]) == {'_native_error': 'native_no_selection'}
    assert len(requests) == 1


@pytest.mark.parametrize('mode', ['unknown', 'multiple', 'invalid_json', 'bad_schema', 'empty',
                                  'oversized', 'bad_index'])
def test_invalid_calls_produce_only_safe_protocol_marker(monkeypatch, tmp_path, mode):
    name = http_binding(prepared())
    name = 'SENSITIVE_UNKNOWN_NAME' if mode == 'unknown' else name
    arguments = '{"method":"GET","path":"/api/one/states"}'
    if mode == 'invalid_json':
        arguments = 'SENSITIVE_INVALID_JSON'
    if mode == 'bad_schema':
        arguments = '{"method":"GET","path":"/api/two/private"}'
    if mode == 'oversized':
        arguments = 'SENSITIVE_' * 30000
    lines = event(fragment(name, arguments, index=9 if mode == 'bad_index' else 0))
    if mode == 'multiple':
        lines += event(fragment(name, arguments, index=1))
    if mode == 'empty':
        lines = event({'tool_calls': [{'index': 0, 'function': {}}]})
    provider, _, _ = adapter(monkeypatch, tmp_path, httpx.Response(
        200, text=lines + 'data: [DONE]\n\n'))
    output = collect(provider)
    marker = json.loads(output[0])
    assert marker['_native_error'] == 'native_invalid_arguments'
    assert 'SENSITIVE_' not in output[0] and '/api/two/private' not in output[0]


@pytest.mark.parametrize('status,error,unsupported', [
    (400, {'code': 'unsupported_parameter', 'param': 'tools'}, True),
    (422, {'message': "Unexpected keyword argument 'tool_choice'"}, True),
    (400, {'message': 'tools are not supported'}, True),
    (401, {'code': 'unsupported_parameter', 'param': 'tools'}, False),
    (403, {'message': 'tools are not supported'}, False),
    (400, {'message': 'tools schema contains unsupported property'}, False),
    (422, {'code': 'invalid_json_schema', 'param': 'tools'}, False),
    (500, {'message': 'tools are not supported'}, False),
])
def test_only_explicit_unsupported_protocol_errors_allow_outer_compatibility(
    monkeypatch, tmp_path, status, error, unsupported,
):
    provider, _, requests = adapter(monkeypatch, tmp_path, httpx.Response(
        status, json={'error': error}))
    with pytest.raises(NativeProtocolUnavailable if unsupported else httpx.HTTPStatusError):
        collect(provider)
    assert len(requests) == 1


@pytest.mark.parametrize('mode', ['timeout', 'partial', 'filter', 'length'])
def test_transport_or_partial_stream_errors_never_become_fallback_markers(
    monkeypatch, tmp_path, mode,
):
    lines = event(fragment(http_binding(prepared()), '{'))
    expected = ValueError
    response = httpx.Response(200, text=lines)
    if mode == 'timeout':
        response = httpx.ReadTimeout('SENSITIVE_TIMEOUT')
        expected = httpx.ReadTimeout
    elif mode == 'filter':
        response = httpx.Response(200, text=event({}, 'content_filter') + 'data: [DONE]\n\n')
        from hub.budgets import ExecutionLimitError
        expected = ExecutionLimitError
    elif mode == 'length':
        response = httpx.Response(200, text=lines + event({}, 'length') + 'data: [DONE]\n\n')
        expected = AnswerLimitReached
    provider, _, requests = adapter(monkeypatch, tmp_path, response)
    with pytest.raises(expected):
        collect(provider)
    assert len(requests) == 1


def test_native_cannot_escape_local_or_mix_with_legacy_schema(monkeypatch, tmp_path):
    provider, _, requests = adapter(monkeypatch, tmp_path, httpx.Response(200))
    with pytest.raises(PermissionError):
        collect(provider, external=True)
    provider.local_json_schema = {'type': 'object'}
    with pytest.raises(PermissionError):
        collect(provider)
    assert not requests


def test_auxiliary_schema_privacy_is_checked_and_revocation_after_slot_blocks_http(
    monkeypatch, tmp_path,
):
    provider, _, requests = adapter(monkeypatch, tmp_path, httpx.Response(200))
    provider.settings = replace(provider.settings, local_allowed_labels=('CLOUD_ALLOWED',))
    async def shared_input():
        return [value async for value in provider.stream([
            ContextPart(content='Synthetic shared input', label='CLOUD_ALLOWED',
                        source_id='synthetic', revision=1),
        ], ['user'], external=False, grants=[])]

    with pytest.raises(PermissionError):
        asyncio.run(shared_input())
    assert not requests
    provider.settings = replace(provider.settings, local_allowed_labels=('LOCAL_ONLY',))
    revoked = False

    def boundary():
        if revoked:
            raise PermissionError('Synthetic revoked')

    provider.before_send = boundary

    async def run():
        nonlocal revoked
        await provider.local_slot.acquire()
        task = asyncio.create_task(anext(provider.stream(
            [ContextPart(content='Synthetic', source_id='synthetic', revision=1)],
            ['user'], external=False, grants=[])))
        await asyncio.sleep(0)
        revoked = True
        provider.local_slot.release()
        with pytest.raises(PermissionError):
            await task
    asyncio.run(run())
    assert not requests


class DelayedFragments(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield event(fragment(http_binding(prepared()))).encode()
        await asyncio.sleep(5.05)
        yield event(fragment(arguments='{"method":"GET","path":"/api/one/states"}')).encode()
        yield b'data: [DONE]\n\n'


def test_native_fragment_starts_idle_deadline_without_waiting_for_natural_text(
    monkeypatch, tmp_path,
):
    provider, _, _ = adapter(monkeypatch, tmp_path, httpx.Response(200, stream=DelayedFragments()))
    provider.settings = replace(
        provider.settings, local_first_token_timeout=5, local_timeout=7,
    )
    assert json.loads(collect(provider)[0])['tool'] == 'http'


def execution_fixture(ha, monkeypatch, tmp_path, *, chars=None, tokens=None, output_tokens=4096,
                      unsupported=False, binding_change=None, revoke_after_wait=None,
                      native_mode=True):
    from hub.action_api import encode
    from hub.agent_instructions import instruction
    from hub.agent_models import AgentJob
    from hub.agent_native import auxiliary_parts, prepare
    from hub.agent_runtime import gate
    from hub.db import ProviderConfig, Run
    from hub.execution import execute_run
    from hub.provider_settings import seed
    from test_agent_capability_runtime import start

    app, client, headers, cfg, identifier, *_ = ha
    cfg = replace(cfg, local_model='synthetic-model',
                  local_base_url='http://127.0.0.1:11444/v1', local_allowed_ip='127.0.0.1',
                  source_dir=str(tmp_path / 'isolated-execution'))
    job_id = start(ha, 'Prüfe Home Assistant und installiere Updates', research_allowed=False)
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        profile, rules, _ = gate(db, cfg, job)[identifier]
        native = prepare(instruction({'home_assistant'}), {
            'interfaces': [{'integration_id': identifier, 'kind': profile.kind,
                            'rules': rules.model_dump(), 'read_only': False}],
            'tools': ['http'], 'history': [],
        })
        parts = [ContextPart(content='Synthetic private input 漢字', source_id='agent-policy',
                             revision=1),
                 ContextPart(content='Synthetic agent data', source_id='agent-data', revision=1)]
        all_parts = [*parts, *auxiliary_parts(native.metadata)]
        byte_bound = sum(len(p.content.encode()) + 64 for p in all_parts) + 4096
        seed(db, cfg)
        local = db.get(ProviderConfig, 'local-default')
        config = json.loads(local.config)
        config.update(model='synthetic-model', base_url=cfg.local_base_url,
                      context_chars=chars or 24000,
                      context_tokens=tokens or byte_bound + 1500, output_tokens=output_tokens)
        local.config = json.dumps(config)
        binding = {'id': local.id, 'revision': local.revision, 'model': 'synthetic-model'}
        if binding_change:
            binding.update(binding_change)
        run = Run(conversation_id=job.model_conversation_id, status='queued',
                  context_snapshot=encode({
            'parts': [p.model_dump(mode='json') for p in parts], 'roles': ['system', 'user'],
            'agent_generation': {
                'job_id': job_id, 'provider_binding': binding, 'decision_format': True,
                'integration_ids': [identifier], 'tool_names': ['http'],
                'interfaces': native.original_data['interfaces'],
                **({'native_plan': native.metadata} if native_mode else {}),
            },
            'model_local_only': True, 'model_cloud_only': False, 'web_search_allowed': False,
        }))
        db.add(run)
        db.commit()
        run_id = run.id
    name = next(name for name, value in native.metadata['bindings'].items()
                if value.get('tool') == 'http')
    response = httpx.Response(400, json={
        'error': {'code': 'unsupported_parameter', 'param': 'tools'},
    })
    if not unsupported:
        response = httpx.Response(200, text=event(fragment(
            name, '{"method":"GET","path":"/api/config"}')) + 'data: [DONE]\n\n')
    if not native_mode and not unsupported:
        response = httpx.Response(200, text=event({'content': json.dumps({
            'kind': 'tool', 'integration_id': identifier, 'tool': 'http',
            'arguments': {'method': 'GET', 'path': '/api/config'}, 'message': 'Synthetic read',
        })}) + 'data: [DONE]\n\n')
    _, _, requests = adapter(monkeypatch, tmp_path, response)
    async def execute():
        if not revoke_after_wait:
            await execute_run(app.state.sessions, cfg, Providers(cfg), run_id)
            return
        from hub.inference_capacity import local_capacity

        async with local_capacity(cfg):
            task = asyncio.create_task(execute_run(app.state.sessions, cfg, Providers(cfg), run_id))
            for _ in range(200):
                with app.state.sessions() as db:
                    waiting = db.get(Run, run_id).status == 'streaming'
                if waiting:
                    break
                await asyncio.sleep(0.005)
            assert waiting
            await asyncio.sleep(0.02)
            with app.state.sessions() as db:
                provider = db.get(ProviderConfig, 'local-default')
                if revoke_after_wait == 'delete':
                    db.delete(provider)
                elif revoke_after_wait == 'disable':
                    provider.enabled = False
                else:
                    provider.revision += 1
                db.commit()
        await task

    asyncio.run(execute())
    with app.state.sessions() as db:
        result = db.get(Run, run_id)
        return result, requests, byte_bound, sum(len(p.content) for p in all_parts), binding


def test_execution_native_auxiliary_budget_and_actual_provider_binding_are_recorded(
    ha, monkeypatch, tmp_path,
):
    result, requests, _, _, binding = execution_fixture(ha, monkeypatch, tmp_path)
    assert result.status == 'succeeded', result.error
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body['max_tokens'] == 1500
    assert body['messages'][0]['content'] == 'Synthetic private input 漢字'
    assert json.loads(result.routing_trace)['native_provider'] == binding
    assert result.provider == 'local' and result.model == 'synthetic-model'


@pytest.mark.parametrize('budget', ['chars', 'tokens'])
def test_execution_rejects_auxiliary_schema_that_exceeds_provider_budget_before_http(
    ha, monkeypatch, tmp_path, budget,
):
    kwargs = {'chars': 100} if budget == 'chars' else {'tokens': 5300}
    result, requests, _, _, _ = execution_fixture(ha, monkeypatch, tmp_path, **kwargs)
    assert result.status == 'failed' and not requests
    assert 'Kontext' in result.error


def test_execution_native_unsupported_has_safe_fixed_error_for_orchestrated_fallback(
    ha, monkeypatch, tmp_path,
):
    result, requests, _, _, binding = execution_fixture(
        ha, monkeypatch, tmp_path, unsupported=True)
    assert len(requests) == 1 and result.status == 'failed'
    assert result.error == 'Native tool protocol unavailable'
    assert json.loads(result.routing_trace)['native_provider'] == binding


def test_execution_rejects_legacy_fallback_when_pinned_provider_revision_changed(
    ha, monkeypatch, tmp_path,
):
    result, requests, _, _, _ = execution_fixture(
        ha, monkeypatch, tmp_path, binding_change={'revision': 99}, native_mode=False)
    assert result.status == 'failed' and not requests


@pytest.mark.parametrize('change', ['revision', 'disable', 'delete'])
def test_execution_rechecks_pinned_native_provider_after_actual_capacity_wait(
    ha, monkeypatch, tmp_path, change,
):
    result, requests, _, _, _ = execution_fixture(
        ha, monkeypatch, tmp_path, revoke_after_wait=change)
    assert result.status == 'failed' and not requests
    assert not (result.error or '').startswith('Native tool protocol unavailable')


def test_explicit_legacy_compatibility_uses_pinned_local_provider_and_original_schema(
    ha, monkeypatch, tmp_path,
):
    result, requests, _, _, binding = execution_fixture(
        ha, monkeypatch, tmp_path, native_mode=False)
    assert result.status == 'succeeded', result.error
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert 'tools' not in body and body['response_format']['type'] == 'json_schema'
    assert body['temperature'] == 0
    assert json.loads(result.routing_trace)['native_provider'] == binding


def test_native_request_does_not_disable_thinking_when_provider_has_not_disabled_it(
    monkeypatch, tmp_path,
):
    provider, _, requests = adapter(monkeypatch, tmp_path, httpx.Response(
        200, text='data: [DONE]\n\n'))
    provider.settings = replace(provider.settings, local_disable_thinking=False)
    collect(provider)
    assert 'enable_thinking' not in json.loads(requests[0].content)
