# 03: webfetch drops hidden HTML elements

**What to build:** `webfetch`'s HTML-to-text conversion drops the content
of elements a human reader would not see: any element with the `hidden`
attribute, `aria-hidden="true"`, or an inline `style` containing
`display:none` or `visibility:hidden` (whitespace- and case-insensitive),
together with everything nested inside it. Visible content, including
content after a hidden element, is unaffected (including a same-name
sibling after a hidden `li`/`p`/... with no end tag; the remaining
implicit-close limits are listed in the spec's Out of Scope).

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0023-shell-guardrails.md` (Requirements R9, R10 for
hidden elements; Implementation Decisions: `webfetch` tools module; Testing
Decisions: Seam 3); **ADRs:** none.

- [x] R9: a start tag with a `hidden` attribute (any value or none),
  `aria-hidden` equal to `true` (trimmed, lowercased), or a `style` whose
  whitespace-stripped, lowercased value contains `display:none` or
  `visibility:hidden` has its content dropped up to its matching end tag,
  counting nested same-name start/end tags; an unclosed one drops to the
  end of the document; a hidden void element (`area`, `base`, `br`, `col`,
  `embed`, `hr`, `img`, `input`, `link`, `meta`, `source`, `track`, `wbr`)
  or self-closing tag drops nothing else. Existing conversion behaviour
  (spec 0022 R11) unchanged.
- [x] R9 (review round 1 amendment): for an element whose end tag is
  optional (`li`, `p`, `dt`, `dd`, `tr`, `td`, `th`, `option`, `optgroup`,
  `rt`, `rp`, `thead`, `tbody`, `tfoot`, `colgroup`, `caption`), a
  same-name start tag while dropping it ends the drop instead of nesting,
  unless that start tag is inside another element opened within the drop
  and not yet closed; the start tag that ended the drop is then handled
  normally (it may start a new drop).
- [x] R10 (part): `README.md` Network Tools section says hidden elements
  (`hidden`, `aria-hidden="true"`, inline `display:none` /
  `visibility:hidden`) are dropped, and that class- or stylesheet-based
  hiding is not detected.
- [x] Seam 3 tests (`execute_batch` against the local HTTP server in
  `tests/test_webfetch.py`): each hiding form dropped; `style="DISPLAY : None"`
  and `display:none !important` dropped; `<div hidden><div>a</div>b</div>c`
  yields only `c`; `<input hidden>visible` keeps `visible`;
  `aria-hidden="false"` and `style="display:block"` kept;
  `<ul><li hidden>x<li>a</ul>` keeps `a` and drops `x`;
  `<p hidden>x<p>y</p><p>after</p>` keeps `y` and `after` and drops `x`;
  `<ul><li hidden><ul><li>x</li></ul></li><li>b</li></ul>` drops `x` and
  keeps `b`; `<ul><li hidden>x<li hidden>z<li>b</ul>` keeps only `b`;
  existing HTML conversion tests unchanged.
- [x] Full offline suite passes.
