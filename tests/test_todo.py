from personal_agent.providers.contract import ToolCall
from personal_agent.tools import registry as tools, workspace


def _execute(arguments):
    return tools.execute_batch([ToolCall(id="1", name="todo", arguments=arguments)])[0]


# --- todo Tool (R13) ---------------------------------------------------------


def test_todo_is_registered_by_default_with_no_confirmation(tmp_path):
    workspace.configure_workspace(tmp_path)
    definitions = {definition.name: definition.parameters for definition in tools.TOOL_DEFS}

    assert "todo" in definitions
    assert tools._REGISTRY["todo"].requires_confirmation is False


def test_todo_replaces_the_list_and_returns_it(tmp_path):
    workspace.configure_workspace(tmp_path)
    todos = [{"content": "step one", "status": "pending"}, {"content": "step two", "status": "in_progress"}]

    result = _execute({"todos": todos})

    assert result.is_error is False
    assert result.content == {"todos": todos}


def test_todo_empty_list_is_valid(tmp_path):
    workspace.configure_workspace(tmp_path)

    result = _execute({"todos": []})

    assert result.is_error is False
    assert result.content == {"todos": []}


def test_todo_invalid_status_is_the_normal_invalid_arguments_error(tmp_path):
    workspace.configure_workspace(tmp_path)

    result = _execute({"todos": [{"content": "x", "status": "unknown"}]})

    assert result.is_error is True
    assert "invalid arguments" in result.content["error"]


def test_todo_missing_field_is_the_normal_invalid_arguments_error(tmp_path):
    workspace.configure_workspace(tmp_path)

    result = _execute({"todos": [{"content": "x"}]})

    assert result.is_error is True
    assert "invalid arguments" in result.content["error"]


def test_todo_extra_field_is_the_normal_invalid_arguments_error(tmp_path):
    workspace.configure_workspace(tmp_path)

    result = _execute({"todos": [{"content": "x", "status": "pending", "priority": 1}]})

    assert result.is_error is True
    assert "invalid arguments" in result.content["error"]
