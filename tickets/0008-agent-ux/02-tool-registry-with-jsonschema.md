# 02: Tool Registry with jsonschema validation

**What to build:** Each Tool is declared once, with its name, description, JSON Schema and function, in a single Tool Registry. That schema is what Providers are told and what every model call is validated against, using the `jsonschema` library, so number, boolean, optional and nested arguments work. Rejected and failed calls still go back to the model as error results.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0008-agent-ux.md` (R03, R04, R13, R14); **ADRs:** `docs/adrs/0002-hand-rolled-provider-contract.md`.

- [x] The Tool module holds one registry of declarations (`name`, `description`, `parameters`, `function`); the three parallel structures (advertised definitions, type map, function map) and the hand-written shape validator are removed.
- [x] The `ToolDef` tuple passed to Providers is derived from the registry; the Provider Contract and all four Providers are unchanged.
- [x] calculator and `current_time` keep their names, descriptions, schemas and results.
- [x] Arguments are validated with `jsonschema`'s `Draft202012Validator`; every registry schema passes `check_schema` (tested).
- [x] Unknown Tool, arguments that are not a valid JSON object, a schema violation, and a `ToolExecutionError` each yield an error Tool result and the rest of the batch still runs. A schema violation's error text starts with `invalid arguments:` followed by the library message for the first error.
- [x] A test-only Tool with a number, an optional and a nested argument proves accepted and rejected inputs through `execute_batch`.
- [x] The two existing assertions on the old hand-written error texts are updated; batch-level correlation checks are unchanged.
- [x] `jsonschema` is declared in `pyproject.toml`; `uv.lock` updated.
- [x] Full offline suite passes, including the end-to-end Tool loop and Call Log `tool_execution` tests.
