# Prompt surface fixtures

`fixtures/prompt-surface/{plan,build,auto}.md` contains complete system text and
ordered Tool schemas captured through the production Router and OpenRouter HTTP
path. The renderer uses temporary home/workspace, synthetic context/config/keys,
all optional Tool gates, and blocked network access; no MCP server or shell runs.

After intentionally changing a prompt or schema, regenerate offline from the repo
root and review all three diffs:

```sh
.venv/bin/python -m tests.prompt_surface tests/fixtures/prompt-surface
.venv/bin/pytest -q tests/test_prompt_surface.py
git diff -- tests/fixtures/prompt-surface
```

Tests also verify unchanged preceding bytes in all four Providers' complete
prepared inputs when Memory, active Skills, Summary or Todo changes, faithful
budgets, schema-array order, real text/schema sensitivity and byte-identical
rendering under changed clock/root/home/credentials/hash seed. These structural
checks supplement behavioral tests; they do not measure cache hits or savings.

# Synthetic model catalog

Startup and REPL boundaries admit the pair through the Models.dev catalog. The
autouse `_synthetic_catalog` fixture in `conftest.py` builds the cache through
the real refresh path from `SYNTHETIC_MODELS` (each ID under all four
Providers, context 128000, output 16000) and stores it outside the temporary
home; catalog HTTP stays blocked. Add an ID there when a REPL or `main()` test
uses a new model. `test_model_catalog.py` restores the real cache path, and
`test_catalog_selection.py` swaps catalogs with `synthetic_models_dev()` and a
fake `_open` to exercise refresh, removal and limits.
