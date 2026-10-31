# Review: 0037/07

status: approved
ticket: 0037/07
reviewed_range: d1003057f87e5fc665b6dad4e1ee5938b3fb18ce..39463a8888964c2d136b8a08466577c5f375b9b9
round: 1

## Criteria

AC1-AC3 pass. `compress()` always raises `PersistenceError` for `OSError`/`PersistenceError`; `fatal_persistence` removed. Manual, above-ceiling and recovery callers raise without dispatch, write no `conversation_compressed`, and leave `load_conversation` unchanged; soft-only regression still passes.

## Findings

1. suggestion, out of scope, pre-existing — `__main__.py` catches only `AuditError`; a `PersistenceError` (or raw Call Log `OSError`) reaches the user as a traceback instead of a "Fatal ..." line with exit 1. Session state stays safe.

## Checks

- Focused suite: 245 passed. Full offline suite: 1632 passed.
- Red check: the 3 new cases fail against the base router.py.
- No non-persistence OSError reaches the conversion in practice: Provider errors become strings in `_run_exchange`, no Tools, asset reads raise ValueError, `model_info` swallows errors, detail writes raise AuditError.
- Tree clean after checks.

## Residual risks

- Theoretical: a broken LiteLLM/tiktoken install raising OSError on the first manual `/compress` count would be reported as a fatal PersistenceError.
