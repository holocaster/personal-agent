# 0027 — Web Search Tool

## Goal

Let the agent discover relevant, current web pages by query before reading a chosen URL with `webfetch`.

## Scope

- Add a model-facing `websearch` Network Tool for both `plan` and `build`. It sends one approved search query to Tavily's REST API using the operator's own key, with basic search (one API credit per request per Tavily's documentation).
- Opt in through a configured Tavily API key. Without a key, do not offer the Tool to the model; other Tools and ordinary startup remain usable. Never put the key in the model's Tool arguments, output, or Call Log.
- Require Tool Confirmation displaying the full search query before every external request, in interactive and piped Runs using the existing confirmation convention. Rejection makes no network request.
- Return a bounded list of titles, URLs and short snippets, with source attribution. Search results are untrusted third-party content; reading a page is a separate `webfetch` call with its existing confirmation. Keep the existing warning before subsequent workspace-changing Tools when third-party content in the current turn may have influenced the model.
- Use the existing Tool Registry validation, result logging, Provider follow-up and Tool Output Cap. Errors (invalid query, network/API failure, exhausted credits) are reported as Tool errors, not invented search results. Test offline with fake transport; no live Tavily call or key is required for development.

## Out of scope

- Multiple search providers, automatic provider selection, scraping an unauthenticated search page, browser automation or deep crawling.
- Full-page content or LLM-generated search answers in the result; use `webfetch` for a selected URL.
- Changing the Provider Contract, Tier routing, Budget Guardrail or Runtime Configuration menu for model API keys.
- `apply_patch`, which is the next separate SDD feature.

## Settled decisions

1. Tavily is the only initial search service; the Tool is opt-in through its own API key and unavailable to the model when unconfigured.
2. Every query requires Tool Confirmation before an external request, because the query may expose workspace text.
3. Return only bounded source links, titles and excerpts, not page content. `webfetch` stays responsible for reading a known URL.
4. Offer the Tool in both Agent Modes, subject to the same confirmation gate.

## Open questions

None for product scope. The planner owns bounded argument/result schemas, key configuration details, errors and ticket slicing under these constraints.
