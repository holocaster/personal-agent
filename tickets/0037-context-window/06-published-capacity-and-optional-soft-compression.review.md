# Review: 0037/06

status: approved
ticket: 0037/06
reviewed_range: 55d7929f3542b035d594e2a817f41e5cbfc6e367..bbdcbeeaf2cd0624fccae3f2e212f7ff1d4bda87
round: 2

## Criteria

AC1-AC6 pass. Round-1 blocking finding resolved: a Call Log persistence failure on the summarization Attempt append in the soft-only path raises PersistenceError and never dispatches the pending exchange (regression test for OSError and PersistenceError). Round-1 suggestions 2 (notice prefix) and 3 (duplicate test) resolved.

## Findings

1. suggestion — soft-only persistence failure is now fatal (PersistenceError, traceback from `__main__`, no session end marker) while the hard path, recovery and manual `/compress` keep a non-fatal "Context budget blocked" stop for the same OSError. Permitted by AC4/R5/R9 ("stop/fatal"); optional alignment to the non-fatal stop.
2. suggestion, out of scope, pre-existing — `compress()` catch-all turns a Call Log failure on the summarization Attempt append into an ordinary error on the hard path, recovery and manual `/compress`, leaving a charged but unlogged Attempt (conflicts with R6 "remain normally logged"). Same at base. Not part of 06.

## Checks

- Focused suite: 380 passed. Full offline suite: 1629 passed.
- Persistence flag narrow: only Call Log writes can raise OSError inside compress(); tokenizer asset reads raise ValueError, detail writes raise AuditError.
- Manual `/compress` unchanged (no fatal_persistence).
- Removed "Compression failed: " prefix breaks no spec/README/ENV_VARS claim.
- Tree clean after checks.
