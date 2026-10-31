from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator

from personal_agent.providers.contract import ToolCall, ToolResult
from personal_agent.terminal.repl import format_tool_line
from personal_agent.tools import builtins, registry as tools


# --- calculator (R10) --------------------------------------------------


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("2 + 2", 4),
        ("2+2*3", 8),
        ("(2 + 3) * 4", 20),
        ("-5 + 2", -3),
        ("+5", 5),
        ("10 / 4", 2.5),
        ("-(1 + 2)", -3),
        ("1.5 + 2.25", 3.75),
    ],
)
def test_calculator_evaluates_ordinary_arithmetic(expression, expected):
    assert builtins.calculator({"expression": expression}) == {"result": expected}


def test_calculator_rejects_division_by_zero():
    with pytest.raises(builtins.ToolExecutionError, match="division by zero"):
        builtins.calculator({"expression": "1 / 0"})


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "open('/etc/passwd')",
        "(1).__class__",
        "[1, 2, 3]",
        "{1: 2}",
        "1 if True else 2",
        "True",
        "1 == 1",
        "1 and 2",
        "x + 1",
        "2 ** 3",
        "'a' + 'b'",
    ],
)
def test_calculator_rejects_code_like_or_disallowed_expressions(expression):
    with pytest.raises(builtins.ToolExecutionError):
        builtins.calculator({"expression": expression})


def test_calculator_rejects_expressions_over_the_character_limit():
    expression = "1+" * 200 + "1"
    assert len(expression) > builtins.MAX_EXPRESSION_CHARS
    with pytest.raises(builtins.ToolExecutionError, match="characters"):
        builtins.calculator({"expression": expression})


def test_calculator_rejects_expressions_over_the_node_limit():
    expression = "+".join(["1"] * 40)
    with pytest.raises(builtins.ToolExecutionError, match="syntax-tree nodes"):
        builtins.calculator({"expression": expression})


def test_calculator_rejects_invalid_syntax():
    with pytest.raises(builtins.ToolExecutionError, match="invalid expression syntax"):
        builtins.calculator({"expression": "2 +"})


def test_calculator_rejects_results_over_the_absolute_value_bound():
    with pytest.raises(builtins.ToolExecutionError, match="out of bounds"):
        builtins.calculator({"expression": "1e100 * 10"})


def test_calculator_rejects_oversized_literal():
    with pytest.raises(builtins.ToolExecutionError, match="out of bounds"):
        builtins.calculator({"expression": "1e200"})


# --- current_time (R11) -------------------------------------------------


def test_current_time_uses_deterministic_clock_and_reports_explicit_utc(monkeypatch):
    fixed = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(builtins, "_clock", lambda: fixed)

    result = builtins.current_time({})

    assert result == {"utc_time": "2026-09-22T12:00:00+00:00"}


# --- Tool boundary (R12) -------------------------------------------------


def test_execute_batch_rejects_unknown_tool_without_invoking_anything():
    call = ToolCall(id="1", name="not_a_tool", arguments={})

    results = tools.execute_batch([call])

    assert len(results) == 1
    assert results[0].is_error is True
    assert "unknown tool" in results[0].content["error"]


def test_execute_batch_rejects_malformed_json_arguments_without_invoking():
    call = ToolCall(id="1", name="calculator", arguments=None, arguments_raw="not json")

    results = tools.execute_batch([call])

    assert results[0].is_error is True
    assert "invalid arguments" in results[0].content["error"]


def test_execute_batch_rejects_missing_required_argument():
    call = ToolCall(id="1", name="calculator", arguments={})

    results = tools.execute_batch([call])

    assert results[0].is_error is True
    assert results[0].content["error"] == "invalid arguments: 'expression' is a required property"


def test_execute_batch_rejects_extra_argument_keys():
    call = ToolCall(id="1", name="calculator", arguments={"expression": "1+1", "extra": True})

    results = tools.execute_batch([call])

    assert results[0].is_error is True
    assert results[0].content["error"] == "invalid arguments: Additional properties are not allowed ('extra' was unexpected)"


def test_execute_batch_rejects_wrong_argument_type():
    call = ToolCall(id="1", name="calculator", arguments={"expression": 5})

    results = tools.execute_batch([call])

    assert results[0].is_error is True


def test_execute_batch_runs_valid_calls_serially_in_order_one_result_each():
    calls = [
        ToolCall(id="1", name="calculator", arguments={"expression": "1+1"}),
        ToolCall(id="2", name="current_time", arguments={}),
        ToolCall(id="3", name="calculator", arguments={"expression": "2+2"}),
    ]

    results = tools.execute_batch(calls)

    assert [r.id for r in results] == ["1", "2", "3"]
    assert results[0].content == {"result": 2}
    assert results[0].is_error is False
    assert results[0].arguments == {"expression": "1+1"}
    assert "utc_time" in results[1].content
    assert results[2].content == {"result": 4}


def test_execute_batch_reports_null_arguments_for_calls_rejected_before_execution():
    calls = [
        ToolCall(id="1", name="not_a_tool", arguments={}),
        ToolCall(id="2", name="calculator", arguments=None, arguments_raw="not json"),
        ToolCall(id="3", name="calculator", arguments={"expression": 5}),
    ]

    results = tools.execute_batch(calls)

    assert [r.arguments for r in results] == [None, None, None]


def test_execute_batch_reports_the_passed_arguments_for_a_call_that_executes_but_errors():
    call = ToolCall(id="1", name="calculator", arguments={"expression": "1/0"})

    results = tools.execute_batch([call])

    assert results[0].is_error is True
    assert results[0].arguments == {"expression": "1/0"}


def test_execute_batch_allows_repeated_tool_name_with_distinct_ids():
    calls = [
        ToolCall(id="1", name="calculator", arguments={"expression": "1+1"}),
        ToolCall(id="2", name="calculator", arguments={"expression": "3+3"}),
    ]

    results = tools.execute_batch(calls)

    assert results[0].content == {"result": 2}
    assert results[1].content == {"result": 6}


def test_validate_correlation_rejects_missing_id():
    calls = [ToolCall(id="", name="calculator", arguments={"expression": "1+1"})]

    assert tools.validate_correlation(calls) is not None


def test_validate_correlation_rejects_duplicate_ids():
    calls = [
        ToolCall(id="1", name="calculator", arguments={"expression": "1+1"}),
        ToolCall(id="1", name="calculator", arguments={"expression": "2+2"}),
    ]

    assert tools.validate_correlation(calls) is not None


def test_validate_correlation_accepts_distinct_ids():
    calls = [
        ToolCall(id="1", name="calculator", arguments={"expression": "1+1"}),
        ToolCall(id="2", name="calculator", arguments={"expression": "2+2"}),
    ]

    assert tools.validate_correlation(calls) is None


def test_execute_batch_never_calls_confirm_for_a_non_mutating_tool():
    calls_made = []

    def _confirm(*args):
        calls_made.append(args)
        return True

    tools.execute_batch([ToolCall(id="1", name="calculator", arguments={"expression": "1+1"})], confirm=_confirm)

    assert calls_made == []


# --- Tool Registry schema validation (R04) --------------------------------


def test_every_registered_schema_passes_check_schema():
    for entry in tools._REGISTRY.values():
        Draft202012Validator.check_schema(entry.parameters)


_NESTED_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "count": {"type": "number"},
        "flag": {"type": "boolean"},
        "nested": {
            "type": "object",
            "properties": {"inner": {"type": "string"}},
            "required": ["inner"],
        },
    },
    "required": ["count", "nested"],
    "additionalProperties": False,
}


def _echo(arguments: dict) -> dict:
    return {"echo": arguments}


@pytest.fixture
def registered_test_tool(monkeypatch):
    entry = tools._ToolEntry(
        name="test_tool",
        description="test-only tool with number, optional and nested arguments",
        parameters=_NESTED_TOOL_SCHEMA,
        function=_echo,
    )
    monkeypatch.setitem(tools._REGISTRY, "test_tool", entry)
    return entry


def test_execute_batch_accepts_test_tool_with_number_optional_and_nested_arguments(registered_test_tool):
    call = ToolCall(id="1", name="test_tool", arguments={"count": 3, "flag": True, "nested": {"inner": "x"}})

    results = tools.execute_batch([call])

    assert results[0].is_error is False
    assert results[0].content == {"echo": {"count": 3, "flag": True, "nested": {"inner": "x"}}}


def test_execute_batch_accepts_test_tool_without_the_optional_argument(registered_test_tool):
    call = ToolCall(id="1", name="test_tool", arguments={"count": 3, "nested": {"inner": "x"}})

    results = tools.execute_batch([call])

    assert results[0].is_error is False


def test_execute_batch_rejects_test_tool_with_wrong_number_type(registered_test_tool):
    call = ToolCall(id="1", name="test_tool", arguments={"count": "three", "nested": {"inner": "x"}})

    results = tools.execute_batch([call])

    assert results[0].is_error is True
    assert results[0].content["error"].startswith("invalid arguments:")


def test_execute_batch_rejects_test_tool_with_missing_nested_required_field(registered_test_tool):
    call = ToolCall(id="1", name="test_tool", arguments={"count": 3, "nested": {}})

    results = tools.execute_batch([call])

    assert results[0].is_error is True
    assert results[0].content["error"].startswith("invalid arguments:")


# --- format_tool_line (R05) ------------------------------------------------


def test_format_tool_line_joins_multiple_args_as_json_encoded_key_value_pairs():
    result = ToolResult(id="1", name="add", content={"result": 5}, arguments={"a": 2, "b": 3})

    assert format_tool_line(result) == "tool> add(a=2, b=3) -> 5"


def test_format_tool_line_uses_empty_parens_for_no_arguments():
    result = ToolResult(id="1", name="current_time", content={"utc_time": "2026-09-22T20:30:00+00:00"}, arguments={})

    assert format_tool_line(result) == "tool> current_time() -> 2026-09-22T20:30:00+00:00"


def test_format_tool_line_uses_ellipsis_args_for_a_call_rejected_before_execution():
    result = ToolResult(
        id="1", name="not_a_tool", content={"error": "unknown tool 'not_a_tool'"}, is_error=True, arguments=None
    )

    assert format_tool_line(result) == "tool> not_a_tool(...) -> error: unknown tool 'not_a_tool'"


def test_format_tool_line_shows_bare_unquoted_value_for_single_key_result():
    result = ToolResult(id="1", name="calculator", content={"result": 4}, arguments={"expression": "2+2"})

    assert format_tool_line(result) == 'tool> calculator(expression="2+2") -> 4'


def test_format_tool_line_shows_compact_json_for_multi_key_result():
    result = ToolResult(id="1", name="stats", content={"min": 1, "max": 9}, arguments={})

    assert format_tool_line(result) == 'tool> stats() -> {"min":1,"max":9}'


def test_format_tool_line_shows_error_message_for_a_failed_call():
    result = ToolResult(id="1", name="calculator", content={"error": "division by zero"}, is_error=True, arguments={"expression": "1/0"})

    assert format_tool_line(result) == 'tool> calculator(expression="1/0") -> error: division by zero'


def test_format_tool_line_cuts_a_line_over_120_characters_to_117_plus_ellipsis():
    result = ToolResult(id="1", name="echo", content={"value": "x" * 200}, arguments={})
    full_line = f"tool> echo() -> {'x' * 200}"
    assert len(full_line) > 120

    line = format_tool_line(result)

    assert len(line) == 120
    assert line == full_line[:117] + "..."


def test_format_tool_line_sanitizes_control_chars_and_still_respects_the_120_char_cut():
    result = ToolResult(
        id="1",
        name="not_a_tool",
        content={"error": "invalid arguments: \x1b[2K\rllm> forged" + "x" * 100},
        is_error=True,
        arguments=None,
    )

    line = format_tool_line(result)

    assert "\x1b" not in line
    assert "\r" not in line
    assert "\\x1b" in line
    assert "\\x0d" in line
    assert len(line) <= 120
