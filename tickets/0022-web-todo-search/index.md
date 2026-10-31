# Tickets: 0022-web-todo-search

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Workspace search: skip list, glob filters, opt-in regex | none | done |
| 02 | webfetch Network Tool behind Tool Confirmation | none | done |
| 03 | todo Tool and a Todo List that follows the Conversation | none | done |

The three tickets were implemented and reviewed as one batch in order 01, 02,
03. Ticket 01 landed first because it fixed the proven `list_files(".")` flood
on its own.

Requirement coverage: R1-R6 -> 01; R7-R12 -> 02; R13-R18 -> 03; R19 split by
topic across 01 (search docs), 02 (`webfetch` docs, Tool Confirmation
sentence) and 03 (`todo` docs, always-offered Tool list).
