import codecs
import re
import time
from dataclasses import dataclass
from email.message import Message
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from personal_agent.tools import workspace
from personal_agent.tools.builtins import ToolExecutionError
from personal_agent.tools.workspace import TRUNCATION_MARKER

TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
LONG_URL_CHARS = 150
USER_AGENT = "personal-agent-webfetch/1.0"
_READ_CHUNK_SIZE = 65536

_DROP_CONTENT_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "nav"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "ul", "ol", "table", "tr", "td", "th", "thead", "tbody", "tfoot",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "section", "article", "header",
        "footer", "aside", "main", "form", "fieldset", "figure", "figcaption", "dl", "dt", "dd",
        "address", "hr",
    }
)
_VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
_OPTIONAL_END_TAGS = frozenset(
    {
        "li", "p", "dt", "dd", "tr", "td", "th", "option", "optgroup",
        "rt", "rp", "thead", "tbody", "tfoot", "colgroup", "caption",
    }
)
_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_LIKE_MEDIA_TYPES = frozenset({"application/json", "application/xml", "application/javascript"})
_WHITESPACE_RUN = re.compile(r"[^\S\n]+")
_ALL_WHITESPACE = re.compile(r"\s+")


def _is_hidden_start_tag(attrs) -> bool:
    """R9: a start tag is hidden by a bare `hidden` attribute, an
    `aria-hidden` value that is `true` once trimmed and lowercased, or a
    `style` value that, with all whitespace removed and lowercased, contains
    `display:none` or `visibility:hidden`."""
    for name, value in attrs:
        if name == "hidden":
            return True
        if name == "aria-hidden" and value is not None and value.strip().lower() == "true":
            return True
        if name == "style" and value is not None:
            compact = _ALL_WHITESPACE.sub("", value).lower()
            if "display:none" in compact or "visibility:hidden" in compact:
                return True
    return False


@dataclass(frozen=True)
class PreparedFetch:
    """Everything webfetch's apply step needs, computed by prepare without
    touching the network: the Tool Confirmation label/preview (both the
    validated URL) and the URL itself."""

    display_path: str
    preview: str
    url: str


class _RedirectHandler(HTTPRedirectHandler):
    """Refuses a redirect to a non-http(s) target (R10): the stdlib's default
    opener also installs FTPHandler, which would otherwise silently follow a
    redirect Location pointing at ftp://."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urlsplit(newurl).scheme.lower()
        if scheme not in ("http", "https"):
            raise ToolExecutionError(f"redirected to unsupported URL scheme: {scheme or newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as exc:
        raise ToolExecutionError(f"malformed URL: {exc}") from exc
    if parsed.scheme.lower() not in ("http", "https"):
        raise ToolExecutionError(f"unsupported URL scheme: {parsed.scheme or url}")
    if not parsed.hostname:
        raise ToolExecutionError("URL has no host")


def prepare_fetch(arguments: dict) -> PreparedFetch:
    """`webfetch`'s prepare step (two-phase Tool Confirmation, R8-R9): scheme
    and host validated here, before Tool Confirmation, and nothing is
    fetched."""
    url = arguments["url"]
    _validate_url(url)
    preview = url
    if len(url) > LONG_URL_CHARS:
        preview += f"\nWarning: long URL ({len(url)} chars). Check it does not carry workspace content."
    return PreparedFetch(display_path=url, preview=preview, url=url)


def _read_capped(response, limit: int, deadline: float) -> bytes:
    """Read `response` to EOF, never buffering beyond `limit + 1` bytes: as
    soon as that many bytes are seen, reading stops and the caller raises.
    `deadline` (a `time.monotonic()` value) enforces the total read time.
    Uses `read1` rather than `read` so each call returns after at most one
    underlying socket read instead of blocking until the requested size is
    filled: `read(n)` on a server that trickles data one byte at a time
    would keep resetting the per-op socket timeout and never let the
    deadline check between reads run."""
    buf = bytearray()
    while len(buf) <= limit:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"request timed out after {TIMEOUT_SECONDS} seconds")
        chunk = response.read1(min(_READ_CHUNK_SIZE, limit + 1 - len(buf)))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _parse_content_type(header: str | None) -> tuple[str | None, str | None]:
    if not header or not header.strip():
        return None, None
    media_type = header.split(";", 1)[0].strip().lower()
    if not media_type:
        return None, None
    message = Message()
    message["content-type"] = header
    return media_type, message.get_content_charset()


def _content_allowed(media_type: str) -> bool:
    if media_type in _HTML_MEDIA_TYPES or media_type in _TEXT_LIKE_MEDIA_TYPES:
        return True
    if media_type.startswith("text/"):
        return True
    return media_type.startswith("application/") and (media_type.endswith("+json") or media_type.endswith("+xml"))


def _decode_body(data: bytes, charset: str | None) -> str:
    if charset:
        try:
            return data.decode(charset, errors="replace")
        except (LookupError, ValueError):
            pass
    return data.decode("utf-8", errors="replace")


class _HTMLTextExtractor(HTMLParser):
    """Converts HTML to plain text (R11): drops the content of
    `_DROP_CONTENT_TAGS` and of any hidden element (R9) together with
    everything nested inside it, breaks a line at every block-level element
    and `<br>`, and relies on `convert_charrefs` (default True) to decode
    character references. One stack of open elements covers the whole
    document: an end tag closes every element opened after its last
    matching open element (an end tag with no open match is ignored, and
    `</html>`/`</body>` never close anything, as in a browser), and a start
    tag of an optional-end-tag element first closes an open element of the
    same name on top of the stack. A dropped element drops text until the
    stack shrinks back below it. Void elements and self-closing tags are
    never pushed, so a hidden one drops nothing beyond itself."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._open: list[str] = []
        self._drop_depth: int | None = None

    def _dropping(self) -> bool:
        return self._drop_depth is not None

    def _close_to(self, depth: int) -> None:
        del self._open[depth:]
        if self._drop_depth is not None and depth <= self._drop_depth:
            self._drop_depth = None

    def handle_starttag(self, tag, attrs):
        if tag in _OPTIONAL_END_TAGS and self._open and self._open[-1] == tag:
            self._close_to(len(self._open) - 1)
        if tag in _VOID_ELEMENTS:
            self.handle_startendtag(tag, attrs)
            return
        if not self._dropping() and (tag in _DROP_CONTENT_TAGS or _is_hidden_start_tag(attrs)):
            self._drop_depth = len(self._open)
        self._open.append(tag)
        if not self._dropping() and tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if self._dropping() or _is_hidden_start_tag(attrs):
            return
        if tag == "br" or tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        dropping = self._dropping()
        if tag in self._open and tag not in ("html", "body"):
            self._close_to(len(self._open) - 1 - self._open[::-1].index(tag))
        if tag in _BLOCK_TAGS and (not dropping or not self._dropping()):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._dropping():
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _collapse_whitespace(text: str) -> str:
    text = _WHITESPACE_RUN.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        blank = line == ""
        if blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = blank
    return "\n".join(collapsed).strip("\n")


def _render_content(media_type: str, text: str) -> str:
    if media_type not in _HTML_MEDIA_TYPES:
        return text
    parser = _HTMLTextExtractor()
    parser.feed(text)
    parser.close()
    return _collapse_whitespace(parser.text())


def _truncate(content: str, cap: int) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= cap:
        return content, False
    marker = TRUNCATION_MARKER.encode()
    keep_len = max(cap - len(marker), 0)
    kept = codecs.getincrementaldecoder("utf-8")().decode(encoded[:keep_len], False)
    return kept + TRUNCATION_MARKER, True


def apply_fetch(prepared: PreparedFetch) -> dict:
    """`webfetch`'s apply step: one GET with redirects followed, classifying
    and converting the response (R10-R12). Every request-construction and
    transport failure is converted to a `ToolExecutionError` (catch-all: the
    stdlib raises more than `URLError`/`OSError` for a malformed request,
    e.g. `http.client.InvalidURL` or a `UnicodeEncodeError` from a
    non-ASCII path)."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    request = Request(prepared.url, headers={"User-Agent": USER_AGENT})
    opener = build_opener(_RedirectHandler)
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
    except HTTPError as exc:
        raise ToolExecutionError(f"HTTP {exc.code} {exc.reason}") from exc
    except ToolExecutionError:
        raise
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ToolExecutionError(f"request timed out after {TIMEOUT_SECONDS} seconds") from exc
        raise ToolExecutionError(f"request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ToolExecutionError(f"request timed out after {TIMEOUT_SECONDS} seconds") from exc
    except Exception as exc:
        raise ToolExecutionError(f"request failed: {exc}") from exc

    try:
        with response:
            final_url = response.geturl()
            status = response.status
            content_type_header = response.headers.get("Content-Type")
            data = _read_capped(response, MAX_DOWNLOAD_BYTES, deadline)
    except TimeoutError as exc:
        raise ToolExecutionError(f"request timed out after {TIMEOUT_SECONDS} seconds") from exc
    except Exception as exc:
        raise ToolExecutionError(f"request failed: {exc}") from exc

    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ToolExecutionError(f"response exceeds the {MAX_DOWNLOAD_BYTES}-byte download limit")

    media_type, charset = _parse_content_type(content_type_header)
    if media_type is None or not _content_allowed(media_type):
        raise ToolExecutionError(f"unsupported content type: {media_type or content_type_header or 'unknown'}")

    text = _decode_body(data, charset)
    content = _render_content(media_type, text)
    cap = workspace.configured_workspace().max_read_bytes
    capped_content, truncated = _truncate(content, cap)
    return {
        "url": final_url,
        "status": status,
        "content_type": media_type,
        "content": capped_content,
        "truncated": truncated,
    }
