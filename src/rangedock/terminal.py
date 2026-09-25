"""prompt_toolkit front end for the lab console: editing, history, completion, and palette."""

from __future__ import annotations

from typing import Callable, Iterable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory, History, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

from .config import create_private_file
from .console import KEY_HINTS, ConsoleSession, history_path, is_private


class ConsoleCompleter(Completer):
    """Serves engine suggestions, or palette actions after Ctrl-K."""

    def __init__(self, session: ConsoleSession):
        self.session = session
        self.palette_open = False

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor
        suggestions = []
        if self.palette_open:
            suggestions = self.session.engine.palette(text, self.session.palette())
            self.palette_open = bool(suggestions)
        if not self.palette_open:
            suggestions = self.session.engine.complete(text)
        for suggestion in suggestions:
            yield Completion(suggestion.text, suggestion.start,
                             display=suggestion.display, display_meta=suggestion.meta)


class ConsoleHistory(FileHistory):
    """File history that skips lines marked '# no-save'."""

    def store_string(self, string: str) -> None:
        if not is_private(string):
            super().store_string(string)


def console_history(session: ConsoleSession) -> History:
    if not session.settings.history:
        return InMemoryHistory()
    path = history_path(session.name)
    create_private_file(path)
    return ConsoleHistory(str(path))


def prompt_reader(session: ConsoleSession) -> Callable[[], str]:
    completer = ConsoleCompleter(session)
    bindings = KeyBindings()

    @bindings.add("c-k")
    def open_palette(event: KeyPressEvent) -> None:
        completer.palette_open = True
        event.app.current_buffer.text = ""
        event.app.current_buffer.start_completion(select_first=False)

    prompt = PromptSession(
        history=console_history(session), completer=completer, complete_while_typing=False,
        key_bindings=bindings, bottom_toolbar=lambda: f" {session.header} │ {KEY_HINTS}",
    )

    def read() -> str:
        completer.palette_open = False
        return prompt.prompt(f"{session.cwd} ❯ ")
    return read
