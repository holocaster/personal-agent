status: approved
ticket: tickets/0017-usage-command/01-usage-command.md
reviewed_range: 9da1fafb290911d01d3195dd2946169eff1959aa..9c76758861c1a9a579acf44822759e23ad50e606

criteria:
  - criterion: RouteResult carries prompt_tokens, completion_tokens, cost_estimated, passed through from _run_exchange's existing usage (nothing recomputed)
    result: pass
  - criterion: run_repl tracks the last successful RouteResult's usage fields alongside last_tier/last_model
    result: pass
  - criterion: /usage added to COMMANDS, HELP_TEXT, and _handle_command dispatch
    result: pass
  - criterion: /usage before any completed turn prints a local message and makes no Provider call
    result: pass
  - criterion: /usage after a successful turn prints tier+model, spend ($ format same as render_footer, plus estimated note), last Attempt's prompt/completion tokens, turns retained vs sent
    result: pass
  - criterion: /usage rejects extra arguments like other no-args commands
    result: pass
  - criterion: Pure render_usage function with a direct unit test, plus REPL-level tests before and after a successful turn
    result: pass
  - criterion: README /help list gets a /usage bullet in the same style
    result: pass

findings:
  - severity: suggestion
    location: src/personal_agent/terminal/repl.py render_usage (the "tokens:" line)
    impact: If a Provider response has no usage block, prompt_tokens/completion_tokens are None and /usage prints "tokens: None prompt, None completion". Cosmetic; not specified by the ticket.
    required_change: Optional - render a placeholder such as "unknown" when the token counts are None.
  - severity: suggestion
    location: src/personal_agent/terminal/repl.py run_repl (/undo interaction)
    impact: After /undo, /usage still reports the tier/model/tokens of the removed answer (turns count does update). Consistent with how the Status Footer already treats last_tier/last_model - not a regression.
    required_change: None required.

checks:
  - "Full pytest suite at head_sha 9c76758: 564 passed in 8.50s"
  - "No lint config/tooling present in the repo; none run"
  - "Manual trace confirmed usage flows correctly through the tool loop (final exchange, not first) and through error/escalation paths (defaults to None/None/False)"
  - "Argument rejection verified via test_usage_with_arguments_is_a_local_error"
  - "Standards: matches repo conventions, no stray comments, mirrors render_footer/_handle_command patterns, no over-engineering"

residual_risks:
  - "After a resumed Session, /usage reports 'No completed turns yet this Run.' even though the Conversation already holds turns - matches the ticket's wording ('this Run'), but may surprise a user."
