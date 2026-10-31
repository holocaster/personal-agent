import json
from collections import deque
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log, chatgpt_auth
from personal_agent.providers import chatgpt
from personal_agent.routing import router, runtime_config
from personal_agent.terminal.repl import run_repl
from tests.test_chatgpt_auth import oauth
from tests.test_chatgpt_provider import completed, connected, exhaustion, function, message
from tests.test_streaming import StreamResponse

REASONING = {"type": "reasoning", "id": "reason-1", "summary": [], "encrypted_content": "opaque-private"}
OUTPUT = {"type": "function_call_output", "call_id": "tool-1", "output": '{"result": 4}'}


def serve(monkeypatch, *responses):
    queue = deque(StreamResponse(chunks) for chunks in responses)
    payloads = []

    def transport(request, timeout):
        payloads.append(json.loads(request.data))
        return queue.popleft()

    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    return payloads


def repl(config, text, resume=None):
    output = StringIO()
    resumed = (resume, *call_log.load_conversation(resume)) if resume else None
    run_repl(config, input_stream=StringIO(text + "exit\n"), output_stream=output, resumed=resumed)
    return output.getvalue(), call_log.current_session_id()


def entries(session_id):
    return [json.loads(line) for line in Path(call_log.session_log_path(session_id)).read_text().splitlines()]


def admitted():
    return runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}))


def connect(auth, state, subject=None):
    if subject is not None:
        state["claims"]["sub"] = subject
    binding = auth.connect(different=subject is not None)
    auth.acknowledge(binding)
    auth.activate(binding, "exact-1", lambda: None)
    return admitted()


TURN = [{"role": "user", "content": "calculate"}, REASONING, function(), OUTPUT, message("four")]


def test_completed_replay_survives_turns_resume_and_same_account_reauth(connected, monkeypatch):
    auth, state, config = connected
    payloads = serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])],
                     [completed([message("next")])])
    output, session = repl(config, "calculate\nnext\n")
    assert payloads[2]["input"] == [*TURN, {"role": "user", "content": "next"}]
    ends = [entry for entry in entries(session) if entry["type"] == "turn_end"]
    assert [end["replay"]["registration"] for end in ends] == [config.chatgpt_binding.registration] * 2
    assert ends[0]["replay"]["items"] == TURN and "Account notice" not in output
    starts = [entry for entry in entries(session) if entry["type"] in {"session_start", "routed_task_submitted"}]
    assert all((entry["access_method"], entry["registration_ref"]) == ("chatgpt_plan", config.chatgpt_binding.registration)
               for entry in starts)

    reauthed = connect(auth, state)
    assert reauthed.chatgpt_binding.registration == config.chatgpt_binding.registration
    payloads = serve(monkeypatch, [completed([message("again")])])
    output, resumed = repl(reauthed, "again\n", resume=session)
    assert resumed == session and "Account notice" not in output
    assert payloads[0]["input"] == [*TURN, {"role": "user", "content": "next"}, message("next"),
                                    {"role": "user", "content": "again"}]


def test_different_registration_keeps_text_drops_opaque_state_and_notice_survives_restart(connected, monkeypatch):
    auth, state, config = connected
    serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])])
    _, session = repl(config, "calculate\n")
    other = connect(auth, state, "account-2")
    assert other.chatgpt_binding.registration != config.chatgpt_binding.registration

    payloads = serve(monkeypatch)
    output, _ = repl(other, "", resume=session)
    assert not payloads and "Account notice" not in output
    payloads = serve(monkeypatch, [completed([message("hello other")])])
    output, _ = repl(other, "next\n", resume=session)
    label = chatgpt_auth.account_label(other.chatgpt_binding.registration)
    assert f"Account notice: retained Conversation text will be sent to {label}." in output
    assert REASONING not in payloads[0]["input"]
    assert payloads[0]["input"][:4] == [{"role": "user", "content": "calculate"},
                                        {key: function()[key] for key in ("type", "call_id", "name", "namespace", "arguments")},
                                        OUTPUT, {"role": "assistant", "content": "four"}]

    payloads = serve(monkeypatch, [completed([message("again")])])
    output, _ = repl(other, "again\n", resume=session)
    assert "Account notice" not in output and len(payloads) == 1


def test_retry_after_restart_replays_pending_batch_without_repeating_tools(connected, monkeypatch):
    _, _, config = connected
    payloads = serve(monkeypatch, [completed([REASONING, function()])], exhaustion())
    output, session = repl(config, "calculate\n")
    assert "Cota atingida" in output and output.count("calculator") == 1
    pending = call_log.load_pending_turn(session)
    assert pending[1]["version"] == 2 and pending[1]["registration"] == config.chatgpt_binding.registration
    assert pending[1]["replay"]["items"] == TURN[:4]

    payloads = serve(monkeypatch, [completed([message("four")])])
    output, _ = repl(config, "/retry\n", resume=session)
    assert payloads[0]["input"] == TURN[:4] and "calculator" not in output
    log = entries(session)
    retried = next(entry for entry in log if entry["type"] == "routed_task_retried")
    assert retried["ordinal"] == 1 and retried["access_method"] == "chatgpt_plan"
    end = [entry for entry in log if entry["type"] == "turn_end"][-1]
    assert end["status"] == "ok" and end["replay"]["items"] == TURN
    assert [m["role"] for m in end["messages"]] == ["user", "assistant", "tool_result", "assistant"]


def test_api_route_uses_normalized_text_and_chatgpt_reuses_bound_turns(connected, monkeypatch):
    _, _, config = connected
    replay = {"version": 1, "provider": "chatgpt", "model": "exact-1",
              "registration": config.chatgpt_binding.registration, "items": TURN}
    messages = ({"role": "user", "content": "calculate"},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "tool-1", "name": "calculator", "arguments": {"expression": "2+2"},
                     "arguments_raw": '{"expression":"2+2"}', "id_is_generated": False}]},
                {"role": "tool_result", "id": "tool-1", "name": "calculator", "content": {"result": 4},
                 "is_error": False, "id_is_generated": False},
                {"role": "assistant", "content": "four"})
    turn = call_log.Turn(messages, replay)
    assert chatgpt.prepare_input("", list(messages), None, router._rebase(
        "chatgpt", chatgpt, {"items": [], "consumed": 0, "active_start": 0, "active_items_start": 0},
        [turn], list(messages), config))["input"] == TURN
    other_model = runtime_config.RuntimeConfig("chatgpt", "exact-2", {}, chatgpt_binding=config.chatgpt_binding)
    assert REASONING not in chatgpt.history_items([turn], other_model.model, other_model.chatgpt_binding)
    payloads = serve(monkeypatch, [completed([message("ok")])])
    assert router.route("next", config, history_turns=[turn], on_compression=lambda _: None).ok
    assert payloads[0]["input"][:5] == TURN


@pytest.mark.parametrize("damage", ["registration", "items", "answer"])
def test_malformed_replay_is_refused_before_resume_append(connected, monkeypatch, damage):
    _, _, config = connected
    serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])])
    _, session = repl(config, "calculate\n")
    path = Path(call_log.session_log_path(session))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    end = next(entry for entry in lines if entry["type"] == "turn_end")
    if damage == "registration":
        end["replay"]["registration"] = "other"
    elif damage == "items":
        end["replay"]["items"] = end["replay"]["items"][:2]
    else:
        end["replay"]["items"][-1] = message("changed")
    path.write_text("".join(json.dumps(entry) + "\n" for entry in lines))
    before = path.read_bytes()
    with pytest.raises(call_log.ResumeError, match="invalid Responses replay"):
        call_log.load_conversation(session)
    assert path.read_bytes() == before


def test_malformed_pending_replay_is_refused_before_resume_append(connected, monkeypatch):
    _, _, config = connected
    serve(monkeypatch, [completed([REASONING, function()])], exhaustion())
    _, session = repl(config, "calculate\n")
    path = Path(call_log.session_log_path(session))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    end = next(entry for entry in lines if entry["type"] == "turn_end")
    end["continuation"]["replay"]["items"][2]["call_id"] = "tool-9"
    path.write_text("".join(json.dumps(entry) + "\n" for entry in lines))
    before = path.read_bytes()
    with pytest.raises(call_log.ResumeError, match="replay graph"):
        repl(config, "", resume=session)
    assert path.read_bytes() == before


def test_fork_copies_bound_replay_and_destination(connected, monkeypatch):
    _, _, config = connected
    serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])])
    output, child = repl(config, "calculate\n/fork\n")
    seed = next(entry for entry in entries(child) if entry["type"] == "conversation_forked")
    assert seed["replays"][0]["items"] == TURN and seed["destination"] == config.chatgpt_binding.registration
    payloads = serve(monkeypatch, [completed([message("child")])])
    output, _ = repl(config, "next\n", resume=child)
    assert "Account notice" not in output and payloads[0]["input"][:5] == TURN


def test_manual_compression_retires_compressed_replay_and_keeps_recent_turns(connected, monkeypatch):
    _, _, config = connected
    tool_turn = [[completed([REASONING, function()])], [completed([message("four")])]]
    payloads = serve(monkeypatch, *tool_turn, [completed([message("two")])], [completed([message("three")])],
                     [completed([message("short summary")])], [completed([message("after")])])
    output, session = repl(config, "calculate\nsecond\nthird\n/compress\nlast\n")
    assert "Compressed 1 turn." in output and "Account notice" not in output
    final = payloads[-1]["input"]
    assert REASONING not in final and final[0] == {"role": "user", "content": "second"}
    assert "short summary" in payloads[-1]["instructions"]
    resumed = call_log.load_conversation(session)
    assert [turn.replay["items"][0]["content"] for turn in resumed[0]] == ["second", "third", "last"]


def test_undo_and_clear_remove_replay_from_later_requests(connected, monkeypatch):
    _, _, config = connected
    payloads = serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])],
                     [completed([message("fresh")])])
    repl(config, "calculate\n/undo\nfresh\n")
    assert payloads[-1]["input"] == [{"role": "user", "content": "fresh"}]
    payloads = serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])],
                     [completed([message("clean")])])
    repl(config, "calculate\n/clear\nclean\n")
    assert payloads[-1]["input"] == [{"role": "user", "content": "clean"}]


def test_api_to_chatgpt_to_api_keeps_portable_text_and_notices_account(connected, monkeypatch, route_env,
                                                                        install_fake_urlopen):
    _, _, config = connected
    api_calls = install_fake_urlopen(["first answer", "third answer"])
    api_open = chatgpt.http.urlopen
    streams = deque([StreamResponse([completed([REASONING, message("second answer")])])])
    plan_payloads = []

    def transport(request, timeout=None):
        if request.full_url == chatgpt.API_URL:
            plan_payloads.append(json.loads(request.data))
            return streams.popleft()
        return api_open(request, timeout)

    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    _, session = repl(runtime_config.load(), "first\n")
    output, _ = repl(config, "second\n", resume=session)
    assert "Account notice" in output
    assert plan_payloads[0]["input"] == [{"role": "user", "content": "first"},
                                         {"role": "assistant", "content": "first answer"},
                                         {"role": "user", "content": "second"}]
    repl(runtime_config.load(), "third\n", resume=session)
    sent = json.dumps(json.loads(api_calls[-1]["request"].data))
    assert "second answer" in sent and "opaque-private" not in sent and "reasoning" not in sent
    openings = [entry for entry in entries(session) if entry["type"] == "routed_task_submitted"]
    assert [entry["access_method"] for entry in openings] == ["api_key", "chatgpt_plan", "api_key"]


def test_manual_compression_on_new_account_shows_notice_first(connected, monkeypatch):
    auth, state, config = connected
    serve(monkeypatch, *([completed([message(f"answer {index}")])] for index in range(3)))
    _, session = repl(config, "one\ntwo\nthree\n")
    other = connect(auth, state, "account-2")
    payloads = serve(monkeypatch, [completed([message("summary")])])
    output, _ = repl(other, "/compress\n", resume=session)
    assert output.index("Account notice") < output.index("Compressed 1 turn.") and len(payloads) == 1


def test_file_recovery_resets_chatgpt_pending_state_to_bound_task(connected, monkeypatch):
    _, _, config = connected
    serve(monkeypatch, [completed([REASONING, function()])], exhaustion())
    _, session = repl(config, "calculate\n")
    call_log.write_file_recovery("started", call_log.latest_execution(session))
    pending = call_log.load_pending_turn(session)[1]
    assert pending == {"version": 2, "task": "calculate", "provider": "chatgpt", "model": "exact-1",
                       "registration": config.chatgpt_binding.registration,
                       "messages": [{"role": "user", "content": "calculate"}], "replay": None, "fetched_urls": []}


def test_interrupted_batch_keeps_actual_and_not_executed_results_in_bound_replay(connected, monkeypatch):
    from personal_agent.tools import registry as tools_module
    _, _, config = connected
    serve(monkeypatch, [completed([REASONING, function(), function("tool-2", arguments='{"expression":"3+3"}')])])
    original = tools_module.execute_batch
    calls = []

    def execute(batch, **kwargs):
        calls.append(batch[0].id)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return original(batch, **kwargs)

    monkeypatch.setattr(tools_module, "execute_batch", execute)
    with pytest.raises(KeyboardInterrupt) as caught:
        router.route("calculate", config)
    state = caught.value.continuation
    assert state["version"] == 2 and state["replay"]["items"][-2:] == [
        OUTPUT, {"type": "function_call_output", "call_id": "tool-2", "output": json.dumps(
            {"error": "Tool call interrupted; no completion result was recorded. Completion is unknown."})}]
    assert state["replay"]["items"][1] == REASONING


@pytest.mark.parametrize("damage", ["other-call", "duplicate"])
def test_completed_turn_with_unanswered_or_repeated_tool_result_is_refused(connected, monkeypatch, damage):
    _, _, config = connected
    serve(monkeypatch, [completed([REASONING, function()])], [completed([message("four")])])
    _, session = repl(config, "calculate\n")
    path = Path(call_log.session_log_path(session))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    end = next(entry for entry in lines if entry["type"] == "turn_end")
    if damage == "other-call":
        end["messages"][2]["id"] = end["replay"]["items"][3]["call_id"] = "tool-9"
    else:
        end["messages"].insert(3, end["messages"][2])
        end["replay"]["items"].insert(4, end["replay"]["items"][3])
    path.write_text("".join(json.dumps(entry) + "\n" for entry in lines))
    before = path.read_bytes()
    with pytest.raises(call_log.ResumeError, match="invalid Responses replay"):
        call_log.load_conversation(session)
    assert path.read_bytes() == before


def test_notice_tracks_last_chatgpt_registration_across_api_turns(connected, monkeypatch, route_env, install_fake_urlopen):
    _, _, config = connected
    install_fake_urlopen(["api answer"])
    api_open = chatgpt.http.urlopen
    streams = deque([StreamResponse([completed([message("one")])]), StreamResponse([completed([message("three")])])])

    def transport(request, timeout=None):
        return streams.popleft() if request.full_url == chatgpt.API_URL else api_open(request, timeout)

    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    _, session = repl(config, "one\n")
    repl(runtime_config.load(), "two\n", resume=session)
    output, _ = repl(config, "three\n", resume=session)
    assert "Account notice" not in output and not streams
