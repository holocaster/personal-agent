# 0021 — Partial reads

## Goal

The model should receive only the parts of a file it asks for, never a whole file by default. Today `read_file` returns the entire file and `PA_MAX_READ_BYTES` (64 KiB) is both the largest readable file and what enters the Conversation, so a large file cannot be read at all and a mid-size one costs its full size in context on every later turn. The same limit also caps `edit`/`write` on existing files, so a 70 KB file cannot be edited even to change one line.

## Scope

- **`read_file(path, offset, limit)`** returns a Read Window of lines. `offset` is 1-based (line 1 is the first line, matching `search_text`'s `line`), default 1. `limit` is a line count, default 500. The file is read streaming, only up to the end of the window; there is no whole-file size limit.
- **Numbered lines**: each returned line is prefixed with its line number and a TAB (`12\t<text>`, the `cat -n` shape). The prefix is not part of the file. The `read_file` and `edit` Tool descriptions say so explicitly and say never to include it in `old_string`. `edit` does not strip prefixes itself.
- **Result shape**: `{content, has_more, next_offset}`. `has_more` is true when lines exist after the window (including when the window was cut by the byte cap); `next_offset` is the offset to continue from, null when `has_more` is false. No total line count.
- **Tool Output Cap**: `PA_MAX_READ_BYTES` now means the most bytes one Tool call hands to the model, default **32 KiB** (was 64 KiB). The line-number prefixes count toward it. When a window would exceed it, cut at the last whole line that fits and report `has_more`/`next_offset` so the model continues from there. If a single line alone exceeds the cap, return that line truncated with the `[...truncated]` marker, and continue at the next line.
- **Binary / non-UTF-8**: checked on the bytes actually read for the window only (NUL byte or invalid UTF-8 → the existing "file is binary or not valid UTF-8" Tool error).
- **`offset` past the end of the file**: a Tool error naming the file's line count, e.g. `offset 900 is past end of file (850 lines)`.
- **`search_text`**: each match's `excerpt` is shortened to about 200 characters centred on the first occurrence of the search text in that line, with `…` marking a cut side. The whole response is also bounded by the Tool Output Cap (existing `truncated` flag set when cut).
- **Mutating File Limit**: `PA_MAX_WRITE_BYTES` becomes the largest file `write` or `edit` may load or produce — the existing file read for `edit` and for `write`'s diff preview, and the resulting content — default **1 MiB** (was 64 KiB). `edit`/`write` no longer read through `PA_MAX_READ_BYTES` at all.
- **`shell` output** keeps defaulting to the effective `PA_MAX_READ_BYTES` (so 32 KiB by default); `PA_SHELL_MAX_OUTPUT_BYTES` still overrides.
- Docs: `README.md`, `docs/ENV_VARS.md`, `.env.example` reflect the new meanings and defaults.

## Out of scope

- A total line count in `read_file`'s result — the model can run `wc -l` through `shell` when it needs one.
- `edit` automatically stripping line-number prefixes from `old_string`.
- Byte-offset reads, or reading by regex/section.
- Changing `list_files`, or `search_text`'s matching rules, depth, or 100-result limit.
- A separate env var for the `search_text` excerpt length (fixed constant).
- Renaming `PA_MAX_READ_BYTES` / `PA_MAX_WRITE_BYTES` to match their new meanings.

## Settled decisions

1. **Windows are in lines, not bytes**, because the model already gets line numbers from `search_text`; bytes would be precise but unnavigable for it.
2. **Default window 500 lines, Tool Output Cap 32 KiB**: 500 typical source lines (40–60 bytes) fit under 32 KiB, and ~8k tokens per read keeps a few reads from filling the context, since each Tool result is resent on every later turn until Compression.
3. **Over-cap windows are cut, never rejected**: rejection would leave the model guessing smaller limits blindly; a cut plus `next_offset` tells it exactly where to continue.
4. **Numbered lines inline (user's choice over plain content + metadata)**: better orientation for the model, accepting ~6 bytes per line and the risk that the prefix leaks into `edit`'s `old_string`. That risk is handled by Tool descriptions only; a leaked prefix just produces the existing "old_string was not found" error, nothing is corrupted. Auto-stripping was rejected because it would corrupt a file whose lines genuinely start with digits and a TAB.
5. **`next_offset` is explicit** rather than inferred from the last visible number, so a byte-cap cut mid-window cannot make the model miscount.
6. **No total line count**: counting requires reading to EOF on every call (≈1 s on a 500 MB log), defeating streaming.
7. **Binary detection covers the window only**, since checking the whole file would defeat streaming.
8. **Offset past EOF is an error with the line count** (known at that point, since the file was read to its end), not a silent empty result.
9. **What the model sees and what `write`/`edit` may touch are separate limits**: Tool Output Cap protects context budget; Mutating File Limit protects memory and the Tool Confirmation diff. `PA_MAX_WRITE_BYTES` was reused for the latter (one knob, existing name) instead of a new constant or no limit.
10. **Mutating File Limit default 1 MiB**: covers any real source or config file, and a 1 MiB diff is still reviewable at Tool Confirmation.
11. **`shell` output keeps inheriting `PA_MAX_READ_BYTES`**: same concept (what one call hands the model); `PA_SHELL_MAX_OUTPUT_BYTES` remains the override.
12. **`search_text` excerpts are in this feature**: an uncapped excerpt of a minified-JSON line times 100 matches is the same leak `read_file` had; centring on the match keeps the match visible where a prefix cut could drop it.

## Open questions

None — grilling frontier closed and confirmed by the user on 2026-09-24.

## Known issues

None yet — feature not yet implemented.
