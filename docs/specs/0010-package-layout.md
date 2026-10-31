## Problem Statement

The Router's flat source directory now mixes routing decisions, Tool behavior,
and terminal presentation. Finding a capability means tracing unrelated files
and imports, and each additional feature makes that locality worse.

## Solution

Move existing implementation into four capability-named packages:
`routing`, `tools`, `terminal`, and the existing `providers`. Keep the root
package as the composition root and leave the independent `call_log`,
`dotenv`, and `cost` modules in place. This is an import-only refactor: the
Router, Provider Contract, Tool Registry, terminal behavior, configuration,
and external behavior do not change.

## User Stories

1. As a maintainer, I want Router decisions grouped under `routing`, so that I can trace classification, tier selection, retries, and Escalation together.
2. As a maintainer, I want Tool declarations and implementations grouped under `tools`, so that I can find the Tool Registry and Workspace Tools without scanning routing or terminal code.
3. As a maintainer, I want terminal input and rendering grouped under `terminal`, so that REPL presentation has a clear home.
4. As a maintainer, I want Providers to remain in their existing capability package, so that external API adapters stay separate from routing policy.
5. As a maintainer, I want the package root to remain the composition root, so that startup wiring is easy to locate without a generic architectural layer.
6. As a Router user, I want the same classifications, retries, Escalation, Budget Guardrail, and Provider calls after the move, so that reorganizing source does not change answers or cost behavior.
7. As a Router user, I want calculator, current-time, and Workspace Tools to retain their schemas, results, validation, and safety boundary, so that local Tool behavior remains reliable.
8. As a terminal user, I want REPL commands, Input Box behavior, color, spinner, output sanitization, and Tool display unchanged, so that the refactor does not alter my workflow.
9. As a developer, I want tests to import the new capability paths and retain their current behavioral coverage, so that stale imports cannot conceal a partial move.
10. As a developer, I want no compatibility modules for old internal paths, so that pre-1.0 source has one authoritative layout.
11. As a developer, I want `call_log`, `dotenv`, and `cost` to remain root leaf modules, so that creating a package does not become a generic dumping ground.

## Implementation Decisions

### Capability boundaries

- `model_router.routing` owns `router`, `classifier`, `tier`, `tier_config`,
  and `budget`. Its Router continues to use the Provider Contract and Tool
  Registry; it does not take ownership of Provider adapters, Tool
  implementations, terminal rendering, or root leaf modules.
- `model_router.tools` owns the Tool Registry and its implementations. Split
  the present single Tool module into `registry` (definitions, JSON-schema
  validation, correlation checks, and batch execution), `builtins`
  (calculator and current-time Tools), and `workspace` (Workspace Root
  configuration and read-only Workspace Tools). Keep the Tool-specific error
  type in the capability without creating a generic cross-package module.
- `model_router.terminal` owns `repl`, `input_box`, and `tty`. Terminal-only
  Tool-result line formatting belongs with the REPL presentation, while the
  Tool Registry remains terminal-agnostic.
- `model_router.providers` remains unchanged as the Provider adapter package.
  The root `__main__` imports these capability packages to load configuration,
  configure the Workspace Root, construct the Input Box, and run the REPL.
- `call_log`, `dotenv`, and `cost` remain root leaf modules. Do not create
  `core`, `common`, `utils`, `services`, factories, compatibility shims, or
  new dependencies. Do not introduce package-root re-exports for moved
  internal modules.

### Import migration and behavior preservation

- Move modules rather than copy them, update every production and test import
  to the new authoritative paths, and remove the former flat module files.
  Preserve public names and callable signatures within their new capability
  modules unless a name only served the former module layout.
- Preserve the existing composition sequence: load `.env`, configure the
  Workspace Root and read limit, load and validate Tier Config, load the
  Budget Guardrail, create an interactive Input Box when applicable, and run
  the REPL.
- Preserve all current behavior, including the Provider Contract and adapter
  implementations; Complexity Tier classification and ladder; retry,
  Escalation, and Budget Guardrail rules; Tool Registry schemas and per-call
  error isolation; Workspace Tool bounds and exclusions; Call Log entries;
  Conversation handling; REPL Commands; input modes; and terminal safety and
  rendering.

## Testing Decisions

A good test continues to drive the same externally observable seam -- a
Router call through the fake Provider, a Tool Registry batch, a driven REPL,
or configuration loading -- and asserts the same result. It does not assert
that a file was moved or that an import has a particular number of layers.

Update imports in the existing focused test modules so the current behavior
suite executes against the new capability paths. The existing routing, Tool,
Workspace Tool, REPL, Input Box, terminal, configuration, budget, Call Log,
and Provider tests are the prior art and retain their assertions. Add no
behavioral tests solely for relocation. Run the complete offline test suite,
then run the installed package with `python -m model_router` under existing
configuration-validation test coverage to prove the composition root resolves
the moved modules.

## Out of Scope

New runtime behavior, configuration, dependencies, Providers, Tools, Tool
schemas, API contracts, package-wide compatibility aliases, generic layers,
moving `call_log`/`dotenv`/`cost`, altering documentation beyond stale source
path references, and any externally published import-path guarantee.

## Further Notes

This feature applies the recorded Package organization decision in
`docs/CONTEXT.md`. It intentionally does not add an ADR: the capability
boundaries and pre-1.0 compatibility choice are already settled there.
