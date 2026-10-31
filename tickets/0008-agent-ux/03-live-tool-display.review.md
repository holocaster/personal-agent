ticket: 0008-agent-ux/03
reviewed_range: f34e54066444473e549250591bc6cd61fa1a2a51..13047876f1e37c67eab5265573b793b0f041589f
status: approved
findings:
  - severity: suggestion
    location: model_router/tools.py format_tool_line
    note: model-supplied Tool name and arguments_raw are printed unescaped; a newline/control char breaks the one-line format.
checks:
  - uv run pytest -> 300 passed
  - no emoji in diff
