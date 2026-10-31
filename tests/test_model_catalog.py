import copy
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from personal_agent import call_log, model_catalog
from personal_agent.__main__ import main
from tests.fakes import FakeCatalogResponse

REAL_CACHE_PATH = model_catalog.cache_path
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "models-dev" / "api.json").read_text())


@pytest.fixture(autouse=True)
def _no_synthetic_cache(_synthetic_catalog, monkeypatch):
    monkeypatch.setattr(model_catalog, "cache_path", REAL_CACHE_PATH)


@pytest.fixture
def catalog_http(monkeypatch):
    def install(*outcomes):
        requests = []

        def fake_open(request, timeout=None):
            requests.append({"request": request, "timeout": timeout})
            outcome = outcomes[len(requests) - 1]
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome if isinstance(outcome, FakeCatalogResponse) else FakeCatalogResponse(outcome)

        monkeypatch.setattr(model_catalog, "_open", fake_open)
        return requests

    return install


def cache_file() -> Path:
    return Path.home() / ".personal_agent" / "models-dev.json"


def write_valid_cache(catalog_http):
    catalog_http(FIXTURE)
    model_catalog.refresh()
    return cache_file().read_bytes()


def test_cli_lists_each_provider_with_exact_ids_without_credentials_or_session(catalog_http, capsys):
    requests = catalog_http(FIXTURE)

    main(["--models", "gemini"])
    out = capsys.readouterr().out
    main(["--models", " OpenRouter "])
    openrouter_out = capsys.readouterr().out

    assert len(requests) == 1
    request = requests[0]["request"]
    assert request.full_url == "https://models.dev/api.json?type=all"
    assert request.get_method() == "GET" and requests[0]["timeout"] == 10
    assert request.get_header("Accept-encoding") == "identity"
    assert not any("key" in name.lower() or name.lower() == "authorization" for name in request.headers)
    assert "gemini-direct  Gemini Direct [alpha]  (context 1048576, output 65536)" in out
    assert "gemini-no-limit" not in out and "gemini-no-tool-field" not in out
    assert "deepseek" not in out
    assert "does not prove account access" in out and "--refresh-models" in out
    assert "vendor/Case-Model  Case Model [beta]" in openrouter_out
    assert call_log.active_session_id() is None
    assert not (Path.home() / ".personal_agent" / "logs").exists()


@pytest.mark.parametrize("provider, expected", [
    ("openrouter", ["vendor/Case-Model"]),
    ("openai", ["gpt-direct"]),
    ("anthropic", ["claude-image-out", "claude-native"]),
    ("gemini", ["gemini-direct", "gemini-no-limit", "gemini-no-tool-field"]),
])
def test_all_four_mappings_keep_exact_offering_ids(catalog_http, provider, expected):
    catalog_http(FIXTURE)
    catalog = model_catalog.load()

    assert list(catalog.offerings[provider]) == sorted(FIXTURE[model_catalog.UPSTREAM_IDS[provider]]["models"])
    assert [offering.id for offering in catalog.search(provider)] == [
        model_id for model_id in expected if catalog.offerings[provider][model_id].eligible
    ]


def test_eligibility_reasons_cover_metadata_matrix(catalog_http):
    catalog_http(FIXTURE)
    offerings = model_catalog.load().offerings

    reasons = {(provider, model_id): offering.reason
               for provider, models in offerings.items() for model_id, offering in models.items()}
    assert reasons == {
        ("openrouter", "vendor/Case-Model"): None,
        ("openrouter", "vendor/interleaved"): "requires interleaved reasoning replay the openrouter adapter cannot retain",
        ("openrouter", "vendor/no-tools"): "does not support Tool calling",
        ("openai", "embed-small"): "specialized 'embedding' model",
        ("openai", "gpt-direct"): None,
        ("openai", "gpt-old"): "deprecated",
        ("openai", "gpt-override"): "requires model-level Provider overrides",
        ("anthropic", "claude-image-out"): "requires text input and output",
        ("anthropic", "claude-native"): None,
        ("gemini", "gemini-direct"): None,
        ("gemini", "gemini-no-limit"): "incomplete metadata: no context/output limit",
        ("gemini", "gemini-no-tool-field"): "incomplete metadata: no Tool-calling evidence",
    }
    assert offerings["openai"]["gpt-direct"].input == 272000


@pytest.mark.parametrize("limit, reason", [
    ({"context": 0, "output": 1}, "invalid context/output limits"),
    ({"context": 1000, "output": 2000}, "invalid context/output limits"),
    ({"context": 1000.5, "output": 10}, "invalid context/output limits"),
    ({"context": 1000, "input": 2000, "output": 10}, "invalid input limit"),
    ({"context": 1000, "input": -1, "output": 10}, "invalid input limit"),
])
def test_unusable_limits_are_retained_as_ineligible(catalog_http, limit, reason):
    document = copy.deepcopy(FIXTURE)
    document["openai"]["models"]["gpt-direct"]["limit"] = limit
    catalog_http(document)

    assert model_catalog.load().offerings["openai"]["gpt-direct"].reason == reason


@pytest.mark.parametrize("field, value, reason", [
    ("status", "retired", "unrecognized status 'retired'"),
    ("type", "chat", None),
    ("interleaved", False, None),
    ("provider", {}, None),
    ("cost", None, None),
])
def test_optional_metadata_edges(catalog_http, field, value, reason):
    document = copy.deepcopy(FIXTURE)
    document["openai"]["models"]["gpt-direct"][field] = value
    catalog_http(document)

    assert model_catalog.load().offerings["openai"]["gpt-direct"].reason == reason


def test_cache_stores_only_consumed_metadata_and_hit_makes_zero_requests(catalog_http, monkeypatch):
    original = write_valid_cache(catalog_http)
    cached = json.loads(original)
    requests = catalog_http()

    catalog = model_catalog.load()

    assert requests == []
    assert catalog.search("openai") and catalog.fetched_at == cached["fetched_at"]
    assert cached["version"] == 1 and cached["source"] == model_catalog.URL
    assert set(cached["providers"]) == {"openrouter", "openai", "anthropic", "gemini"}
    assert cached["providers"]["gemini"]["id"] == "google"
    text = original.decode()
    assert "cost" not in text and "future_field" not in text and "evil.example" not in text and "secret" not in text
    assert oct(cache_file().stat().st_mode & 0o777) == "0o600"


def test_old_cache_of_any_age_is_used_offline(catalog_http, capsys):
    write_valid_cache(catalog_http)
    cached = json.loads(cache_file().read_text())
    cached["fetched_at"] = "2001-01-01T00:00:00Z"
    cache_file().write_text(json.dumps(cached))
    catalog_http(URLError("offline"))

    main(["--models", "openai"])

    assert "fetched 2001-01-01T00:00:00Z" in capsys.readouterr().out


@pytest.mark.parametrize("corrupt", [
    b"{not json",
    b'{"version": 2}',
    b"x" * (16 * 1024 * 1024 + 1),
    "missing-provider",
    "bad-timestamp",
])
def test_unusable_cache_triggers_exactly_one_fetch_and_replacement(catalog_http, corrupt):
    write_valid_cache(catalog_http)
    if corrupt == "missing-provider":
        cached = json.loads(cache_file().read_text())
        del cached["providers"]["gemini"]
        corrupt = json.dumps(cached).encode()
    elif corrupt == "bad-timestamp":
        cached = json.loads(cache_file().read_text())
        cached["fetched_at"] = "yesterday"
        corrupt = json.dumps(cached).encode()
    cache_file().write_bytes(corrupt)
    requests = catalog_http(FIXTURE)

    catalog = model_catalog.load()

    assert len(requests) == 1
    assert catalog.search("gemini")
    assert json.loads(cache_file().read_text())["version"] == 1


def test_no_cache_and_failed_fetch_reports_refresh_guidance(catalog_http, capsys):
    requests = catalog_http(URLError(TimeoutError("timed out")))

    with pytest.raises(SystemExit) as exc_info:
        main(["--models", "openai"])

    assert exc_info.value.code == 1 and len(requests) == 1
    err = capsys.readouterr().err
    assert "Models.dev catalog unavailable" in err and "no cached catalog" in err
    assert "personal-agent --refresh-models" in err
    assert not cache_file().exists()


def response_with(**kwargs):
    body = kwargs.pop("body", FIXTURE)
    return FakeCatalogResponse(body, **kwargs)


@pytest.mark.parametrize("outcome, message", [
    (TimeoutError("timed out"), "fetch failed"),
    (HTTPError(model_catalog.URL, 503, "Service Unavailable", None, None), "fetch failed: HTTP Error 503"),
    (lambda: response_with(status=204), "unexpected HTTP status 204"),
    (lambda: response_with(content_type="text/html"), "unexpected media type 'text/html'"),
    (lambda: response_with(headers={"Content-Encoding": "gzip"}), "unexpected compressed response"),
    (lambda: response_with(url="https://evil.example/api.json"), "refused catalog response"),
    (lambda: response_with(url="http://models.dev/api.json"), "refused catalog response"),
    (lambda: response_with(headers={"Content-Length": str(16 * 1024 * 1024 + 1)}), "exceeds 16 MiB"),
    (lambda: response_with(body=b" " * (16 * 1024 * 1024 + 1)), "exceeds 16 MiB"),
    (lambda: response_with(body=b'{"openai": {', headers={"Content-Length": "999"}), "truncated response"),
    (lambda: response_with(body=b'{"openai": {'), "malformed JSON"),
    (lambda: response_with(body=b'{"a": 1, "a": 2}'), "duplicate key 'a'"),
    (lambda: response_with(body=b"[]"), "top level is not an object"),
])
def test_failed_refresh_preserves_cache_bytes(catalog_http, capsys, outcome, message):
    original = write_valid_cache(catalog_http)
    requests = catalog_http(outcome() if callable(outcome) else outcome)

    with pytest.raises(SystemExit) as exc_info:
        main(["--refresh-models"])

    assert exc_info.value.code == 1 and len(requests) == 1
    err = capsys.readouterr().err
    assert "Models.dev catalog refresh failed" in err and message in err
    assert "Existing cache and settings kept" in err
    assert cache_file().read_bytes() == original


def test_fetch_stops_after_total_time_budget(catalog_http, monkeypatch):
    original = write_valid_cache(catalog_http)
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr(model_catalog, "monotonic", lambda: next(clock))
    catalog_http(response_with())

    with pytest.raises(model_catalog.CatalogError, match="exceeded 30 seconds"):
        model_catalog.refresh()

    assert cache_file().read_bytes() == original


def test_redirect_guard_allows_only_https_models_dev():
    guard = model_catalog._RedirectGuard()
    request = Request(model_catalog.URL)

    with pytest.raises(model_catalog.CatalogError, match="refused catalog redirect"):
        guard.redirect_request(request, None, 302, "Found", {}, "https://evil.example/api.json")
    with pytest.raises(model_catalog.CatalogError, match="refused catalog redirect"):
        guard.redirect_request(request, None, 302, "Found", {}, "http://models.dev/api.json")
    assert guard.redirect_request(request, None, 302, "Found", {}, "https://models.dev/api.json?x=1") is not None


def mutate(path, value):
    document = copy.deepcopy(FIXTURE)
    target = document
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return document


@pytest.mark.parametrize("document, message", [
    (mutate(("google",), KeyError), "missing or mismatched 'google' section"),
    (mutate(("openai", "id"), "open-ai"), "missing or mismatched 'openai' section"),
    (mutate(("anthropic", "models"), {}), "'anthropic' has no models"),
    (mutate(("openai", "models", "gpt-direct", "id"), "gpt-other"), "mismatched id"),
    (mutate(("openai", "models", "gpt-direct", "tool_call"), "yes"), "invalid tool_call"),
    (mutate(("openai", "models", "gpt-direct", "limit"), {"context": "big", "output": 1}), "invalid context limit"),
    (mutate(("openai", "models", "gpt-direct", "modalities"), {"input": "text", "output": ["text"]}), "invalid input modalities"),
    (mutate(("openai", "models", "gpt-direct", "modalities", "input"), ["text"] * 17), "invalid input modalities"),
    (mutate(("openai", "models", "gpt-direct", "name"), "n" * 257), "invalid name"),
    (mutate(("openai", "models", "gpt-direct"), "not an object"), "is not an object"),
])
def test_malformed_documents_are_refused_whole(catalog_http, document, message):
    original = write_valid_cache(catalog_http)
    catalog_http(document)

    with pytest.raises(model_catalog.CatalogError, match="invalid catalog schema") as exc_info:
        model_catalog.refresh()

    assert message in str(exc_info.value)
    assert cache_file().read_bytes() == original


def test_offering_count_and_id_length_limits(catalog_http):
    long_id = "m" * 257
    catalog_http(mutate(("openai", "models", long_id), {"id": long_id}))
    with pytest.raises(model_catalog.CatalogError, match="id must be 1-256 characters"):
        model_catalog.refresh()

    many = {f"m{index}": {"id": f"m{index}"} for index in range(10_001)}
    catalog_http(mutate(("openai", "models"), many))
    with pytest.raises(model_catalog.CatalogError, match="exceeds 10000 offerings"):
        model_catalog.refresh()


@pytest.mark.parametrize("fault", ["replace", "fsync"])
def test_write_faults_keep_prior_bytes_and_remove_temporary_file(catalog_http, monkeypatch, fault):
    original = write_valid_cache(catalog_http)
    catalog_http(mutate(("openai", "models", "gpt-direct", "name"), "Renamed"))

    def broken(*args, **kwargs):
        raise OSError(f"{fault} failed")

    with monkeypatch.context() as patch:
        patch.setattr(model_catalog.os, fault, broken)
        with pytest.raises(model_catalog.CatalogError, match=f"cache write failed: {fault} failed"):
            model_catalog.refresh()

    assert cache_file().read_bytes() == original
    assert [path.name for path in cache_file().parent.iterdir() if path.name.startswith(".models-dev")] == []


def test_initial_fetch_that_cannot_be_saved_reports_write_failure(catalog_http, monkeypatch):
    catalog_http(FIXTURE)
    monkeypatch.setattr(model_catalog.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(model_catalog.CatalogError, match="cache write failed: disk full") as exc_info:
        model_catalog.load()

    assert "Retry with personal-agent --refresh-models" in str(exc_info.value)


def test_linked_cache_target_is_refused_and_left_untouched(catalog_http, tmp_path):
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("keep")
    cache_file().parent.mkdir(parents=True, exist_ok=True)
    cache_file().symlink_to(elsewhere)
    catalog_http(FIXTURE, FIXTURE)

    with pytest.raises(model_catalog.CatalogError, match="refusing to replace linked or nonregular cache"):
        model_catalog.refresh()
    with pytest.raises(model_catalog.CatalogError, match="cache write failed|refusing"):
        model_catalog.load()

    assert cache_file().is_symlink() and elsewhere.read_text() == "keep"


def test_lookup_is_exact_and_case_sensitive_with_reasons(catalog_http):
    catalog_http(FIXTURE)
    catalog = model_catalog.load()

    assert catalog.lookup("openrouter", "vendor/Case-Model").name == "Case Model"
    with pytest.raises(model_catalog.CatalogError, match="not in the Models.dev catalog for openrouter"):
        catalog.lookup("openrouter", "vendor/case-model")
    with pytest.raises(model_catalog.CatalogError, match="locally unsupported: incomplete metadata"):
        catalog.lookup("gemini", "gemini-no-limit")
    with pytest.raises(model_catalog.CatalogError, match="Unknown Provider 'google'"):
        catalog.lookup("google", "gemini-direct")


def test_search_is_literal_case_insensitive_on_id_or_name(catalog_http, capsys):
    catalog_http(FIXTURE)

    main(["--models", "openrouter", "--search", "CASE"])
    by_id = capsys.readouterr().out
    main(["--models", "anthropic", "--search", "native"])
    by_name = capsys.readouterr().out
    main(["--models", "openrouter", "--search", ".*"])
    literal = capsys.readouterr().out

    assert "vendor/Case-Model" in by_id
    assert "claude-native" in by_name and "claude-image-out" not in by_name
    assert "0 eligible model(s) matching '.*'" in literal


def test_rendering_is_sanitized_sorted_and_bounded(catalog_http, capsys):
    models = {f"model-{index:03d}": {"id": f"model-{index:03d}", "name": "Evil\x1b[2J\nName", "tool_call": True,
                                     "modalities": {"input": ["text"], "output": ["text"]},
                                     "limit": {"context": 1000, "output": 100}}
              for index in reversed(range(150))}
    catalog_http(mutate(("openai", "models"), models))

    main(["--models", "openai"])
    out = capsys.readouterr().out

    rows = [line for line in out.splitlines() if line.startswith("  model-")]
    assert len(rows) == 100 and rows[0].startswith("  model-000") and rows[-1].startswith("  model-099")
    assert "\x1b" not in out and "Evil\\x1b[2J\\nName" in out
    assert "Showing 100 of 150; narrow the list with --search <text>." in out
    assert len(out.encode()) <= 16 * 1024


def test_rendering_respects_byte_bound_before_row_bound(catalog_http, capsys):
    models = {f"m{index:02d}" + "x" * 200: {"id": f"m{index:02d}" + "x" * 200, "name": "y" * 250, "tool_call": True,
                                             "modalities": {"input": ["text"], "output": ["text"]},
                                             "limit": {"context": 1000, "output": 100}}
              for index in range(90)}
    catalog_http(mutate(("openai", "models"), models))

    main(["--models", "openai"])
    out = capsys.readouterr().out

    assert len(out.encode()) <= 16 * 1024
    assert "narrow the list with --search <text>." in out


def test_refresh_then_list_and_refresh_alone(catalog_http, capsys):
    requests = catalog_http(FIXTURE, FIXTURE)

    main(["--refresh-models"])
    refreshed = capsys.readouterr().out
    main(["--refresh-models", "--models", "openai"])
    combined = capsys.readouterr().out

    assert len(requests) == 2
    assert "eligible models: openrouter 1, openai 1, anthropic 1, gemini 1." in refreshed
    assert "Models.dev catalog refreshed" in combined and "gpt-direct" in combined


def test_combined_refresh_failure_is_nonzero_without_listing(catalog_http, capsys):
    original = write_valid_cache(catalog_http)
    catalog_http(URLError("offline"))

    with pytest.raises(SystemExit) as exc_info:
        main(["--refresh-models", "--models", "openai"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 1 and "refresh failed" in captured.err and captured.out == ""
    assert cache_file().read_bytes() == original


@pytest.mark.parametrize("argv, message", [
    (["--models", "google"], "Unknown Provider 'google'; choose one of: openrouter, openai, anthropic, gemini"),
    (["--search", "x"], "--search requires --models <provider>"),
    (["--resume", "last", "--models", "openai"], "--resume cannot be combined"),
])
def test_invalid_catalog_cli_usage_has_no_side_effects(catalog_http, capsys, argv, message):
    requests = catalog_http()

    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    assert exc_info.value.code != 0 and message in capsys.readouterr().err
    assert requests == [] and not (Path.home() / ".personal_agent").exists()
    assert call_log.active_session_id() is None


def test_catalog_commands_ignore_provider_settings(catalog_http, monkeypatch, capsys):
    monkeypatch.setenv("PA_PROVIDER", "nonsense")
    (Path.cwd() / ".env").write_text("OPENROUTER_API_KEY=should-not-load\n")
    catalog_http(FIXTURE)

    main(["--models", "openai"])

    assert "gpt-direct" in capsys.readouterr().out
    assert "OPENROUTER_API_KEY" not in os.environ
