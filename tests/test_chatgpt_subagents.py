import json
import multiprocessing
import pickle
import threading
import time
from dataclasses import replace
from collections import deque
from pathlib import Path

import pytest

from personal_agent import call_log, chatgpt_auth, subagents
from personal_agent.providers import chatgpt
from personal_agent.routing import runtime_config
from personal_agent.routing.router import route
from personal_agent.tools.workspace import configure_workspace
from tests.subagent_worker import install_chatgpt_provider
from tests.test_chatgpt_auth import oauth
from tests.test_chatgpt_provider import completed, function, message
from tests.test_streaming import StreamResponse
from tests.test_subagents import interrupt_on_file, role

USAGE = {"input_tokens": 20, "output_tokens": 5}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def expire(auth):
    with auth._locked() as directory:
        record = auth._read(directory)
        record["session"].update(expires_at=0, earliest_refresh_at=0)
        auth._save(directory, record)


@pytest.fixture
def plan(tmp_path, monkeypatch, oauth):
    fixture, state = oauth

    def transport(url, **kwargs):
        result = fixture.transport(url, **kwargs)
        if url == chatgpt_auth.TOKEN and kwargs["form"]["grant_type"] == "refresh_token":
            with open(tmp_path / "token-calls", "a") as calls:
                calls.write(json.dumps({"process": "parent", "refresh_token": kwargs["form"]["refresh_token"]}) + "\n")
            time.sleep(state.get("refresh_delay", 0))
            result.update(access_token="parent-access", refresh_token="parent-refresh")
        return result

    auth = chatgpt_auth.ChatGPTAuth(transport=transport, browser=fixture.browser)
    binding = auth.connect()
    auth.acknowledge(binding)
    auth.activate(binding, "exact-1", lambda: None)
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    monkeypatch.setattr(subagents, "worker_bootstrap", install_chatgpt_provider)
    configure_workspace(tmp_path)
    role(tmp_path)
    config = runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}))
    parent = call_log.start_session(config)
    payloads = []
    spawned = []
    spawn = multiprocessing.get_context("spawn")
    original = spawn.Process

    def recording(*args, **kwargs):
        spawned.append(kwargs["args"][2])
        return original(*args, **kwargs)

    monkeypatch.setattr(spawn, "Process", recording)

    def run(actions, *, agents=1, before_dispatch=None, **script):
        (tmp_path / "worker-script.json").write_text(json.dumps({"actions": actions, **script}))
        call_log.write_routed_task(1, "Parent task", config)
        calls = [function(f"delegate-{index}", "agent", json.dumps({"name": "researcher", "task": "Inspect"}))
                 for index in range(agents)]
        responses = deque([[completed(calls, USAGE)], [completed([message("Parent completed")], USAGE)]])

        def respond(request, timeout):
            payloads.append({"bearer": request.get_header("Authorization"), **json.loads(request.data)})
            return StreamResponse(responses.popleft())

        monkeypatch.setattr(chatgpt.http, "urlopen", respond)
        if before_dispatch:
            execute = subagents.Delegation.execute
            def dispatch(self, call):
                before_dispatch()
                return execute(self, call)
            monkeypatch.setattr(subagents.Delegation, "execute", dispatch)
        results = []
        routed = route("Parent task", run.config,
                       on_tool_result=lambda result: results.append(result) if result.name == "agent" else None)
        return routed, [result.content for result in results]

    run.auth, run.state, run.binding, run.config, run.parent = auth, state, binding, config, parent
    run.payloads, run.spawned = payloads, spawned
    run.requests = lambda: lines(tmp_path / "child-requests.jsonl")
    run.refreshes = lambda: lines(tmp_path / "token-calls")
    return run


def attempts(session):
    return [entry for entry in call_log._read_entries(session) if entry["type"] == "attempt"]


def receipts(parent):
    return [entry for entry in call_log._read_entries(parent) if entry["type"] == "delegation_receipt"]


def test_child_inherits_selected_reasoning_effort(plan):
    offering = replace(plan.config.offering, reasoning_levels=("medium", "xhigh"), default_reasoning="medium")
    plan.config = replace(plan.config, offering=offering, chatgpt_reasoning_effort="xhigh")
    routed, results = plan([{"answer": "child done"}])
    assert routed.ok and results[0]["answer"] == "child done"
    assert plan.spawned[0]["config"].chatgpt_reasoning_effort == "xhigh"
    assert all(request["reasoning"] == {"effort": "xhigh"} for request in [*plan.payloads, *plan.requests()])


def test_child_inherits_pinned_account_model_and_capacity_without_tokens(plan):
    routed, results = plan([{"calls": [("read_file", {"path": "missing"})]}, {"answer": "child done"}])
    assert routed.ok and routed.answer == "Parent completed", routed.error
    child = results[0]
    assert child["status"] == "completed" and child["answer"] == "child done"
    payload = plan.spawned[0]
    assert (payload["config"].provider, payload["config"].model) == ("chatgpt", "exact-1")
    assert payload["config"].chatgpt_binding == plan.binding
    assert dict(payload["config"].capacity_snapshot) == dict(plan.config.capacity_snapshot)
    encoded = pickle.dumps(payload)
    assert all(secret.encode() not in encoded for secret in ("access-fixture", "refresh-fixture"))
    requests = plan.requests()
    assert [(request["model"], request["bearer"]) for request in requests] == [("exact-1", "access-fixture")] * 2
    assert "access-fixture" not in json.dumps([request["input"] for request in requests])

    entries = call_log._read_entries(child["session_id"])
    assert (entries[0]["access_method"], entries[0]["registration_ref"]) == ("chatgpt_plan", plan.binding.registration)
    end = next(entry for entry in entries if entry["type"] == "turn_end")
    assert end["replay"]["registration"] == plan.binding.registration and end["replay"]["model"] == "exact-1"
    child_attempts = attempts(child["session_id"])
    assert len(child_attempts) == 2 and all(entry["registration_ref"] == plan.binding.registration for entry in child_attempts)
    credited = receipts(plan.parent)
    assert sorted(entry["attempt_id"] for entry in credited) == sorted(entry["attempt_id"] for entry in child_attempts)
    assert all(entry["access_method"] == "chatgpt_plan" and entry["registration_ref"] == plan.binding.registration
               and entry["cost"] is None and not entry["cost_estimated"]
               and (entry["prompt_tokens"], entry["completion_tokens"], entry["cached_tokens"], entry["reasoning_tokens"])
               == (10, 2, 3, 1) for entry in credited)
    usage = call_log.plan_usage()
    assert usage["attempts"] == 4
    assert usage["prompt_tokens"] == {"total": 60, "known": 4, "missing": 0, "invalid": 0}
    assert usage["cached_tokens"] == {"total": 6, "known": 2, "missing": 2, "invalid": 0}
    assert call_log.total_cost() == 0


@pytest.mark.parametrize("change", ["disconnect", "replace", "reauthorize", "model"])
def test_account_change_between_admission_and_dispatch_never_retargets_child_or_parent(plan, monkeypatch, change):
    def switch():
        if change == "disconnect":
            plan.auth.disconnect()
        elif change == "model":
            plan.auth.activate(plan.binding, "exact-2", lambda: None)
            monkeypatch.setenv("PA_MODEL", "exact-2")
        else:
            if change == "replace":
                plan.state["claims"] = {"sub": "account-2"}
            new = plan.auth.connect(different=change == "replace")
            plan.auth.acknowledge(new)
            plan.auth.activate(new, "exact-1", lambda: None)
            assert new != plan.binding

    routed, results = plan([{"answer": "child done"}], before_dispatch=switch)
    child = results[0]
    if change == "model":
        assert routed.ok and child["status"] == "completed"
        assert [request["model"] for request in plan.requests()] == ["exact-1"]
        assert [payload["model"] for payload in plan.payloads] == ["exact-1", "exact-1"]
        return
    assert child["status"] == "error" and "changed or disconnected" in child["error"]
    assert plan.requests() == [] and attempts(child["session_id"]) == []
    assert not routed.ok and "changed or disconnected" in routed.error and len(plan.payloads) == 1
    assert routed.continuation["messages"][-1]["content"]["session_id"] == child["session_id"]
    assert plan.refreshes() == []


@pytest.mark.parametrize("first", ["parent", "child"])
def test_parent_and_child_refresh_rotate_once_within_the_pinned_generation(plan, first):
    racing = []

    def refresh_soon():
        expire(plan.auth)
        if first == "parent":
            plan.state["refresh_delay"] = 1
            thread = threading.Thread(target=lambda: racing.append(plan.auth.resolve(plan.binding).access_token))
            thread.start()
            racing.append(thread)

    call_log.start_coverage(True)
    routed, results = plan([{"answer": "secret check", "echo": True}], before_dispatch=refresh_soon)
    call_log.end_coverage(True)
    if racing:
        racing[0].join(5)
    assert routed.ok, routed.error
    calls = plan.refreshes()
    assert [call["process"] for call in calls] == [first]
    assert calls[0]["refresh_token"] == "refresh-fixture"
    current = json.loads(plan.auth.path.read_text())["session"]
    assert current["generation"] == plan.binding.generation
    child_bearer = plan.requests()[0]["bearer"]
    assert child_bearer == current["access_token"] and plan.payloads[1]["bearer"] == "Bearer " + child_bearer
    if first == "parent":
        assert racing[1:] == ["parent-access"] and child_bearer == "parent-access"
    else:
        assert child_bearer.startswith("child-access-")

    child = results[0]
    assert child["answer"].startswith("secret check") and "[redacted]" in child["answer"]
    evidence = json.dumps(results) + "".join(Path(path(session)).read_text() for session in (plan.parent, child["session_id"])
                                             for path in (call_log.session_log_path, call_log.detail_path))
    for secret in ("access-fixture", "refresh-fixture", "parent-access", "parent-refresh", "child-access-", "child-refresh"):
        assert secret not in evidence and secret not in json.dumps(plan.payloads[1]["input"])


def test_child_plan_exhaustion_stops_parent_and_further_children_without_fallback(plan):
    routed, results = plan([{"calls": [("read_file", {"path": "missing"})]}, {"exhaust": True}], agents=2)
    assert results[0]["status"] == "error" and "Cota atingida" in results[0]["error"] and "condition" not in results[0]
    assert "not dispatched" in results[1]["error"]
    assert not routed.ok and routed.plan_exhausted and "Cota atingida" in routed.error
    assert len(plan.payloads) == 1 and len(plan.spawned) == 1
    messages = routed.continuation["messages"]
    assert [message["role"] for message in messages[-2:]] == ["tool_result", "tool_result"]
    child = results[0]["session_id"]
    entries = call_log._read_entries(child)
    end = next(entry for entry in entries if entry["type"] == "turn_end")
    assert end["status"] == "error" and end["continuation"]["messages"][-1]["role"] == "tool_result"
    assert attempts(child)[-1]["error_code"] == "subscription_sharing_usage_limit_exceeded"
    assert len(receipts(plan.parent)) == 2 and call_log.plan_usage()["attempts"] == 3
    started = [entry for entry in call_log._read_entries(plan.parent) if entry["type"] == "delegation_started"]
    assert len(started) == 1


def test_parent_cancellation_reaps_plan_child_and_credits_each_attempt_once(plan, tmp_path):
    ready = tmp_path / "child-ready"
    with interrupt_on_file(ready) as observed:
        with pytest.raises(KeyboardInterrupt) as interrupted:
            plan([{"calls": [("read_file", {"path": "missing"})]}, {"wait": str(ready)}])
    assert observed
    outcome = interrupted.value.continuation["messages"][-1]["content"]
    assert outcome["error"] == "Subagent interrupted"
    child_attempts = attempts(outcome["session_id"])
    credited = receipts(plan.parent)
    assert sorted(entry["attempt_id"] for entry in credited) == sorted(entry["attempt_id"] for entry in child_attempts)
    assert len(child_attempts) == 2 and call_log.plan_usage()["attempts"] == 3
    finished = [entry for entry in call_log._read_entries(plan.parent) if entry["type"] == "delegation_finished"]
    assert finished[-1]["status"] == "interrupted"
    assert len(plan.payloads) == 1


def test_delegated_receipts_keep_access_identity_and_never_price_plan_work(tmp_path):
    configure_workspace(tmp_path)
    call_log.start_session(runtime_config.RuntimeConfig("openrouter", "vendor/test-model", {"openrouter": "key"}))
    child = call_log.mint_session_id()
    reference = "a" * 32
    assert call_log.credit_delegated_attempt(child, {"attempt_id": "1" * 32, "cost": 0.5, "cost_estimated": False,
                                                     "access_method": "api_key"})
    assert call_log.credit_delegated_attempt(child, {"attempt_id": "2" * 32, "cost": 9.0, "access_method": "chatgpt_plan",
                                                     "registration_ref": reference, "prompt_tokens": 7,
                                                     "completion_tokens": -1, "invalid_usage": ["cached_tokens"]})
    assert not call_log.credit_delegated_attempt(child, {"attempt_id": "2" * 32, "access_method": "chatgpt_plan",
                                                         "registration_ref": reference, "prompt_tokens": 7})
    for receipt in ({"access_method": "chatgpt_plan", "registration_ref": "account@example.com"},
                    {"access_method": "oauth"}):
        with pytest.raises(ValueError):
            call_log.credit_delegated_attempt(child, {"attempt_id": "3" * 32, **receipt})
    assert call_log.total_cost() == 0.5
    usage = call_log.plan_usage()
    assert usage["attempts"] == 1 and usage["prompt_tokens"]["total"] == 7
    assert (usage["completion_tokens"]["invalid"], usage["cached_tokens"]["invalid"], usage["reasoning_tokens"]["missing"]) == (1, 1, 1)
    plan_receipt = receipts(call_log.current_session_id())[1]
    assert (plan_receipt["cost"], plan_receipt["cost_status"], plan_receipt["registration_ref"]) == (None, "invalid", reference)
