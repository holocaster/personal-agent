# 01: Move source into capability packages

**What to build:** The Router keeps its current behavior while its source has
one navigable home per capability: routing policy in `routing`, Tool Registry
and implementations in `tools`, REPL presentation in `terminal`, and Provider
adapters in `providers`. The composition root wires those packages together;
root leaf modules stay root leaves.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0010-package-layout.md` (all sections); **ADRs:** none.

- [x] Move Router execution, Classifier, Complexity Tier, Tier Config, and
  Budget Guardrail into `model_router.routing`; update their internal imports
  and root-leaf `call_log` imports without changing routing behavior.
- [x] Create `model_router.tools` with a terminal-agnostic Tool Registry,
  separate built-in calculator/current-time implementation, and separate
  Workspace Tool implementation. Retain the exact Tool definitions, schemas,
  validation, batch/error behavior, Workspace Root configuration, bounds, and
  exclusions; move Tool-result display formatting to terminal presentation.
- [x] Move REPL, Input Box, and terminal helpers into
  `model_router.terminal`, keeping local commands, interactive and piped
  modes, spinner/color behavior, output sanitization, and Tool-result display
  unchanged.
- [x] Keep `model_router.providers` intact. Update `__main__` as the
  composition root so startup still loads `.env`, configures Workspace Tools,
  validates Tier Config, loads the Budget Guardrail, selects the Input Box,
  and starts the REPL in the same order.
- [x] Remove the old flat implementation modules after every production and
  test import uses the new capability paths. Do not leave compatibility shims,
  package-root re-exports, generic packages, dependencies, or behavior
  changes. Keep `call_log`, `dotenv`, and `cost` at the root.
- [x] Update existing focused tests to exercise the moved paths and run the
  complete offline suite. Verify package startup through the existing main
  configuration tests; preserve the current observable assertions rather than
  testing file moves directly.
