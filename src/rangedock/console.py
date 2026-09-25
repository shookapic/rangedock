"""Interactive lab console: a prompt with history and completion over one workspace.

Commands run inside the selected workspace through the same Workbench as the CLI;
the console adds no privileges, mounts, or host shell access.
"""

from __future__ import annotations

import re
import shlex
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .completion import CommandNode, CompletionEngine, CompletionSources, PaletteAction
from .config import config_dir, write_private_text
from .core import RangeDockError, Workbench, valid_name
from .preferences import Preferences
from .profiles import ProfileStore
from .tools import describe_tool, options_from_help, workspace_tools

NO_SAVE = "# no-save"
SHELL_CHARS = frozenset("|&;<>()$`*?[]{}~!#")
CHAINING_CHARS = frozenset("|&;<>()`")
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
DEFAULT_CWD = "/workspace"
KEY_HINTS = "Tab complete · Ctrl-P history · Ctrl-R search · Ctrl-K palette · Ctrl-D exit"
PALETTE = (
    PaletteAction("Workspace info", "rangedock info {name}"),
    PaletteAction("VPN status", "rangedock vpn status {name}"),
    PaletteAction("VPN connect", "rangedock vpn connect {name}"),
    PaletteAction("VPN logs", "rangedock vpn logs {name}"),
    PaletteAction("Open desktop", "rangedock desktop {name}"),
    PaletteAction("Installed tools", "rangedock tools {name}"),
    PaletteAction("Image list", "rangedock image list"),
    PaletteAction("Workspace list", "rangedock list"),
    PaletteAction("Exit console", "exit"),
)

Dispatch = Callable[[list[str]], int]


@dataclass(frozen=True)
class ConsoleCommand:
    text: str
    words: list[str]
    shell: bool


def is_private(line: str) -> bool:
    """Lines ending in '# no-save' never reach the history file."""
    return line.rstrip().endswith(NO_SAVE)


def parse_line(line: str) -> ConsoleCommand | None:
    """Split a console line into an argument vector, or mark it for the workspace shell."""
    text = line.strip()
    if is_private(text):
        text = text[:-len(NO_SAVE)].rstrip()
    if not text:
        return None
    try:
        words = shlex.split(text)
    except ValueError as exc:
        raise RangeDockError(f"Cannot parse command: {exc}") from exc
    shell = any(char in SHELL_CHARS for char in text) or bool(ASSIGNMENT_RE.match(text))
    return ConsoleCommand(text, words, shell)


@contextmanager
def forward_interrupts() -> Iterator[None]:
    """Let Ctrl-C stop the command in the workspace without closing the console."""
    previous = signal.signal(signal.SIGINT, lambda signum, frame: None)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def history_path(name: str) -> Path:
    return config_dir() / "history" / name


def last_workspace_path() -> Path:
    return config_dir() / "last-console"


def last_workspace() -> str:
    try:
        name = last_workspace_path().read_text(encoding="utf-8").strip()
    except OSError:
        name = ""
    if not name:
        raise RangeDockError("No console has been opened yet. Run 'rangedock console NAME'.")
    return valid_name(name)


class ConsoleSession:
    def __init__(self, bench: Workbench, name: str, *, tree: CommandNode, dispatch: Dispatch,
                 profiles: ProfileStore | None = None, preferences: Preferences | None = None):
        self.bench = bench
        self.name = valid_name(name)
        self.dispatch = dispatch
        self.profiles = profiles or ProfileStore()
        self.preferences = preferences or Preferences()
        self.sources = CompletionSources()
        self.engine = CompletionEngine(tree, self.sources)
        self.cwd = DEFAULT_CWD
        self.header = f"RangeDock · {self.name}"

    def palette(self) -> list[PaletteAction]:
        return [PaletteAction(action.title, action.command.format(name=self.name)) for action in PALETTE]

    def refresh(self) -> None:
        """Reload workspace state and the names used by completion."""
        details = self.bench.info(self.name)
        parts = ["RangeDock", self.name, details["profile"], details["status"]]
        if details["vpn"] != "none":
            label = "VPN" if details["vpn_profile"] == "none" else f"VPN {details['vpn_profile']}"
            parts.append(f"{label} {self.bench.vpn_state(self.name).replace('workspace ', '')}")
        self.header = " · ".join(parts)
        self.sources.workspaces = sorted(row.get("Names", "").removeprefix("rangedock-")
                                         for row in self.bench.list())
        try:
            self.sources.profiles = self.profiles.names()
        except RangeDockError:
            self.sources.profiles = []

    def start(self) -> None:
        self.bench.start(self.name)
        self.sources.tools = workspace_tools(self.bench, self.name)
        self.refresh()
        write_private_text(last_workspace_path(), f"{self.name}\n")

    def handle(self, line: str) -> bool:
        """Run one console line. Returns False when the console should close."""
        command = parse_line(line)
        if command is None:
            return True
        name = command.words[0]
        if name in ("exit", "quit"):
            return False
        if name == "cd":
            self.change_directory(command)
        elif name == "help":
            self.show_help(command.words[1:])
        elif name == "tool":
            if len(command.words) != 2:
                raise RangeDockError("Usage: tool NAME")
            self.show_tool_summary(command.words[1])
        elif name == "rangedock":
            self.run_rangedock(command)
        else:
            self.run_in_workspace(command)
        return True

    def run_in_workspace(self, command: ConsoleCommand) -> None:
        """Run catalogued tools as an argument vector; anything else goes to the workspace shell."""
        direct = not command.shell and self.sources.tools.find(command.words[0]) is not None
        argv = command.words if direct else ["bash", "-c", command.text]
        started = time.monotonic()
        with forward_interrupts():
            code = self.bench.execute(self.name, argv, workdir=self.cwd)
        print(f"[exit {code} · {time.monotonic() - started:.2f}s]")

    def run_rangedock(self, command: ConsoleCommand) -> None:
        if command.shell:
            raise RangeDockError("RangeDock commands in the console do not support shell syntax.")
        args = command.words[1:]
        if args[:1] == ["console"]:
            raise RangeDockError("Already in a console. Use 'exit' first to switch workspaces.")
        try:
            code = self.dispatch(args)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        self.refresh()
        if code:
            print(f"[exit {code}]")

    def change_directory(self, command: ConsoleCommand) -> None:
        """Resolve the target with the workspace shell so '~' and variables expand as usual."""
        if any(char in CHAINING_CHARS for char in command.text):
            raise RangeDockError("cd takes a single path; it cannot be combined with other commands.")
        target = command.text.split(None, 1)[1] if len(command.words) > 1 else DEFAULT_CWD
        self.cwd = self.bench.capture(self.name, ["bash", "-c", f"cd {target} && pwd"], workdir=self.cwd)

    def show_help(self, args: list[str]) -> None:
        if args:
            self.show_tool_help(args[0])
            return
        print("Commands run inside the workspace. Console commands:")
        print("  cd PATH           change the working directory for later commands")
        print("  tool TOOL         show a tool's options from the manifest, without running it")
        print("  help TOOL         run a tool's --help and learn its options for completion")
        print("  rangedock ...     run a RangeDock command, e.g. 'rangedock vpn status'")
        print("  exit              leave the console; the workspace keeps running")
        print(f"End a command with '{NO_SAVE}' to keep it out of history.")
        print(KEY_HINTS)
        print("Palette:")
        for action in self.palette():
            print(f"  {action.title:<16} {action.command}")

    def show_tool_summary(self, command: str) -> None:
        tool = self.sources.tools.find(command)
        if tool is None:
            raise RangeDockError(
                f"'{command}' is not in this image's tool manifest. "
                f"Run 'help {command}' for its own --help, or 'rangedock tools {self.name}' to list tools."
            )
        print("\n".join(describe_tool(tool)))

    def show_tool_help(self, command: str) -> None:
        tool = self.sources.tools.find(command)
        if tool is None:
            raise RangeDockError(f"'{command}' is not in this image's tool manifest. Run '{command} --help' directly.")
        text = self.bench.capture(self.name, ["sh", "-c", '"$0" --help 2>&1 || true', tool.name])
        print(text)
        self.sources.learned_options[tool.name] = options_from_help(text)

    def run(self, *, plain: bool = False) -> None:
        self.start()
        read = self._plain_reader() if plain else self._prompt_reader()
        print(self.header)
        print("Type 'help' for console commands. Commands run inside the workspace.")
        while True:
            try:
                line = read()
            except KeyboardInterrupt:
                continue
            except EOFError:
                print()
                break
            try:
                if not self.handle(line):
                    break
            except RangeDockError as exc:
                print(f"rangedock: {exc}", file=sys.stderr)

    def _plain_reader(self) -> Callable[[], str]:
        def read() -> str:
            return input(f"{self.name}:{self.cwd}> ")
        return read

    def _prompt_reader(self) -> Callable[[], str]:
        from .terminal import prompt_reader  # prompt_toolkit loads only when a console opens
        return prompt_reader(self)


def open_console(bench: Workbench, name: str, *, tree: CommandNode, dispatch: Dispatch,
                 plain: bool = False, preferences: Preferences | None = None) -> None:
    preferences = preferences or Preferences()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    session = ConsoleSession(bench, name, tree=tree, dispatch=dispatch, preferences=preferences)
    session.run(plain=plain or preferences.get("console.plain") or not interactive)
