import json
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from prompt_toolkit.output.base import Size

from personal_agent import call_log
from personal_agent.providers import http
from personal_agent.providers.contract import ToolCall
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import registry, workspace
from tests.fakes import FakeOpenRouterResponse


def _entries():
    return [entry for line in Path(call_log.session_log_path()).read_text().splitlines()
            if (entry := json.loads(line))["type"] not in {"audit_event", "audit_coverage_start", "audit_coverage_end"}]


def _call(questions, id="q"):
    return {"id": id, "name": "question", "arguments": {"questions": questions}}


class Box:
    def __init__(self, tasks, answers):
        self.tasks = iter(tasks)
        self.answers = iter(answers)
        self.prompts = []

    def read(self):
        return next(self.tasks)

    def ask(self, prompt):
        self.prompts.append(prompt)
        value = next(self.answers)
        if isinstance(value, BaseException):
            raise value
        return value

    def terminal_size(self):
        return Size(rows=24, columns=80)


def test_all_four_questions_and_choices_are_visible_before_first_prompt(route_env, install_fake_urlopen):
    install_fake_urlopen([{"tool_calls": [_call([
        {"text": f"Question {i}?", "choices": ["yes", "no"]} for i in range(1, 5)
    ])]}, "done"])
    output = StringIO()

    class WatchingBox(Box):
        def ask(self, prompt):
            if not self.prompts:
                text = output.getvalue()
                assert all(f"{i}. Question {i}?" in text for i in range(1, 5))
                assert text.count("  2. no") == 4
            return super().ask(prompt)

    box = WatchingBox(["summarize this request", "/exit"], ["yes"] * 4)
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    assert box.prompts == [f"Answer {i}: " for i in range(1, 5)]


@pytest.mark.parametrize("object_choices", [False, True])
def test_interactive_batch_shows_all_questions_before_answers_and_reaches_followup_and_resume(
    object_choices, route_env, install_fake_urlopen
):
    questions = [
        {"text": "First\x1b[2K?", "choices": ["Yes\r", "No"]},
        {"text": "Second?", "choices": ["One", "Two"]},
        {"text": "Third?"},
        {"text": "Fourth?"},
    ]
    if object_choices:
        questions[0]["choices"] = [{"text": label} for label in questions[0]["choices"]]
    calls = install_fake_urlopen([{"tool_calls": [_call(questions)]}, "done"])
    output = StringIO()
    box = Box(["summarize this request", "/history", "/exit"], ["1", "text: 2", "free", "last"])
    run_repl(runtime_config.load(), output_stream=output, input_box=box)

    expected = {"answers": [
        {"question": "First\x1b[2K?", "answer": "Yes\r"},
        {"question": "Second?", "answer": "2"},
        {"question": "Third?", "answer": "free"},
        {"question": "Fourth?", "answer": "last"},
    ]}
    text = output.getvalue()
    assert text.index("4. Fourth?") < text.index("tool> question")
    assert "\x1b[2K" not in text and "\\x1b" in text and "\\x0d" in text
    assert "1. First" in text and "2. No" in text
    assert box.prompts == ["Answer 1: ", "Answer 2: ", "Answer 3: ", "Answer 4: "]
    assert len(calls) == 2
    followup = json.loads(calls[1]["request"].data)
    assert followup["messages"][-1] == {
        "role": "tool", "tool_call_id": "q", "content": json.dumps(expected),
    }
    assert "tool_result: question [ok]" in text and "Fourth?" in text
    entries = _entries()
    assert next(e for e in entries if e["type"] == "tool_execution")["result"] == expected
    session_id = call_log.current_session_id()
    turns, summary, todos, _ = call_log.load_conversation(session_id)
    assert turns[0][2]["content"] == expected
    run_repl(runtime_config.load(), input_stream=StringIO("/history\nexit\n"), output_stream=output,
             resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]))
    assert text in output.getvalue()


@pytest.mark.parametrize("mode", ["plan", "build", "auto"])
def test_single_question_free_text_reprompt_and_mode_offering(mode, route_env, install_fake_urlopen):
    calls = install_fake_urlopen([{"tool_calls": [_call([{"text": "Choose?", "choices": ["one", "two"]}])]}, "done"])
    box = Box([f"/mode {mode}", "summarize this request", "/exit"], [" ", "x" * 1001, "2"])
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    assert len(box.prompts) == 3
    assert "blank" in output.getvalue().lower() and "1000" in output.getvalue()
    initial = json.loads(calls[0]["request"].data)
    assert "question" in {tool["function"]["name"] for tool in initial["tools"]}
    assert "tool> question" in output.getvalue()
    assert _entries()[-2]["type"] == "turn_end"


def test_free_text_with_choices_is_kept_at_1000_character_boundary(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([{"tool_calls": [_call([{"text": "Choose?", "choices": ["one"]}])]}, "done"])
    run_repl(runtime_config.load(), output_stream=StringIO(),
             input_box=Box(["summarize this request", "/exit"], ["x" * 1000]))
    followup = json.loads(calls[1]["request"].data)
    assert json.loads(followup["messages"][-1]["content"]) == {
        "answers": [{"question": "Choose?", "answer": "x" * 1000}],
    }


@pytest.mark.parametrize("text, label", [("x" * 500, "y" * 120), ("ok", "one")])
@pytest.mark.parametrize("object_choices", [False, True])
def test_registry_accepts_schema_boundaries_and_1000_character_answer(text, label, object_choices):
    questions = [{"text": text, "choices": [{"text": label} if object_choices else label] * 6}] * 4
    answers = {"answers": [{"question": text, "answer": "z" * 1000}] * 4}
    result = registry.execute_batch(
        [ToolCall(**_call(questions))], question=lambda batch: answers,
    )[0]
    assert result.content == answers and result.arguments == {"questions": questions}


@pytest.mark.parametrize("tool_name", ["write", "edit", "shell", "webfetch"])
@pytest.mark.parametrize("later_round", [False, True])
def test_question_answer_does_not_confirm_later_or_same_batch_tool(
    tool_name, later_round, route_env, install_fake_urlopen, tmp_path
):
    workspace.configure_workspace(tmp_path)
    (tmp_path / "note.txt").write_text("before")
    registry.enable_shell_tool()
    args = {
        "write": {"path": "new.txt", "content": "changed"},
        "edit": {"path": "note.txt", "old_string": "before", "new_string": "changed"},
        "shell": {"command": "touch new.txt"},
        "webfetch": {"url": "https://example.com/"},
    }
    modifying = {"id": "m", "name": tool_name, "arguments": args[tool_name]}
    question = _call([{"text": "Proceed?", "choices": ["yes", "no"]}])
    responses = ([{"tool_calls": [question]}, {"tool_calls": [modifying]}, "done"] if later_round
                 else [{"tool_calls": [question, modifying]}, "done"])
    calls = install_fake_urlopen(responses)
    box = Box(["summarize this request", "/history", "/exit"], ["yes", "n"])
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    assert len(calls) == len(responses)
    assert len(box.prompts) == 2 and box.prompts[0] == "Answer 1: "
    assert box.prompts[1] in ("Apply this change? [y/N] ", "Run this command? [y/N] ", "Fetch this URL? [y/N] ")
    assert [(e["name"], e["ok"]) for e in _entries() if e["type"] == "tool_execution"] == [
        ("question", True), (tool_name, False),
    ]
    assert (tmp_path / "note.txt").read_text() == "before" and not (tmp_path / "new.txt").exists()
    assert "tool_result: question [ok]" in output.getvalue()


@pytest.mark.parametrize("provider", ["openrouter", "anthropic", "openai", "gemini"])
def test_question_result_correlates_with_provider_followup(provider, route_env, install_fake_urlopen):
    config = runtime_config.load()
    config = replace(config, api_keys={**config.api_keys, provider: "test-key"}, provider=provider)
    calls = install_fake_urlopen([{"tool_calls": [_call([{"text": "Which?"}], id="question-id")]}, "done"])
    box = Box(["summarize this request", "/exit"], ["plain answer"])
    run_repl(config, output_stream=StringIO(), input_box=box)
    assert len(calls) == 2
    body = json.loads(calls[1]["request"].data)
    result = {"answers": [{"question": "Which?", "answer": "plain answer"}]}
    if provider in ("openrouter", "openai"):
        assert body["messages"][-1] == {
            "role": "tool", "tool_call_id": "question-id", "content": json.dumps(result),
        }
    elif provider == "anthropic":
        assert body["messages"][-1] == {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "question-id", "content": json.dumps(result)},
        ]}
    else:
        parts = body["contents"][-1]["parts"]
        assert parts == [{"functionResponse": {"name": "question", "response": result}}]


def test_gemini_explicit_question_id_is_kept_on_followup(route_env, monkeypatch):
    config = runtime_config.load()
    config = replace(config, api_keys={**config.api_keys, "gemini": "test-key"}, provider="gemini")
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(json.loads(request.data))
        if len(requests) == 1:
            return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [
                {"functionCall": {"id": "question-id", "name": "question", "args": {"questions": [{"text": "Why?"}]}}}
            ]}}]})
        return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": "done"}]}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    run_repl(config, output_stream=StringIO(), input_box=Box(["summarize this request", "/exit"], ["because"]))
    assert len(requests) == 2
    assert requests[1]["contents"][-1]["parts"] == [{"functionResponse": {
        "id": "question-id", "name": "question", "response": {
            "answers": [{"question": "Why?", "answer": "because"}],
        },
    }}]


@pytest.mark.parametrize("questions", [
    [], [{"text": "x"}] * 5, [{"text": " "}], [{"text": "x" * 501}],
    [{"text": "ok", "choices": []}], [{"text": "ok", "choices": ["x"] * 7}],
    [{"text": "ok", "choices": [" "]}], [{"text": "ok", "choices": ["x" * 121]}],
    [{"text": "ok", "other": 1}], [{"text": 42}],
    [{"text": "ok", "choices": [{}]}],
    [{"text": "ok", "choices": [{"label": "one"}]}],
    [{"text": "ok", "choices": [{"text": "one", "extra": "unexpected"}]}],
    [{"text": "ok", "choices": [{"text": 42}]}],
    [{"text": "ok", "choices": [{"text": None}]}],
    [{"text": "ok", "choices": [{"text": ""}]}],
    [{"text": "ok", "choices": [{"text": " "}]}],
    [{"text": "ok", "choices": [{"text": "x" * 121}]}],
])
def test_registry_rejects_invalid_question_batches_before_input(questions):
    called = []
    result = registry.execute_batch([ToolCall(**_call(questions))], question=lambda q: called.append(q))[0]
    assert result.is_error and result.content["error"].startswith("invalid arguments:")
    assert result.arguments is None and called == []


@pytest.mark.parametrize("args", [{}, {"questions": "x"}, {"questions": [{"text": "ok", "choices": [4]}]},
                                  {"questions": [{"text": "ok"}], "extra": 1}])
def test_registry_rejects_malformed_question_envelope(args):
    result = registry.execute_batch([ToolCall(id="q", name="question", arguments=args)])[0]
    assert result.is_error and "invalid arguments" in result.content["error"]


@pytest.mark.parametrize("provider", ["openrouter", "anthropic", "openai", "gemini"])
def test_object_and_mixed_choices_are_asked_without_a_model_retry(provider, route_env, install_fake_urlopen):
    choices = ["Full MVP with a few core modules", "Single module built deeply"]
    questions = [
        {"text": "Which scope fits you best?", "choices": [{"text": choice} for choice in choices]},
        {"text": "Which starting point?", "choices": ["Greenfield", {"text": "Existing ERP"}]},
    ]
    config = runtime_config.load()
    config = replace(config, api_keys={**config.api_keys, provider: "test-key"}, provider=provider)
    calls = install_fake_urlopen([
        {"tool_calls": [_call(questions, id="erp-question")]},
        "ERP requirements captured",
    ])
    box = Box(["what can you build ? Can you build a ERP system", "/exit"], ["1", "2"])
    output = StringIO()

    run_repl(config, output_stream=output, input_box=box)

    bodies = [json.loads(call["request"].data) for call in calls]
    assert len(bodies) == 2
    assert box.prompts == ["Answer 1: ", "Answer 2: "]
    result = {
        "answers": [{"question": questions[0]["text"], "answer": choices[0]},
                    {"question": questions[1]["text"], "answer": "Existing ERP"}],
    }
    if provider in ("openrouter", "openai"):
        assert json.loads(bodies[1]["messages"][-1]["content"]) == result
    elif provider == "anthropic":
        assert json.loads(bodies[1]["messages"][-1]["content"][0]["content"]) == result
    else:
        assert bodies[1]["contents"][-1]["parts"][0]["functionResponse"]["response"] == result
    execution = next(entry for entry in _entries() if entry["type"] == "tool_execution")
    assert execution["ok"] and execution["arguments"] == {"questions": questions} and execution["result"] == result
    text = output.getvalue()
    assert "  1. Full MVP with a few core modules" in text and "  2. Existing ERP" in text
    assert "invalid arguments" not in text and "{'text':" not in text
    assert "ERP requirements captured" in output.getvalue()


def test_piped_question_error_preserves_next_task(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([{"tool_calls": [_call([{"text": "Ask?"}])]}, "error handled", "next answer"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("first task\nsecond task\nexit\n"), output_stream=output)
    assert len(calls) == 3
    assert "interactive input is required" in output.getvalue()
    assert json.loads(calls[2]["request"].data)["messages"][-1]["content"] == "second task"
    assert [e["ok"] for e in _entries() if e["type"] == "tool_execution"] == [False]


@pytest.mark.parametrize("interruption", [EOFError(), KeyboardInterrupt()])
def test_eof_or_interrupt_after_completed_tool_keeps_prior_execution(
    interruption, route_env, install_fake_urlopen
):
    calls = install_fake_urlopen([{"tool_calls": [
        {"id": "c", "name": "calculator", "arguments": {"expression": "2+2"}},
        _call([{"text": "First?"}, {"text": "Second?"}]),
    ]}, "finished"] if isinstance(interruption, EOFError) else [{"tool_calls": [
        {"id": "c", "name": "calculator", "arguments": {"expression": "2+2"}},
        _call([{"text": "First?"}, {"text": "Second?"}]),
    ]}])
    box = Box(["summarize this request", "/exit"], ["yes", interruption])
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    tools = [e for e in _entries() if e["type"] == "tool_execution"]
    assert tools[0]["name"] == "calculator" and tools[0]["ok"]
    if isinstance(interruption, EOFError):
        assert len(calls) == 2 and len(tools) == 2
        assert "end of input" in tools[1]["error"].lower()
        assert _entries()[-2]["status"] == "ok"
        followup = json.loads(calls[1]["request"].data)
        assert "end of input" in followup["messages"][-1]["content"]
        assert "answers" not in followup["messages"][-1]["content"]
        session_id = call_log.current_session_id()
        turns, summary, todos, _ = call_log.load_conversation(session_id)
        assert turns[0][3]["is_error"] is True
        run_repl(runtime_config.load(), input_stream=StringIO("/history\nexit\n"), output_stream=output,
                 resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]))
        assert "tool_result: question [error]" in output.getvalue()
    else:
        assert len(calls) == 1 and len(tools) == 1
        assert _entries()[-2]["status"] == "interrupted"


FOUR = ["alpha", "beta", "gamma", "delta"]


def _answer_one(install_fake_urlopen, choices, answers):
    question = {"text": "Pick?", **({"choices": choices} if choices else {})}
    calls = install_fake_urlopen([{"tool_calls": [_call([question])]}, "done"])
    box = Box(["summarize this request", "/exit"], answers)
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    assert len(calls) == 2
    content = json.loads(json.loads(calls[1]["request"].data)["messages"][-1]["content"])
    execution = next(e for e in _entries() if e["type"] == "tool_execution")
    assert execution["result"] == content and execution["arguments"] == {"questions": [question]}
    return content["answers"][0]["answer"], box.prompts, output.getvalue()


@pytest.mark.parametrize("answers, expected, prompts", [
    (["10", "1"], "alpha", ["Answer 1: ", "Answer 1: "]),
    (["5", "custom"], "custom", ["Answer 1: ", "Custom answer 1: "]),
    (["0", "-1", "-0", "+0", "6", "9" * 1000, "1"], "alpha", ["Answer 1: "] * 7),
    ([" 2 "], "beta", ["Answer 1: "]),
    (["002"], "beta", ["Answer 1: "]),
    (["+3"], "gamma", ["Answer 1: "]),
    (["\t04\n"], "delta", ["Answer 1: "]),
    ([" +005 ", "mine"], "mine", ["Answer 1: ", "Custom answer 1: "]),
    (["1.5"], "1.5", ["Answer 1: "]),
    ([" free text "], " free text ", ["Answer 1: "]),
    (["text: 3"], "3", ["Answer 1: "]),
    (["text: 10"], "10", ["Answer 1: "]),
    (["5", "10"], "10", ["Answer 1: ", "Custom answer 1: "]),
    (["5", "5"], "5", ["Answer 1: ", "Custom answer 1: "]),
    (["5", "text: 5"], "text: 5", ["Answer 1: ", "Custom answer 1: "]),
    (["5", "  spaced  "], "  spaced  ", ["Answer 1: ", "Custom answer 1: "]),
    (["5", " ", "x" * 1001, "x" * 1000], "x" * 1000, ["Answer 1: "] + ["Custom answer 1: "] * 3),
])
def test_choice_selection_other_and_invalid_numbers(answers, expected, prompts, route_env, install_fake_urlopen):
    answer, asked, text = _answer_one(install_fake_urlopen, FOUR, answers)
    assert answer == expected and asked == prompts
    assert "  4. delta\n  5. Other (custom answer)\n" in text
    invalid = ("10", "0", "-1", "-0", "+0", "6", "9" * 1000)
    assert text.count("Choose a number from 1 to 5") == sum(
        1 for raw, prompt in zip(answers, prompts) if prompt == "Answer 1: " and raw in invalid)


def test_six_choices_offer_seventh_local_other(route_env, install_fake_urlopen):
    choices = [f"c{i}" for i in range(1, 7)]
    answer, prompts, text = _answer_one(install_fake_urlopen, choices, ["8", "7", "own"])
    assert answer == "own" and prompts == ["Answer 1: ", "Answer 1: ", "Custom answer 1: "]
    assert "  7. Other (custom answer)" in text and "Choose a number from 1 to 7" in text


@pytest.mark.parametrize("answers, expected", [
    (["5"], "5"), (["-1"], "-1"), (["0"], "0"), (["text: 5"], "5"), (["text: ", "ok"], "ok"),
])
def test_questions_without_choices_keep_numeric_and_escape_answers(answers, expected, route_env, install_fake_urlopen):
    answer, prompts, text = _answer_one(install_fake_urlopen, None, answers)
    assert answer == expected and prompts == ["Answer 1: "] * len(answers)
    assert "Other" not in text and "Choose a number" not in text


@pytest.mark.parametrize("interruption", [EOFError(), KeyboardInterrupt()])
def test_eof_or_interrupt_during_custom_answer(interruption, route_env, install_fake_urlopen):
    responses = [{"tool_calls": [_call([{"text": "Pick?", "choices": FOUR}])]}]
    calls = install_fake_urlopen(responses + (["finished"] if isinstance(interruption, EOFError) else []))
    box = Box(["summarize this request", "/exit"], ["5", interruption])
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    assert box.prompts == ["Answer 1: ", "Custom answer 1: "]
    tools = [e for e in _entries() if e["type"] == "tool_execution"]
    if isinstance(interruption, EOFError):
        assert len(calls) == 2 and "end of input" in tools[0]["error"].lower()
    else:
        assert len(calls) == 1 and tools == [] and _entries()[-2]["status"] == "interrupted"


def test_other_yes_does_not_confirm_later_mutating_tool(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    question = _call([{"text": "Proceed?", "choices": ["no", "maybe"]}])
    write = {"id": "w", "name": "write", "arguments": {"path": "new.txt", "content": "changed"}}
    calls = install_fake_urlopen([{"tool_calls": [question, write]}, "done"])
    box = Box(["summarize this request", "/exit"], ["3", "yes", "n"])
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    assert box.prompts == ["Answer 1: ", "Custom answer 1: ", "Apply this change? [y/N] "]
    assert len(calls) == 2 and not (tmp_path / "new.txt").exists()
    assert [(e["name"], e["ok"]) for e in _entries() if e["type"] == "tool_execution"] == [
        ("question", True), ("write", False),
    ]
    assert next(e for e in _entries() if e["type"] == "tool_execution")["result"] == {
        "answers": [{"question": "Proceed?", "answer": "yes"}],
    }
