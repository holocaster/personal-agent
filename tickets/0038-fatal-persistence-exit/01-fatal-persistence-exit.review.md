# Review: 0038/01

status: approved
ticket: 0038/01
reviewed_range: 50f453aa1de950f767f6a73fbe3c71c3349d170f..b8a168e94edc9be99968be05a00d4a933adecb30
round: 1

## Criteria

AC1-AC3 pass. `main()` prints `Fatal persistence error: <message>` and exits 1 for `PersistenceError` and `OSError`; `Fatal audit error` unchanged; KeyboardInterrupt and other exceptions still propagate; run_repl session-end semantics untouched.

## Findings

1. suggestion — a non-Call-Log `OSError` (realistically `BrokenPipeError` on a closed stdout pipe in non-tty mode) is labeled "persistence". Exit status and no traceback are correct; only the label is imprecise. Optional future narrowing.

## Checks

- tests/test_main.py: 46 passed (PersistenceError/OSError cases failed before the fix). Full offline suite: 1635 passed.
- Tree clean after checks.

## Residual risks

- Ticket text says run_repl writes no session end; true only for PersistenceError. A raw OSError still writes `SESSION_END_ERROR` before re-raising (pre-existing, unchanged).
- Tests stub run_repl; no end-to-end Call Log failure through main().
