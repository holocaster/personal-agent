import os
import shutil
import signal
import time

import pytest

from personal_agent.providers.contract import ToolCall
from personal_agent.tools import registry as tools, shell as shell_tool, workspace


# --- Opt-in registration (ticket 0018-01) -----------------------------------


def test_shell_is_absent_from_the_registry_and_tool_defs_by_default():
    names = {definition.name for definition in tools.TOOL_DEFS}

    assert "shell" not in names
    assert tools._REGISTRY.get("shell") is None


def test_enable_shell_tool_adds_shell_and_job_tools_and_leaves_every_other_tool_unchanged():
    before = {definition.name: definition for definition in tools.TOOL_DEFS}

    tools.enable_shell_tool()

    after = {definition.name: definition for definition in tools.TOOL_DEFS}
    assert after.keys() == before.keys() | {"shell", "job_status", "job_stop"}
    for name in before:
        assert after[name] == before[name]
    shell_def = after["shell"]
    assert shell_def.parameters == {
        "type": "object",
        "properties": {"command": {"type": "string", "minLength": 1},
                       "background": {"type": "boolean", "default": False}},
        "required": ["command"],
        "additionalProperties": False,
    }


def test_enable_shell_tool_is_idempotent():
    tools.enable_shell_tool()
    tools.enable_shell_tool()

    names = [definition.name for definition in tools.TOOL_DEFS]
    assert names.count("shell") == 1


# --- execute_batch (ticket 0018-01) -----------------------------------------


def _shell_call(command, call_id="1"):
    return ToolCall(id=call_id, name="shell", arguments={"command": command})


def _always_confirm(*_args):
    return True


def test_shell_call_returns_stdout_stderr_and_exit_code(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("echo out; echo err 1>&2; exit 3")], confirm=_always_confirm)[0]

    assert result.is_error is False
    assert result.content == {"stdout": "out\n", "stderr": "err\n", "exit_code": 3}


def test_shell_non_zero_exit_is_a_normal_result_not_a_tool_error(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("exit 1")], confirm=_always_confirm)[0]

    assert result.is_error is False
    assert result.content["exit_code"] == 1


def test_shell_runs_in_the_workspace_root_as_cwd(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("pwd")], confirm=_always_confirm)[0]

    assert result.content["stdout"].strip() == str(tmp_path.resolve())


def test_shell_gets_no_stdin_so_a_reading_command_sees_eof_immediately(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("cat")], confirm=_always_confirm)[0]

    assert result.content == {"stdout": "", "stderr": "", "exit_code": 0}


def test_shell_supports_pipes_redirects_and_and_and(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch(
        [_shell_call("echo hi | tr h H > out.txt && cat out.txt")], confirm=_always_confirm
    )[0]

    assert result.content["stdout"] == "Hi\n"
    assert (tmp_path / "out.txt").read_text() == "Hi\n"


def test_shell_decodes_non_utf8_output_with_replacement_characters(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("printf '\\xff'")], confirm=_always_confirm)[0]

    assert result.is_error is False
    assert result.content["stdout"] == "�"


def test_shell_rejected_by_confirm_runs_nothing(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("touch marker.txt")], confirm=lambda *_args: False)[0]

    assert result.is_error is True
    assert result.content["error"] == "change rejected by the user"
    assert not (tmp_path / "marker.txt").exists()


def test_shell_with_no_confirm_callback_runs_nothing(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("touch marker.txt")])[0]

    assert result.is_error is True
    assert result.content["error"] == "change rejected by the user"
    assert not (tmp_path / "marker.txt").exists()


def test_shell_confirm_is_called_with_the_workspace_root_and_the_exact_command(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    seen = []

    def _confirm(*args):
        seen.append(args)
        return True

    tools.execute_batch([_shell_call("echo hi")], confirm=_confirm)

    assert seen == [("shell", str(tmp_path.resolve()), "echo hi", (), ())]


def test_shell_missing_binary_is_a_tool_error_before_confirm_is_called(tmp_path, monkeypatch):
    empty_bin_dir = tmp_path / "empty-bin"
    empty_bin_dir.mkdir()
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    workspace.configure_workspace(workspace_root)
    tools.enable_shell_tool()
    monkeypatch.setenv("PATH", str(empty_bin_dir))
    confirm_calls = []

    result = tools.execute_batch(
        [_shell_call("echo hi")], confirm=lambda *args: confirm_calls.append(args) or True
    )[0]

    assert result.is_error is True
    assert "bash" in result.content["error"]
    assert confirm_calls == []


def test_shell_apply_failure_to_start_the_process_is_a_tool_error(tmp_path, monkeypatch):
    import subprocess

    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    def _boom(*args, **kwargs):
        raise OSError("no such file or directory")

    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = tools.execute_batch([_shell_call("echo hi")], confirm=_always_confirm)[0]

    assert result.is_error is True
    assert "no such file or directory" in result.content["error"]


# --- Timeout and output cap (ticket 0018-02) --------------------------------


def test_shell_command_past_the_timeout_is_a_tool_error_with_no_partial_output(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell("1", None, 1024)

    result = tools.execute_batch([_shell_call("echo partial; sleep 5")], confirm=_always_confirm)[0]

    assert result.is_error is True
    assert "command timed out after 1 seconds" in result.content["error"]
    assert "background: true" in result.content["error"] and "job_status" in result.content["error"]
    assert "inner timeout cannot extend" in result.content["error"]


def test_shell_timeout_kills_a_background_child_in_the_same_process_group(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell("1", None, 1024)

    tools.execute_batch(
        [_shell_call("sleep 100 & echo $! > child.pid; sleep 100")], confirm=_always_confirm
    )

    child_pid = int((tmp_path / "child.pid").read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_shell_timeout_does_not_hang_on_a_backgrounded_child_that_inherits_stdout(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell("1", None, 1024)

    start = time.monotonic()
    result = tools.execute_batch(
        [_shell_call("sleep 30 & echo $! > child.pid; echo hi")], confirm=_always_confirm
    )[0]
    elapsed = time.monotonic() - start

    assert elapsed < 5
    assert result.is_error is True
    assert result.content["error"].startswith("command timed out after 1 seconds;")
    child_pid = int((tmp_path / "child.pid").read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_shell_timeout_sigkills_a_backgrounded_child_that_ignores_sigterm(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell("1", None, 1024)

    start = time.monotonic()
    result = tools.execute_batch(
        [_shell_call("(trap '' TERM; sleep 30) & echo $! > child.pid; echo hi")], confirm=_always_confirm
    )[0]
    elapsed = time.monotonic() - start

    assert elapsed < 5
    assert result.is_error is True
    assert result.content["error"].startswith("command timed out after 1 seconds;")
    child_pid = int((tmp_path / "child.pid").read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_shell_bounded_capture_survives_a_flood_of_output_before_the_timeout(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell("1", "1024", 1024)

    result = tools.execute_batch([_shell_call("yes")], confirm=_always_confirm)[0]

    assert result.is_error is True
    assert result.content["error"].startswith("command timed out after 1 seconds;")


def test_shell_stdout_and_stderr_are_capped_independently_with_a_truncation_marker(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell(None, "5", 5)

    result = tools.execute_batch(
        [_shell_call("printf '0123456789'; printf 'abcdefghij' 1>&2")], confirm=_always_confirm
    )[0]

    assert result.is_error is False
    assert result.content == {"stdout": "01234[...truncated]", "stderr": "abcde[...truncated]", "exit_code": 0}


def test_shell_output_under_the_cap_has_no_truncation_marker(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell(None, "1024", 1024)

    result = tools.execute_batch([_shell_call("echo short")], confirm=_always_confirm)[0]

    assert result.content["stdout"] == "short\n"
    assert "[...truncated]" not in result.content["stdout"]


def test_shell_max_output_bytes_defaults_to_the_effective_max_read_bytes_when_unset(tmp_path):
    workspace.configure_workspace(tmp_path, max_read_bytes_value="10")
    tools.enable_shell_tool()

    result = tools.execute_batch([_shell_call("printf '0123456789ABCDE'")], confirm=_always_confirm)[0]

    assert result.content["stdout"] == "0123456789[...truncated]"


# --- Always-clean process lifecycle and bounded final drain (ticket 0018-03) -


def _assert_process_gone(pid, timeout=2.0):
    """Poll for the killed child's pid to disappear rather than checking
    once: `os.kill(pid, 0)` also succeeds on a zombie (dead, unreaped by its
    now-gone parent), and reaping an orphan reparented to init is an
    OS-scheduled detail with no fixed latency this test controls."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_shell_normal_completion_kills_a_background_child_with_redirected_output(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch(
        [_shell_call("sleep 30 >/dev/null 2>&1 & echo $! > child.pid; echo hi")], confirm=_always_confirm
    )[0]

    assert result.is_error is False
    assert result.content == {"stdout": "hi\n", "stderr": "", "exit_code": 0}
    child_pid = int((tmp_path / "child.pid").read_text().strip())
    _assert_process_gone(child_pid)


def test_shell_normal_completion_sigkills_a_background_child_that_ignores_sigterm(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    result = tools.execute_batch(
        [_shell_call("(trap '' TERM; sleep 30) >/dev/null 2>&1 & echo $! > child.pid; echo hi")],
        confirm=_always_confirm,
    )[0]

    assert result.is_error is False
    assert result.content == {"stdout": "hi\n", "stderr": "", "exit_code": 0}
    child_pid = int((tmp_path / "child.pid").read_text().strip())
    _assert_process_gone(child_pid)


def test_shell_ordinary_command_returns_well_under_the_kill_grace_period(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    start = time.monotonic()
    result = tools.execute_batch([_shell_call("echo hi")], confirm=_always_confirm)[0]
    elapsed = time.monotonic() - start

    assert result.content == {"stdout": "hi\n", "stderr": "", "exit_code": 0}
    assert elapsed < shell_tool.KILL_GRACE_SECONDS


def test_shell_process_that_escapes_the_group_with_setsid_ends_in_a_bounded_drain_error(tmp_path):
    if shutil.which("setsid") is None:
        pytest.skip("setsid is not on PATH")
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell_tool.configure_shell("1", None, 1024)
    escaped_pid = None
    try:
        start = time.monotonic()
        result = tools.execute_batch(
            [_shell_call("setsid sleep 30 & echo $! > child.pid; echo hi")], confirm=_always_confirm
        )[0]
        elapsed = time.monotonic() - start

        escaped_pid = int((tmp_path / "child.pid").read_text().strip())
        assert result.is_error is True
        assert result.content == {
            "error": "command timed out after 1 seconds; a process that left the process group may still be running"
        }
        upper_bound = (
            1 + shell_tool.KILL_GRACE_SECONDS + shell_tool.DRAIN_JOIN_TIMEOUT_SECONDS + 3
        )
        assert elapsed < upper_bound
    finally:
        if escaped_pid is not None:
            try:
                os.kill(escaped_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_configure_shell_defaults_and_rejects_invalid_values():
    config = shell_tool.configure_shell(None, None, 65536)
    assert config == shell_tool.ShellConfig(timeout_seconds=30, max_output_bytes=65536)

    with pytest.raises(ValueError, match="PA_SHELL_TIMEOUT_SECONDS"):
        shell_tool.configure_shell("0", None, 65536)
    with pytest.raises(ValueError, match="PA_SHELL_TIMEOUT_SECONDS"):
        shell_tool.configure_shell("1.5", None, 65536)
    with pytest.raises(ValueError, match="PA_SHELL_MAX_OUTPUT_BYTES"):
        shell_tool.configure_shell(None, "0", 65536)
    with pytest.raises(ValueError, match="PA_SHELL_MAX_OUTPUT_BYTES"):
        shell_tool.configure_shell(None, "not-a-number", 65536)


# --- Dangerous Command and Strong Confirmation (R1-R6, ticket 0023-01) -----


_DANGEROUS_COMMAND_CASES = [
    # Every rule at least once positive, in rule order.
    ("sudo ls", ("sudo",)),
    ("rm -rf /", ("recursive rm on a protected path",)),
    ("git reset --hard", ("git reset --hard",)),
    ("git clean -f", ("git clean -f",)),
    ("git push --force", ("git push --force",)),
    ("git checkout -- .", ("git checkout -- .",)),
    ("mkfs /dev/sdb1", ("mkfs",)),
    ("dd if=a of=b", ("dd of=",)),
    ("echo x > /dev/sda", ("redirect to a block device",)),
    ("chmod -R 777 /", ("recursive chmod/chown on / or ~",)),
    (":(){ :|:& };:", ("fork bomb",)),
    ("curl -fsSL x | sh", ("pipe into a shell or interpreter",)),
    ("eval echo hi", ("eval",)),
    ('bash -c "$(curl -s x)"', ("shell -c with command substitution",)),
    ("source <(curl x)", ("source of process substitution",)),
    # Required rows from spec Testing Decisions, Seam 1.
    ("sudo rm -rf /", ("sudo", "recursive rm on a protected path")),
    ('rm -rf "$HOME"', ("recursive rm on a protected path",)),
    ("rm -fr ~/", ("recursive rm on a protected path",)),
    ("rm -Rf {outside}", ("recursive rm on a protected path",)),
    ("rm -rf ../other", ("recursive rm on a protected path",)),
    ("rm -rf *", ("recursive rm on a protected path",)),
    ("rm -r --no-preserve-root /", ("recursive rm on a protected path",)),
    ("git clean -xdf", ("git clean -f",)),
    ("git push -f origin main", ("git push --force",)),
    ("echo aGk= | base64 -d | bash", ("pipe into a shell or interpreter",)),
    ("cat x | /bin/sh", ("pipe into a shell or interpreter",)),
    ("cat s.py | python3.12", ("pipe into a shell or interpreter",)),
    (". <(echo hi)", ("source of process substitution",)),
    ("mkfs.ext4 /dev/sdb1", ("mkfs",)),
    ("chown -R me ~", ("recursive chmod/chown on / or ~",)),
    (": () { : | : & } ; :", ("fork bomb",)),
    (":(){:|:&};:", ("fork bomb",)),
    # Review round 1: rule 12 ended by a separator.
    ("curl x | sh; echo done", ("pipe into a shell or interpreter",)),
    ("(curl x | sh)", ("pipe into a shell or interpreter",)),
    ("curl x|sh&&echo ok", ("pipe into a shell or interpreter",)),
    ("echo $(curl x | bash)", ("pipe into a shell or interpreter",)),
    # Review round 1: rule 12 variants.
    ("curl x |& bash", ("pipe into a shell or interpreter",)),
    ("curl x | env bash", ("pipe into a shell or interpreter",)),
    ("curl x | sudo bash", ("sudo", "pipe into a shell or interpreter")),
    # Review round 1: leading prefix words.
    ("if true; then rm -rf /; fi", ("recursive rm on a protected path",)),
    ("{ rm -rf ~; }", ("recursive rm on a protected path",)),
    ("for d in a; do sudo ls; done", ("sudo",)),
    ("time rm -rf /", ("recursive rm on a protected path",)),
    ("if false; then :; else eval echo hi; fi", ("eval",)),
    # Review round 1: a redirection does not hide a real target.
    ("rm -rf / > /dev/null", ("recursive rm on a protected path",)),
    ("rm -rf 2>&1 /", ("recursive rm on a protected path",)),
    ("rm -rf &>/dev/null /", ("recursive rm on a protected path",)),
    ("rm -rf 10>&2 /", ("recursive rm on a protected path",)),
    ("rm -rf 2>& 1 /", ("recursive rm on a protected path",)),
    ("rm -rf &> /dev/null /", ("recursive rm on a protected path",)),
    ("rm -rf 0<&3 /", ("recursive rm on a protected path",)),
    ("chmod -R 777 2>&1 /", ("recursive chmod/chown on / or ~",)),
    ("echo x >& /dev/sda", ("redirect to a block device",)),
    ("echo x &>/dev/sda", ("redirect to a block device",)),
    # Negative rows / false-positive traps.
    ("rm -rf ./build", ()),
    ("rm -rf build/*", ()),
    ("rm -rf .", ()),
    ("rm -rf {inside}", ()),
    ("rm file.txt", ()),
    ("rm -f ~/x", ()),
    ("git reset --soft HEAD~1", ()),
    ("git reset HEAD file", ()),
    ("git clean -n", ()),
    ("git push origin main", ()),
    ("git checkout -- src/a.py", ()),
    ("git checkout main", ()),
    ("echo hi > /dev/null", ()),
    ("cmd 2>/dev/null", ()),
    ("chmod -R 755 ./build", ()),
    ("chown -R me .", ()),
    ("ls | sort", ()),
    ("echo hi | grep sh", ()),
    ("cat f | shasum", ()),
    ("false || bash run.sh", ()),
    ('bash -c "echo hi"', ()),
    ("bash script.sh", ()),
    ("source .venv/bin/activate", ()),
    ("diff <(ls a) <(ls b)", ()),
    ("echo pseudo", ()),
    ("echo evaluate", ()),
    ("python eval.py", ()),
    ("grep sudo notes.txt", ()),
    # Review round 1: negative traps for rule 12, leading prefix words and
    # the redirection exclusion.
    ("cat f | bash-foo", ()),
    ("cat f | python3x", ()),
    ("echo time rm -rf /", ()),
    ("echo do sudo ls", ()),
    ("rm -rf build > /dev/null 2>&1", ()),
    ("rm -rf build 2>/dev/null", ()),
    ("rm -rf build >> /tmp/rm.log", ()),
    ("chmod -R 755 ./build > /dev/null", ()),
    ("rm -rf build &>/dev/null", ()),
    ("rm -rf build 2>&1 && echo ok", ()),
    ("ls 2>&1 & echo hi", ()),
    ("rm -rf ';' /", ("recursive rm on a protected path",)),
    ("echo ';' rm -rf /", ()),
    ('echo "hello\nrm -rf /\nworld"', ()),
    ('rm -rf "&&" /', ("recursive rm on a protected path",)),
    ("rm -rf \\; /", ("recursive rm on a protected path",)),
    ("echo \\; rm -rf /", ()),
    ("echo '|' '&' '(' ')' '||' '&&' rm -rf /", ()),
    ("echo ''\\; rm -rf /", ()),
    ("echo 'hello\nrm -rf /\nworld'", ()),
    ('echo "hello\nworld"\nrm -rf /', ("recursive rm on a protected path",)),
    ('r"m" -rf /', ("recursive rm on a protected path",)),
    ("echo hi # don't rm -rf /", ()),
    ("rm -rf build#old /", ("recursive rm on a protected path",)),
    ("chmod -R 777 build#old /", ("recursive chmod/chown on / or ~",)),
    ("echo build#old; rm -rf /", ("recursive rm on a protected path",)),
    ("chown -R me build#old ~", ("recursive chmod/chown on / or ~",)),
    ("rm -rf build#old", ()),
    ("rm -rf build # /", ()),
    ("chmod -R 777 build # /", ()),
    ("# rm -rf /", ()),
    ("echo build;# rm -rf /", ()),
    ("echo build && # rm -rf /", ()),
    ("echo build # rm -rf /\nrm -rf /", ("recursive rm on a protected path",)),
    ("echo build#old # don't rm -rf /", ()),
    ("rm -rf '#old' /", ("recursive rm on a protected path",)),
    ('rm -rf "#old" /', ("recursive rm on a protected path",)),
    ("rm -rf ''#old /", ("recursive rm on a protected path",)),
    ('rm -rf ""#old /', ("recursive rm on a protected path",)),
    ("rm -rf \\#old /", ("recursive rm on a protected path",)),
    ("rm -rf build\\ #old /", ("recursive rm on a protected path",)),
    ("echo 'build#old; rm -rf /'", ()),
    ('echo "build#old; rm -rf /"', ()),
    ("echo build#old\\; rm -rf /", ()),
    ("echo build#old && rm -rf /", ("recursive rm on a protected path",)),
    ("rm -rf build 2>log#old /", ("recursive rm on a protected path",)),
    ("rm -rf build 2>log#old", ()),
    ("rm -rf build#old 2>&1 /", ("recursive rm on a protected path",)),
    ("rm -rf build#old 2>&1 # /", ()),
    ("rm -rf build#'hello\nworld' /", ("recursive rm on a protected path",)),
    ('rm -rf build#"hello\nworld" /', ("recursive rm on a protected path",)),
    ("echo build#'hello\nrm -rf /\nworld'", ()),
    ('echo build#"hello\nrm -rf /\nworld"', ()),
    ("rm -rf ''#'hello\nworld' /", ("recursive rm on a protected path",)),
    ('rm -rf ""#"hello\nworld" /', ("recursive rm on a protected path",)),
    ("rm -rf \\#'hello\nworld' /", ("recursive rm on a protected path",)),
    ('rm -rf \\#"hello\nworld" /', ("recursive rm on a protected path",)),
    ("echo ''#'hello\nrm -rf /\nworld'", ()),
    ('echo ""#"hello\nrm -rf /\nworld"', ()),
    ("echo \\#'hello\nrm -rf /\nworld'", ()),
    ('echo \\#"hello\nrm -rf /\nworld"', ()),
    ("echo build#'hello\nworld'; rm -rf /", ("recursive rm on a protected path",)),
    ("echo build#'hello\nworld' # don't\nrm -rf /", ("recursive rm on a protected path",)),
    ("echo build#'hello\nrm -rf /\nworld' # don't", ()),
    ('echo build#"hello\nrm -rf /\nworld" # "', ()),
    ("echo 'hello\nrm -rf /\nworld' # don't", ()),
    ('echo "hello\nrm -rf /\nworld" # "', ()),
    ("echo 'build\nrm -rf /", ("recursive rm on a protected path",)),
]


@pytest.mark.parametrize("command_template, expected_rules", _DANGEROUS_COMMAND_CASES)
def test_dangerous_command_rules_at_execute_batch(tmp_path, command_template, expected_rules):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    outside = str(tmp_path.parent / "x")
    inside = str(tmp_path / "sub" / "file")
    command = command_template.replace("{outside}", outside).replace("{inside}", inside)
    seen = []

    def _confirm(tool_name, path, preview, dangerous_rules, fetched_urls=()):
        seen.append(dangerous_rules)
        return False

    tools.execute_batch([_shell_call(command)], confirm=_confirm)

    assert seen == [expected_rules]


def test_non_shell_tool_call_gets_no_dangerous_rules(tmp_path):
    workspace.configure_workspace(tmp_path)
    seen = []

    def _confirm(tool_name, path, preview, dangerous_rules, fetched_urls=()):
        seen.append(dangerous_rules)
        return True

    call = ToolCall(id="1", name="write", arguments={"path": "note.txt", "content": "hi"})
    tools.execute_batch([call], confirm=_confirm)

    assert seen == [()]


def test_shell_tool_result_carries_the_matched_dangerous_rules(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    approved = tools.execute_batch([_shell_call("eval echo hi")], confirm=_always_confirm)[0]
    rejected = tools.execute_batch([_shell_call("eval echo hi")], confirm=lambda *_args: False)[0]
    normal = tools.execute_batch([_shell_call("echo hi")], confirm=_always_confirm)[0]

    assert approved.dangerous_rules == ("eval",)
    assert rejected.dangerous_rules == ("eval",)
    assert normal.dangerous_rules == ()
