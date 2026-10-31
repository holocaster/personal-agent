# Review: Batch 0022-web-todo-search 01-03

ticket: [0022-web-todo-search/01, 0022-web-todo-search/02, 0022-web-todo-search/03]
reviewed_range: 2610702da61e690c8b5c93576aed9c783dbc312f..b9edc7e5b35e80f437b916becddc9c26f67e8f5b
status: approved
round: 3

All criteria pass (01 R1-R6, 02 R7-R12, 03 R13-R18, R19). Full suite 697 passed.
Round 2 findings 1-3 resolved: trickle probes (Content-Length, chunked, one large chunk,
close-delimited) all time out at ~1.0 s with TIMEOUT_SECONDS=1; the deadline test fails when
read1 is swapped back to read (regression power confirmed); malformed Content-Type is a Tool
error; redundant except removed. Round 1 crash cases re-probed, no regressions.

## Findings

1. suggestion (no change required) - webfetch.py _read_capped, chunked path: http.client reads the
   chunk-size line with readline(65536) before read1 returns, so a hostile server trickling a very
   long chunk-size line resets the per-op timeout without the total deadline being checked. Bounded
   by 65536 x per-byte delay. Same class as the accepted per-operation residual risk.

Residual risks (accepted): connect/header/DNS phase and chunk-size lines are bounded per operation
only; Auto-Compress has no dedicated todo test (shares _run_compression with tested /compress).
