# Ticket0053-05 acceptance self-check

Criterion review completed before the final privacy-fix freeze. No known uncovered functional obligation remains; independent review is still required.

| Requirement | Production boundary and evidence |
| --- | --- |
| R21 execution/latest/eligibility | Session+Run+opening+ordinal; repeated edit/patch and canonical aliases; distinct Retry restore set; error/interrupted/no-TurnEnd; no-op/reject/read-only/rolled-back later work retains the old set. |
| R22 exact/private/safe storage | Base64+SHA256+bytes/mode/absence and link/parent identity;0700/0600; owner/permissions/link/FIFO/hardlink/schema/base64/hash/bounds refusal; same/cross-project read/list/search and direct/alias Project Instructions exclude recovery storage; actual Provider request privacy RED/GREEN. |
| R23 approved apply/durable ordering | prepare effects rechecked after confirmation for all three Tools; live plan gate; fsync intent before mutation and observed promotion before dependent exchange; six real-process capture deaths; before/after/promotion persistence errors; actual partial write rollback. |
| R24 local preview/yes/modes | Exact identity/outcome, actions/paths/reverse diffs, sanitized/redacted bounded output with omission notices, exclusions/bounds/shell/older-Retry scope; full literal yes in auto/piped/interactive, no/y/YES/EOF/Ctrl+C cancellation; plan/live switch; unexpected args; no extra Provider call or Conversation change. |
| R25 whole-set conflicts | Content/chmod/absence/leaf replacement/parent replacement; revalidation during recovery confirmation; alias preservation; hardlink refusal; no new parent creation or outside-root writes. |
| R26 restore/failure/Call Log | Real create/delete/edit/modes after Resume; partial second-file restore rollback to known after-states; failed rollback unresolved/fatal; started/finished partial append prefix restoration and failed-truncate fatality; completion failure and promotion reconciliation; successful consumption never steps into older history. |
| R27 Resume/continuation | Real-process death at five restore boundaries; before/intended-after capture reconciliation and uncertainty refusal; matching prefix/Todo/nonempty fetched URLs/Gemini reset; Retry contributor lineage across live/Resume/no-TurnEnd; unrelated later pending and independent same-ordinal Retry preserved; manual Compression dispatch blocked on unresolved journal. |
| R28 retention/bounds/legacy | Current PA_MAX_WRITE_BYTES capped4MiB; actual4MiB+1 and64-path refusal; scaled16MiB/24MiB/80MiB peak-before-write proofs; exact set not truncated; clear/undo/compress/read-only/noop/reject/rollback retention; no companion legacy works with existing runtime config; actual shell effects excluded. |
| R32 integration/delivery | Source/callers/fixtures, concise README/help, ENV_VARS, dated research status; context changes proposed in handoff; no deps/install/paid calls/sudo/push; local commit only after frozen full passes. |

Production root causes proved during implementation and fixes are recorded in `/tmp/0053-ticket05-implementation-handoff.json`. Final freeze and pytest XML are recorded there after completion.
