# 02: webfetch Network Tool behind Tool Confirmation

**What to build:** The model can call `webfetch(url)` to read one
`http`/`https` page. The REPL first shows `webfetch: <url>` and asks
`Fetch this URL? [y/N] `; only `y`/`yes` fetches, and end of input rejects.
An approved fetch GETs the URL (redirects followed), converts HTML to plain
text with the stdlib parser, passes text-like types through, rejects binary
types, and returns `{url, status, content_type, content, truncated}` bounded
by the Tool Output Cap. Registered by default; stdlib only.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0022-web-todo-search.md` (Requirements R7-R12, R19 for
`webfetch` and the Tool Confirmation sentence; Implementation Decisions: new
`webfetch` module, Tool Registry, Terminal (REPL); Testing Decisions: Seam 1
and Seam 2 for the REPL prompt); **ADRs:** none.

- [x] R7: `webfetch` is in the Tool Registry by default (no env var), schema
  `{url: string minLength 1}` required, no additional properties;
  description per R7.
- [x] R8: a non-`http`/`https` scheme or a URL without a host is a Tool
  error and `confirm` is never called; localhost/private addresses allowed.
- [x] R9: `webfetch` goes through prepare -> Tool Confirmation -> apply; the
  Tool Registry flag that routes a Tool through confirmation is generalized
  (renamed) to cover Network Tools, with `execute_batch` behaviour otherwise
  unchanged. The REPL shows `webfetch: <url>` and asks
  `Fetch this URL? [y/N] `; rejection or EOF gives the existing
  `change rejected by the user` Tool error with no request made.
- [x] R10: one GET with a fixed `User-Agent`; redirects followed, a redirect
  to a non-`http(s)` scheme is a Tool error; constants 30 s timeout and
  5242880-byte download limit; HTTP >= 400 (`HTTP <status> <reason>`),
  timeout, over-limit body (never buffering beyond limit + 1 bytes) and other
  network failures are Tool errors.
- [x] R11: `text/html` and `application/xhtml+xml` converted to plain text,
  dropping `script`, `style`, `noscript`, `template`, `svg`, `iframe`, `nav`
  content, breaking lines at block elements and `<br>`, collapsing spaces
  and blank-line runs, decoding character references; `text/*`,
  `application/json`, `application/*+json`, `application/xml`,
  `application/*+xml`, `application/javascript` pass through; anything else
  or a missing `Content-Type` is `unsupported content type: <type>`.
  Decoding uses the header charset when present and known, else UTF-8 with
  replacement.
- [x] R12: result `{url (final), status, content_type (media type), content,
  truncated}`; over-cap content is cut on a character boundary so content +
  `[...truncated]` fits the Tool Output Cap, with `truncated: true`.
- [x] R19 (part): `README.md` documents `webfetch` as a Network Tool (its
  confirmation, limits, content handling, result shape) and the "only
  Tool-execution gate" sentence covers it.
- [x] Tests at the `tools.execute_batch` seam against a real
  `http.server.ThreadingHTTPServer` on `127.0.0.1` port 0: HTML conversion
  (dropped elements, line breaks, entities), JSON and markdown passthrough,
  redirect returning the final URL, 404 error with status, binary type
  error, oversized body error, timeout error (constants monkeypatched
  small), truncation with the marker, scheme error with `confirm` never
  called, rejection with no request received by the server. A REPL test
  shows the `webfetch: <url>` header and `Fetch this URL? [y/N] ` prompt
  and that EOF rejects. Registry-wide schema test covers the entry. No
  network outside localhost. Full offline suite passes.
