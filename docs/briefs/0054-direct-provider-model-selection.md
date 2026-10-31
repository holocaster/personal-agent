# 0054: Direct Provider and model selection

## Goal

The user selects only a Provider and model. Remove complexity tiers and the evaluator from normal operation, superseding 0053's retained-tier design while preserving its cache, reporting, recovery and prompt improvements.

## Settled scope

- Support exactly the existing `openrouter`, `openai`, `anthropic` and `gemini` adapters. Offer a fixed Provider list and a searchable model list from Models.dev with a local cache, explicitly chosen by the user on 2026-10-15. Fetch the public JSON directly using existing Python facilities; no SDK, new dependency or background polling. Map our `gemini` adapter to the catalog's `google` Provider.
- Reject unknown Providers with the supported choices. Reject models absent from the selected Provider's catalog or with known incompatible metadata, preserving the old selection and saved settings. Distinguish locally unsupported from nonexistent/remotely inaccessible; never claim the catalog proves account access or full runtime compatibility. Do not infer compatibility solely from a model-name prefix. Planner specifies conservative handling of incomplete capabilities from actual Models.dev fields.
- Define bounded fetching, validated cache replacement and a simple refresh path. A failed request or malformed response preserves the last valid cache and route. With no usable cache and no successful fetch, explain how to retry rather than invent a model or silently substitute the LiteLLM list. Planner owns the smallest startup/refresh policy that gives useful offline behavior without periodic requests.
- Replace `TIER_*`, Tier/TierConfig and runtime tier policies with one explicitly chosen Provider/model pair and only the selected Provider's required key. Remove evaluator calls/input/policy, easy/medium/complex selection, keep/raise and fallback tier logic; no automatic route substitution or inference from old settings.
- Ordinary tasks, Tool follow-ups, same-route retries and all manual/preventive/overflow Compression use the chosen pair. Explicit changes apply at established task/Retry boundaries, preserving immutable task snapshots. Keep live Agent Mode independent.
- Simplify startup/configuration, model commands/help/completion, footer, `/usage`/`/report` and logs to the actual Provider/model. Preserve explicit submission/Retry identity independently of removed evaluator state. No free-form bypass or custom Provider/endpoints is requested for this version.
- Preserve complete-input budgets/capacities/output limits, streaming and Provider replay, cancellation/overflow recovery, cost provenance and unknown metrics, OpenRouter ordinary/auxiliary affinity, and complete deterministic prompt/schema fixtures. Preserve Tool gates, Memory, Skills, Todo and Project Instructions.
- Preserve new-Session Resume/continuation and `/recover` exact-state, privacy, conflict, rollback and contributor-lineage guarantees. Do not lose ordinal/execution identity by removing tier policy.
- Update current README, ENV_VARS, CLAUDE, CONTEXT, relevant research status and `.notebook` navigation. Remove current tier claims and configuration examples; retain dated specs/ADRs/reviews as historical evidence with supersession references. Remove obsolete-only tests and preserve unrelated behavioral coverage.

## Breaking development change

The user explicitly said old Sessions need not be supported because this is a development project. No backward compatibility, old tier-policy replay, historical Resume/config migration or compatibility wrappers. Existing files are not deleted; unsupported old formats may be refused clearly. New Sessions still require working Resume, reporting and recovery.

## Evidence and implementation reach

[Reference research](../research/done/2026-10-15-reference-model-catalogs.md) pins current OpenCode/Hermes/Harness source. These systems combine catalog/configuration/metadata and do not establish universal entitlement or runtime compatibility. Its initial recommendation to use LiteLLM for selection was superseded by the user's explicit Models.dev choice. Retain existing LiteLLM cost estimation and any capacity behavior still required; selection catalog changes must not silently redefine accounting or claim that missing pricing means an invalid model.

The official [Models.dev usage guide](https://models.dev/) documents `api.json` (Provider models), `models.json` (Provider-independent metadata) and `catalog.json` (combined). A public GET of `https://models.dev/api.json?type=all` returned HTTP 200, `application/json`, 5,701,856 bytes on 2026-10-15. Our generic `webfetch` accepts JSON but has a 5 MiB download limit and bounded text output, so the catalog integration must fetch/parse/filter directly rather than send the complete catalog through that Tool. The planner may use the default endpoint when specialized model types are unnecessary; do not copy a fixed catalog size into a requirement.

Reach includes tier/config/store and their callers, router/compression, CLI/REPL/footer, Call Log/report/discovery/continuation, capacity/accounting metadata and Provider callers, fixtures and affected test fakes. Delete obsolete machinery through existing seams; no new generic selection framework.

## Authorization and execution

On 2026-10-15 the user authorized feature 0054 local commits ("E sim, autorizo o commit"), requested activating sdd-main and proceeding after the reference comparison, and then chose "Models.dev com cache local". No paid calls, installs/new dependencies, Provider SDK/API migrations, sudo, pushes, model benchmarks, new UI framework or unrelated Gemini reasoning-cost correction are authorized.

No product questions remain for this scope. Planner owns exact command/configuration syntax, catalog eligibility/metadata semantics, new persistence format, superseding ADR/spec and executable ticket granularity. Main owns brief/state and current vocabulary. Implement/review sequentially; independent final verification covers the complete removal and preserved 0053 behavior. No source has changed yet.

## Plan review (2026-10-15)

The user reviewed plan ddec366: keep ticket 01 unchanged; split ticket 02 into two sequential tickets to reduce review size. Direction: first ticket switches config, `/model`/`/models`, dispatch and Compression to the direct pair and removes evaluator/Tier; second moves Call Log v3, Resume, reporting and recovery onto the direct route. Each must be a working, tested slice without compatibility shims; the interim state may refuse Resume of new Sessions clearly. Planner owns the exact seam and may choose a different one if this is not viable, explaining why.
