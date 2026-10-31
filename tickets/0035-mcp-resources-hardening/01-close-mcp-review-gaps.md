# 01: Close MCP Resources review gaps

**What to build:** Close the open suggestions and residual risks left by the approved review of 0034 (`tickets/0034-mcp-resources/01-use-local-mcp-resources.review.md`), without changing the 0034 scope.

**Blocked by:** None (can start immediately).

**Spec:** none (fast path). `docs/specs/0034-mcp-resources.md` R4, R5 and Testing Decisions remain the reference; the acceptance criteria below are normative.

- [x] Deadline mid-pagination (spec R5 lists deadline as a stop condition): when the 30-second deadline expires after at least one page was collected, a list Tool returns the entries gathered so far with `truncated: true` instead of a timed out error. Expiry before any page is collected stays a Tool error. Applies to both list Tools; the child is still reaped. Test with the existing shortened-deadline seam and a new fixture mode (a server that answers page 1 then hangs).
- [x] `test_ctrl_c_reaps_server` asserts the driver died from KeyboardInterrupt (returncode -SIGINT or equivalent), not only that the child exited.
- [x] Server-instruction untrusted-content test at the REPL/Provider seam: the server `instructions` text never reaches Provider messages, and a plan/build MCP call still prompts for confirmation afterwards. Replace or strengthen the weak `'INJECTED' not in str(result.content)` check.
- [x] Server-initiated sampling and elicitation requests: add fixture modes where the server sends `sampling/createMessage` and an elicitation request during a list or read. Assert the request is rejected, no host action or retry happens, the call ends with a bounded Tool error (or the normal result if the server proceeds), and the child is reaped.
- [x] Interactive Ctrl-C at a live prompt_toolkit terminal during an MCP call: try a one-off pty-driven probe (scratchpad, not committed). Report the observed result, or state precisely why it cannot be automated. Do not commit a flaky test.
- [x] README updated only if the deadline behavior changes what it says.
- [x] Full offline suite passes; record commands and results.
