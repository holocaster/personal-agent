# 0010 - Capability Package Layout

## Goal

Make the Router's source layout navigable by moving related implementation
behind capability-named packages. The current flat `model_router` directory
mixes routing, Tool, and terminal concerns, which makes dependencies harder to
trace as each area grows.

## Scope

1. Move routing execution, classification, tiers, tier configuration, and
   budget handling into `model_router.routing`.
2. Turn the current Tool module into `model_router.tools`, separating its
   registry, built-in Tools, and Workspace Tool implementation where that
   improves locality.
3. Move REPL, Input Box, and terminal rendering into `model_router.terminal`.
4. Keep `model_router.providers` as the Provider adapter package and make the
   composition root import the new capability packages.
5. Update internal imports and tests; preserve all observable behavior,
   existing Tool contracts, and test coverage.

## Out of scope

- New runtime behavior, Provider, Tool, configuration, or dependency.
- Generic `core`, `common`, `utils`, service, factory, or compatibility-shim
  packages.
- Moving single-purpose leaf modules (`call_log`, `dotenv`, `cost`) without a
  real cohesive package around them.
- Public backward compatibility for the project's pre-1.0 internal module
  paths.

## Settled decisions

- Packages are named for cohesive capabilities: `routing`, `tools`,
  `terminal`, and the existing `providers`.
- The package root remains the composition root, not another generic layer.
- The refactor is behavior-preserving; tests must prove the existing behavior
  survives the import migration.

## Open questions

None.
