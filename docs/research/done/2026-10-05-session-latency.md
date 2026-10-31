# Session latency diagnosis

**Status (2026-10-05):** investigated; feature 0045 changes OpenRouter requests to prefer upstream generation throughput. No paid model calls made. Measurements below describe the session before this change, not a comparative model benchmark.

## Evidence

Session: `~/.personal_agent/logs/pa_log-20261005T092917Z-p6b4c8.jsonl` and its audit companion. Durations use logged request/tool events; interaction intervals include human time and must not be counted as model latency.

| Measurement | Result |
| --- | --- |
| First user turn, wall time | 276.227 s |
| First turn, provider time | 214.904 s; six calls including evaluator |
| Second user turn, wall time | 428.917 s |
| Second turn, provider time | 177.500 s; nine calls |
| MiniMax M3 task calls | 14; total 391.231 s; median 16.143 s; max 74.348 s; five over 30 s |
| Easy-tier evaluator | 1.173 s |
| M3 tokens across calls | 178,353 input; 140,801 cached input; 16,135 output |
| Recorded `list_files` call | 13.185 s |
| Completed tool execution excluding question/confirmation intervals | 13.326 s; includes `list_files` |
| Completed question interaction intervals | 180.437 s; interrupted question without end excluded |
| Confirmation intervals | 124.195 s; include preparation/display/human time |

The audit attempt intervals exceed logged provider duration by only 14 ms in aggregate, at most 2 ms per attempt. The large model-call durations occur inside the provider boundary, rather than in surrounding routing/accounting code. This does **not** isolate network transit, OpenRouter overhead, host queueing, prefill, reasoning, or decoding. The session did not retain generation IDs or reasoning-token counters, so those contributions remain unproven.

Cached input is 78.95% of M3 input. Five calls with under 10% cache hits had median 36.043 s, versus 10.989 s for seven calls above 90%; this is correlation in a small sample, not proof that cache caused the difference. A warm call generating 7,044 tokens still took 72.445 s. Blindly switching hosts or rewriting prompts can lose cache benefits, and cache alone cannot explain every slow call.

## Proven local bottleneck

**Resolved (2026-10-06, feature 0048):** shared lazy traversal now stops listing/search when their matching result or output limit is established. Independent ordering, filtering and safety checks passed. Measurements below describe the previous eager implementation. Immediate children still require sorting, and search still reads each inspected file in full.

`src/personal_agent/tools/workspace.py` eagerly walks and globally sorts every eligible path in `_walk_files`; `list_files` then converts all paths before applying its result cap. With workspace set to the home directory, the actual `list_files({"path": "."})` reproduction walked 153,674 files: 10.151 s in the walker, 16.169 s total, returning only 100 paths with `truncated: true`. This reproduces the expensive scan observed in the session.

The deterministic check `/tmp/personal-agent-listing-latency-check.py`, run with `.venv/bin/python`, failed before feature 0048 because traversal entered `z_later` after 101 root matches have already established the first 100 sorted results plus truncation. It is a diagnostic artifact, not a committed regression test. `search_text` shares the walker: any implementation change must preserve ordering, apply glob filtering before the result cap, and retain symlink exclusions.

## Current provider documentation

OpenRouter defaults to price-weighted selection among healthy hosts. `provider.sort: "latency"` prioritizes time to first token; `"throughput"` prioritizes output speed. Explicit sorting disables price-weighted balancing. Soft latency/throughput preferences prioritize qualifying hosts without guaranteeing the threshold. These settings address different parts of completion time and need a workload benchmark, including cache reuse and cost. [Provider selection](https://openrouter.ai/docs/guides/routing/provider-selection), [latency guidance](https://openrouter.ai/docs/guides/best-practices/latency-and-performance).

MiniMax's M3 README documents native `thinking` modes `enabled`, `adaptive`, and `disabled`. The current OpenRouter model record reports `reasoning.mandatory: false` and includes `reasoning` in supported parameters, but omits effort/default metadata. Therefore M3 is not documented as always requiring reasoning. OpenRouter exposes unified reasoning controls; disabling is a candidate experiment, not a verified improvement in this application's flow. `reasoning.exclude: true` only hides reasoning output: computation and billing continue. Do not substitute exclusion for disabling. [MiniMax M3 README](https://github.com/MiniMax-AI/MiniMax-M3), [OpenRouter model metadata](https://openrouter.ai/api/v1/models), [reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

OpenRouter's generation metadata endpoint accepts a completion's generation ID and reports host, latency, generation time, cached/completion/reasoning tokens, and whether the call streamed. Persist the ID and reasoning count rather than putting metadata polling on the response path. Streaming exposes response deltas and final usage; headers or keep-alive comments are not first content. It can improve visible progress and provide timing evidence; it does not by itself prove faster task completion, and complete tool arguments are still required before execution. [Generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-request-%26-usage-metadata-for-a-generation), [streaming](https://openrouter.ai/docs/api_reference/streaming).

## Smallest useful next steps

The user selected upstream provider speed as the immediate scope. Feature 0045 adds `provider.sort: "throughput"` to the existing OpenRouter adapter while retaining `require_parameters: true` and default fallbacks. This requests speed-first host selection for the configured model; it may cost more and has no measured live speedup yet. Filesystem, evaluator, reasoning and streaming changes are outside this follow-up.

1. Bound file enumeration at the shared traversal seam, preserving existing results and safety behavior. Validate the deterministic operation check and existing workspace-tool tests before timing again. This addresses a reproduced defect, but cannot remove the 391 s of provider time.
2. Retain existing completion IDs and reasoning usage in call diagnostics; collect TTFT and full completion time when adding streaming. This makes queue/prefill versus generated output diagnosable without synchronous lookup delays.
3. Benchmark M3's default host selection against throughput/latency preferences and supported reasoning-off behavior, one variable at a time. Keep tool workload, cache conditions, answer quality, output budget, and cost comparable. No measured speedup is available yet.
4. Reduce avoidable sequential model rounds using existing batchable tools such as `skill(names)`. Preserve questions/confirmations that are actually required; their human interaction time is separate from infrastructure latency.
5. Add streaming for progress if silent waits remain the main UX problem. Treat total task time and perceived responsiveness as separate outcomes.

Do not remove the tier evaluator to address this incident: its measured 1.173 s is negligible compared with M3 calls. Do not recommend a replacement model from unrelated benchmark scores or claim a host/reasoning change fixes the root cause without a comparable replay.
