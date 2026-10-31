ticket: 0008-agent-ux/04
reviewed_range: 2a46e5ce7b1ff8dbf49afa52cefd439b46482351..7c063357982e2981bc53558c5a651f6cb2d36e80
status: approved
pending:
  - manual real-terminal check (framing, scrollback, resize, paste, Alt+Enter, completion menu room) -- deferred to the user after ticket 05, one check for both
findings:
  - severity: suggestion
    location: tests/test_input_box.py::test_tab_completes_a_repl_command
    note: 0.2s wall-clock timer; flaky if startup exceeds 0.2s. Trigger Enter on a buffer condition instead.
  - severity: suggestion
    location: tests/test_input_box.py::test_tab_offers_no_completion_when_input_does_not_start_with_a_slash
    note: timer not needed; send input in one batch.
residual_risks:
  - dont_extend_height set on layout.current_window after construction; a prompt_toolkit upgrade could break it silently.
  - with reserve_space_for_menu=0 a multi-match completion menu may be clipped.
checks:
  - uv run pytest -q -> 315 passed
