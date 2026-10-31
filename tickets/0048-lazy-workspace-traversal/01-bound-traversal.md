# 01: Stop workspace traversal after enough matching results

**What to build:** Make Workspace Tools enumerate files lazily so bounded listing and text search stop walking once their result/output limit is established.

**Blocked by:** None.

**Spec:** none (fast path)

- [x] A deterministic operation-count regression first reproduces the current eager traversal: 101 matching root files establish the 100-file listing and truncation, yet a later directory is still visited. After the fix that directory is not visited.
- [x] Fix the shared `_walk_files` seam and both consumers, `list_files` and directory `search_text`, without loading every eligible file path before applying limits. Filtering happens lazily before the relevant result limit; search stops traversal when its result/output cap is established.
- [x] Preserve global workspace-relative POSIX lexical ordering, including punctuation around directory names (`a.txt` versus `a/file.txt`), search line ordering, correct `truncated`, nested explicit search roots, glob matching, skipped directories, depth limits, and existing secret/symlink exclusions. Exact 100 matches without another eligible match remain non-truncated.
- [x] Meaningful regressions cover listing early-stop, selective glob filtering, lexical directory/file ordering and search early-stop. Relevant existing Workspace Tool tests pass; no new dependency or unnecessary code comment.

## Evidence and constraints

The previous turn reproduced the defect with 101 `aNNN.txt` files plus `z_later/unused.txt`: listing returned 100 with truncation but entered `z_later`. `_walk_files` currently collects all paths and globally sorts; both consumers eagerly filter. The 2026-10-05 latency research records a large-workspace reproduction.

Implementation remained uncommitted during review; the user authorized commit and push on 2026-10-06. Preserve all other agents' edits. Work one validation step at a time. Changes are reviewed as an immutable uncommitted supplement to the captured branch HEAD.
