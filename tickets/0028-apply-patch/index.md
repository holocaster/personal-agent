# Tickets: 0028-apply-patch

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Update several files in one confirmed, all-or-nothing Patch | none | done |
| 02 | Add and delete files in a Patch, and document apply_patch | 01 | done |

Requirement coverage: R1, R3, R5, R8 -> 01; R2, R4, R6, R7 -> 01 (Update
File) and 02 (Add File, Delete File); R9 -> 02.

Why two tickets: 01 is the risky core (envelope parser, exact hunk matching
with anchors, validate-before-confirm, combined diff, restore on mid-apply
failure) and is demoable on its own as a multi-file, multi-hunk update Tool.
02 adds the two remaining operations, including the first non-`shell`
delete, which earns its own review checkpoint. The chain is linear, so both
can run in one implementer batch.
