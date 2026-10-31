ticket: 0008-agent-ux/02
reviewed_range: a7ba4f084633e7eb114973e9885deb68f1454e91..8bbd6462ed83ae10fa48f981d21b9ab8fb6f12c5
status: approved
findings:
  - severity: suggestion
    location: tests/test_tools.py
    note: no test asserts tools.TOOL_DEFS equals the registry's name/description/schema.
  - severity: suggestion
    location: tests/test_tools.py
    note: no mixed batch proves a valid call still succeeds after a schema violation or ToolExecutionError.
checks:
  - uv run pytest at head_sha -> 287 passed
  - Draft202012Validator rejects list-as-object and bool-as-number
