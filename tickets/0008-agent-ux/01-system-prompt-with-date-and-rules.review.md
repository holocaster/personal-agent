ticket: 0008-agent-ux/01
reviewed_range: 8b72d874ad12b0ff101410defdce0997df095096..94db67a0f5d447b9719b73f7b1b697b1f626e97d
status: approved
findings:
  - severity: suggestion
    location: tests/test_routing.py test_system_prompt_carries_the_date_line_and_tool_rules
    note: rule assertions match single keywords ("guess", "language"); optional to tighten.
checks:
  - uv run pytest -q at head_sha -> 282 passed
  - strftime('%Y-%m-%d %H:%M %:z') verified on Python 3.12
