# Tickets: 0034-mcp-resources

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Use local MCP Resources during routed tasks | none | done |

Coverage: R1–R9 → 01. Frontier: 01.

One vertical slice includes opt-in configuration, all three closely related operations, confirmation, lifecycle, bounded Conversation results, documentation and offline verification. Splitting the three operations would repeat the same transport and gate review without isolating an independent architectural risk. The single-node dependency graph is acyclic and has no missing blockers.
