"""Tool catalog for console completion and the 'rangedock tools' diagnostic."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from importlib import resources

from .core import RangeDockError, Workbench

MANIFEST_PATH = "/usr/share/rangedock/tools.json"
HELP_OPTION_RE = re.compile(r"(?<![\w-])(--?[A-Za-z0-9][\w.-]*=?)")

# Lists the catalogued commands that exist in the workspace without running any of them.
INSTALLED_SCRIPT = 'for tool; do if command -v "$tool" >/dev/null 2>&1; then echo "$tool"; fi; done'


@dataclass(frozen=True)
class ToolOption:
    flag: str
    description: str


@dataclass(frozen=True)
class Tool:
    name: str
    category: str
    description: str
    aliases: tuple[str, ...] = ()
    options: tuple[ToolOption, ...] = ()


@dataclass(frozen=True)
class ToolCatalog:
    tools: tuple[Tool, ...]
    source: str

    def find(self, command: str) -> Tool | None:
        for tool in self.tools:
            if command == tool.name or command in tool.aliases:
                return tool
        return None

    def commands(self) -> dict[str, Tool]:
        """Every invocable name, including aliases, mapped to its tool."""
        return {name: tool for tool in self.tools for name in (tool.name, *tool.aliases)}


def parse_tools(text: str, origin: str) -> tuple[Tool, ...]:
    try:
        data = json.loads(text)
        return tuple(
            Tool(
                name=entry["name"],
                category=entry.get("category", "other"),
                description=entry.get("description", ""),
                aliases=tuple(entry.get("aliases", ())),
                options=tuple(ToolOption(option["flag"], option.get("description", ""))
                              for option in entry.get("options", ())),
            )
            for entry in data["tools"]
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise RangeDockError(f"Invalid tool manifest from {origin}: {exc}") from exc


def bundled_tools() -> tuple[Tool, ...]:
    text = resources.files("rangedock").joinpath("tools.json").read_text(encoding="utf-8")
    return parse_tools(text, "the RangeDock package")


def workspace_tools(bench: Workbench, name: str) -> ToolCatalog:
    """Load the tool manifest pinned in a workspace image.

    Images built before the manifest existed fall back to the bundled catalog,
    filtered to the commands the workspace actually has.
    """
    try:
        text = bench.capture(name, ["cat", MANIFEST_PATH])
    except RangeDockError:
        catalog = bundled_tools()
        commands = [command for tool in catalog for command in (tool.name, *tool.aliases)]
        installed = set(bench.capture(name, ["sh", "-c", INSTALLED_SCRIPT, "sh", *commands]).splitlines())
        tools = tuple(
            replace(tool, aliases=tuple(alias for alias in tool.aliases if alias in installed))
            for tool in catalog if tool.name in installed
        )
        return ToolCatalog(tools, "bundled catalog (image has no tool manifest)")
    return ToolCatalog(parse_tools(text, MANIFEST_PATH), f"image manifest {MANIFEST_PATH}")


def options_from_help(text: str) -> list[str]:
    """Extract option flags from a tool's --help output."""
    return sorted(set(HELP_OPTION_RE.findall(text)))
