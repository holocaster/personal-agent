import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from personal_agent.providers.contract import ToolCall
from personal_agent.tools import registry as tools, webfetch, workspace


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.server.requests.append(self.path)
        route = self.server.routes.get(self.path)
        if route is None:
            self._respond(404, {"Content-Type": "text/plain"}, b"not found")
            return
        delay = route.get("delay")
        if delay:
            time.sleep(delay)
        trickle = route.get("trickle")
        if trickle is not None:
            self._respond_trickle(route["status"], route.get("headers", {}), trickle)
            return
        self._respond(route["status"], route.get("headers", {}), route.get("body", b""))

    def _respond(self, status, headers, body):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _respond_trickle(self, status, headers, trickle):
        chunk, count, delay = trickle["chunk"], trickle["count"], trickle["delay"]
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(chunk) * count))
        self.end_headers()
        for _ in range(count):
            self.wfile.write(chunk)
            self.wfile.flush()
            time.sleep(delay)


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.routes = {}
    httpd.requests = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join()


def _url(server, path):
    return f"http://127.0.0.1:{server.server_port}{path}"


def _execute(url, confirm=True):
    seen = []

    def _confirm(*args):
        seen.append(args)
        return confirm

    call = ToolCall(id="1", name="webfetch", arguments={"url": url})
    result = tools.execute_batch([call], confirm=_confirm)[0]
    return result, seen


# --- Registration and schema (R7) -------------------------------------------


def test_webfetch_is_registered_by_default(tmp_path):
    workspace.configure_workspace(tmp_path)
    definitions = {definition.name: definition.parameters for definition in tools.TOOL_DEFS}

    assert definitions["webfetch"] == {
        "type": "object",
        "properties": {"url": {"type": "string", "minLength": 1}},
        "required": ["url"],
        "additionalProperties": False,
    }


# --- URL validation (R8) -----------------------------------------------------


def test_webfetch_rejects_a_non_http_scheme_without_calling_confirm(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, seen = _execute("ftp://example.com/file")

    assert result.is_error is True
    assert "scheme" in result.content["error"]
    assert seen == []


def test_webfetch_rejects_a_url_with_no_host_without_calling_confirm(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, seen = _execute("http:///no-host")

    assert result.is_error is True
    assert seen == []


def test_webfetch_rejects_a_malformed_host_without_calling_confirm(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, seen = _execute("http://127.0.0.1:abc/")

    assert result.is_error is True
    assert seen == []


# --- Tool Confirmation (R9) --------------------------------------------------


def test_webfetch_rejected_by_confirm_makes_no_request(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/page"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": b"hi"}

    result, seen = _execute(_url(server, "/page"), confirm=False)

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert len(seen) == 1
    assert server.requests == []


def test_webfetch_confirmation_warns_about_a_long_url(tmp_path):
    workspace.configure_workspace(tmp_path)
    long_url = "http://127.0.0.1:1/x?q=" + "a" * webfetch.LONG_URL_CHARS

    _, seen = _execute(long_url, confirm=False)

    preview = seen[0][2]
    assert preview.startswith(long_url)
    assert f"Warning: long URL ({len(long_url)} chars)" in preview


def test_webfetch_confirmation_has_no_warning_for_a_short_url(tmp_path):
    workspace.configure_workspace(tmp_path)

    _, seen = _execute("http://127.0.0.1:1/page", confirm=False)

    assert seen[0][2] == "http://127.0.0.1:1/page"


# --- Fetch and errors (R10) ---------------------------------------------------


def test_webfetch_follows_a_redirect_and_reports_the_final_url(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/redirect"] = {"status": 302, "headers": {"Location": _url(server, "/final")}}
    server.routes["/final"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": b"final content"}

    result, _ = _execute(_url(server, "/redirect"))

    assert result.is_error is False
    assert result.content["url"] == _url(server, "/final")
    assert result.content["status"] == 200
    assert result.content["content"] == "final content"


def test_webfetch_http_error_status_is_a_tool_error_naming_the_status(server, tmp_path):
    workspace.configure_workspace(tmp_path)

    result, _ = _execute(_url(server, "/missing"))

    assert result.is_error is True
    assert result.content["error"].startswith("HTTP 404")


def test_webfetch_timeout_is_a_tool_error(server, tmp_path, monkeypatch):
    workspace.configure_workspace(tmp_path)
    monkeypatch.setattr(webfetch, "TIMEOUT_SECONDS", 0.2)
    server.routes["/slow"] = {
        "status": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": b"too late",
        "delay": 1.0,
    }

    result, _ = _execute(_url(server, "/slow"))

    assert result.is_error is True
    assert "timed out" in result.content["error"]


def test_webfetch_oversized_body_is_a_tool_error(server, tmp_path, monkeypatch):
    workspace.configure_workspace(tmp_path)
    monkeypatch.setattr(webfetch, "MAX_DOWNLOAD_BYTES", 10)
    server.routes["/big"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": b"x" * 1000}

    result, _ = _execute(_url(server, "/big"))

    assert result.is_error is True
    assert "download limit" in result.content["error"]


def test_webfetch_url_with_a_space_is_a_tool_error_not_a_crash(server, tmp_path):
    workspace.configure_workspace(tmp_path)

    result, _ = _execute(_url(server, "/a b"))

    assert result.is_error is True
    assert "request failed" in result.content["error"]


def test_webfetch_url_with_a_non_ascii_path_is_a_tool_error_not_a_crash(server, tmp_path):
    workspace.configure_workspace(tmp_path)

    result, _ = _execute(_url(server, "/café"))

    assert result.is_error is True
    assert "request failed" in result.content["error"]


def test_webfetch_enforces_a_total_deadline_while_reading(server, tmp_path, monkeypatch):
    workspace.configure_workspace(tmp_path)
    monkeypatch.setattr(webfetch, "TIMEOUT_SECONDS", 0.2)
    server.routes["/trickle"] = {
        "status": 200,
        "headers": {"Content-Type": "text/plain"},
        "trickle": {"chunk": b"x", "count": 200, "delay": 0.05},
    }

    start = time.monotonic()
    result, _ = _execute(_url(server, "/trickle"))
    elapsed = time.monotonic() - start

    assert result.is_error is True
    assert "timed out" in result.content["error"]
    assert elapsed < webfetch.TIMEOUT_SECONDS * 10


# --- Content handling (R11) ---------------------------------------------------


def test_webfetch_converts_html_dropping_elements_breaking_lines_and_decoding_entities(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    body = (
        b"<html><head><style>.x{color:red}</style></head><body>"
        b"<nav>Site Nav</nav>"
        b"<h1>Hello&nbsp;World</h1>"
        b"<p>Some<script>evil()</script> text</p>"
        b"Line one<br>Line two"
        b"</body></html>"
    )
    server.routes["/html"] = {"status": 200, "headers": {"Content-Type": "text/html; charset=utf-8"}, "body": body}

    result, _ = _execute(_url(server, "/html"))

    assert result.is_error is False
    assert result.content["content_type"] == "text/html"
    content = result.content["content"]
    lines = [line for line in content.split("\n") if line]
    assert "Hello World" in lines
    assert "Some text" in lines
    assert "Line one" in lines
    assert "Line two" in lines
    assert "Site Nav" not in content
    assert "evil()" not in content
    assert "color:red" not in content


def test_webfetch_self_closing_drop_tag_does_not_swallow_later_text(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    body = b"<html><body><p>before</p><svg/><p>after</p></body></html>"
    server.routes["/svg"] = {"status": 200, "headers": {"Content-Type": "text/html; charset=utf-8"}, "body": body}

    result, _ = _execute(_url(server, "/svg"))

    assert result.is_error is False
    assert "before" in result.content["content"]
    assert "after" in result.content["content"]


def test_webfetch_falls_back_to_utf8_when_the_charset_codec_rejects_replace(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/idna"] = {
        "status": 200,
        "headers": {"Content-Type": "text/plain; charset=idna"},
        "body": "hello".encode("utf-8"),
    }

    result, _ = _execute(_url(server, "/idna"))

    assert result.is_error is False
    assert result.content["content"] == "hello"


def test_webfetch_json_and_markdown_pass_through_unchanged(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/json"] = {"status": 200, "headers": {"Content-Type": "application/json"}, "body": b'{"a":1}'}
    server.routes["/md"] = {
        "status": 200,
        "headers": {"Content-Type": "text/markdown"},
        "body": b"# Title\n\nbody\n",
    }

    json_result, _ = _execute(_url(server, "/json"))
    md_result, _ = _execute(_url(server, "/md"))

    assert json_result.content == {
        "url": _url(server, "/json"),
        "status": 200,
        "content_type": "application/json",
        "content": '{"a":1}',
        "truncated": False,
    }
    assert md_result.content["content"] == "# Title\n\nbody\n"
    assert md_result.content["content_type"] == "text/markdown"


def test_webfetch_binary_content_type_is_a_tool_error_naming_the_type(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/binary"] = {"status": 200, "headers": {"Content-Type": "image/png"}, "body": b"\x89PNG\r\n"}

    result, _ = _execute(_url(server, "/binary"))

    assert result.is_error is True
    assert result.content["error"] == "unsupported content type: image/png"


def test_webfetch_malformed_content_type_without_a_slash_is_a_tool_error(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/malformed"] = {"status": 200, "headers": {"Content-Type": "image"}, "body": b"x"}

    result, _ = _execute(_url(server, "/malformed"))

    assert result.is_error is True
    assert result.content["error"] == "unsupported content type: image"


# --- Result and truncation (R12) ---------------------------------------------


def test_webfetch_truncates_content_over_the_tool_output_cap(server, tmp_path):
    workspace.configure_workspace(tmp_path, "50")
    server.routes["/long"] = {
        "status": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": b"x" * 500,
    }

    result, _ = _execute(_url(server, "/long"))

    assert result.is_error is False
    assert result.content["truncated"] is True
    assert result.content["content"].endswith("[...truncated]")
    assert len(result.content["content"].encode("utf-8")) <= 50


# --- Fetched-Content Warning turn tracking (R3, R7, ticket 0023-02) --------


def test_webfetch_then_write_in_one_batch_write_confirm_receives_the_final_url(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/redirect"] = {"status": 302, "headers": {"Location": _url(server, "/final")}}
    server.routes["/final"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": b"hi"}
    seen = []

    def _confirm(tool_name, path, preview, dangerous_rules, fetched_urls):
        seen.append((tool_name, fetched_urls))
        return True

    calls = [
        ToolCall(id="1", name="webfetch", arguments={"url": _url(server, "/redirect")}),
        ToolCall(id="2", name="write", arguments={"path": "note.txt", "content": "hi"}),
    ]
    tools.execute_batch(calls, confirm=_confirm)

    assert seen[0] == ("webfetch", ())
    assert seen[1] == ("write", (_url(server, "/final"),))


def test_rejected_webfetch_adds_no_url_to_the_turn(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/page"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": b"hi"}
    seen = []

    def _confirm(tool_name, path, preview, dangerous_rules, fetched_urls):
        seen.append((tool_name, fetched_urls))
        return tool_name != "webfetch"

    calls = [
        ToolCall(id="1", name="webfetch", arguments={"url": _url(server, "/page")}),
        ToolCall(id="2", name="write", arguments={"path": "note.txt", "content": "hi"}),
    ]
    tools.execute_batch(calls, confirm=_confirm)

    assert seen[1] == ("write", ())


def test_failed_webfetch_adds_no_url_to_the_turn(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    seen = []

    def _confirm(tool_name, path, preview, dangerous_rules, fetched_urls):
        seen.append((tool_name, fetched_urls))
        return True

    calls = [
        ToolCall(id="1", name="webfetch", arguments={"url": _url(server, "/missing")}),
        ToolCall(id="2", name="write", arguments={"path": "note.txt", "content": "hi"}),
    ]
    tools.execute_batch(calls, confirm=_confirm)

    assert seen[1] == ("write", ())


def test_the_same_url_fetched_twice_is_listed_once(server, tmp_path):
    workspace.configure_workspace(tmp_path)
    server.routes["/page"] = {"status": 200, "headers": {"Content-Type": "text/plain"}, "body": b"hi"}
    seen = []

    def _confirm(tool_name, path, preview, dangerous_rules, fetched_urls):
        seen.append((tool_name, fetched_urls))
        return True

    calls = [
        ToolCall(id="1", name="webfetch", arguments={"url": _url(server, "/page")}),
        ToolCall(id="2", name="webfetch", arguments={"url": _url(server, "/page")}),
        ToolCall(id="3", name="write", arguments={"path": "note.txt", "content": "hi"}),
    ]
    tools.execute_batch(calls, confirm=_confirm)

    assert seen[2] == ("write", (_url(server, "/page"),))


# --- Hidden HTML elements (R9, ticket 0023-03) ------------------------------


def _fetch_html(server, tmp_path, body):
    workspace.configure_workspace(tmp_path)
    server.routes["/hidden"] = {
        "status": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": body,
    }
    result, _ = _execute(_url(server, "/hidden"))
    assert result.is_error is False
    return result.content["content"]


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body><div hidden>secret</div>visible</body></html>",
        b'<html><body><div aria-hidden="true">secret</div>visible</body></html>',
        b'<html><body><div style="display:none">secret</div>visible</body></html>',
        b'<html><body><div style="DISPLAY : None">secret</div>visible</body></html>',
        b'<html><body><div style="display:none !important">secret</div>visible</body></html>',
        b'<html><body><div style="visibility:hidden">secret</div>visible</body></html>',
        b'<html><body><div style="VISIBILITY:Hidden">secret</div>visible</body></html>',
    ],
)
def test_webfetch_drops_each_hidden_form(server, tmp_path, body):
    content = _fetch_html(server, tmp_path, body)

    assert "secret" not in content
    assert "visible" in content


def test_webfetch_drops_a_hidden_elements_nested_children_including_same_name_nesting(server, tmp_path):
    body = b"<html><body><div hidden><div>a</div>b</div>c</body></html>"

    content = _fetch_html(server, tmp_path, body)

    assert "a" not in content
    assert "b" not in content
    assert content.strip() == "c"


def test_webfetch_hidden_void_element_drops_nothing_beyond_itself(server, tmp_path):
    body = b"<html><body><input hidden>visible</body></html>"

    content = _fetch_html(server, tmp_path, body)

    assert "visible" in content


def test_webfetch_keeps_aria_hidden_false_and_display_block(server, tmp_path):
    body = b'<html><body><div aria-hidden="false">a</div><div style="display:block">b</div></body></html>'

    content = _fetch_html(server, tmp_path, body)

    assert "a" in content
    assert "b" in content


def test_webfetch_optional_end_tag_sibling_implicitly_closes_the_hidden_one(server, tmp_path):
    body = b"<html><body><ul><li hidden>x<li>a</ul></body></html>"

    content = _fetch_html(server, tmp_path, body)

    assert "x" not in content
    assert content.strip() == "a"


def test_webfetch_optional_end_tag_hidden_p_closed_by_sibling_p_start_tags(server, tmp_path):
    body = b"<html><body><p hidden>x<p>y</p><p>after</p></body></html>"

    content = _fetch_html(server, tmp_path, body)

    assert "x" not in content
    assert "y" in content
    assert "after" in content


def test_webfetch_nested_same_name_inside_hidden_optional_end_tag_stays_dropped(server, tmp_path):
    body = b"<html><body><ul><li hidden><ul><li>x</li></ul></li><li>b</li></ul></body></html>"

    content = _fetch_html(server, tmp_path, body)

    assert "x" not in content
    assert content.strip() == "b"


def test_webfetch_consecutive_hidden_optional_end_tag_siblings_all_drop(server, tmp_path):
    body = b"<html><body><ul><li hidden>x<li hidden>z<li>b</ul></body></html>"

    content = _fetch_html(server, tmp_path, body)

    assert "x" not in content
    assert "z" not in content
    assert content.strip() == "b"


@pytest.mark.parametrize(
    "body, expected_lines",
    [
        (b"<table><tr hidden><td>a<td>b</tr><tr><td>visible</td></tr></table>after", ["visible", "after"]),
        (b"<ul><li hidden><p>x</li><li>b</li></ul>after", ["b", "after"]),
        (b"<ul><li hidden><ul><li>i1<li>i2</ul><li>b</ul>", ["b"]),
        (b"<ul><li hidden><div><li>inj</div>still<li>b</ul>", ["b"]),
        (b"<ul><li hidden><ul><li>injected</li></ul></li><li>b</li></ul>after", ["b", "after"]),
        (b"<ul><li>a<li hidden>x</ul>after", ["a", "after"]),
        (b"<div><span hidden>x</div>after", ["after"]),
        (b"<div hidden></p>injected</div>after", ["after"]),
        (b"<div hidden>x</body>injected</html>", []),
    ],
)
def test_webfetch_hidden_element_ends_at_its_own_or_an_ancestors_end_tag(body, expected_lines):
    content = webfetch._render_content("text/html", (b"<html><body>" + body + b"</body></html>").decode())

    assert [line for line in content.split("\n") if line] == expected_lines
