"""Local MCP adapter for existing RangeDock workspaces."""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict

from .core import RangeDockError, Workbench, valid_name
from .profiles import ProfileStore
from .tools import workspace_tools


class McpService:
    """Small, policy-aware adapter over RangeDock's existing operations."""

    def __init__(self, bench: Workbench | None = None, store: ProfileStore | None = None,
                 *, workspace: str | None = None, allow_exec: bool = False):
        if workspace is not None:
            valid_name(workspace)
        if allow_exec and workspace is None:
            raise RangeDockError("--allow-exec requires --workspace NAME.")
        self.bench = bench or Workbench()
        self.store = store or ProfileStore()
        self.workspace = workspace
        self.allow_exec = allow_exec

    def _allowed(self, name: str) -> str:
        valid_name(name)
        if self.workspace is not None and name != self.workspace:
            raise RangeDockError(f"This MCP server is limited to workspace '{self.workspace}'.")
        return name

    def _scoped(self) -> str:
        if not self.allow_exec or self.workspace is None:
            raise RangeDockError("Execution is disabled. Start rangedock-mcp with --workspace NAME --allow-exec.")
        return self.workspace

    def workspace_info(self, name: str) -> dict[str, str]:
        details = self.bench.info(self._allowed(name))
        return {key: details[key] for key in ("name", "status", "image", "profile", "vpn_profile")}

    def list_workspaces(self) -> list[dict[str, str]]:
        rows = []
        for row in self.bench.list():
            container = row.get("Names", "")
            if not container.startswith("rangedock-"):
                continue
            name = container.removeprefix("rangedock-")
            if self.workspace is None or name == self.workspace:
                rows.append(self.workspace_info(name))
        return rows

    def list_vpn_profiles(self) -> list[dict[str, str | bool]]:
        return [{"name": profile.name, "type": profile.type, "available": profile.available}
                for profile in self.store.list()]

    def vpn_status(self, name: str) -> dict[str, str]:
        name = self._allowed(name)
        details = self.bench.info(name)
        state = "not configured" if details["vpn"] == "none" else self.bench.vpn_state(name)
        return {"workspace": name, "profile": details["vpn_profile"], "state": state}

    def list_tools(self, name: str) -> dict[str, str | list[dict[str, str]]]:
        name = self._allowed(name)
        catalog = workspace_tools(self.bench, name, start=False)
        return {"workspace": name, "source": catalog.source,
                "tools": [{"name": tool.name, "category": tool.category,
                           "description": tool.description} for tool in catalog.tools]}

    def tool_info(self, name: str, tool_name: str) -> dict[str, str | list[str] | list[dict[str, str]]]:
        name = self._allowed(name)
        catalog = workspace_tools(self.bench, name, start=False)
        tool = catalog.find(tool_name)
        if tool is None:
            raise RangeDockError(f"Tool '{tool_name}' is not in workspace '{name}' catalog.")
        return {"workspace": name, "name": tool.name, "category": tool.category,
                "description": tool.description, "aliases": list(tool.aliases),
                "options": [asdict(option) for option in tool.options]}

    def start_workspace(self) -> dict[str, str]:
        name = self._scoped()
        started = self.bench.start(name)
        return {"workspace": name, "state": "started" if started else "already running"}

    def stop_workspace(self) -> dict[str, str]:
        name = self._scoped()
        stopped = self.bench.stop(name)
        return {"workspace": name, "state": "stopped" if stopped else "already stopped"}

    def run_command(self, argv: list[str], timeout_seconds: int = 30) -> dict[str, str | int | float | bool]:
        name = self._scoped()
        result = self.bench.execute_result(name, argv, timeout_seconds=timeout_seconds)
        return {"workspace": name, **asdict(result)}


def build_server(service: McpService):
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer("RangeDock")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @server.tool(annotations=read_only)
    def list_workspaces() -> list[dict[str, str]]:
        """List managed workspaces visible to this local RangeDock server."""
        return service.list_workspaces()

    @server.tool(annotations=read_only)
    def workspace_info(name: str) -> dict[str, str]:
        """Get status, image, and VPN profile for a managed workspace."""
        return service.workspace_info(name)

    @server.tool(annotations=read_only)
    def list_vpn_profiles() -> list[dict[str, str | bool]]:
        """List saved VPN profile names and availability without revealing file paths or keys."""
        return service.list_vpn_profiles()

    @server.tool(annotations=read_only)
    def vpn_status(name: str) -> dict[str, str]:
        """Read a workspace's current VPN connection state."""
        return service.vpn_status(name)

    @server.tool(annotations=read_only)
    def list_tools(name: str) -> dict[str, str | list[dict[str, str]]]:
        """List the tools in a running workspace without starting a stopped one."""
        return service.list_tools(name)

    @server.tool(annotations=read_only)
    def tool_info(name: str, tool_name: str) -> dict[str, str | list[str] | list[dict[str, str]]]:
        """Describe one installed tool and its common options from the image catalog."""
        return service.tool_info(name, tool_name)

    if service.allow_exec:
        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
        def start_workspace() -> dict[str, str]:
            """Start the one workspace explicitly granted to this server."""
            return service.start_workspace()

        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
        def stop_workspace() -> dict[str, str]:
            """Stop the granted workspace. Files in its host folder remain."""
            return service.stop_workspace()

        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                                open_world_hint=True))
        def run_command(argv: list[str], timeout_seconds: int = 30) -> dict[str, str | int | float | bool]:
            """Run one command in the granted workspace; it may change files or contact the network."""
            return service.run_command(argv, timeout_seconds)

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rangedock-mcp", description="Local RangeDock MCP server.")
    parser.add_argument("--workspace", metavar="NAME", help="limit this server to one existing workspace")
    parser.add_argument("--allow-exec", action="store_true",
                        help="expose start, stop, and command execution for --workspace")
    args = parser.parse_args(argv)
    try:
        service = McpService(workspace=args.workspace, allow_exec=args.allow_exec)
        server = build_server(service)
    except ImportError:
        print("RangeDock MCP needs the optional SDK. Install 'rangedock[mcp]'.", file=sys.stderr)
        return 1
    except RangeDockError as exc:
        print(f"rangedock-mcp: {exc}", file=sys.stderr)
        return 1
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
