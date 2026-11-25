"""A model's completion claim cannot substitute for requested system evidence."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentPolicy
from hub.db import ProviderConfig
from hub.provider_settings import seed
from hub.providers import Providers
from test_agent_capability_runtime import execute, start
from test_agent_native_transport import event, fragment

pytest_plugins = ['test_agent_capability_runtime']
GOAL = 'Welche Updates stehen in Home Assistant aus?'
WRONG = 'Home Assistant hat keine Updates. Alle Add-ons sind auf dem neuesten Stand.'
STATES = [
    {'entity_id': 'update.synthetic_core', 'state': 'on',
     'attributes': {'friendly_name': 'Synthetic Core', 'installed_version': '1',
                    'latest_version': '2'}},
    {'entity_id': 'update.synthetic_addon', 'state': 'off',
     'attributes': {'friendly_name': 'Synthetic Add-on', 'installed_version': '3',
                    'latest_version': '3'}},
]


def test_legacy_model_premature_finish_is_replanned_and_never_echoed(ha, monkeypatch):
    turns, calls = [], []

    async def model(*args):
        data = args[-1]
        turns.append(data)
        assert data['request_contract']['requirements'][0]['domain'] == 'update'
        if len(turns) == 1:
            assert not data['allow_finish'] and not data['goal_evidence']['satisfied']
            return {'kind': 'finish', 'message': WRONG}
        if len(turns) == 2:
            assert any(row['kind'] == 'feedback' for row in data['history'])
            assert not data['goal_evidence']['satisfied']
            return {'kind': 'tool', 'integration_id': ha[4], 'tool': 'http',
                    'arguments': {'method': 'GET', 'path': '/api/states'}, 'message': 'Read'}
        raise AssertionError('Complete update evidence needs no further model request')

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert tool == 'http' and args['method'] == 'GET'
        calls.append(args['path'])
        payload = STATES if args['path'] == '/api/states' else {}
        if args.get('projection') is not None:
            from hub.agent_context import project

            payload = project(payload, args['projection'])
        return {'http_status': 200, 'body': payload}

    monkeypatch.setattr(runtime, 'generate', model)
    monkeypatch.setattr(runtime, 'invoke', invoke)
    result = execute(ha, start(ha, GOAL, research_allowed=False))
    assert result['status'] == 'observed', {
        'status': result['status'], 'summary': result['summary'], 'turn_count': len(turns),
        'proofs': [d.get('goal_evidence') for d in turns],
        'feedback': [s['document'] for s in result['steps'] if s['kind'] == 'feedback'],
        'errors': [s['document'] for s in result['steps'] if s['kind'] == 'error'],
    }
    assert len(turns) == 2 and calls == ['/api/', '/api/states']
    assert 'Synthetic Core' in result['summary'] and '2' in result['summary']
    assert WRONG not in result['summary'] and 'keine Updates' not in result['summary']
    assert not [s for s in result['steps'] if s['kind'] in {'effect', 'input', 'approval'}]


def test_native_metadata_is_not_completion_and_websocket_states_ground_the_answer(
    ha, monkeypatch, tmp_path,
):
    app, client, _, cfg, identifier, *_ = ha
    cfg = replace(cfg, local_model='synthetic-evidence-model',
                  local_base_url='http://127.0.0.1:11444/v1', local_allowed_ip='127.0.0.1',
                  source_dir=str(tmp_path / 'synthetic-evidence-inference'))
    with app.state.sessions() as db:
        policy = db.get(AgentPolicy, identifier)
        rules = json.loads(policy.rules)
        rules['ha_websocket_prefixes'] += ['get_states', 'supervisor/api']
        policy.rules = json.dumps(rules)
        seed(db, cfg)
        row = db.get(ProviderConfig, 'local-default')
        row.config = json.dumps({**json.loads(row.config), 'model': cfg.local_model,
                                 'base_url': cfg.local_base_url})
        db.commit()
    requests, calls = [], []
    directives = iter(['config', 'supervisor', 'premature', 'states', 'finish'])
    original = httpx.AsyncClient

    def model(request):
        body = json.loads(request.content)
        requests.append(body)
        if 'response_format' in body:
            intent = RequestIntent(target_ids=[identifier], mode='observe', topic='system',
                requirements=[Requirement(kind='system', integration_id=identifier)])
            return httpx.Response(200, text=event({'content': intent.model_dump_json()})
                                  + 'data: [DONE]\n\n')
        data = json.loads(body['messages'][1]['content'])
        directive = next(directives)
        names = [t['function']['name'] for t in body['tools']]
        if directive != 'finish':
            assert 'finish_run' not in names and not data['allow_finish']
            assert data['goal_evidence']['missing'][0]['domain'] == 'update'
        else:
            assert 'finish_run' in names and data['goal_evidence']['satisfied']
        if directive == 'config':
            name = next(n for n in names if n.endswith('_http_read'))
            args = {'arguments': {'path': '/api/config'}}
        elif directive in {'supervisor', 'states'}:
            name = next(n for n in names if n.endswith('_ha_websocket'))
            args = {'arguments': {'type': 'get_states', 'parameters': {}}}
            if directive == 'supervisor':
                args['arguments'] = {'type': 'supervisor/api',
                                     'parameters': {'method': 'get', 'endpoint': '/info'}}
        else:
            name, args = 'finish_run', {'message': WRONG}
        return httpx.Response(200, text=event(fragment(name, json.dumps(args)))
                              + 'data: [DONE]\n\n')

    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kw: original(**kw, transport=httpx.MockTransport(model)))
    monkeypatch.setattr(Providers, '_target', lambda *_: (
        'http://127.0.0.1/v1/chat/completions', {'Host': 'synthetic-model'}, {}, ''))

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        calls.append((tool, args.get('path') or args.get('type')))
        if tool == 'ha.websocket':
            return {'success': True, 'response': STATES if args['type'] == 'get_states'
                    else {'homeassistant': 'synthetic', 'channel': 'stable',
                          'update_available': False}}
        assert args['method'] == 'GET'
        return {'http_status': 200, 'body': {'version': 'synthetic'}}

    monkeypatch.setattr(runtime, 'invoke', invoke)
    job_id = start(ha, GOAL, research_allowed=False)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, Providers(cfg), job_id))
    result = client.get('/api/agent-runs/' + job_id).json()
    assert result['status'] == 'observed', result
    assert len(requests) == 5 and len(calls) == 4
    assert [c for c in calls if c[0] == 'ha.websocket'] == [
        ('ha.websocket', 'supervisor/api'), ('ha.websocket', 'get_states')]
    assert 'Synthetic Core' in result['summary'] and WRONG not in result['summary']
    assert 'keine Updates' not in result['summary']
    assert not [s for s in result['steps'] if s['kind'] in {'effect', 'input', 'approval'}]


def test_native_entities_alias_omitted_domain_is_narrowed_and_grounded_via_api(
    ha, monkeypatch, tmp_path,
):
    from hub.agent_context import project

    app, client, _, cfg, identifier, *_ = ha
    cfg = replace(cfg, local_model='synthetic-entities-model',
                  local_base_url='http://127.0.0.1:11444/v1', local_allowed_ip='127.0.0.1',
                  source_dir=str(tmp_path / 'synthetic-entities-inference'))
    with app.state.sessions() as db:
        seed(db, cfg)
        row = db.get(ProviderConfig, 'local-default')
        row.config = json.dumps({**json.loads(row.config), 'model': cfg.local_model,
                                 'base_url': cfg.local_base_url})
        db.commit()
    requests, calls = [], []
    original = httpx.AsyncClient

    def model(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert 'response_format' in body
            intent = RequestIntent(target_ids=[identifier], mode='observe', topic='system',
                requirements=[Requirement(kind='system', integration_id=identifier)])
            return httpx.Response(200, text=event({'content': intent.model_dump_json()})
                                  + 'data: [DONE]\n\n')
        assert len(requests) == 2, 'Complete actual state evidence needs no further model'
        names = [t['function']['name'] for t in body['tools']]
        assert names[0].endswith('_ha_entities')
        assert 'finish_run' not in names
        return httpx.Response(200, text=event(fragment(names[0], json.dumps({'arguments': {}})))
                              + 'data: [DONE]\n\n')

    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kw: original(**kw, transport=httpx.MockTransport(model)))
    monkeypatch.setattr(Providers, '_target', lambda *_: (
        'http://127.0.0.1/v1/chat/completions', {'Host': 'synthetic-model'}, {}, ''))

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert tool == 'http' and args['method'] == 'GET'
        calls.append(args)
        if args['path'] == '/api/':
            return {'http_status': 200, 'body': {'message': 'API running'}}
        assert args['path'] == '/api/states'
        assert args['projection'] == {
            'items_path': '', 'where_pointer': '/entity_id', 'where_prefix': 'update.',
            'where_equals': None, 'fields': [], 'limit': 100,
        }
        return {'http_status': 200, 'body': project(STATES, args['projection'])}

    monkeypatch.setattr(runtime, 'invoke', invoke)
    job_id = start(ha, GOAL, research_allowed=False)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, Providers(cfg), job_id))
    result = client.get('/api/agent-runs/' + job_id).json()
    assert result['status'] == 'observed', result
    assert len(requests) == 2
    assert [a['path'] for a in calls] == ['/api/', '/api/states']
    assert 'Synthetic Core' in result['summary'] and '2' in result['summary']
    assert 'keine Updates' not in result['summary']
    assert not [s for s in result['steps'] if s['kind'] in {'effect', 'input', 'approval'}]
    reads = [s for s in result['steps'] if s['kind'] == 'read']
    assert len(reads) == 2 and all(s['status'] == 'succeeded' for s in reads)
    assert reads[-1]['document']['tool'] == 'http'
    assert reads[-1]['document']['integration_id'] == identifier
    assert reads[-1]['document']['arguments'] == calls[-1]


def test_unverified_effect_terminal_never_waives_missing_read_or_another_target():
    effect = SimpleNamespace(kind='effect', status='succeeded',
        document=json.dumps({'integration_id': 'one'}),
        result=json.dumps({'effect_verified': False}))
    post = {'kind': 'effect_postcondition', 'integration_id': 'one'}
    assert runtime.unverified_effect_completion({'missing': [post]}, [effect])
    assert not runtime.unverified_effect_completion({'missing': []}, [effect])
    assert not runtime.unverified_effect_completion({'missing': [post,
        {'kind': 'entity_states', 'integration_id': 'one', 'domain': 'update'}]}, [effect])
    assert not runtime.unverified_effect_completion({'missing': [
        {**post, 'integration_id': 'another'}]}, [effect])
