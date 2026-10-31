import re
from io import StringIO

import pytest

from personal_agent.terminal.tty import (
    CLEAR_LINE,
    SPINNER_FRAMES,
    Spinner,
    StreamingMarkdown,
    color_enabled,
    colorize,
    compact_preview,
    next_frame,
    write_markdown,
    preview_details,
    sanitize_control_chars,
)


def test_next_frame_cycles_through_all_frames_in_order_then_repeats():
    sequence = [next_frame(i) for i in range(len(SPINNER_FRAMES) * 2)]

    assert sequence == list(SPINNER_FRAMES) * 2


def test_next_frame_is_pure_and_deterministic_for_a_given_index():
    assert next_frame(0) == next_frame(len(SPINNER_FRAMES))
    assert next_frame(3) == SPINNER_FRAMES[3]


def test_colorize_wraps_text_in_ansi_codes_when_enabled():
    assert colorize("hi", "red", True) == "\033[31mhi\033[0m"


def test_colorize_returns_text_unchanged_when_disabled():
    assert colorize("hi", "red", False) == "hi"


def test_colorize_puts_reset_before_a_trailing_newline():
    assert colorize("hi\n", "red", True) == "\033[31mhi\033[0m\n"


class _TTYStream(StringIO):
    def isatty(self):
        return True


def test_color_enabled_true_only_on_a_tty_stream_without_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color_enabled(_TTYStream()) is True


def test_color_enabled_false_on_a_non_tty_stream(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color_enabled(StringIO()) is False


def test_color_enabled_false_when_no_color_is_set_even_on_a_tty_stream(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled(_TTYStream()) is False


def test_spinner_write_line_clears_the_frame_and_appends_the_line():
    stream = StringIO()
    spinner = Spinner(stream)

    spinner.write_line("tool> calculator(expression=\"2+2\") -> 4")

    assert stream.getvalue() == f'{CLEAR_LINE}tool> calculator(expression="2+2") -> 4\n'


def test_spinner_resumes_after_each_pause():
    from threading import Event

    drawn = Event()

    class Stream(StringIO):
        def write(self, text):
            result = super().write(text)
            if any(frame in text for frame in SPINNER_FRAMES):
                drawn.set()
            return result

    spinner = Spinner(Stream())
    for _ in range(3):
        drawn.clear()
        spinner.start()
        try:
            assert drawn.wait(1), "Spinner did not resume after a pause"
        finally:
            spinner.stop()


# --- sanitize_control_chars (R15) -------------------------------------


def test_sanitize_control_chars_escapes_esc():
    assert sanitize_control_chars("a\x1bb", multiline=True) == "a\\x1bb"


def test_sanitize_control_chars_escapes_bel():
    assert sanitize_control_chars("a\x07b", multiline=True) == "a\\x07b"


def test_sanitize_control_chars_escapes_cr_in_both_modes():
    assert sanitize_control_chars("a\rb", multiline=True) == "a\\x0db"
    assert sanitize_control_chars("a\rb", multiline=False) == "a\\x0db"


def test_sanitize_control_chars_escapes_del():
    assert sanitize_control_chars("a\x7fb", multiline=True) == "a\\x7fb"


def test_sanitize_control_chars_escapes_a_c1_character():
    assert sanitize_control_chars("a\x9bb", multiline=True) == "a\\x9bb"


def test_sanitize_control_chars_keeps_newline_and_tab_in_multiline_mode():
    assert sanitize_control_chars("a\nb\tc", multiline=True) == "a\nb\tc"


def test_sanitize_control_chars_escapes_newline_as_backslash_n_in_one_line_mode_but_keeps_tab():
    assert sanitize_control_chars("a\nb\tc", multiline=False) == "a\\nb\tc"


def test_sanitize_control_chars_returns_plain_text_unchanged():
    text = "just a normal sentence, with punctuation!"
    assert sanitize_control_chars(text, multiline=True) == text
    assert sanitize_control_chars(text, multiline=False) == text


@pytest.mark.parametrize("text,columns,rows,expected", [
    ("short\n", 10, 2, ("short\n", False)),
    ("a\nb\nc\n", 10, 2, ("a\nb\n", True)),
    ("x" * 10000, 4, 2, ("xxxxxxxx", True)),
    ("界" * 10, 4, 2, ("界界界界", True)),
    ("1234567\tZ", 8, 1, ("1234567 ", True)),
    ("界\tZ", 8, 1, ("界      ", True)),
    ("界", 1, 1, ("", True)),
    ("e\u0301e\u0301e\u0301", 2, 1, ("e\u0301e\u0301", True)),
])
def test_compact_preview_bounds_terminal_rows(text, columns, rows, expected):
    assert compact_preview(text, columns, rows) == expected


def test_preview_details_count_original_bytes_and_diff_hunks_without_header_lines():
    preview = "--- a\n+++ a\n@@ -1 +1 @@\n-old\n+new\n--- b\n+++ b\n@@ -0,0 +1 @@\n+++ content\n"
    assert preview_details(preview) == f"Preview: 9 lines, {len(preview.encode())} bytes, +2/-1, 2 hunks"
    assert preview_details("界\n") == "Preview: 1 lines, 4 bytes"


@pytest.mark.parametrize("separator", ["\r", "\v", "\f", "\u2028", "\u2029"])
def test_preview_details_parse_actual_diff_by_lf_without_splitting_content(separator):
    from personal_agent.tools.workspace import _unified_diff

    preview = _unified_diff("f", "old\nkeep\n", f"new{separator}-old\nkeep\n")
    assert preview_details(preview) == f"Preview: 6 lines, {len(preview.encode())} bytes, +1/-1, 1 hunks"


@pytest.mark.parametrize("prefix,lines", [("", 2), ("--- f\n+++ f\n", 4)])
def test_preview_details_accept_arbitrary_content_resembling_a_diff_header(prefix, lines):
    preview = prefix + "@@ -0,0 +1," + "9" * 5000 + " @@\n+content\n"
    assert preview_details(preview) == f"Preview: {lines} lines, {len(preview.encode())} bytes"


def test_spinner_write_line_never_has_frame_text_spliced_inside_it_while_running():
    stream = StringIO()
    spinner = Spinner(stream, interval=0.001)
    spinner.start()
    lines = [f'tool> calculator(expression="{i}+{i}") -> {i * 2}' for i in range(30)]

    for line in lines:
        spinner.write_line(line)
    spinner.stop()

    output = stream.getvalue()
    for line in lines:
        assert f"{CLEAR_LINE}{line}\n" in output


def test_write_markdown_leaves_no_trailing_pad_and_unindented_code():
    stream = StringIO()

    write_markdown("## Title\n\nsome **bold** text\n\n- item\n\n> quote\n\n```python\nprint(1)\n```", stream)

    output = stream.getvalue()
    plain = [re.sub(r"\033\[[0-9;]*m", "", line) for line in output.split("\n")]
    assert all(line == line.rstrip() for line in plain)
    assert "print(1)" in plain
    assert "some bold text" in plain
    assert output.endswith("\n") and "\033[1mbold\033[0m" in output


@pytest.mark.parametrize("fence", ["```", "````", "~~~"])
@pytest.mark.parametrize("split", [1, 2, 7, 4096])
def test_streaming_markdown_keeps_fenced_blank_lines_and_split_markup(fence, split):
    body = f"**before**\n\n{fence}text\nalpha\n\n**literal**\n{fence}\n\n**after**"
    output, expected = StringIO(), StringIO()
    streaming = StreamingMarkdown(output)
    for start in range(0, len(body), split):
        streaming.write(body[start:start + split])
    streaming.finish()
    streaming.finish()
    write_markdown(body, expected)

    def lines(text):
        return [line for line in re.sub(r"\033\[[0-9;]*m", "", text).splitlines() if line.strip()]

    assert lines(output.getvalue()) == lines(expected.getvalue())
    assert "**literal**" in output.getvalue() and "\033[1mbefore\033[0m" in output.getvalue()


@pytest.mark.parametrize("body", ["First paragraph.\n\nSecond paragraph.", "**First**\n\n**Second**", "## Title\n\nParagraph."])
def test_streaming_markdown_preserves_paragraph_spacing(body):
    output, expected = StringIO(), StringIO()
    stream = StreamingMarkdown(output)
    stream.write(body)
    stream.finish()
    write_markdown(body, expected)
    assert output.getvalue() == expected.getvalue()
