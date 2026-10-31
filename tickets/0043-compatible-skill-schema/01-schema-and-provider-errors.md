# 01: Make skill schemas compatible and classify Provider errors correctly

**What to build:** Correct the captured OpenAI rejection of the skill schema and avoid reporting invalid tool definitions as lack of model Tool support.

**Blocked by:** None.

**Spec:** none (fast path)

## Acceptance criteria

- [x] Advertised `skill` parameters are an object without root-level oneOf/anyOf/allOf/enum/const/not. Existing scalar `name` and array `names` calls remain supported across Providers.
- [x] Local validation still requires exactly one of `name` or `names`, preserves current name/count/unique/extra-field constraints and rejects malformed input before loading instructions.
- [x] The captured invalid_function_parameters response remains a readable non-retryable schema/request error containing the original Provider evidence, never a ToolsUnsupportedError.
- [x] Only positive evidence that Tool support is unavailable produces ToolsUnsupportedError. Merely mentioning tools in an unrelated 400/404/422 does not suffice. Existing positive unsupported cases, context-overflow priority and usage preservation remain covered.
- [x] Provider wire-shape regression checks cover the actual advertised skill definition and its compatibility. Focused checks and existing regressions pass; no live API calls.

## Execution guidance

Keep the change small and follow current registry/Provider seams. Do not migrate the skill argument API, disable skills, introduce a dependency, or modify continuation behavior in this ticket. Compare against `/tmp/personal-agent-0043-before` to preserve earlier question-choice, documentation and configurable-round changes. No commits or pushes are authorized.
