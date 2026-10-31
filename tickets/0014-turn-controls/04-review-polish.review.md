ticket: 0014-turn-controls/04
reviewed_range: 00b7ef68311ca13c1093f648fe337e2e52d86e80..fe7e1949af738ad295f954694fce6a8917ba0a0c
status: approved
round: 1

All 4 criteria pass. Full suite: 433 passed. The routed System Prompt is byte-identical to the one at base_sha, and the README change is rewrapping only.

Suggestions:
1. The README System Prompt paragraph overstated "every exchange" for the /compress call. Addressed by the orchestrator in the approval commit, together with the matching CONTEXT.md System Prompt wording.
2. The `tools` parameter of `_build_system_prompt` has no type annotation. Not applied.
