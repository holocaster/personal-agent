# 01: Search the web with a confirmed, bounded Tavily Network Tool

**What to build:** Let a user who supplies a Tavily API key approve one
search query and receive a short attributed set of sources in either Agent
Mode; without a key, ordinary Runs work but the model cannot invoke search.
Keep remote results and the credential behind the existing Tool safety and
Call Log boundaries, so the model may choose a URL for separately confirmed
`webfetch` without treating snippets as instructions.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0027-websearch.md` (R1–R8, Testing Decisions);
**ADRs:** ADR-0005 (Call Log/Conversation); network consent follows
`docs/briefs/0022-web-todo-search.md`.

- [x] Wire `TAVILY_API_KEY` through the existing startup dotenv path, independent
      of the `/config` Provider-key menu. With a nonblank key, advertise and
      execute `websearch` in both `plan` and `build`; without one, omit it from
      the Tool Registry and reject a fabricated call before confirmation or
      network I/O, without breaking other Tools or startup. Keep the key out
      of Tool definitions, model arguments and Call Log entries. (R1, R6)
- [x] Define and validate the single `{query}` model argument (required string,
      1–500 chars, no extra properties). Reject whitespace-only queries before
      asking the user; pass the exact approved query. Reuse Tool Registry's
      prepare → Tool Confirmation → apply path for each call, including mixed
      batches and later rounds. Show the *complete* query safely with the
      `Search the web? [y/N] ` prompt in interactive and piped Runs; refusal,
      EOF or no confirmation callback yields a Tool error and zero requests;
      Ctrl-C interrupts as it does for `webfetch`. (R2, R3)
- [x] After approval, issue only one bounded JSON POST to Tavily's fixed
      HTTPS `/search` endpoint, bearer key in header only, explicit basic depth,
      max five results, one chunk per source, and answer/raw content/images/
      auto parameters disabled. No credential-forwarding redirects, retry or
      live test. Project at most five Tavily `results[].title/url/content`
      items in order to `{title, url, snippet}` (200/300 character limits),
      filtering unusable/non-HTTP URLs. Cap the serialized result to the Tool
      Output Cap, omitting trailing entries as necessary; preserve valid zero
      hits as `{"results": []}` (error if even this cannot fit). `webfetch`
      stays a separate, confirmed GET.
      (R4, R5, R7)
- [x] Convert invalid arguments, malformed response, timeout, oversized body
      and HTTP/transport failures to Tool errors, including status when
      available and distinguishing 401/429/432/433; do not invent results or
      expose upstream response/error bodies. Redact the Tavily key in any
      projected result and the Router's existing Provider-output/Tool-argument
      redaction path. Assert no key appears in terminal output, Tool results,
      Provider follow-up or Call Log; no Tool failure triggers Tier
      Escalation. (R6)
- [x] Extend System Prompt guidance to include untrusted `websearch` results.
      After *successful* search only, give later `shell`, `write`, `edit`
      confirmations in the same turn the existing Fetched-Content Warning,
      identifying external search content without erasing the `webfetch`
      warning; never warn for rejected/failed searches or carry the marker
      across turns. Preserve the normal Tool result, Call Log, Provider
      follow-up and separate `webfetch` Tool Confirmation. (R7)
- [x] Document the optional key, basic-credit cost, query confirmation and
      source-link-only result alongside `webfetch` in README/config example.
      (R8)
- [x] Verify offline using fake Tavily transport and scripted `run_repl` Tool
      calls. Cover registration and both modes with/without key; interactive
      and piped approval/refusal/EOF; schema and whitespace errors; precise
      request shape and request count; redirect refusal; response/error cases
      including rate limit and exhausted credits; caps, malformed data and
      zero hits; untrusted guidance and same-turn warning; Call Log/key
      redaction; independent confirmed `webfetch`. Run the full offline suite.
      (R1–R8)
