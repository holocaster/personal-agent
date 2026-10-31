from collections.abc import Callable, Iterable
import asyncio
import os
import signal
from threading import Event, Thread
from time import monotonic

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application, get_app, in_terminal
from prompt_toolkit.application.current import set_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import to_filter
from prompt_toolkit.history import DummyHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.input.typeahead import get_typeahead, store_typeahead
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Label, TextArea

from personal_agent.terminal.tty import next_frame, sanitize_control_chars

_STYLE = Style.from_dict({"bottom-toolbar": "noreverse"})
for _sequence in ("\x1b[27;2;13~", "\x1b[13;2u"):
    ANSI_SEQUENCES[_sequence] = Keys.ControlJ


class _CommandCompleter(Completer):
    def __init__(self, commands: Iterable[str]):
        self._commands = tuple(commands)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for command in self._commands:
            if command.startswith(text):
                yield Completion(command, start_position=-len(text))


def _key_bindings(commands: tuple[str, ...], toggle_mode: Callable[[], bool]) -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event):
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    @bindings.add("c-j")
    def _shift_newline(event):
        event.current_buffer.insert_text("\n")

    @bindings.add("tab")
    def _complete_command(event):
        buffer = event.current_buffer
        text = buffer.document.text_before_cursor
        if not text.startswith("/") or "\n" in text:
            return
        if buffer.complete_state:
            buffer.complete_next()
            return
        matches = tuple(command for command in commands if command.startswith(text))
        if len(matches) == 1:
            buffer.apply_completion(Completion(matches[0], start_position=-len(text)))
        elif matches:
            buffer.start_completion(select_first=True)

    @bindings.add("s-tab")
    def _toggle_mode(event):
        if toggle_mode():
            event.app.invalidate()

    return bindings


def _rule() -> str:
    return "─" * get_app().output.get_size().columns


def _task_message() -> str:
    return _rule() + "\n> "


class InputBox:
    def __init__(self, commands: Iterable[str], input=None, output=None):
        self._commands = tuple(commands)
        self.footer: Callable[[], str] = lambda: ""
        self.on_mode_toggle: Callable[[], None] | None = None
        self._busy_app = None
        self._stream_future = None
        self._stream_release = None
        self._session = PromptSession(
            message=_task_message,
            bottom_toolbar=self._toolbar,
            completer=_CommandCompleter(self._commands),
            complete_while_typing=False,
            key_bindings=_key_bindings(self._commands, self._toggle_mode),
            multiline=True,
            reserve_space_for_menu=0,
            style=_STYLE,
            input=input,
            output=output,
        )
        self._secret_session = PromptSession(
            history=DummyHistory(),
            is_password=True,
            multiline=False,
            key_bindings=_key_bindings((), self._toggle_mode),
            bottom_toolbar=lambda: self.footer(),
            input=input,
            output=output,
        )
        self._session.layout.current_window.dont_extend_height = to_filter(True)

    def _toolbar(self) -> str:
        text = self._session.default_buffer.text
        if text.startswith("/") and "\n" not in text:
            if text.startswith("/skill off "):
                return _rule() + "\n /skill off [name]"
            matches = [command for command in self._commands if command.startswith(text)]
            if matches:
                return _rule() + "\n " + "  ".join(
                    "/skill off [name]" if command == "/skill off" else command for command in matches
                )
        return _rule() + "\n" + self.footer()

    def _toggle_mode(self) -> bool:
        if self.on_mode_toggle is None:
            return False
        self.on_mode_toggle()
        return True

    def read(self) -> str:
        return self._session.prompt(message=_task_message, multiline=True)

    def ask(self, question: str) -> str:
        """A one-off single-line prompt for Tool Confirmation, reusing this
        Input Box's own prompt_toolkit session rather than a second one.
        prompt_toolkit keeps per-call arguments on the session, so read()
        must pass its own message and multiline back every time."""
        return self._session.prompt(message=question, multiline=False)

    def ask_secret(self, question: str) -> str:
        return self._secret_session.prompt(message=question, multiline=False, is_password=True)

    def choose(self, title: str, choices: list[str]) -> int | None:
        if not choices:
            return None
        selected = [0]
        bindings = KeyBindings()

        @bindings.add("up")
        def up(event):
            selected[0] = (selected[0] - 1) % len(choices)

        @bindings.add("down")
        def down(event):
            selected[0] = (selected[0] + 1) % len(choices)

        @bindings.add("enter")
        def select(event):
            event.app.exit(result=selected[0])

        @bindings.add("escape", eager=True)
        @bindings.add("c-c")
        @bindings.add("c-d")
        def cancel(event):
            event.app.exit(result=None)

        def text():
            rows = [sanitize_control_chars(title, multiline=False)]
            start = max(0, selected[0] - 8)
            for index in range(start, min(len(choices), start + 16)):
                rows.append(("> " if index == selected[0] else "  ")
                            + sanitize_control_chars(choices[index], multiline=False))
            return "\n".join(rows) + "\nUp/Down, Enter to select, Escape to cancel"

        app = Application(layout=Layout(Label(text)), key_bindings=bindings,
                          input=self._session.input, output=self._session.output, erase_when_done=True)
        try:
            return app.run()
        except (EOFError, KeyboardInterrupt):
            return None

    def terminal_size(self):
        return self._session.output.get_size()

    def start_stream(self):
        app = self._busy_app
        if app is None:
            return
        opened = Event()
        release = asyncio.Event()
        self._stream_release = release

        def read_keys():
            app.key_processor.feed_multiple(app.input.read_keys())
            app.key_processor.process_keys()
            if app.input.closed and not app.is_done:
                app.exit(exception=EOFError())

        async def stream():
            try:
                with set_app(app):
                    async with in_terminal():
                        with app.input.raw_mode(), app.input.attach(read_keys):
                            opened.set()
                            await release.wait()
            finally:
                opened.set()

        self._stream_future = asyncio.run_coroutine_threadsafe(stream(), app.loop)
        while not opened.wait(0.05):
            if not app.is_running:
                self._stream_future.cancel()
                raise RuntimeError("Busy terminal stopped before stream output")
        if self._stream_future.done():
            self._stream_future.result()

    def end_stream(self):
        future = self._stream_future
        if future is None:
            return
        app = self._busy_app
        if app.loop is not None and app.loop.is_running():
            app.loop.call_soon_threadsafe(self._stream_release.set)
        try:
            future.result()
        finally:
            if future.done():
                self._stream_future = self._stream_release = None

    def run_busy(self, operation: Callable, *, cancel: Event | None = None):
        bindings = KeyBindings()
        queued = get_typeahead(self._session.input)
        pending = []
        ready = Event()
        failures = []

        @bindings.add("s-tab", eager=True)
        def toggle(event):
            try:
                if self._toggle_mode():
                    event.app.invalidate()
            except BaseException as exc:
                failures.append(exc)
                event.app.exit()
                os.kill(os.getpid(), signal.SIGINT)

        @bindings.add("c-c", eager=True)
        def interrupt(event):
            if cancel is not None:
                cancel.set()
                event.app.exit()
            else:
                os.kill(os.getpid(), signal.SIGINT)

        @bindings.add("c-d", filter=to_filter(cancel is not None))
        @bindings.add("escape", filter=to_filter(cancel is not None), eager=True)
        def cancel_wait(event):
            cancel.set()
            event.app.exit()

        @bindings.add(Keys.Any)
        def queue(event):
            if cancel is None:
                pending.extend(event.key_sequence)

        animate = not os.environ.get("NO_COLOR")
        app = Application(layout=Layout(Label(lambda:
            (next_frame(int(monotonic() / 0.08)) + " Working...\n" if animate else "") + self.footer())),
            key_bindings=bindings, refresh_interval=0.08 if animate else None,
            erase_when_done=True, input=self._session.input, output=self._session.output)

        def start():
            app.key_processor.feed_multiple(queued)
            app.key_processor.process_keys()
            ready.set()

        def listen():
            try:
                app.run(pre_run=start, set_exception_handler=False, handle_sigint=False)
            except EOFError:
                if cancel is not None:
                    cancel.set()
            except BaseException as exc:
                failures.append(exc)
            finally:
                ready.set()

        reader = Thread(target=listen, name="agent-mode-input")
        self._busy_app = app
        try:
            reader.start()
            ready.wait()
            if failures:
                raise failures[0]
            return operation()
        finally:
            try:
                self.end_stream()
            finally:
                if app.loop is not None:
                    app.loop.call_soon_threadsafe(lambda: app.exit() if not app.is_done else None)
                reader.join()
                self._busy_app = None
                pending.extend(get_typeahead(self._session.input))
                if cancel is None:
                    store_typeahead(self._session.input, pending)
            if failures:
                raise failures[0]

    def view_preview(self, text: str) -> None:
        preview = TextArea(text=sanitize_control_chars(text, multiline=True), read_only=True,
                           wrap_lines=True, scrollbar=True)
        bindings = KeyBindings()

        @bindings.add("s-tab")
        def toggle(event):
            if self._toggle_mode():
                event.app.invalidate()

        @bindings.add("q")
        @bindings.add("escape")
        def close(event):
            event.app.exit()

        @bindings.add("c-c")
        def interrupt(event):
            event.app.exit(exception=KeyboardInterrupt())

        @bindings.add("c-d")
        def reject(event):
            event.app.exit(exception=EOFError())

        Application(layout=Layout(HSplit([
            preview, Label("Arrows / Page Up / Page Down: scroll | q / Escape: return to approval"),
            Label(lambda: self.footer()),
        ]), focused_element=preview), key_bindings=bindings, full_screen=True,
                    enable_page_navigation_bindings=True,
                    input=self._session.input, output=self._session.output).run()
