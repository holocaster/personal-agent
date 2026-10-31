import json
import os
import stat
from pathlib import Path

import pytest

from personal_agent import call_log
from personal_agent.routing import runtime_config


def test_owned_legacy_storage_directories_become_private_on_write():
    project = call_log.storage_identity()["project_id"]
    with call_log.storage_directory(project, create=True):
        pass
    root = Path.home() / ".personal_agent"
    paths = (root, root / "logs", root / "logs" / project)
    for path in paths:
        path.chmod(0o775)
    with call_log.storage_directory(project, create=True, private=True):
        pass
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in paths)


def test_storage_never_changes_permissions_for_another_owner(monkeypatch):
    with call_log.storage_directory(create=True):
        pass
    path = Path.home() / ".personal_agent"
    path.chmod(0o775)
    monkeypatch.setattr(os, "getuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(OSError, match="owner"):
        with call_log.storage_directory(create=True):
            pass
    assert stat.S_IMODE(path.stat().st_mode) == 0o775


def test_storage_captures_home_and_project_and_ignores_old_overrides(tmp_path, monkeypatch, route_env):
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv('PA_LOG_PATH', str(tmp_path / 'wrong.jsonl'))
    monkeypatch.setenv('PA_WORKSPACE', str(tmp_path / 'wrong'))
    sid = call_log.start_session(runtime_config.load())
    original = Path(call_log.session_log_path(sid))
    record = json.loads(original.read_text().splitlines()[0])
    assert original.parent.parent == tmp_path / '.personal_agent' / 'logs'
    assert original.name == f'pa_log-{sid}.jsonl'
    assert record['workspace_root'] == str(project)
    assert record['project_id'] == original.parent.name
    assert len(record['run_id']) == 32
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'other-home'))
    call_log.end_session('exit_command')
    assert Path(call_log.session_log_path(sid)) == original
    assert len(original.read_text().splitlines()) == 2


def test_last_uses_latest_physical_run_in_current_project(tmp_path, monkeypatch, route_env):
    config = runtime_config.load()
    ids = iter(['20260101T000000Z-aaaaaa', '20260201T000000Z-bbbbbb', '20260301T000000Z-cccccc'])
    stamps = iter(['2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z', '2026-04-01T00:00:00Z', '2026-05-01T00:00:00Z'])
    monkeypatch.setattr(call_log, '_mint_session_id', lambda: next(ids))
    monkeypatch.setattr(call_log, '_now_iso', lambda: next(stamps))
    older = call_log.start_session(config)
    call_log.start_session(config)
    call_log.resume_session(older, config)
    assert call_log.resolve_resume_session('last') == older
    sibling = tmp_path / 'sibling'
    sibling.mkdir()
    call_log.initialize_storage(sibling)
    other = call_log.start_session(config)
    assert call_log.resolve_resume_session('last') == other
    call_log.initialize_storage(tmp_path)
    assert call_log.resolve_resume_session('last') == older
    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(other)


@pytest.mark.parametrize('boundary', ['session_start', 'session_resumed'])
@pytest.mark.parametrize('field,value', [('workspace_root', '/another-project'), ('project_id', 'wrong'), ('run_id', None)])
def test_resume_refuses_mismatched_run_identity_without_appending(route_env, boundary, field, value):
    config = runtime_config.load()
    sid = call_log.start_session(config)
    path = Path(call_log.session_log_path(sid))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if boundary == 'session_resumed':
        rows.append({**rows[0], 'type': boundary})
    rows[-1][field] = value
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    before = path.read_bytes()
    with pytest.raises(call_log.ResumeError, match='identity'):
        call_log.resume_session(sid, config)
    assert path.read_bytes() == before


@pytest.mark.parametrize('unsafe', ['symlink', 'fifo', 'directory'])
def test_fresh_resume_and_audit_opens_refuse_unsafe_files(tmp_path, monkeypatch, route_env, unsafe):
    import os
    config = runtime_config.load()
    sid = call_log.start_session(config)
    path = Path(call_log.session_log_path(sid))
    path.unlink()
    outside = tmp_path / 'outside'
    outside.write_text('untouched')
    for selected in (path, Path(call_log.detail_path(sid))):
        if unsafe == 'symlink':
            selected.symlink_to(outside)
        elif unsafe == 'fifo':
            os.mkfifo(selected)
        else:
            selected.mkdir()
    with pytest.raises(call_log.ResumeError):
        call_log.resume_session(sid, config)
    monkeypatch.setattr(call_log, '_mint_session_id', lambda: sid)
    with pytest.raises(OSError):
        call_log.start_session(config)
    with pytest.raises(call_log.AuditError):
        call_log.open_detail()
    assert outside.read_text() == 'untouched'


@pytest.mark.parametrize('component', ['.personal_agent', 'logs', 'project'])
def test_storage_refuses_symlink_directories_for_reads_and_writes(tmp_path, route_env, component):
    config = runtime_config.load()
    sid = call_log.start_session(config)
    project = Path(call_log.session_log_path(sid)).parent
    selected = project if component == 'project' else (project.parent if component == 'logs' else project.parent.parent)
    moved = tmp_path / 'moved'
    selected.rename(moved)
    selected.symlink_to(moved, target_is_directory=True)
    before = (moved / f'pa_log-{sid}.jsonl').read_bytes() if component == 'project' else None
    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(sid)
    with pytest.raises(call_log.ResumeError):
        call_log.resolve_resume_session('last')
    with pytest.raises(OSError):
        call_log.start_session(config)
    with pytest.raises(call_log.AuditError):
        call_log.open_detail()
    if before is not None:
        assert (moved / f'pa_log-{sid}.jsonl').read_bytes() == before


def test_last_tolerates_unrelated_invalid_activity_but_strict_resume_rejects_it(route_env):
    config = runtime_config.load()
    sid = call_log.start_session(config)
    path = Path(call_log.session_log_path(sid))
    with path.open('ab') as file:
        file.write(b'\nnot-json\n\xff\n[]\n' + b'x' * (256 * 1024 + 1) + b'\n')
    assert call_log.resolve_resume_session('last') == sid
    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(sid)


@pytest.mark.parametrize('bound', ['entries', 'bytes', 'records'])
def test_last_never_selects_partial_scan(route_env, bound):
    config = runtime_config.load()
    sid = call_log.start_session(config)
    path = Path(call_log.session_log_path(sid))
    if bound == 'entries':
        for index in range(4096):
            (path.parent / f'ignored-{index}').touch()
    else:
        with path.open('ab') as file:
            file.write(b'\n' * 8192 if bound == 'records' else b'x' * (8 * 1024 * 1024) + b'\n')
    with pytest.raises(call_log.ResumeError, match='budget exhausted'):
        call_log.resolve_resume_session('last')


def test_last_uses_physical_boundary_even_when_timestamp_goes_backwards(route_env, monkeypatch):
    config = runtime_config.load()
    stamps = iter(['2026-04-01T00:00:00Z', '2026-02-01T00:00:00Z', '2026-01-01T00:00:00Z'])
    monkeypatch.setattr(call_log, '_now_iso', lambda: next(stamps))
    first = call_log.start_session(config)
    second = call_log.start_session(config)
    call_log.resume_session(first, config)
    assert call_log.resolve_resume_session('last') == second


def test_fresh_session_refuses_folder_metadata_from_other_project(route_env):
    config = runtime_config.load()
    sid = call_log.start_session(config)
    path = Path(call_log.session_log_path(sid))
    initial = json.loads(path.read_text())
    initial['workspace_root'] = '/another-project'
    path.write_text(json.dumps(initial) + '\n')
    before = sorted(path.parent.iterdir())
    with pytest.raises(call_log.ResumeError, match='identity'):
        call_log.start_session(config)
    assert sorted(path.parent.iterdir()) == before


@pytest.mark.parametrize('path,expected', [
    ('/', 'root--8a5edab28263'),
    ('/a/b', 'a_b--662b7b62a798'),
    ('/a_b', 'a_b--328ff01fbf3d'),
    ('/tmp/café/项目', 'tmp_caf--969a7f755ac5'),
    ('/TMP/Case', 'TMP_Case--5d1bb265af95'),
    ('/tmp/case', 'tmp_case--df3296d9335f'),
    ('/' + 'a' * 110 + 'x', 'a' * 96 + '--aaf4468eb473'),
    ('/' + 'a' * 110 + 'y', 'a' * 96 + '--5c9fa623b00b'),
])
def test_project_folder_encoding(path, expected):
    assert call_log.project_id(path) == expected


def test_last_timestamp_tie_uses_descending_session_id(route_env, monkeypatch):
    monkeypatch.setattr(call_log, '_now_iso', lambda: '2026-01-01T00:00:00Z')
    ids = iter(['20260101T000000Z-aaaaaa', '20260101T000000Z-bbbbbb'])
    monkeypatch.setattr(call_log, '_mint_session_id', lambda: next(ids))
    call_log.start_session(runtime_config.load())
    second = call_log.start_session(runtime_config.load())
    assert call_log.resolve_resume_session('last') == second


@pytest.mark.parametrize('timestamp', [None, 'unknown', '2026-01-01T00:00:00'])
def test_last_rejects_unknown_run_timestamp(route_env, timestamp):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path(sid))
    entry = json.loads(path.read_text())
    entry['timestamp'] = timestamp
    path.write_text(json.dumps(entry) + '\n')
    with pytest.raises(call_log.ResumeError, match='timestamp'):
        call_log.resolve_resume_session('last')


@pytest.mark.parametrize('session', ['../outside', '/tmp/file', '20260101T000000Z-aaaaaa/../file'])
def test_explicit_session_id_cannot_escape_project(session):
    with pytest.raises(call_log.ResumeError):
        call_log.resolve_resume_session(session)
    with pytest.raises(call_log.ResumeError):
        call_log.session_log_path(session)


@pytest.mark.parametrize('operation', ['read', 'append', 'audit'])
def test_replacement_file_symlink_is_not_followed_between_stat_and_open(tmp_path, route_env, monkeypatch, operation):
    import os
    config = runtime_config.load()
    sid = call_log.start_session(config)
    selected = Path(call_log.detail_path(sid) if operation == 'audit' else call_log.session_log_path(sid))
    if operation == 'audit':
        selected.write_text('')
        selected.chmod(0o600)
    original_open = os.open
    outside = tmp_path / 'outside'
    outside.write_text('untouched')
    replaced = False

    def replace_at_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == selected.name and not replaced:
            replaced = True
            selected.rename(selected.with_suffix('.original'))
            selected.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', replace_at_open)
    error = call_log.ResumeError if operation == 'read' else call_log.AuditError if operation == 'audit' else OSError
    with pytest.raises(error):
        if operation == 'read':
            call_log.load_conversation(sid)
        elif operation == 'audit':
            call_log.open_detail()
        else:
            call_log.end_session('exit_command')
    assert replaced and outside.read_text() == 'untouched'


@pytest.mark.parametrize('component', ['.personal_agent', 'logs', 'project'])
def test_replacement_directory_symlink_is_not_followed(tmp_path, route_env, monkeypatch, component):
    import os
    sid = call_log.start_session(runtime_config.load())
    project = Path(call_log.session_log_path(sid)).parent
    selected = project if component == 'project' else project.parent if component == 'logs' else project.parent.parent
    moved = tmp_path / 'moved'
    original_open = os.open
    replaced = False

    def replace_at_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == selected.name and not replaced:
            replaced = True
            selected.rename(moved)
            selected.symlink_to(moved, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', replace_at_open)
    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(sid)
    assert replaced


def test_strict_resume_rejects_parseable_incomplete_tail(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path(sid))
    with path.open('ab') as file:
        file.write(json.dumps({'type': 'attempt', 'session_id': sid}).encode())
    assert call_log.resolve_resume_session('last') == sid
    with pytest.raises(call_log.ResumeError, match='incomplete'):
        call_log.load_conversation(sid)


def test_last_rejects_a_later_boundary_with_wrong_session_identity(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path(sid))
    boundary = json.loads(path.read_text())
    boundary.update(type='session_resumed', session_id='20260101T000000Z-aaaaaa')
    with path.open('a') as file:
        file.write(json.dumps(boundary) + '\n')
    with pytest.raises(call_log.ResumeError, match='identity'):
        call_log.resolve_resume_session('last')


def test_repl_cwd_fallback_keeps_instructions_tools_and_logs_fixed(tmp_path, route_env, install_fake_urlopen, monkeypatch):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl
    project = tmp_path / 'project'
    sibling = tmp_path / 'sibling'
    project.mkdir()
    sibling.mkdir()
    (project / 'AGENTS.md').write_text('ORIGINAL_INSTRUCTIONS')
    (project / 'evidence.txt').write_text('original evidence')
    (sibling / 'AGENTS.md').write_text('WRONG_INSTRUCTIONS')
    (sibling / 'evidence.txt').write_text('wrong evidence')
    monkeypatch.chdir(project)
    calls = install_fake_urlopen([
        {'tool_calls': [{'id': 'read-1', 'name': 'read_file', 'arguments': {'path': 'evidence.txt'}}]},
        'done',
    ])

    def inputs():
        monkeypatch.chdir(sibling)
        yield 'read evidence\n'
        yield 'exit\n'

    run_repl(runtime_config.load(), input_stream=inputs(), output_stream=StringIO())
    first = json.loads(calls[0]['request'].data)
    followup = json.loads(calls[1]['request'].data)
    assert 'ORIGINAL_INSTRUCTIONS' in first['messages'][0]['content']
    assert 'WRONG_INSTRUCTIONS' not in json.dumps(first)
    assert 'original evidence' in followup['messages'][-1]['content']
    assert 'wrong evidence' not in json.dumps(followup)
    start = json.loads(Path(call_log.session_log_path()).read_text().splitlines()[0])
    assert start['workspace_root'] == str(project)


def test_main_captures_cwd_before_configuration_changes_it(tmp_path, monkeypatch, route_env):
    from personal_agent.__main__ import main
    from personal_agent.tools import workspace
    sibling = tmp_path / 'sibling'
    sibling.mkdir()
    captured = {}
    monkeypatch.setattr('personal_agent.__main__.load_dotenv', lambda *args: monkeypatch.chdir(sibling))
    monkeypatch.setattr('personal_agent.__main__.run_repl', lambda *args, **kwargs: captured.update(kwargs))
    main()
    assert captured['workspace_root'] == tmp_path
    assert workspace.configured_workspace().root == tmp_path
    assert call_log.storage_identity()['workspace_root'] == str(tmp_path)
