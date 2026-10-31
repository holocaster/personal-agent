# 0027 — Web Search Tool

Brief: `docs/briefs/0027-websearch.md`. Existing Network Tool and confirmation
decisions: `docs/briefs/0022-web-todo-search.md` and
`docs/specs/0022-web-todo-search.md`. Agent Mode and fetched-content warning:
`docs/specs/0025-plan-build-mode.md` and `docs/CONTEXT.md`. The Call Log
remains the Conversation record (ADR-0005). Tavily REST contract:
https://docs.tavily.com/documentation/api-reference/endpoint/search (consulted
2026-09-27). No new ADR is needed; the brief already settles the service,
consent, and result boundary.

## Problem Statement

`webfetch` reads a URL the model already knows, but cannot discover relevant
current pages from a query. Users must supply a URL or resort to `shell` and
manually identify sources, without a query-specific disclosure gate.

## Solution

Offer an opt-in `websearch` Network Tool in both Agent Modes when the operator
has supplied a Tavily key. Before *every* request, show the entire query for
Tool Confirmation. One approved call asks Tavily for basic search results and
returns only a small, attributed set of links, titles and excerpts. The model
may then choose a URL and separately ask to `webfetch` it, with its own
confirmation. Search results are third-party data, not instructions.

## User Stories

1. As a user, I want to enable search with my own Tavily key, so that I control whether the model can use this paid service.
2. As a user without a key, I want ordinary Runs and other Tools to keep working, so that search is truly optional.
3. As a user in `plan`, I want the model to discover links without mutating my workspace, so that I can research before building.
4. As a user in `build`, I want the same search capability, so that implementation can use current sources.
5. As a user, I want the whole query displayed before each external request, so that I can spot workspace text or other sensitive information before it leaves my machine.
6. As a piped-input user, I want EOF or a refusal to prevent a request, so that non-interactive Runs cannot silently spend credits or disclose text.
7. As a user, I want each approved query to issue at most one basic search request, so that confirmation corresponds to one credit-priced action rather than hidden retries.
8. As a user, I want my Tavily key kept out of model-facing schemas, results, and the Call Log, so that configuring search does not expose the credential.
9. As the model, I want short, attributed titles, source URLs and snippets, so that I can identify a useful page to read.
10. As the model, I want `webfetch` to remain a separate confirmed action, so that search does not silently download full pages.
11. As a user, I want search results treated as untrusted third-party text, so that an injected snippet cannot change the safety guidance of my turn.
12. As a user, I want the Fetched-Content Warning before a later workspace-changing Tool after search results, so that I notice external text may have influenced the model.
13. As the model, I want bad queries or a rejected request reported as Tool errors, so that I do not assume a search happened.
14. As the model, I want transport, HTTP and quota failures reported as Tool errors, so that I never mistake failure for a zero-hit search.
15. As a user, I want a genuinely empty search to return an empty results list, so that it is distinguishable from failure.
16. As a Call Log reader, I want the query, decision and bounded result/error to follow normal Tool execution logging, so that I can audit the search without disclosing the key.
17. As a developer, I want fake-transport tests with no credentials or live Tavily calls, so that the feature can be verified offline.

## Requirements

- **R1 — Opt-in registration.** Read `TAVILY_API_KEY` from the existing startup
  environment/.env loading path (not the `/config` Provider-key menu). A
  nonempty, non-whitespace key enables `websearch` in the Tool Registry for a
  Run; unset/blank disables it, without failing startup or altering other Tool
  definitions. Both `plan` and `build` advertise it only when enabled. A
  fabricated call while disabled returns an unknown/unavailable Tool error
  before confirmation or transport. Do not put the key in the Tool schema,
  advertised description, model arguments, result, or Call Log.
- **R2 — Bounded argument contract.** Advertise and validate exactly one
  required field `query` (string, 1–500 characters, no extra properties).
  Reject all-whitespace queries before Tool Confirmation. The query is sent
  exactly as approved, without silently adding workspace content; its full
  value is shown without truncation in confirmation (control characters may
  be escaped for safe display). No model-controllable endpoint, search depth,
  result count, authentication header, or other Tavily parameter.
- **R3 — Consent.** Use the existing prepare → Tool Confirmation → apply path
  for every call, including subsequent calls in a batch or later Tool rounds.
  The Terminal displays `websearch: <query>` and the complete query, then asks
  `Search the web? [y/N] `. Only trimmed, case-insensitive `y` or `yes`
  approves; any other answer, piped EOF or missing confirmation callback
  returns the ordinary rejection Tool error without a request. Ctrl-C follows
  the existing interrupted-turn semantics.
- **R4 — Tavily request.** After approval, send exactly one POST to
  `https://api.tavily.com/search` with JSON `query`, `search_depth: "basic"`,
  `max_results: 5`, `chunks_per_source: 1`, `include_answer: false`,
  `include_raw_content: false`, `include_images: false`, and
  `auto_parameters: false`. Authenticate only via `Authorization: Bearer
  <TAVILY_API_KEY>`; do not use query parameters for the key. Use a fixed
  endpoint, fixed 30-second timeout and 1 MiB response-body limit (stop
  reading after limit + 1 bytes), no automatic redirects of the credential, and no automatic
  retry. Tavily documents basic search as one API credit per request; do not
  invoke its advanced/auto depth or full-content/answer features. No live
  request is necessary for development.
- **R5 — Bounded attributed result.** Return `{"results": [{"title": str,
  "url": str, "snippet": str}, ...]}` with at most five results in Tavily
  order. Read only `results[].title`, `results[].url`, and
  `results[].content` (rename to `snippet`); omit Tavily's answer, raw
  content, images, scores and metadata. Limit each title to 200 characters
  and each snippet to 300 characters (truncate overlong values rather than
  passing page content). Only include results whose URL is a usable
  `http`/`https` URL; an empty Tavily `results` array succeeds as `[]`.
  Keep the final serialized result within the existing Tool Output Cap,
  dropping trailing entries if needed; if even the empty result object does
  not fit, return a Tool error rather than malformed JSON. A source URL is
  attribution, not proof of credibility.
- **R6 — Error and secret boundary.** Invalid arguments, malformed API
  response, timeout, oversized response, transport failure and non-2xx
  statuses produce Tool errors (include the HTTP status when present).
  Distinguish 401 (bad key), 429 (rate limit), and 432/433 (quota/plan
  exhausted) without echoing the untrusted upstream body, URL or exception
  text that might contain the key. No synthesized results, retries, or
  Escalation on Tool errors. Keep the configured key out of all emitted Tool
  results/errors, terminal lines, Provider follow-ups, and Call Log records;
  include it in the Router's existing active-key redaction for Provider text
  and Tool arguments. The key is used only inside the transport request.
- **R7 — Existing flow and untrusted content.** Search follows Tool Registry
  validation, Tool execution result logging, Provider follow-up, and Tool
  Output Cap as `webfetch` does. System Prompt guidance marks both `websearch`
  results and `webfetch` content as untrusted third-party data and forbids
  following their instructions. After a successful search, a subsequent
  `shell`, `write`, or `edit` Tool Confirmation in the *same turn* shows the
  existing Fetched-Content Warning adapted to name the search query/source
  URLs (without exposing the key); rejected or failed searches add no warning.
  Subsequent `webfetch` of a search URL still requires its own confirmation.
- **R8 — Documentation and offline proof.** Document `TAVILY_API_KEY`, opt-in
  behavior, per-query confirmation and credit-priced basic search alongside
  `webfetch` in the README/config example if present. Tests use a fake
  transport, never a live key or Tavily request.

## Implementation Decisions

- Add a cohesive `websearch` implementation alongside `webfetch` in Tools;
  keep the credential in local Run configuration, not in model-provided
  arguments or the Provider Contract. Load it after the existing dotenv
  sequence, wire it into Tool Registry enablement and Router active-key
  redaction; avoid a new Provider or `/config` entry.
- Reuse Tool Registry schema validation and confirmed prepare/apply execution;
  an absent key removes both definition and executable entry, including in
  plan mode. Avoid treating a disabled call as valid merely because a model
  sent its name. Reset test-only registry state as existing shell tests do.
- Reuse Terminal confirmation input semantics and existing per-turn warning
  plumbing; preserve warning behavior for `webfetch` while adding a search
  source marker only after success. Search-only results never count as a
  fetched page; display language may say "external search content" rather
  than pretending a page was fetched.
- Use stdlib REST transport like `webfetch`. Tavily's documented JSON `POST
  /search` takes bearer auth and returns `results[].title/url/content`.
  Explicit basic depth, one chunk per source and disabled answer/raw content
  bound cost and data even if service defaults change. Treat response fields
  as untrusted; projection, HTTP URL filtering and caps happen before logging
  or forwarding. Never log the raw response or auth header.
- No new ADR: Tavily-only, key opt-in, per-query consent and no full-page
  search response are already settled in the feature brief; existing ADR-0005
  handles Tool record persistence.

## Testing Decisions

- Test observable effects at the highest existing seam: `run_repl` with
  scripted Provider Tool calls, input/confirmation, Call Log capture and fake
  Tavily transport. Prior art: `tests/test_repl.py`, `tests/test_webfetch.py`,
  `tests/test_routing.py`, `tests/test_tools.py`. Verify offered Tools for both
  Agent Modes with/without key, normal startup without key, refusal/EOF and
  approval in both input modes, exact confirmed query, one request per
  approval, no redirects/retries, redaction, result logging/follow-up,
  independent `webfetch` confirmation, and same-turn warning only on success.
- At the Tool Registry/transport seam, exercise schema and whitespace errors
  before confirmation; fake HTTP 401/429/432/433/500, timeout, oversized and
  malformed payloads; valid zero hits, too many/overlong results, invalid
  source URLs and small Tool Output Cap. Assert no exception/HTTP body leaks
  the credential and no failure becomes a successful result. Run the existing
  offline suite after the slice lands.
- Avoid testing private helper names or a particular HTTP-client mock shape;
  assert outbound method, endpoint, authorization header, JSON options and
  bounded public Tool result instead. Fake transport must not require a
  network connection.

## Out of Scope

Additional search services, automatic provider selection, web scraping,
browser automation, crawling, page text or AI answers in search results,
query rewriting, model API-key `/config` edits, Provider Contract/Tier/Budget
changes, and `apply_patch`. Search does not make a chosen URL trusted or
bypass the `webfetch` Tool Confirmation.

## Further Notes

Tavily's documented 429 means rate limited, while 432 means key/plan limit
and 433 means pay-as-you-go limit; not all exhausted-credit cases are 429.
One approved basic request is billed according to Tavily's external terms,
not the local Budget Guardrail. A confirmation is a disclosure gate, not a
guarantee the remote service is safe or a source is reliable.
