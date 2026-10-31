# 01: Mutating File Limit for write and edit

**What to build:** `write` and `edit` are bounded by the Mutating File Limit
(`PA_MAX_WRITE_BYTES`, default now 1 MiB) instead of `PA_MAX_READ_BYTES`, for
both the existing file they load and the content they produce. A user can
have the model `edit` one line of a 70 KB file, and overwrite it with `write`
and see the diff at Tool Confirmation. `read_file` is untouched in this
ticket; this lands first so that lowering the Tool Output Cap in ticket 02
can never shrink what `edit`/`write` accept.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0021-partial-reads.md` (Requirements R14, R16 for the
`PA_MAX_WRITE_BYTES` parts; Implementation Decisions: Workspace tools module,
Configuration; Testing Decisions); **ADRs:** none.

- [x] `PA_MAX_WRITE_BYTES` defaults to 1048576 (1 MiB); name and
  positive-integer validation unchanged.
- [x] `edit` loads the existing file bounded by the Mutating File Limit; an
  existing file larger than it is the Tool error
  `file exceeds the <N>-byte write limit`, returned before `confirm` is
  called.
- [x] `write` overwriting an existing file loads it for the diff preview
  bounded by the same limit, with the same error before `confirm`.
- [x] Resulting content over the limit is still the unchanged
  `content exceeds the <N>-byte write limit` error for both Tools.
- [x] `edit` and `write` no longer depend on `PA_MAX_READ_BYTES` at all: with
  a read cap smaller than the file, both still succeed.
- [x] `README.md` (Mutating Tools section, including the `edit` paragraph that
  currently says the file is read with `PA_MAX_READ_BYTES`), `docs/ENV_VARS.md`
  and `.env.example` describe `PA_MAX_WRITE_BYTES` as the Mutating File Limit,
  default 1048576, applying to the existing file and the result.
- [x] Tests at the `tools.execute_batch` seam: default limit via
  `configure_workspace`; `edit` of a file larger than the read cap succeeds;
  existing file over the write limit is an error for `edit` and for a `write`
  overwrite with `confirm` never called. Existing tests encoding the 64 KiB
  write default are updated. Full offline suite passes.
