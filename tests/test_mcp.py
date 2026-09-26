import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rangedock.core import CommandResult, RangeDockError, Workbench, run_bounded
from rangedock.mcp_server import McpService, build_server, main
from rangedock.profiles import ProfileStore
from rangedock.tools import Tool, ToolCatalog
from test_core import FakeDocker

try:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
except ImportError:  # the MCP SDK is an optional install
    Client = None


class BoundedProcessTests(unittest.TestCase):
    def test_captures_stdout_stderr_and_exit_code(self):
        result = run_bounded([
            sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)",
        ], timeout=5, max_output_bytes=1024)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.stdout.strip(), "out")
        self.assertEqual(result.stderr.strip(), "err")
        self.assertFalse(result.timed_out)

    def test_caps_large_output(self):
        result = run_bounded([sys.executable, "-c", "print('x' * 100000)"],
                             timeout=5, max_output_bytes=1024)
        self.assertTrue(result.output_truncated)
        self.assertEqual(len(result.stdout.encode()) + len(result.stderr.encode()), 1024)

    def test_kills_a_timed_out_process(self):
        result = run_bounded([sys.executable, "-c", "import time; time.sleep(2)"],
                             timeout=0.1, max_output_bytes=1024)
        self.assertTrue(result.timed_out)
        self.assertLess(result.seconds, 2)


class WorkbenchResultTests(unittest.TestCase):
    def test_stopped_workspace_is_not_started_implicitly(self):
        fake = FakeDocker()
        fake.exists = True
        bench = Workbench(fake)
        with self.assertRaisesRegex(RangeDockError, "stopped"):
            bench.execute_result("lab", ["id"])
        self.assertFalse(any(args[:2] == ["container", "start"] for args, _, _ in fake.calls))

    def test_running_workspace_uses_container_timeout_and_argv(self):
        fake = FakeDocker()
        fake.exists = True
        fake.running = True
        fake.result = mock.Mock(return_value=CommandResult(0, "ok", "", 0.1, False, False))
        result = Workbench(fake).execute_result("lab", ["nmap", "--version"], timeout_seconds=10)
        self.assertEqual(result.stdout, "ok")
        args = fake.result.call_args.args[0]
        self.assertEqual(args[-6:], ["timeout", "--signal=TERM", "--kill-after=2s", "10s",
                                     "nmap", "--version"])
        self.assertEqual(fake.result.call_args.kwargs["max_output_bytes"], 65536)

    def test_rejects_invalid_command_and_timeout_before_docker(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        for words, timeout in [([], 30), (["id"], 0), (["x" * 8193], 30)]:
            with self.subTest(words=words[:1], timeout=timeout), self.assertRaises(RangeDockError):
                bench.execute_result("lab", words, timeout_seconds=timeout)
        self.assertFalse(fake.calls)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ProfileStore(Path(temporary.name) / "profiles.toml")
        self.fake = FakeDocker()
        self.fake.exists = True
        self.fake.running = True
        self.fake.workspace = str(Path(temporary.name) / "private-workspace")
        self.bench = Workbench(self.fake)

    def test_workspace_info_omits_host_and_vpn_paths(self):
        self.fake.vpn = str(Path(self.fake.workspace) / "secret-client.ovpn")
        service = McpService(self.bench, self.store)
        info = service.workspace_info("lab")
        self.assertEqual(info["name"], "lab")
        self.assertNotIn("workspace", info)
        self.assertNotIn("vpn", info)

    def test_profile_list_returns_names_without_config_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "client.ovpn"
            config.write_text("client\n<key>secret-material</key>\n", encoding="utf-8")
            self.store.add("htb", config)
            rows = McpService(self.bench, self.store).list_vpn_profiles()
        self.assertEqual(rows, [{"name": "htb", "type": "openvpn", "available": True}])
        self.assertNotIn(str(config), str(rows))
        self.assertNotIn("secret-material", str(rows))

    def test_scope_blocks_other_workspaces(self):
        service = McpService(self.bench, self.store, workspace="lab")
        with self.assertRaisesRegex(RangeDockError, "limited"):
            service.workspace_info("other")
        self.assertFalse(self.fake.calls)

    def test_catalog_read_does_not_request_workspace_start(self):
        service = McpService(self.bench, self.store)
        catalog = ToolCatalog((Tool("nmap", "recon", "Network scanner"),), "image manifest")
        with mock.patch("rangedock.mcp_server.workspace_tools", return_value=catalog) as load:
            rows = service.list_tools("lab")
        self.assertEqual(rows["tools"][0]["name"], "nmap")
        load.assert_called_once_with(self.bench, "lab", start=False)

    def test_exec_requires_a_scoped_grant(self):
        with self.assertRaisesRegex(RangeDockError, "requires --workspace"):
            McpService(self.bench, self.store, allow_exec=True)
        with self.assertRaisesRegex(RangeDockError, "disabled"):
            McpService(self.bench, self.store).run_command(["id"])

    def test_missing_extra_has_actionable_error(self):
        with mock.patch("rangedock.mcp_server.build_server", side_effect=ImportError):
            with mock.patch("sys.stderr") as stderr:
                self.assertEqual(main([]), 1)
        self.assertTrue(stderr.write.called)


@unittest.skipIf(Client is None, "install the optional mcp extra for protocol tests")
class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_process_handshake_and_discovery(self):
        process = StdioServerParameters(command=sys.executable,
                                        args=["-m", "rangedock.mcp_server"])
        async with Client(process) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            self.assertIn("list_workspaces", names)
            self.assertNotIn("run_command", names)

    async def test_read_only_server_advertises_only_discovery_tools(self):
        fake = FakeDocker()
        fake.exists = True
        fake.running = True
        service = McpService(Workbench(fake), ProfileStore(Path(tempfile.gettempdir()) / "missing-rangedock-profiles.toml"))
        async with Client(build_server(service)) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            self.assertIn("list_workspaces", names)
            self.assertIn("workspace_info", names)
            self.assertNotIn("run_command", names)
            result = await client.call_tool("workspace_info", {"name": "lab"})
            self.assertEqual(result.structured_content["name"], "lab")
            catalog = ToolCatalog((Tool("nmap", "recon", "Network scanner"),), "image manifest")
            with mock.patch("rangedock.mcp_server.workspace_tools", return_value=catalog):
                listed = await client.call_tool("list_tools", {"name": "lab"})
                described = await client.call_tool("tool_info", {"name": "lab", "tool_name": "nmap"})
            self.assertEqual(listed.structured_content["tools"][0]["name"], "nmap")
            self.assertEqual(described.structured_content["name"], "nmap")

    async def test_scoped_exec_server_advertises_and_calls_execution(self):
        fake = FakeDocker()
        fake.exists = True
        fake.running = True
        fake.result = mock.Mock(return_value=CommandResult(0, "hello", "", 0.1, False, False))
        service = McpService(Workbench(fake), workspace="lab", allow_exec=True)
        async with Client(build_server(service)) as client:
            tools = await client.list_tools()
            self.assertIn("run_command", {tool.name for tool in tools.tools})
            result = await client.call_tool("run_command", {"argv": ["printf", "hello"]})
            self.assertFalse(result.is_error, str(result.content))
            self.assertEqual(result.structured_content["stdout"], "hello")
            self.assertEqual(result.structured_content["exit_code"], 0)
        fake.result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
