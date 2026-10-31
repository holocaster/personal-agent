import os
import re
import threading
from typing import TextIO

from prompt_toolkit.utils import get_cwidth
from rich.console import Console
from rich.markdown import CodeBlock, Markdown
from rich.syntax import Syntax

RESET = "\033[0m"
CLEAR_LINE = "\r\033[K"

_COLOR_CODES = {
    "cyan": "36",
    "green": "32",
    "red": "31",
    "yellow": "33",
}

SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def color_enabled(output_stream: TextIO) -> bool:
    """True only when output_stream is an interactive terminal and NO_COLOR
    (https://no-color.org) is unset/empty. Gates both color and the spinner."""
    if os.environ.get("NO_COLOR"):
        return False
    return getattr(output_stream, "isatty", lambda: False)()


def colorize(text: str, name: str, enabled: bool) -> str:
    if not enabled:
        return text
    body, trailing_newline = (text[:-1], "\n") if text.endswith("\n") else (text, "")
    return f"\033[{_COLOR_CODES[name]}m{body}{RESET}{trailing_newline}"


def sanitize_control_chars(text: str, multiline: bool) -> str:
    """One pure sanitizer for untrusted (model- or Provider-controlled) text
    (R15): every C0 control (U+0000-U+001F), DEL (U+007F) and C1 control
    (U+0080-U+009F) becomes a visible `\\xNN` escape, so nothing is silently
    dropped and a forgery attempt stays visible. Multi-line mode keeps `\n`
    and `\t`; one-line mode keeps `\t` and shows `\n` as the two characters
    `\\n`. Applied before `colorize` so the REPL's own color codes, spinner
    frames and line clears are untouched."""
    out = []
    for ch in text:
        code = ord(ch)
        if ch == "\t":
            out.append(ch)
        elif ch == "\n":
            out.append(ch if multiline else "\\n")
        elif code <= 0x1F or code == 0x7F or 0x80 <= code <= 0x9F:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    return "".join(out)


_TRAILING_PAD = re.compile(r"(?:\033\[[0-9;]*m| )*$")


class _CopyableCodeBlock(CodeBlock):
    def __rich_console__(self, console, options):
        yield Syntax(str(self.text).rstrip(), self.lexer_name, theme=self.theme, word_wrap=True,
                     background_color="default")


class _CopyableMarkdown(Markdown):
    elements = {**Markdown.elements, "fence": _CopyableCodeBlock, "code_block": _CopyableCodeBlock}


def _strip_trailing_pad(line: str) -> str:
    pad = _TRAILING_PAD.search(line).group()
    return line[:len(line) - len(pad)] + (RESET if "\033" in pad else "")


def write_markdown(text: str, output_stream: TextIO) -> None:
    console = Console(file=output_stream, force_terminal=True)
    with console.capture() as capture:
        console.print(_CopyableMarkdown(text, hyperlinks=False))
    output_stream.write("\n".join(_strip_trailing_pad(line) for line in capture.get().split("\n")))


class StreamingMarkdown:
    def __init__(self, output_stream: TextIO):
        self.output_stream = output_stream
        self.pending = ""
        self.lines = []
        self.fence = ""

    def write(self, text: str) -> None:
        self.pending += text
        while "\n" in self.pending:
            line, _, self.pending = self.pending.partition("\n")
            self.lines.append(line + "\n")
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if marker:
                if not self.fence:
                    self.fence = marker[1]
                elif marker[1][0] == self.fence[0] and len(marker[1]) >= len(self.fence) and not marker[2].strip():
                    self.fence = ""
            if not line.strip() and not self.fence:
                self._render()

    def finish(self) -> None:
        self.lines.append(self.pending)
        self.pending = ""
        self._render()
        self.fence = ""

    def _render(self) -> None:
        text = "".join(self.lines)
        self.lines.clear()
        if text.strip():
            write_markdown(text, self.output_stream)
            if text.endswith("\n\n"):
                self.output_stream.write("\n")
            self.output_stream.flush()


def compact_preview(text: str, columns: int, rows: int) -> tuple[str, bool]:
    columns, rows = max(1, columns), max(1, rows)
    row, column = 1, 0
    shown = []
    for index, character in enumerate(text):
        if character == "\n":
            shown.append(character)
            column = 0
            row += 1
            if row > rows and index + 1 < len(text):
                return "".join(shown), True
            continue
        characters = " " * (8 - column % 8) if character == "\t" else character
        for character in characters:
            width = get_cwidth(character)
            if width and column + width > columns:
                row += 1
                column = 0
            if row > rows or width > columns:
                return "".join(shown), True
            shown.append(character)
            column += width
    return text, False


def preview_details(text: str) -> str:
    lines = text.split("\n")
    if not lines[-1]:
        lines.pop()
    details = f"Preview: {len(lines)} lines, {len(text.encode('utf-8'))} bytes"
    if not text.startswith("--- "):
        return details
    added, removed, hunks, remaining = 0, 0, 0, 0
    for line in lines:
        match = re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if match:
            try:
                remaining = sum(int(count) if count is not None else 1 for count in match.groups())
            except ValueError:
                remaining = 0
                continue
            hunks += 1
        elif remaining and line.startswith("+"):
            added += 1
            remaining -= 1
        elif remaining and line.startswith("-"):
            removed += 1
            remaining -= 1
        elif remaining and line.startswith(" "):
            remaining -= 2
    if hunks:
        details += f", +{added}/-{removed}, {hunks} hunks"
    return details


def next_frame(index: int) -> str:
    """Pure frame-cycling step: which spinner frame follows call number `index`.

    Kept separate from Spinner's threaded loop so the sequence is
    unit-testable without real sleeps or a real thread.
    """
    return SPINNER_FRAMES[index % len(SPINNER_FRAMES)]


class Spinner:
    """Animates a braille spinner on the current line in a background thread
    while the caller blocks on a synchronous call. No-op unless started."""

    def __init__(self, output_stream: TextIO, interval: float = 0.08):
        self._output_stream = output_stream
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        index = 0
        while not self._stop_event.is_set():
            with self._lock:
                self._output_stream.write(f"\r{next_frame(index)} ")
                self._output_stream.flush()
            index += 1
            self._stop_event.wait(self._interval)

    def write_line(self, text: str) -> None:
        """Print one line without garbling the running frame: clear the
        current frame, write the line, and let the frame loop's next tick
        redraw over it. Guarded by the same lock as the frame loop so the two
        writes never interleave."""
        with self._lock:
            self._output_stream.write(f"{CLEAR_LINE}{text}\n")
            self._output_stream.flush()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            self._output_stream.write(CLEAR_LINE)
            self._output_stream.flush()
