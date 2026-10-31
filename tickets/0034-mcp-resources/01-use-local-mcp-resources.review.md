status: approved
ticket: 0034-mcp-resources/01
reviewed_range: 6eee474cb7c7f829fd52e2d4dfedc4aba4e09566..fcce0c259205ccfcbe1582c4c55db85eca8ad2b0
round: 2

Round 1 findings 1-7 all fixed (blocking ExceptionGroup swallowing specific errors, missing test coverage, MCP confirm question, asyncio.run, public import, C1 URI check, README order). R1-R9 and Testing Decisions pass.

checks:
- uv run pytest: 1201 passed
- independent probe of 9 fixture modes: specific errors surfaced, child reaped each time
- independent SIGINT probe (hang, hang-init): KeyboardInterrupt propagated, child reaped

open suggestions (optional):
- test_ctrl_c_reaps_server should assert the driver died from KeyboardInterrupt, not only that the child exited
- 'instructions' test is weak: assert at the REPL/Provider seam that server instruction text never reaches Provider messages and plan/build still prompt

residual_risks:
- Ctrl-C at a live prompt_toolkit terminal during an MCP call not tested interactively
- deadline expiring mid-pagination returns a timed out error, not a truncated partial catalog
- server-initiated sampling/elicitation rejection relies on SDK default plus input_required_max_rounds=0
