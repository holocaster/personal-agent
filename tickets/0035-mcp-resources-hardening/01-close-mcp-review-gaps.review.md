status: approved
ticket: 0035-mcp-resources-hardening/01
reviewed_range: 625b6abcb00f265cfaaed2e8def906f3e06df804..69d23b2787556a0bf7a981fc228ff6765ef5fbae
round: 1

All criteria pass. uv run pytest: 1208 passed. Independent probes: partial result with truncated true after a page, error before any page, child reaped, SIGINT after page 1 still raises KeyboardInterrupt, specific errors still surface.

Interactive pty Ctrl-C (implementer one-off probe, not committed): the REPL printed "Interrupted.", the server child exited, the prompt redrew, and the REPL exited 0 on "exit". Reviewer did not re-run it.

known limitation: if a list completes and the deadline expires during Client teardown, the result is returned as truncated true although complete. Correct and within the cap, only mislabeled; the window is tiny.
