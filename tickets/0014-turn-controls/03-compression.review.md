ticket: 0014-turn-controls/03
reviewed_range: eeb5cc0d6528e19f5cba8a29532082d62e95ea1a..0b61c470dc50e8d25ae2af8deab1b509c15fe13b
status: approved
round: 1

All 11 criteria pass. Full suite at head: 432 passed. The end-to-end run passed: four turns, /compress, one more turn, exit, then --resume last and /history.

Both declared deviations were judged sound:
- A non-string summary on Resume raises ResumeError.
- Ctrl-C during /compress is treated as a failure, and the Run continues.

Suggestions (non-blocking):
1. The REPL prints "Compressed 1 turns." when a single turn is replaced.
2. The summary call carries the normal System Prompt, including the Tool rules, but advertises no Tools.
3. Two README lines are longer than the usual wrap width.
