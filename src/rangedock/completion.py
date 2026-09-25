"""Local, deterministic completion for the lab console.

Nothing here runs a command: suggestions come from the CLI parser, Docker labels,
the profile file, and the image tool manifest that the console loads up front.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from .tools import ToolCatalog

BUILTINS = {
    "cd": "change the console working directory",
    "help": "console help, or 'help TOOL' for a tool's options",
    "exit": "leave the console; the workspace keeps running",
    "rangedock": "run a RangeDock command",
}
WORKSPACE_DESTS = {"name"}
PROFILE_DESTS = {"vpn_profile", "profile_name"}


@dataclass(frozen=True)
class Argument:
    dest: str
    help: str = ""
    choices: tuple[str, ...] = ()
    takes_value: bool = True


@dataclass
class CommandNode:
    help: str = ""
    subcommands: dict[str, CommandNode] = field(default_factory=dict)
    options: dict[str, Argument] = field(default_factory=dict)
    positionals: list[Argument] = field(default_factory=list)


def command_tree(parser: argparse.ArgumentParser, help_text: str = "") -> CommandNode:
    """Mirror an argparse parser so completion always matches the real CLI."""
    node = CommandNode(help_text)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            for name, subparser in action.choices.items():
                node.subcommands[name] = command_tree(subparser, helps.get(name, ""))
            continue
        choices = tuple(str(choice) for choice in action.choices or ())
        if action.option_strings:
            argument = Argument(action.dest, action.help or "", choices, takes_value=action.nargs != 0)
            for flag in action.option_strings:
                node.options[flag] = argument
        else:
            node.positionals.append(Argument(action.dest, action.help or "", choices))
    return node


@dataclass(frozen=True)
class Suggestion:
    text: str
    start: int
    meta: str = ""
    display: str | None = None


@dataclass(frozen=True)
class PaletteAction:
    title: str
    command: str


@dataclass
class CompletionSources:
    """Data the console refreshes; completion only reads it."""

    tools: ToolCatalog = field(default_factory=lambda: ToolCatalog((), "none"))
    workspaces: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    learned_options: dict[str, list[str]] = field(default_factory=dict)


class CompletionEngine:
    def __init__(self, tree: CommandNode, sources: CompletionSources):
        self.tree = tree
        self.sources = sources

    def complete(self, text: str) -> list[Suggestion]:
        words = text.split()
        current = "" if not text or text[-1].isspace() else words.pop()
        if not words:
            return self._first_word(current)
        if words[0] == "rangedock":
            return self._rangedock(words[1:], current)
        if words[0] == "help" and len(words) == 1:
            tools = self.sources.tools.commands()
            return self._match(current, {name: tool.description for name, tool in tools.items()})
        tool = self.sources.tools.find(words[0])
        if tool is None:
            return []
        options = {option.flag: option.description for option in tool.options}
        for flag in self.sources.learned_options.get(tool.name, ()):
            options.setdefault(flag, "from --help")
        return self._match(current, options)

    def palette(self, text: str, actions: list[PaletteAction]) -> list[Suggestion]:
        query = text.strip().lower()
        return [
            Suggestion(action.command, -len(text), action.command, action.title)
            for action in actions
            if query in action.title.lower() or action.command.startswith(query)
        ]

    def _first_word(self, current: str) -> list[Suggestion]:
        candidates = dict(BUILTINS)
        for name, tool in self.sources.tools.commands().items():
            candidates.setdefault(name, tool.description)
        return self._match(current, candidates)

    def _rangedock(self, words: list[str], current: str) -> list[Suggestion]:
        node, pending, position = self.tree, None, 0
        for word in words:
            if pending is not None:
                pending = None
            elif word.startswith("-"):
                argument = node.options.get(word)
                pending = argument if argument and argument.takes_value else None
            elif position == 0 and word in node.subcommands:
                node = node.subcommands[word]
            else:
                position += 1
        if pending is not None:
            return self._values(pending, current)
        if current.startswith("-"):
            return self._match(current, {flag: argument.help for flag, argument in node.options.items()})
        if position == 0 and node.subcommands:
            return self._match(current, {name: child.help for name, child in node.subcommands.items()})
        if position < len(node.positionals):
            return self._values(node.positionals[position], current)
        return []

    def _values(self, argument: Argument, current: str) -> list[Suggestion]:
        if argument.choices:
            values = argument.choices
        elif argument.dest in WORKSPACE_DESTS:
            values = self.sources.workspaces
        elif argument.dest in PROFILE_DESTS:
            values = self.sources.profiles
        else:
            values = ()
        return self._match(current, dict.fromkeys(values, ""))

    @staticmethod
    def _match(current: str, candidates: dict[str, str]) -> list[Suggestion]:
        return [Suggestion(name, -len(current), meta)
                for name, meta in sorted(candidates.items()) if name.startswith(current)]
