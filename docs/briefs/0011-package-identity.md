# 0011 - Personal Agent Package Identity

## Goal

Make the Python package identify the whole Personal Agent rather than only its
Router capability. The application now includes terminal presentation, local
Tools, routing, and Provider adapters, so `model_router` is too narrow as the
source and distribution identity.

## Scope

1. Move source to the standard `src/personal_agent` layout and migrate all
   active production and test imports to `personal_agent`.
2. Configure Hatchling to build `src/personal_agent`; update the distribution
   name from `model-router` to `personal-agent` and keep the lockfile valid.
3. Preserve `python -m personal_agent` as the composition-root entry point
   and all existing runtime behavior.
4. Remove the unused root sketches `reference_agent_loop.py` and
   `reference_model_router.py`, plus active documentation that tells readers
   to use them as reference material.
5. Update active README and notebook source pointers.

## Out of scope

- Changing routing, Tools, terminal behavior, Providers, dependencies, or
  configuration.
- A package named `src` or compatibility aliases for `model_router`.
- Rewriting historical specs, tickets, ADRs, or reviews that record the old
  name accurately at the time they were written.

## Settled decisions

- `src` is the source-layout container; `personal_agent` is the importable
  package and application identity.
- The Router remains the `routing` capability, not the package root.
- The reference sketches are unused and are deleted rather than preserved or
  moved.

## Open questions

None.
