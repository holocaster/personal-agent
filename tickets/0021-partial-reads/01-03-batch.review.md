status: approved
ticket: [0021-partial-reads/01, 0021-partial-reads/02, 0021-partial-reads/03]
reviewed_range: 1313bb3f2edb2ed2e9e61734dd125e53ee24f87d..ec0f53a961d0c08d6ed46e96f1df567f3db976a5
review_round: 0

criteria: all pass (01: R14 + write docs; 02: R1-R10, R15, R16; 03: R11-R13, R16)

checks:
- uv run pytest -q at ec0f53a: 640 passed
- ad-hoc probes: CRLF/unterminated last line numbering, offset-past-end message, window-only UTF-8 check, exact-fit line, degenerate cap below prefix+marker, search_text first match over cap

findings (all suggestion, none required):
- read_file end-of-window has_more peek scans the whole next line; memory bounded, measured 0.02s on a 200 MB next line (warm cache).
- _read_text limit_label parameter now only ever receives "write"; could be hard-coded.
- some new docstrings (_excerpt, _r2_lines) restate the spec, against the user's no-comments preference.

residual_risks:
- integral floats pass the integer schema (offset=2.0); cosmetic only in error text.
- search_text no longer splits on form feed / U+2028 / lone \r; accepted in spec Further Notes.
