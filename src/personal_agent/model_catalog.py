import http.client
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from personal_agent.terminal.tty import sanitize_control_chars

URL = "https://models.dev/api.json?type=all"
UPSTREAM_IDS = {"openrouter": "openrouter", "openai": "openai", "anthropic": "anthropic", "gemini": "google"}
PROVIDERS = tuple(UPSTREAM_IDS)
CACHE_VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
NETWORK_SECONDS = 10
TOTAL_SECONDS = 30
MAX_OFFERINGS = 10_000
MAX_ID_CHARS = 256
MAX_NAME_CHARS = 256
MAX_MODALITIES = 16
MAX_ROWS = 100
MAX_OUTPUT_BYTES = 16 * 1024
REFRESH_COMMAND = "personal-agent --refresh-models"
ACCESS_CAVEAT = ("Catalog metadata does not prove account access, System or Streaming support; "
                 "remote errors remain possible.")
_REPLAY_LIMITED = {"openai", "openrouter"}
_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"


class CatalogError(Exception):
    pass


@dataclass(frozen=True)
class Offering:
    provider: str
    id: str
    name: str
    status: str | None
    context: int | None
    input: int | None
    output: int | None
    reason: str | None
    reasoning_levels: tuple[str, ...] = ()
    default_reasoning: str | None = None

    @property
    def eligible(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class Catalog:
    fetched_at: str
    offerings: dict[str, dict[str, Offering]]

    def search(self, provider: str, query: str = "") -> list[Offering]:
        needle = query.casefold()
        return [offering for offering in self.offerings[normalize_provider(provider)].values()
                if offering.eligible and (needle in offering.id.casefold() or needle in offering.name.casefold())]

    def lookup(self, provider: str, model_id: str) -> Offering:
        provider = normalize_provider(provider)
        offering = self.offerings[provider].get(model_id)
        if offering is None:
            raise CatalogError(f"Model {model_id!r} is not in the Models.dev catalog for {provider} "
                               f"(fetched {self.fetched_at}); catalog omission does not prove account access. "
                               f"Refresh with {REFRESH_COMMAND} or choose a listed model.")
        if offering.reason is not None:
            raise CatalogError(f"Model {model_id!r} for {provider} is locally unsupported: {offering.reason}.")
        return offering


class _RedirectGuard(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise CatalogError(f"refused catalog redirect to {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_open = build_opener(_RedirectGuard).open


def cache_path() -> Path:
    return Path.home() / ".personal_agent" / "models-dev.json"


def normalize_provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in UPSTREAM_IDS:
        raise CatalogError(f"Unknown Provider {value!r}; choose one of: {', '.join(PROVIDERS)}")
    return provider


def cached() -> Catalog:
    return _from_cache(_read_cache())


def load() -> Catalog:
    try:
        return _from_cache(_read_cache())
    except CatalogError as cache_problem:
        try:
            return refresh()
        except CatalogError as exc:
            raise CatalogError(f"Models.dev catalog unavailable (cache: {cache_problem}; fetch: {exc}). "
                               f"Retry with {REFRESH_COMMAND}.") from exc


def refresh() -> Catalog:
    document = _parse(_fetch())
    if not isinstance(document, dict):
        raise CatalogError("invalid catalog schema: top level is not an object")
    fetched_at = datetime.now(timezone.utc).strftime(_TIMESTAMP)
    sections = {provider: _section(provider, document.get(upstream)) for provider, upstream in UPSTREAM_IDS.items()}
    _write_cache({"version": CACHE_VERSION, "source": URL, "fetched_at": fetched_at, "providers": sections})
    return _catalog(fetched_at, sections)


def render(catalog: Catalog, provider: str, query: str = "", narrow: str = "--search <text>") -> str:
    provider = normalize_provider(provider)
    matches = catalog.search(provider, query)
    clean = lambda text: sanitize_control_chars(text, multiline=False)
    header = [f"Models.dev {provider} catalog fetched {catalog.fetched_at} from {URL}; refresh with {REFRESH_COMMAND}.",
              ACCESS_CAVEAT,
              f"{len(matches)} eligible model(s)" + (f" matching {clean(query[:MAX_NAME_CHARS])!r}" if query else "") + ":"]
    lines = list(header)
    size = sum(len(line.encode()) + 1 for line in lines)
    shown = 0
    for offering in matches:
        status = f" [{clean(offering.status)}]" if offering.status else ""
        limits = f"context {offering.context}" + (f", input {offering.input}" if offering.input else "") + f", output {offering.output}"
        row = f"  {clean(offering.id)}  {clean(offering.name)}{status}  ({limits})"
        if shown == MAX_ROWS or size + len(row.encode()) + 1 > MAX_OUTPUT_BYTES - 200:
            break
        lines.append(row)
        size += len(row.encode()) + 1
        shown += 1
    if shown < len(matches):
        lines.append(f"Showing {shown} of {len(matches)}; narrow the list with {narrow}.")
    return "\n".join(lines)


def _allowed_url(url: str) -> bool:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == "models.dev" and port in (None, 443)


def _fetch() -> bytes:
    deadline = monotonic() + TOTAL_SECONDS
    request = Request(URL, headers={"Accept": "application/json", "Accept-Encoding": "identity",
                                    "User-Agent": "personal-agent"})
    try:
        with _open(request, timeout=NETWORK_SECONDS) as response:
            if not _allowed_url(response.geturl()):
                raise CatalogError(f"refused catalog response from {response.geturl()!r}")
            if response.status != 200:
                raise CatalogError(f"unexpected HTTP status {response.status}")
            if response.headers.get_content_type() != "application/json":
                raise CatalogError(f"unexpected media type {response.headers.get_content_type()!r}")
            if response.headers.get("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
                raise CatalogError("unexpected compressed response")
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.strip().isdigit() or int(declared) > MAX_BYTES):
                raise CatalogError("response exceeds 16 MiB or has an invalid length")
            chunks, total = [], 0
            while True:
                if monotonic() > deadline:
                    raise CatalogError(f"fetch exceeded {TOTAL_SECONDS} seconds")
                chunk = response.read(min(64 * 1024, MAX_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    raise CatalogError("response exceeds 16 MiB")
            if declared is not None and total != int(declared):
                raise CatalogError("truncated response")
            return b"".join(chunks)
    except CatalogError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise CatalogError(f"fetch failed: {exc}") from exc


def _parse(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    def constant(name):
        raise ValueError(f"invalid constant {name}")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise CatalogError(f"malformed JSON: {exc}") from exc


def _section(provider: str, section) -> dict:
    upstream = UPSTREAM_IDS[provider]
    if not isinstance(section, dict) or section.get("id") != upstream:
        raise CatalogError(f"invalid catalog schema: missing or mismatched {upstream!r} section")
    models = section.get("models")
    if not isinstance(models, dict) or not models:
        raise CatalogError(f"invalid catalog schema: {upstream!r} has no models")
    if len(models) > MAX_OFFERINGS:
        raise CatalogError(f"invalid catalog schema: {upstream!r} exceeds {MAX_OFFERINGS} offerings")
    return {"id": upstream, "models": {key: _consumed(upstream, key, model) for key, model in models.items()}}


def _consumed(upstream: str, key: str, model) -> dict:
    def bad(detail: str) -> CatalogError:
        return CatalogError(f"invalid catalog schema: {upstream}/{key[:MAX_ID_CHARS]!r} {detail}")

    if not isinstance(model, dict):
        raise bad("is not an object")
    if model.get("id") != key:
        raise bad("has a mismatched id")
    if not 1 <= len(key) <= MAX_ID_CHARS:
        raise bad(f"id must be 1-{MAX_ID_CHARS} characters")
    out = {"id": key}
    present = {field: value for field, value in model.items() if value is not None}
    for field, kind, limit in (("name", str, MAX_NAME_CHARS), ("status", str, MAX_NAME_CHARS),
                               ("type", str, MAX_NAME_CHARS), ("tool_call", bool, None)):
        if field in present:
            if not isinstance(present[field], kind) or (limit and len(present[field]) > limit):
                raise bad(f"has invalid {field}")
            out[field] = present[field]
    if "interleaved" in present:
        if not isinstance(present["interleaved"], (bool, dict)):
            raise bad("has invalid interleaved")
        out["interleaved"] = present["interleaved"] is not False
    if "provider" in present:
        if not isinstance(present["provider"], dict):
            raise bad("has invalid provider")
        out["provider"] = {name: True for name in present["provider"]}
    if "modalities" in present:
        modalities = present["modalities"]
        if not isinstance(modalities, dict):
            raise bad("has invalid modalities")
        out["modalities"] = {}
        for side in ("input", "output"):
            values = modalities.get(side)
            if values is None:
                continue
            if (not isinstance(values, list) or len(values) > MAX_MODALITIES
                    or not all(isinstance(value, str) and len(value) <= MAX_NAME_CHARS for value in values)):
                raise bad(f"has invalid {side} modalities")
            out["modalities"][side] = values
    if "limit" in present:
        limit = present["limit"]
        if not isinstance(limit, dict):
            raise bad("has invalid limit")
        out["limit"] = {}
        for field in ("context", "input", "output"):
            value = limit.get(field)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise bad(f"has invalid {field} limit")
            out["limit"][field] = value
    return out


def _reason(provider: str, model: dict) -> str | None:
    positive = lambda value: type(value) is int and value > 0
    modalities = model.get("modalities", {})
    limit = model.get("limit", {})
    if model.get("type", "chat") != "chat":
        return f"specialized {model['type']!r} model"
    if model.get("status") == "deprecated":
        return "deprecated"
    if model.get("status") not in (None, "alpha", "beta"):
        return f"unrecognized status {model['status']!r}"
    if model.get("provider"):
        return "requires model-level Provider overrides"
    if model.get("interleaved") and provider in _REPLAY_LIMITED:
        return f"requires interleaved reasoning replay the {provider} adapter cannot retain"
    if "tool_call" not in model:
        return "incomplete metadata: no Tool-calling evidence"
    if not model["tool_call"]:
        return "does not support Tool calling"
    if "input" not in modalities or "output" not in modalities:
        return "incomplete metadata: no input/output modality evidence"
    if "text" not in modalities["input"] or "text" not in modalities["output"]:
        return "requires text input and output"
    if "context" not in limit or "output" not in limit:
        return "incomplete metadata: no context/output limit"
    if not positive(limit["context"]) or not positive(limit["output"]) or limit["output"] > limit["context"]:
        return "invalid context/output limits"
    if "input" in limit and (not positive(limit["input"]) or limit["input"] > limit["context"]):
        return "invalid input limit"
    return None


def _catalog(fetched_at: str, sections: dict) -> Catalog:
    offerings = {}
    for provider, section in sections.items():
        offerings[provider] = {
            key: Offering(provider=provider, id=key, name=model.get("name", ""), status=model.get("status"),
                          context=model.get("limit", {}).get("context"), input=model.get("limit", {}).get("input"),
                          output=model.get("limit", {}).get("output"), reason=_reason(provider, model))
            for key, model in sorted(section["models"].items())
        }
    return Catalog(fetched_at=fetched_at, offerings=offerings)


def _from_cache(raw: bytes) -> Catalog:
    data = _parse(raw)
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != CACHE_VERSION
            or data.get("source") != URL):
        raise CatalogError("unsupported cache version or source")
    fetched_at = data.get("fetched_at")
    try:
        datetime.strptime(fetched_at, _TIMESTAMP)
    except (TypeError, ValueError):
        raise CatalogError("invalid cache fetched_at") from None
    providers = data.get("providers")
    if not isinstance(providers, dict) or set(providers) != set(PROVIDERS):
        raise CatalogError("invalid cache Provider map")
    return _catalog(fetched_at, {provider: _section(provider, providers[provider]) for provider in PROVIDERS})


def _read_cache() -> bytes:
    try:
        fd = os.open(cache_path(), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise CatalogError("no cached catalog") from None
    except OSError as exc:
        raise CatalogError(f"cannot read cache: {exc}") from exc
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CatalogError("cache is not a regular file")
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CatalogError("cache exceeds 16 MiB")
    return raw


def _write_cache(document: dict) -> None:
    target = cache_path()
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise CatalogError("cache would exceed 16 MiB")
    temporary = None
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            mode = os.lstat(target).st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None and not stat.S_ISREG(mode):
            raise CatalogError(f"refusing to replace linked or nonregular cache {target}")
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        temporary = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise CatalogError(f"cache write failed: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
