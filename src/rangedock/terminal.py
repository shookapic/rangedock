"""prompt_toolkit front end for the lab console: editing, history, completion, and palette."""

from __future__ import annotations

import re
import shutil
import sys
from typing import Callable, Iterable

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (CompleteEvent, Completer, Completion, ThreadedCompleter,
                                       get_common_complete_suffix)
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples
from prompt_toolkit.history import FileHistory, History, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.styles import Style

from .config import create_private_file
from .console import BUILTINS, KEY_HINTS, ConsoleSession, history_path, is_private

STYLE = Style.from_dict({
    "rule": "#3b4048",
    "badge": "bg:#1f6f78 #ffffff bold",
    "cwd": "#c678dd",
    "ok": "#98c379",
    "warn": "#e5c07b",
    "dim": "#7f848e",
    "arrow": "#98c379 bold",
    "cmd": "#98c379",
    "flag": "bg:#1f6f78 #e6ffff",
    "string": "#e5c07b",
    "operator": "#c678dd",
    "banner": "bold #61afef",
    "hint": "#7f848e",
    "exit.ok": "#5c6370",
    "exit.fail": "#e06c75",
    "error": "#e06c75",
    "bottom-toolbar": "noreverse bg:#21252b #abb2bf",
    "bottom-toolbar.name": "bold #61afef",
    "auto-suggestion": "#5c6370",
    "completion-menu.completion": "bg:#282c34 #abb2bf",
    "completion-menu.completion.current": "bg:#1f6f78 #ffffff",
    "completion-menu.meta.completion": "bg:#21252b #7f848e",
    "completion-menu.meta.completion.current": "bg:#1f6f78 #e6ffff",
})
TOKEN_RE = re.compile(r"\s+|\"[^\"]*\"?|'[^']*'?|\|\||&&|[|;&]|[^\s|;&]+")
OPERATORS = frozenset({"|", "||", "&&", ";", "&"})


def state_style(kind: str, text: str) -> str:
    if kind == "status":
        return "class:ok" if text == "running" else "class:warn"
    if kind == "vpn":
        if text.endswith(" connected"):
            return "class:ok"
        return "class:warn" if text.endswith(" connecting") else "class:dim"
    return "class:dim"


class ConsoleLexer(Lexer):
    """Colors command names, flags, quoted strings, and shell operators on the input line."""

    def __init__(self, session: ConsoleSession):
        self.session = session

    def style_line(self, line: str) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        expect_command = True
        for token in TOKEN_RE.findall(line):
            if token.isspace():
                style = ""
            elif token in OPERATORS:
                style, expect_command = "class:operator", True
                fragments.append((style, token))
                continue
            elif expect_command:
                known = token in BUILTINS or self.session.sources.tools.find(token) is not None
                style = "class:cmd" if known else ""
                expect_command = False
            elif token.startswith("-"):
                style = "class:flag"
            elif token[0] in "\"'":
                style = "class:string"
            else:
                style = ""
            fragments.append((style, token))
        return fragments

    def lex_document(self, document: Document) -> Callable[[int], StyleAndTextTuples]:
        return lambda lineno: self.style_line(document.lines[lineno])


def prompt_message(session: ConsoleSession) -> StyleAndTextTuples:
    width = max(shutil.get_terminal_size().columns - 1, 10)
    line: StyleAndTextTuples = [("class:rule", "─" * width + "\n"),
                                ("class:badge", f" {session.name} "), ("", " "), ("class:cwd", session.cwd)]
    for kind, text in session.segments:
        if kind == "vpn":
            line += [("", "  "), (state_style(kind, text), text)]
    return line + [("", "\n"), ("class:arrow", "❯ ")]


def toolbar(session: ConsoleSession) -> StyleAndTextTuples:
    bar: StyleAndTextTuples = [("class:bottom-toolbar.name", " RangeDock "), ("class:dim", "· "),
                               ("bold", session.name)]
    for kind, text in session.segments:
        bar += [("class:dim", " · "), (state_style(kind, text), text)]
    return bar + [("class:dim", f"  │  {KEY_HINTS}")]


def styled_echo(color_depth: ColorDepth | None) -> Callable[[str, str], None]:
    def echo(text: str, style: str = "") -> None:
        print_formatted_text(FormattedText([(f"class:{style}" if style else "", text)]), style=STYLE,
                             color_depth=color_depth, file=sys.stderr if style == "error" else None)
    return echo


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
    if not session.preferences.get("console.history"):
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

    @bindings.add("tab")
    def complete_or_cycle(event: KeyPressEvent) -> None:
        buffer = event.app.current_buffer
        if buffer.complete_state and buffer.complete_state.current_completion:
            buffer.complete_next()
            return
        completions = list(completer.get_completions(buffer.document, CompleteEvent(completion_requested=True)))
        if len(completions) == 1:
            buffer.apply_completion(completions[0])
        elif suffix := get_common_complete_suffix(buffer.document, completions):
            buffer.insert_text(suffix)
        elif buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.start_completion(select_first=True)

    editing = EditingMode.VI if session.preferences.get("console.editing") == "vi" else EditingMode.EMACS
    color_depth = None if session.preferences.get("console.color") else ColorDepth.DEPTH_1_BIT
    session.echo = styled_echo(color_depth)
    prompt = PromptSession(
        history=console_history(session), completer=ThreadedCompleter(completer), complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=bindings, editing_mode=editing, color_depth=color_depth, style=STYLE,
        lexer=ConsoleLexer(session), bottom_toolbar=lambda: toolbar(session),
    )

    def read() -> str:
        completer.palette_open = False
        return prompt.prompt(lambda: prompt_message(session))
    return read
