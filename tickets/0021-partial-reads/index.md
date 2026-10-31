# Tickets: 0021-partial-reads

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Mutating File Limit for write and edit | none | done |
| 02 | read_file returns a Read Window bounded by the Tool Output Cap | 01 | done |
| 03 | search_text excerpts centred on the match and bounded by the Tool Output Cap | 02 | done |

Linear chain. 01 is a standalone checkpoint (editing a 70 KB file works) and
lands first so the lower read default in 02 never shrinks what `edit`/`write`
accept. 02 is the core Read Window. 03 closes the remaining `search_text`
leak on 02's line model. All three may run as one implementer + reviewer
batch.

Requirement coverage: R14 -> 01; R1-R10, R15 -> 02; R11-R13 -> 03; R16 split
by topic across 01 (`PA_MAX_WRITE_BYTES`), 02 (`PA_MAX_READ_BYTES`,
`read_file`, `shell` default) and 03 (`search_text`).
