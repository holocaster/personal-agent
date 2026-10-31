ticket: 0014-turn-controls/01
reviewed_range: abfbac385178fd9b439f75c63d746dc5640f7dfb..ea6d88c4c1ec3f7521ee992e31fa9140916b485c
status: approved
round: 1

All 10 criteria pass. Full suite at head: 396 passed.

Suggestions (non-blocking):
1. The invalid-argument test does not include a raw model id such as `/model vendor/easy-model`. The allow-list already rejects it.
2. In repl.py, `pinned_tier` is a one-element list used as a mutable cell. Returning the new pin from the handler would be more consistent.
