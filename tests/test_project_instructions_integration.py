import json
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log
from personal_agent.project_instructions import LoadError
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl

def bodies(calls):
    return [json.loads(call['request'].data) for call in calls]


def test_startup_failure_precedes_session_and_every_provider_call(route_env, install_fake_urlopen, tmp_path):
    (tmp_path / 'AGENTS.md').write_text('@missing')
    calls = install_fake_urlopen('unexpected')
    with pytest.raises(LoadError, match='missing'):
        run_repl(runtime_config.load(), input_stream=StringIO('task\n'), output_stream=StringIO(),
                 workspace_root=tmp_path)
    assert calls == []
    assert list(tmp_path.glob('pa_log-*')) == []


@pytest.mark.parametrize('provider', ['openrouter', 'openai', 'anthropic', 'gemini'])
def test_ordinary_prompts_receive_complete_lower_priority_sources_only(route_env, install_fake_urlopen, tmp_path, monkeypatch, provider):
    monkeypatch.setenv('PA_PROVIDER', provider)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider], 'test-key')
    (tmp_path / 'AGENTS.md').write_text('@rules')
    (tmp_path / 'rules').write_text('INSTRUCTION_SENTINEL')
    calls = install_fake_urlopen(['done'])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO('task\nexit\n'), output_stream=output,
             workspace_root=tmp_path)
    [ordinary] = bodies(calls)
    system = (ordinary['system'] if provider == 'anthropic' else ordinary['systemInstruction']['parts'][0]['text']
              if provider == 'gemini' else ordinary['messages'][0]['content'])
    assert '[Project source: rules]\nINSTRUCTION_SENTINEL' in system
    assert 'lower-priority' in system
    assert 'explicit user requests' in system
    assert 'Tool Confirmation' in system and 'Workspace Root' in system
    assert 'AGENTS.md' in output.getvalue() and 'rules' in output.getvalue()
    assert 'INSTRUCTION_SENTINEL' not in output.getvalue()


@pytest.mark.parametrize('resume', [False, True])
def test_reload_failure_keeps_submission_pending_and_repairs_with_retry(route_env, install_fake_urlopen, tmp_path, monkeypatch, resume):
    from personal_agent.__main__ import main
    path = tmp_path / 'AGENTS.md'
    path.write_text('VALID_OLD')
    calls = install_fake_urlopen(['done'])
    output = StringIO()
    def inputs():
        path.write_text('@missing')
        yield 'accepted task\n'
        assert calls == []
        pending = call_log.load_pending_turn(call_log.current_session_id())
        assert pending[0] == 1 and pending[1]['task'] == 'accepted task'
        assert pending[1]['version'] == 1 and pending[1]['messages'] == [{'role': 'user', 'content': 'accepted task'}]
        assert call_log.load_conversation(call_log.current_session_id())[3] == 1
        if not resume:
            path.write_text('REPAIRED_CURRENT')
            yield '/retry\n'
        yield 'exit\n'
    run_repl(runtime_config.load(), input_stream=inputs(), output_stream=output, workspace_root=tmp_path)
    if resume:
        path.write_text('REPAIRED_CURRENT')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr('sys.stdin', StringIO('/retry\nexit\n'))
        main(['--resume', call_log.current_session_id()])
    assert len(calls) == 1
    assert 'REPAIRED_CURRENT' in bodies(calls)[-1]['messages'][0]['content']
    assert 'VALID_OLD' not in bodies(calls)[-1]['messages'][0]['content']
    assert bodies(calls)[0]['messages'][-1] == {'role': 'user', 'content': 'accepted task'}
    assert call_log.load_conversation(call_log.current_session_id())[3] == 1
    assert call_log.load_pending_turn(call_log.current_session_id()) is None
    assert 'Repair the files, then use /retry' in output.getvalue()


def test_snapshot_survives_transient_attempt_tools_and_mode_toggle_then_reloads(route_env, install_fake_urlopen, tmp_path, monkeypatch):
    from urllib.error import HTTPError
    from personal_agent.providers import http
    from personal_agent.routing import router
    from tests.test_continuation import Box, tool
    path = tmp_path / 'AGENTS.md'
    path.write_text('INITIAL_SNAPSHOT')
    calls = install_fake_urlopen([HTTPError('https://example.invalid', 503, 'retry', None, None),
                                 tool('calculator', {'expression': '2+2'}), 'first done', 'next done', 'retry done'])
    original = http.urlopen
    monkeypatch.setattr(router, '_sleep', lambda _: None)
    def tasks():
        yield 'first task'
        yield 'next task'
        path.write_text('RETRY_SNAPSHOT')
        yield '/retry'
        yield 'exit'
    box = Box(tasks())
    def changed(request, timeout=None):
        if not calls:
            path.write_text('NEXT_SNAPSHOT')
            box.on_mode_toggle()
        return original(request, timeout=timeout)
    monkeypatch.setattr(http, 'urlopen', changed)
    run_repl(runtime_config.load(), input_box=box, output_stream=StringIO(), workspace_root=tmp_path)
    assert len(calls) == 5
    systems = [body['messages'][0]['content'] for body in bodies(calls)]
    assert all('INITIAL_SNAPSHOT' in system and 'NEXT_SNAPSHOT' not in system for system in systems[:3])
    assert 'Auto mode' in systems[1] and 'Auto mode' in systems[2]
    assert 'NEXT_SNAPSHOT' in systems[3] and 'INITIAL_SNAPSHOT' not in systems[3]
    assert 'RETRY_SNAPSHOT' in systems[4] and 'NEXT_SNAPSHOT' not in systems[4]


def test_root_precedence_is_reselected_and_local_commands_do_not_reload(route_env, install_fake_urlopen, tmp_path):
    agents = tmp_path / 'AGENTS.md'
    (tmp_path / 'CLAUDE.md').write_text('FALLBACK_CURRENT')
    calls = install_fake_urlopen(['one', 'two', 'three'])
    output = StringIO()
    def tasks():
        yield 'first\n'
        agents.write_text('PREFERRED_CURRENT')
        yield 'second\n'
        agents.write_text('@missing')
        yield '/usage\n'
        yield '/history\n'
        assert len(calls) == 2
        agents.unlink()
        yield '/retry\n'
        yield 'exit\n'
    run_repl(runtime_config.load(), input_stream=tasks(), output_stream=output, workspace_root=tmp_path)
    ordinary = bodies(calls)
    assert 'FALLBACK_CURRENT' in ordinary[0]['messages'][0]['content']
    assert 'PREFERRED_CURRENT' in ordinary[1]['messages'][0]['content']
    assert 'FALLBACK_CURRENT' in ordinary[2]['messages'][0]['content']
    assert 'Project instructions:' in output.getvalue()
    assert 'Repair' not in output.getvalue()


def test_omitted_root_loads_cwd_instructions_and_router_never_loads_files(route_env, install_fake_urlopen, tmp_path):
    from personal_agent.routing.router import route
    from personal_agent.tools import workspace
    (tmp_path / 'AGENTS.md').write_text('CWD_INSTRUCTIONS')
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen(['repl done', 'route done'])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO('task\nexit\n'), output_stream=output)
    assert route('direct', runtime_config.load()).ok
    assert len(calls) == 2
    assert 'CWD_INSTRUCTIONS' in json.dumps(bodies(calls)[0])
    assert 'CWD_INSTRUCTIONS' not in json.dumps(bodies(calls)[1])
    assert 'Project instructions:' in output.getvalue()


@pytest.mark.parametrize('resume', [False, True])
def test_main_passes_configured_root_and_stops_invalid_graph_before_activity(route_env, install_fake_urlopen, tmp_path, monkeypatch, capsys, resume):
    from personal_agent.__main__ import main
    root = tmp_path / 'configured'
    root.mkdir()
    (root / 'CLAUDE.md').write_text('[@"bad\x1b[31m name"]')
    monkeypatch.chdir(root)
    monkeypatch.setattr('sys.stdin', StringIO('task\n'))
    config = runtime_config.load()
    session_id = call_log.start_session(config) if resume else None
    before = Path(call_log.session_log_path(session_id)).read_bytes() if resume else None
    calls = install_fake_urlopen('unexpected')
    with pytest.raises(SystemExit) as caught:
        main(['--resume', session_id] if resume else [])
    assert caught.value.code == 1 and calls == []
    error = capsys.readouterr().err
    assert 'Project instructions error' in error and 'bad' in error
    assert '\x1b' not in error
    if resume:
        assert Path(call_log.session_log_path(session_id)).read_bytes() == before
    else:
        assert list(tmp_path.glob('pa_log-*')) == []


def test_loaded_sources_are_sanitized_without_instruction_bodies(route_env, install_fake_urlopen, tmp_path):
    (tmp_path / 'AGENTS.md').write_text('[@"rules\x1b[31m"]')
    (tmp_path / 'rules\x1b[31m').write_text('PRIVATE_BODY')
    calls = install_fake_urlopen(['done'])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO('task\nexit\n'), output_stream=output, workspace_root=tmp_path)
    assert '\x1b' not in output.getvalue() and 'PRIVATE_BODY' not in output.getvalue()
    assert 'PRIVATE_BODY' in bodies(calls)[-1]['messages'][0]['content']


@pytest.mark.parametrize('provider', ['openrouter', 'gemini'])
@pytest.mark.parametrize('resume', [False, True])
def test_failed_reload_preserves_completed_prefix_todos_fetched_urls_and_exact_replay(
    route_env, install_fake_urlopen, tmp_path, monkeypatch, provider, resume
):
    from dataclasses import replace
    from types import SimpleNamespace
    from personal_agent.tools import registry, workspace
    from tests.fakes import FakeOpenRouterResponse
    from tests.test_continuation import Box
    monkeypatch.setenv('PA_PROVIDER', provider)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider], 'test-key')
    workspace.configure_workspace(tmp_path)
    path = tmp_path / 'AGENTS.md'
    path.write_text('INITIAL_INSTRUCTIONS')
    todos = [{'content': 'preserved todo', 'status': 'in_progress'}]
    tool_calls = [
        {'id': 'todo-once', 'name': 'todo', 'arguments': {'todos': todos}},
        {'id': 'fetch-once', 'name': 'webfetch', 'arguments': {'url': 'https://example.com/page'}},
    ]
    first = {'tool_calls': tool_calls}
    if provider == 'gemini':
        parts = [{'functionCall': {'id': call['id'], 'name': call['name'], 'args': call['arguments']},
                  'thoughtSignature': 'EXACT_SIGNATURE'} for call in tool_calls]
        first = FakeOpenRouterResponse({'candidates': [{'content': {'parts': parts}}]})
    fetch = registry._REGISTRY['webfetch']
    monkeypatch.setitem(registry._REGISTRY, 'webfetch', replace(fetch,
        prepare=lambda args: SimpleNamespace(display_path=args['url'], preview='fetch'),
        apply=lambda _: {'url': 'https://example.com/page', 'content': 'external', 'status': 200}))
    calls = install_fake_urlopen([first, ValueError('follow-up failure'), 'finished'])
    def tasks():
        yield 'work'
        before = call_log.load_pending_turn(call_log.current_session_id())
        assert before[1]['fetched_urls'] == ['https://example.com/page']
        path.write_text('@missing')
        yield '/retry'
        after = call_log.load_pending_turn(call_log.current_session_id())
        assert before == after
        assert len(calls) == 2
        path.write_text('REPAIRED_INSTRUCTIONS')
        if not resume:
            yield '/retry'
        yield 'exit'
    run_repl(runtime_config.load(), input_box=Box(tasks(), ['y']), output_stream=StringIO(), workspace_root=tmp_path)
    if resume:
        resumed = (call_log.current_session_id(), *call_log.load_conversation(call_log.current_session_id()))
        run_repl(runtime_config.load(), input_stream=StringIO('/retry\nexit\n'), output_stream=StringIO(),
                 workspace_root=tmp_path, resumed=resumed)
    assert len(calls) == 3
    last = bodies(calls)[-1]
    assert 'REPAIRED_INSTRUCTIONS' in json.dumps(last)
    assert 'preserved todo' in json.dumps(last)
    if provider == 'gemini':
        assert last['contents'][1]['parts'] == parts
    rows = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert [row['name'] for row in rows if row['type'] == 'tool_execution'] == ['todo', 'webfetch']
    assert len([row for row in rows if row['type'] == 'routed_task_submitted']) == 1


@pytest.mark.parametrize('recovery', [False, True])
def test_full_snapshot_survives_compression_and_counts_in_protected_and_candidate_inputs(
    route_env, install_fake_urlopen, tmp_path, monkeypatch, recovery
):
    from dataclasses import replace
    from personal_agent import context_budget, project_instructions, token_estimate
    from personal_agent.providers import http
    from tests.test_compression import fixture_estimate, seed
    from tests.test_continuation import tool
    from tests.test_context_overflow import rejection
    path = tmp_path / 'AGENTS.md'
    sentinel = 'FULL_INSTRUCTION_SENTINEL\n' * 500
    path.write_text(sentinel)
    full_snapshot = project_instructions.load(tmp_path).text
    config = replace(runtime_config.load(), capacity_overrides=(
        {'provider': 'openrouter', 'model': 'vendor/test-model', 'total_tokens': 250000},))
    monkeypatch.setattr(context_budget, 'model_info', lambda *_: {})
    resumed = seed(config, ({'role': 'user', 'content': 'old-context ' * 300},))
    measured = []
    def estimate(model, prepared):
        measured.append(prepared)
        if 'tools' not in prepared:
            assert 'FULL_INSTRUCTION_SENTINEL' not in json.dumps(prepared)
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        if 'old-context' in text:
            tokens = 224001 if not recovery and 'tool_call_id' in text else 174000
        else:
            tokens = 149000 if 'short summary' in text else 148000 if 'FULL_INSTRUCTION_SENTINEL' in text else 100000
        return token_estimate.TokenEstimate(tokens, 'instruction budget fixture', True)
    monkeypatch.setattr(token_estimate, 'estimate', estimate)
    calls = install_fake_urlopen([tool('calculator', {'expression': '2+2'})] +
        ([rejection()] if recovery else []) + ['short summary', 'task done', 'next done'])
    original = http.urlopen
    def edit_during_summary(request, timeout=None):
        response = original(request, timeout=timeout)
        if 'tools' not in json.loads(request.data):
            path.write_text('NEXT_TASK_INSTRUCTIONS')
        return response
    monkeypatch.setattr(http, 'urlopen', edit_during_summary)
    output = StringIO()
    run_repl(config, input_stream=StringIO('pending task\nnext task\nexit\n'), output_stream=output,
             workspace_root=tmp_path, resumed=resumed)
    ordinary_prepared = [prepared for prepared in measured if 'tools' in prepared]
    active = [prepared for prepared in ordinary_prepared if 'next task' not in json.dumps(prepared)]
    assert len(active) >= 4
    assert all(full_snapshot in prepared['messages'][0]['content'] for prepared in active)
    protected = [prepared for prepared in active if 'old-context' not in json.dumps(prepared)
                 and 'short summary' not in json.dumps(prepared)]
    candidates = [prepared for prepared in active if 'short summary' in json.dumps(prepared)]
    assert protected and candidates
    requests = bodies(calls)
    summaries = [body for body in requests if 'tools' not in body]
    assert len(summaries) == 1 and summaries[0]['max_tokens'] == 2000
    assert 'FULL_INSTRUCTION_SENTINEL' not in json.dumps(summaries)
    assert full_snapshot in requests[-2]['messages'][0]['content']
    assert 'NEXT_TASK_INSTRUCTIONS' in requests[-1]['messages'][0]['content']
    assert 'Automatic Compression completed' in output.getvalue()
    assert len([entry for entry in measured if 'tools' not in entry]) > 0


def test_complete_protected_instructions_overflow_blocks_before_ordinary_dispatch(route_env, install_fake_urlopen, tmp_path, monkeypatch):
    from dataclasses import replace
    from personal_agent import context_budget, token_estimate
    from tests.test_compression import fixture_estimate
    path = tmp_path / 'AGENTS.md'
    path.write_text('PROTECTED_SENTINEL')
    config = replace(runtime_config.load(), capacity_overrides=(
        {'provider': 'openrouter', 'model': 'vendor/test-model', 'total_tokens': 250000},))
    monkeypatch.setattr(context_budget, 'model_info', lambda *_: {})
    def estimate(model, prepared):
        if 'tools' not in prepared:
            assert 'PROTECTED_SENTINEL' not in json.dumps(prepared)
            return fixture_estimate(model, prepared)
        assert 'PROTECTED_SENTINEL' in prepared['messages'][0]['content']
        return token_estimate.TokenEstimate(224001, 'protected instruction fixture', True)
    monkeypatch.setattr(token_estimate, 'estimate', estimate)
    calls = install_fake_urlopen([])
    output = StringIO()
    run_repl(config, input_stream=StringIO('task\nexit\n'), output_stream=output, workspace_root=tmp_path)
    assert len(calls) == 0
    assert 'Context budget blocked' in output.getvalue() and '224001' in output.getvalue()


def test_manual_summary_and_its_estimates_omit_instructions_and_skip_reload(route_env, install_fake_urlopen, tmp_path, monkeypatch):
    from personal_agent import token_estimate
    from tests.test_compression import fixture_estimate, seed
    path = tmp_path / 'AGENTS.md'
    path.write_text('MANUAL_EXCLUDED_SENTINEL')
    resumed = seed(runtime_config.load(), ({'role': 'user', 'content': 'old context ' * 300},))
    estimates = []
    def estimate(model, prepared):
        estimates.append(prepared)
        assert 'MANUAL_EXCLUDED_SENTINEL' not in json.dumps(prepared)
        return fixture_estimate(model, prepared)
    monkeypatch.setattr(token_estimate, 'estimate', estimate)
    calls = install_fake_urlopen('short summary')
    def commands():
        path.write_text('@missing')
        yield '/compress\n'
        yield 'exit\n'
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=commands(), output_stream=output, resumed=resumed, workspace_root=tmp_path)
    assert estimates and len(calls) == 1
    assert 'MANUAL_EXCLUDED_SENTINEL' not in json.dumps(bodies(calls))
    assert 'Compressed 1 turn.' in output.getvalue() and 'Repair' not in output.getvalue()
