from personal_agent.terminal.tty import sanitize_control_chars

_ACTIVE_STATUSES = frozenset({"pending", "in_progress"})
_CHECKLIST_MARKERS = {"pending": " ", "in_progress": "~", "completed": "x", "cancelled": "-"}
# Mirrors terminal.repl.MAX_TOOL_LINE_CHARS: duplicated rather than imported,
# since repl.py already imports this module (current_list/update_from_results
# feed the Router, checklist_text feeds the live printer) and importing back
# would cycle.
MAX_LINE_CHARS = 120


def todo(arguments: dict) -> dict:
    return {"todos": arguments["todos"]}


def current_list(turns, baseline: list[dict]) -> list[dict]:
    """The current Todo List (R14): the todos of the latest successful `todo`
    result across every message of every turn, in order, else the given
    baseline. A pure fold over the same turn structure the REPL and Router
    already hold, so no state lives here."""
    current = baseline
    for turn in turns:
        for message in turn:
            if (
                message.get("role") == "tool_result"
                and message.get("name") == "todo"
                and not message.get("is_error")
            ):
                current = message["content"]["todos"]
    return current


def update_from_results(current: list[dict], results) -> list[dict]:
    """Fold one Tool round's results into the Todo List (R16): the last
    successful `todo` result in the batch wins."""
    updated = current
    for result in results:
        if result.name == "todo" and not result.is_error:
            updated = result.content["todos"]
    return updated


def system_prompt_block(todos: list[dict]) -> str | None:
    """The System Prompt's `Todo List:` block (R15), or None when nothing is
    `pending`/`in_progress`."""
    if not any(item["status"] in _ACTIVE_STATUSES for item in todos):
        return None
    lines = [f"- [{item['status']}] {item['content']}" for item in todos]
    return "Todo List:\n" + "\n".join(lines)


def checklist_text(todos: list[dict]) -> str:
    """The REPL's live checklist printed in place of the generic Tool line
    after a successful `todo` call (R17)."""
    if not todos:
        return "tool> todo (empty)"
    lines = ["tool> todo"]
    for item in todos:
        marker = _CHECKLIST_MARKERS[item["status"]]
        line = sanitize_control_chars(f"  [{marker}] {item['content']}", multiline=False)
        if len(line) > MAX_LINE_CHARS:
            line = line[: MAX_LINE_CHARS - 3] + "..."
        lines.append(line)
    return "\n".join(lines)
