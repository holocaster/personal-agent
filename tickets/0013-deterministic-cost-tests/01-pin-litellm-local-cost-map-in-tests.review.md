ticket: 0013-deterministic-cost-tests/01
reviewed_range: d9fdf6725d4719f84e95041c436345eb0f456bce..9fd822aeb660784a3af0fc0efa8bc8e95523da2e
status: approved
round: 1

Checks:
- At head, run from /tmp with LITELLM_LOCAL_MODEL_COST_MAP unset: 377 passed.
- At base, same conditions: the same 2 failures. This confirms the root cause.

Suggestion (not applied): the docstring cites a line in a litellm internal file, which may go stale when litellm is upgraded.
