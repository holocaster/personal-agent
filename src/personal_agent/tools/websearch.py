import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from personal_agent.tools import workspace
from personal_agent.tools.builtins import ToolExecutionError

ENDPOINT = "https://api.tavily.com/search"
TIMEOUT_SECONDS = 30
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PreparedSearch:
    display_path: str
    preview: str
    query: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolExecutionError("Tavily redirect refused")


def prepare_search(arguments: dict) -> PreparedSearch:
    query = arguments["query"]
    if not query.strip():
        raise ToolExecutionError("query must not be blank")
    return PreparedSearch(query, query, query)


def _usable_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme.lower() in ("http", "https") and bool(parsed.hostname)
                and parsed.port != 0 and " " not in url and not parsed.username and not parsed.password
                and not any(ord(char) < 32 or ord(char) == 127 for char in url))
    except ValueError:
        return False


def _http_error(code: int) -> str:
    reason = {401: "invalid API key", 429: "rate limit", 432: "key or plan limit exhausted",
              433: "pay-as-you-go limit exhausted"}.get(code, "request failed")
    return f"Tavily HTTP {code}: {reason}"


def _bound_results(results: list[dict]) -> dict:
    cap = workspace.configured_workspace().max_read_bytes
    while len(json.dumps({"results": results}).encode("utf-8")) > cap:
        if not results:
            raise ToolExecutionError("Tool Output Cap too small for search results")
        results.pop()
    return {"results": results}


def redact_search_results(content: dict, secrets: tuple[str, ...]) -> dict:
    keys = sorted({key for key in secrets if key}, key=len, reverse=True)
    results = []
    for item in content["results"]:
        if any(key in item["url"] for key in keys):
            continue
        title, snippet = item["title"], item["snippet"]
        for key in keys:
            title = title.replace(key, "[redacted]")
            snippet = snippet.replace(key, "[redacted]")
        results.append({"title": title[:200], "url": item["url"], "snippet": snippet[:300]})
    return _bound_results(results)


def apply_search(prepared: PreparedSearch, api_key: str) -> dict:
    payload = {
        "query": prepared.query, "search_depth": "basic", "max_results": 5, "chunks_per_source": 1,
        "include_answer": False, "include_raw_content": False, "include_images": False,
        "auto_parameters": False,
    }
    try:
        request = Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        })
        deadline = time.monotonic() + TIMEOUT_SECONDS
        with build_opener(_NoRedirect).open(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            if not 200 <= status < 300:
                raise ToolExecutionError(_http_error(status))
            body = bytearray()
            while len(body) <= MAX_BODY_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError
                reader = getattr(response, "read1", response.read)
                chunk = reader(min(65536, MAX_BODY_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
    except HTTPError as exc:
        raise ToolExecutionError(_http_error(exc.code)) from None
    except ToolExecutionError:
        raise
    except TimeoutError:
        raise ToolExecutionError("Tavily request timed out") from None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ToolExecutionError("Tavily request timed out") from None
        raise ToolExecutionError("Tavily request failed") from None
    except Exception:
        raise ToolExecutionError("Tavily request failed") from None

    if len(body) > MAX_BODY_BYTES:
        raise ToolExecutionError("Tavily response exceeds download limit")
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError
        entries = data["results"]
        results = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError
            title, url, snippet = entry["title"], entry["url"], entry["content"]
            if not all(isinstance(value, str) for value in (title, url, snippet)):
                raise ValueError
            if _usable_url(url) and api_key not in url:
                results.append({"title": title.replace(api_key, "[redacted]")[:200],
                                "url": url,
                                "snippet": snippet.replace(api_key, "[redacted]")[:300]})
            if len(results) == 5:
                break
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        raise ToolExecutionError("malformed Tavily response") from None

    return _bound_results(results)
