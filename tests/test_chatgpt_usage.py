import json
import re
from collections import deque
from io import StringIO

import pytest

from personal_agent import call_log, chatgpt_auth, session_report
from personal_agent.context_budget import ExchangeLimits
from personal_agent.providers import http
from personal_agent.routing import runtime_config
from personal_agent.terminal import repl
from personal_agent.terminal.repl import render_context_usage, render_footer, run_repl
from personal_agent.token_estimate import TokenEstimate
from tests.fakes import FakeOpenRouterResponse
from tests.test_chatgpt_auth import oauth
from tests.test_chatgpt_provider import completed, connected, exhaustion, message
from tests.test_streaming import StreamResponse

PUBLIC = ExchangeLimits(128000, "Models.dev", None, None, 16000, "Models.dev", 128000, 16000, 102000)
ASSUMED = ExchangeLimits(128000, "unknown; assumed", None, None, None, None, 128000, 16000, 102000)


def assessed(limits, tokens=500):
    return {"limits": limits, "estimate": TokenEstimate(tokens, "cl100k_base", True)}


class Box:
    def __init__(self, commands, choices=()):
        self.commands = iter(commands)
        self.choices = iter(choices)
        self.footers = []

    def read(self):
        self.footers.append(self.footer())
        return next(self.commands)

    def choose(self, title, choices):
        return next(self.choices)


def test_footer_follows_selected_route_readiness_capacity_and_exhaustion():
    api = {"attempts": 3, "reported": 1, "estimated": 1, "unknown": 1}
    assert render_footer("openai", "gpt-x", 0.25, ready=True, assessment=assessed(PUBLIC), api=api) == (
        " mode: build · openai gpt-x · API key · ctx ~500/102000 public · "
        "$0.2500 (1 reported, 1 estimated, 1 unknown) · /help")
    plan = render_footer("chatgpt", "exact-1", 0.25, assessment=assessed(ASSUMED), api=api)
    assert plan == " mode: build · chatgpt exact-1 · Assinatura ChatGPT · ctx ~500/102000 assumed · /usage · /help"
    assert "Cota atingida · /usage" in render_footer("chatgpt", "exact-1", 0, assessment=assessed(ASSUMED), exhausted=True)
    manual = ExchangeLimits(90000, "manual", None, None, 16000, "Models.dev", 90000, 16000, 64000)
    assert "ctx ~70000/64000 manual" in render_footer("openai", "gpt-x", 0, assessment=assessed(manual, 70000))
    blocked = ExchangeLimits(20000, "manual", None, None, None, None, 20000, 16000, -6000)
    assert "ctx blocked (no input allowance)" in render_footer("openai", "gpt-x", 0, assessment=assessed(blocked))
    assert "ctx unknown" in render_footer("openai", "gpt-x", 0, assessment={"limits": PUBLIC, "estimate": None})
    for footer in (render_footer("chatgpt", "exact-1", 1.5, ready=False, assessment=assessed(PUBLIC)),
                   render_footer("", "", 1.5)):
        assert "unready · ctx unknown · /config" in footer
        assert "$" not in footer and "Assinatura" not in footer and "API key" not in footer
    assert render_footer("", "", 0).startswith(" mode: build · no route · unready")


def test_usage_separates_api_cost_coverage_from_plan_observations():
    config = runtime_config.RuntimeConfig("chatgpt", "exact-1", {})
    api = {"attempts": 2, "reported": 1, "estimated": 0, "unknown": 1}
    plan = {"attempts": 2, "prompt_tokens": {"total": 21, "known": 2, "missing": 0, "invalid": 0},
            "completion_tokens": {"total": 3, "known": 1, "missing": 1, "invalid": 0},
            "cached_tokens": {"total": 0, "known": 0, "missing": 1, "invalid": 1},
            "reasoning_tokens": {"total": 1, "known": 1, "missing": 1, "invalid": 0}}
    text = render_context_usage(config, None, 0.25, 0, api=api, plan=plan, exhausted=True)
    assert "access: Assinatura ChatGPT" in text
    assert "current input occupancy: unknown" in text
    assert ("spend: $0.2500 API cost [1 reported, 0 estimated, 1 unknown of 2 API Attempts]; "
            "API-only subtotal, excludes ChatGPT plan use") in text
    assert ("ChatGPT plan: cost unknown (ChatGPT plan); not priced as API spend; observed Attempts 2; "
            "input 21 [2/2 known, 0 missing, 0 invalid]; output 3 [1/2 known, 1 missing, 0 invalid]; "
            "cache-read unknown [0/2 known, 1 missing, 1 invalid]; reasoning 1 [1/2 known, 1 missing, 0 invalid]") in text
    assert "Cota atingida: wait or select another Provider" in text
    assert "Manage usage: " + chatgpt_auth.USAGE_URL in text
    assert "$0.0000" not in text and "quota" not in text.replace("no quota or reset information", "")
    current = {**assessed(ASSUMED, 900), "task_budget": 250000, "provider": "chatgpt", "model": "exact-1",
               "outcome": "completed", "reported_input": 950, "completion_tokens": 4, "cost_estimated": False,
               "sent_turns": 1, "output_reservation_estimated": True}
    text = render_context_usage(config, current, 0, 1, current=current, plan=plan)
    assert "current input occupancy: ~900/102000 assumed of effective input allowance" in text
    assert "not cumulative usage" in text and "planning estimate" in text and "spend:" not in text


def test_stale_assessment_never_reports_occupancy_after_context_or_route_changes(route_env, install_fake_urlopen):
    install_fake_urlopen(["a", "b", "c", "summary", "d", "e"])
    box = Box(["a", "b", "c", "/compress", "/usage", "d", "/mode plan", "/mode build", "/remember note",
               "e", "/model openrouter vendor/other-model", "/undo", "/exit"])
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    footers = box.footers
    occupied = [bool(re.search(r"ctx ~\d+/\d+ public", footer)) for footer in footers]
    assert occupied == [False, True, True, True, False, False, True, False, True, False, True, False, False]
    usage = output.getvalue().split("Compressed")[1]
    assert "current input occupancy: unknown" in usage and "outcome: completed" in usage
    assert all("API key" in footer for footer in footers)


def test_memory_replacement_with_same_count_invalidates_occupancy(route_env, install_fake_urlopen):
    install_fake_urlopen(["a"])
    box = Box(["/remember first note", "a", "/forget 1", "/remember " + "longer replacement " * 30, "/exit"])
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    assert [bool(re.search(r"ctx ~\d+/\d+", footer)) for footer in box.footers] == [False, False, True, False, False]


def test_reactivated_skill_with_changed_content_invalidates_occupancy(route_env, install_fake_urlopen, tmp_path):
    from tests.test_workspace_skills import _skill
    install_fake_urlopen(["a"])
    root = tmp_path / "workspace"
    root.mkdir()
    path = _skill(root, "alpha")

    def commands():
        yield from ["/skill alpha", "a", "/skill off"]
        path.write_text(path.read_text().replace("Do the task carefully.", "Do it differently " * 40))
        yield from ["/skill alpha", "/exit"]

    box = Box(commands())
    run_repl(runtime_config.load(), workspace_root=root, output_stream=StringIO(), input_box=box)
    assert [bool(re.search(r"ctx ~\d+/\d+", footer)) for footer in box.footers] == [False, False, True, False, False]


def test_plan_only_delegation_never_shows_a_dollar_subtotal(connected, monkeypatch):
    _, _, config = connected
    call_log.start_session(config)
    child = call_log.mint_session_id()
    call_log.write_delegation("started", child_session_id=child, agent_name="researcher")
    assert call_log.credit_delegated_attempt(child, {
        "attempt_id": "3" * 32, "cost": None, "access_method": "chatgpt_plan",
        "registration_ref": config.chatgpt_binding.registration, "prompt_tokens": 8, "completion_tokens": 2})
    call_log.write_delegation("finished", child_session_id=child, status="completed", coverage="complete")
    report = session_report.render()
    assert "Delegated API cost subtotal: no API Attempts; delegated ChatGPT plan Attempts 1: cost unavailable" in report
    assert "Delegated cost subtotal" not in report


@pytest.mark.parametrize("command", ["/disconnect chatgpt", "/connect chatgpt different"])
def test_disconnect_and_account_change_make_the_selected_plan_route_unready(connected, monkeypatch, command):
    auth, state, config = connected
    state["claims"]["sub"] = "account-2"
    box = Box([command, "task", "/exit"], [0, None])
    requests = []
    monkeypatch.setattr(http, "urlopen", lambda request, timeout: requests.append(request))
    output = StringIO()
    run_repl(config, output_stream=output, input_box=box)
    assert "Assinatura ChatGPT" in box.footers[0]
    assert "unready · ctx unknown · /config" in box.footers[1] and "Assinatura" not in box.footers[1]
    assert not requests and "Nothing was sent" in output.getvalue()


def test_config_shows_access_readiness_and_permission_alternative(oauth, monkeypatch, route_env):
    auth, state = oauth
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    state["scope"] = "openid profile email offline_access"
    auth.connect()
    text = repl._render_config_menu(runtime_config.load(), {}, set())
    assert "Access: API key" in text
    assert "plan permission disabled" in text and "configure your own API key" in text
    assert "Manage usage: " + chatgpt_auth.USAGE_URL in text
    unready = repl._render_config_menu(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}, readiness_error="disconnected"),
                                       {}, set())
    assert "Access: unready: disconnected" in unready


def test_linked_child_evidence_is_counted_once_in_usage_and_report(tmp_path):
    config = runtime_config.RuntimeConfig("openrouter", "vendor/test-model", {"openrouter": "key"})
    call_log.initialize_storage(tmp_path)
    call_log.start_session(config)
    reference = "b" * 32
    child = call_log.mint_session_id()
    call_log.write_delegation("started", child_session_id=child, agent_name="researcher")
    for receipt in ({"attempt_id": "1" * 32, "cost": 0.5, "cost_estimated": False, "access_method": "api_key"},
                    {"attempt_id": "2" * 32, "cost": None, "access_method": "chatgpt_plan", "registration_ref": reference,
                     "prompt_tokens": 8, "completion_tokens": 2}):
        assert call_log.credit_delegated_attempt(child, receipt)
        assert not call_log.credit_delegated_attempt(child, receipt)
    call_log.write_delegation("finished", child_session_id=child, status="completed", coverage="complete")
    usage = render_context_usage(config, None, call_log.total_cost(), 0, api=call_log.api_usage(), plan=call_log.plan_usage())
    assert "spend: $0.5000 API cost [1 reported, 0 estimated, 0 unknown of 1 API Attempts]" in usage
    assert "observed Attempts 1; input 8 [1/1 known" in usage
    report = session_report.render()
    assert ("Delegated API cost subtotal: $0.5; coverage: 1/1 known, 0 missing, 0 invalid; "
            "delegated ChatGPT plan Attempts 1: cost unavailable; child evidence incomplete/unavailable: 0") in report


def test_mixed_run_keeps_api_spend_and_unknown_plan_cost_through_retry_resume_and_fork(oauth, monkeypatch, route_env):
    auth, state = oauth
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    plan_usage = {"input_tokens": 12, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 2},
                  "output_tokens_details": {"reasoning_tokens": 1}}
    plan_streams = deque([[completed([message("plan answer")], plan_usage)], exhaustion({"input_tokens": 9}),
                          [completed([message("retried")], plan_usage)]])
    sent = []

    def respond(request, timeout=None):
        sent.append(request.full_url)
        if request.full_url == "https://api.openai.com/v1/responses":
            return StreamResponse(plan_streams.popleft())
        return FakeOpenRouterResponse({"choices": [{"message": {"content": "api answer"}}],
                                       "usage": {"cost": 0.25, "prompt_tokens": 7, "completion_tokens": 2}}).stream()

    monkeypatch.setattr(http, "urlopen", respond)
    box = Box(["api task", "/connect chatgpt", "/connect chatgpt", "plan task", "failing task", "/usage", "/retry",
               "/model openrouter vendor/test-model", "/usage", "/report", "/exit"], [0, None, 0])
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    text = output.getvalue()
    footers = box.footers
    assert "Model selection cancelled" in text
    assert "API key" in footers[2] and "$0.2500 (1 reported)" in footers[2]
    assert re.search(r"Assinatura ChatGPT · ctx unknown · /usage", footers[3])
    assert re.search(r"Assinatura ChatGPT · ctx ~\d+/102000 assumed · /usage", footers[4])
    assert "Cota atingida · /usage" in footers[5] and "$" not in footers[5]
    assert "Cota atingida" not in footers[7] and "Assinatura ChatGPT" in footers[7]
    assert "API key · ctx unknown · $0.2500 (1 reported) · /help" in footers[8]
    exhausted = text.split("llm> retried")[0].split("access: Assinatura ChatGPT")[-1]
    final = text.split("Selected openrouter")[1]
    assert "Cota atingida: wait or select another Provider" in exhausted
    assert "observed Attempts 2" in exhausted
    assert "spend: $0.2500 API cost [1 reported, 0 estimated, 0 unknown of 1 API Attempts]" in final
    assert ("ChatGPT plan: cost unknown (ChatGPT plan); not priced as API spend; observed Attempts 3; "
            "input 33 [3/3 known, 0 missing, 0 invalid]; output 6 [2/3 known, 1 missing, 0 invalid]") in final
    assert "By access method (API costs exclude ChatGPT plan use):" in final
    label = "ChatGPT plan, " + chatgpt_auth.account_label(auth.status().binding.registration).removeprefix("ChatGPT ")
    assert f"  {label}: Attempts 3" in final and "  API key: Attempts 1" in final
    assert "cost: recorded API $0.25" in final and "ChatGPT plan Attempts 3: cost unavailable (not priced)" in final
    assert f"execution chatgpt/exact-1 [{label}]" in final
    plan_rows = [row for row in final.splitlines() if f"[{label}]" in row or row.startswith("  ChatGPT plan")]
    assert plan_rows and all("$" not in row and "no API Attempts" in row for row in plan_rows)
    assert "access-fixture" not in text and "refresh-fixture" not in text
    session = call_log.current_session_id()

    resumed = StringIO()
    box = Box(["/usage", "/report", "/fork", "/usage", "/report", "/exit"])
    run_repl(runtime_config.load(), output_stream=resumed, input_box=box,
             resumed=(session, *call_log.load_conversation(session)))
    before_fork, after_fork = resumed.getvalue().split("Forked Session")
    assert "spend: $0.0000 API cost [0 reported, 0 estimated, 0 unknown of 0 API Attempts]" in before_fork
    assert "cost: recorded API $0.25" in before_fork and "ChatGPT plan Attempts 3: cost unavailable" in before_fork
    assert "No ordinary exchange assessed yet this Run." in after_fork and "spend: $0.0000" in after_fork
    assert "Session subtotal: Attempts 0" in after_fork
    assert all("ctx unknown" in footer for footer in box.footers)
