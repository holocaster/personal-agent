# 0057: ChatGPT subscription provider

## Goal and status

Let any Personal Agent user connect their own eligible ChatGPT account through a distinct `chatgpt` Provider, independently of existing API-key Providers. Discovery concluded on 2026-10-21 with the user's agreement. No product questions remain. The specification, ADR-0015 and five tickets are committed. The user subsequently authorized implementation and the local commits of this feature and its review corrections. Continue the SDD loop without asking again for those local commits. No push is authorized.

Research: `docs/research/2026-10-20-chatgpt-subscription-provider.md`. The spike proves behavior for one account at that time, not access for every user. Follow the official contract when the research's observations contradict it.

## Connection and model selection

- One connected account per installation; each user supplies their own authorization. Preserve separate registration identities internally, without an account selector.
- `/connect chatgpt` performs local-browser login, then fetches account models and opens a terminal picker with display names and exact slugs. Arrows navigate, Enter confirms and Escape cancels. A valid existing session needs no browser login again. Use the existing `InputBox`/`prompt-toolkit` infrastructure without a new UI dependency.
- `/disconnect chatgpt` disconnects only ChatGPT; existing `/config` shows safe connection status. Do not add external authentication CLI commands or a separate status command.
- Allow REPL entry without a usable route so users can configure credentials and connect. Model-backed tasks, Retry and Compression require a usable authenticated route; expose invalid configuration rather than silently replacing it. Noninteractive input must never hang on a popup.
- Selecting a ChatGPT model before login offers an explicit connect-now choice before opening the browser. Authentication, account-model validation and explicit model selection must succeed before atomically saving/activating the new route. Login alone does not change selection.
- Cancellation, failed login, unavailable plan permission, invalid model or failed settings save preserves the previous selection, or leaves a new installation unconfigured. A successful login survives a cancelled picker, empty model list or failed catalog request; show the remaining action clearly.
- Reuse `/model chatgpt <slug>`, `/model openai <model-id>` and existing model-listing forms. Account authorization and API keys may coexist. Selection determines the credential; no automatic fallback or need to disconnect ChatGPT to use an API key.
- When switching ChatGPT accounts, preserve normalized Conversation text and show an explicit notice before sending it to the new account. Never reuse account-bound opaque replay under another registration. Do not require clearing the Conversation.

## Requests, catalog and lifecycle

- Use the account's model listing for ChatGPT choices independently of Models.dev admission. Public metadata can complement capacities; assumed limits remain identifiable. Listing does not guarantee successful inference.
- Follow the official output contract: omit `max_output_tokens`; output reservation is an estimate without a guaranteed remote cap.
- On plan exhaustion, stop with clear guidance and preserve retryable work. The user decides whether to wait or explicitly select another Provider before `/retry`; no automatic waiting or fallback.
- Cover streaming, Tools and follow-ups, `/retry`, Resume, Fork, Compression, subagents, replay and reports while preserving existing API-key behavior. Subagents keep the parent's selected route/account; account changes must not alter in-flight task identity.
- Keep tokens outside model-visible context, project settings and logs. Validate JWT signatures/JWKS and identity/consent bindings fully; preserve private storage, safe refresh across processes and server revocation on disconnect. These are mandatory security obligations, not optional product choices.

## TUI and accounting

The footer identifies the active route's access method and context occupancy. Merely connecting an account must not relabel an unchanged route. Disconnected/unconfigured routes must not appear ready. Use the existing compact terminal style; values below are illustrative:

```text
build · openai/<model> · API key · ctx ~10k/258k · API ~$0.024
build · chatgpt/<model> · Assinatura ChatGPT · ctx ~10k/258k · /usage
```

- Context occupancy is estimated complete model-facing input versus effective input allowance, accounting for configured budget, route capacity and output reservation. It is not cumulative token consumption; assumed capacities must not look verified.
- API spend covers the current Run's accumulated API costs, retaining reported/estimated provenance and unknown coverage. With ChatGPT selected, remove the monetary counter rather than showing frozen API spend or `$0` as plan cost.
- Preserve earlier API costs in `/usage` and `/report`, distinguishable from plan consumption. Record unknown plan monetary cost as `cost=null`; do not convert usage into hypothetical API prices or claim zero billing.
- `/usage` shows observed plan token details and Manage usage access; missing counters remain unknown. Never invent remaining quota percentages or reset times. Show `Cota atingida` on plan exhaustion with usage guidance.
- Include first-login confirmation for plan use and the usage-management destination required by the official UI guidelines.

## Verified sources and planning responsibilities

Official documentation checked on 2026-10-21: [eligibility](https://developers.openai.com/siwc/quickstart), [login](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [account/session lifecycle](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions), [model discovery](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [preview restrictions](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations), and [UI requirements](https://developers.openai.com/siwc/ui-ux-guidelines). Recheck relevant contracts during specification; undocumented capacity fields and spike behavior are not guarantees.

The planner owns technical seams, ADR amendments (especially ADR-0011/0012), Call Log/account binding, context provenance, failure handling and testable acceptance criteria. Resolve these from the existing scope; return only genuine new product trade-offs to the user.

Out of scope: shared maintainer credentials, hosted account service, account selector, SSH/headless login or credential transfer, automatic Provider fallback, and external authentication CLI commands.
