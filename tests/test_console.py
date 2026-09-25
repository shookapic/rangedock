import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from rangedock.cli import build_parser
from rangedock.completion import CompletionEngine, CompletionSources, command_tree
from rangedock.console import ConsoleSession, is_private, last_workspace, parse_line
from rangedock.core import RangeDockError, Workbench
from rangedock.profiles import ProfileStore
from rangedock.terminal import ConsoleHistory
from rangedock.tools import MANIFEST_PATH, Tool, ToolCatalog, ToolOption, options_from_help, workspace_tools
from test_core import FakeDocker

NMAP = Tool("nmap", "recon", "Network exploration tool", (),
            (ToolOption("-sT", "TCP connect scan"), ToolOption("-sV", "Service versions"), ToolOption("-p", "Ports")))
CATALOG = ToolCatalog((NMAP, Tool("nc", "network", "Netcat", ("netcat",))), "test")


def completions(engine, text):
    return [suggestion.text for suggestion in engine.complete(text)]


def vpn_not_running(args):
    raise RangeDockError("No such file: /run/rangedock-openvpn.pid")


class ParseLineTests(unittest.TestCase):
    def test_plain_commands_become_argument_vectors(self):
        command = parse_line("  nmap -sT 'my host' ")
        self.assertEqual(command.words, ["nmap", "-sT", "my host"])
        self.assertFalse(command.shell)

    def test_shell_syntax_is_left_to_the_workspace_shell(self):
        for line in ("ls | grep x", "echo $HOME", "cat *.txt", "a && b", "FOO=1 env", "cd ~"):
            with self.subTest(line=line):
                self.assertTrue(parse_line(line).shell)

    def test_no_save_marker_is_stripped(self):
        self.assertTrue(is_private("export TOKEN=abc # no-save"))
        self.assertEqual(parse_line("curl -H 'X: 1' # no-save").words, ["curl", "-H", "X: 1"])
        self.assertIsNone(parse_line("  # no-save"))
        self.assertIsNone(parse_line("   "))

    def test_unbalanced_quotes_are_reported(self):
        with self.assertRaisesRegex(RangeDockError, "Cannot parse"):
            parse_line("echo 'open")


class CompletionTests(unittest.TestCase):
    def setUp(self):
        sources = CompletionSources(CATALOG, ["ctf-box", "lab"], ["htb", "thm"])
        self.engine = CompletionEngine(command_tree(build_parser()), sources)

    def test_first_word_offers_builtins_and_installed_tools(self):
        self.assertEqual(completions(self.engine, "n"), ["nc", "netcat", "nmap"])
        self.assertIn("rangedock", completions(self.engine, ""))
        suggestion = self.engine.complete("nma")[0]
        self.assertEqual((suggestion.start, suggestion.meta), (-3, "Network exploration tool"))

    def test_rangedock_commands_follow_the_cli_parser(self):
        self.assertEqual(completions(self.engine, "rangedock vpn pro"), ["profile"])
        self.assertEqual(completions(self.engine, "rangedock vpn profile "), ["add", "list", "remove", "show"])
        self.assertEqual(completions(self.engine, "rangedock info "), ["ctf-box", "lab"])
        self.assertEqual(completions(self.engine, "rangedock vpn profile show "), ["htb", "thm"])
        self.assertEqual(completions(self.engine, "rangedock create x --vpn-profile t"), ["thm"])
        self.assertEqual(completions(self.engine, "rangedock create x --image "), ["base", "desktop", "web"])
        self.assertIn("--vpn-profile", completions(self.engine, "rangedock create x --v"))
        self.assertEqual(completions(self.engine, "rangedock console --profile "), ["htb", "thm"])

    def test_known_tools_offer_maintained_and_learned_options(self):
        self.assertEqual(completions(self.engine, "nmap -s"), ["-sT", "-sV"])
        self.engine.sources.learned_options["nmap"] = ["--reason"]
        self.assertIn("--reason", completions(self.engine, "nmap 10.0.0.1 --"))

    def test_unknown_commands_get_no_invented_suggestions(self):
        self.assertEqual(completions(self.engine, "custom-tool --"), [])

    def test_palette_filters_by_title_or_command(self):
        session = ConsoleSession(Workbench(FakeDocker()), "lab", tree=command_tree(build_parser()),
                                 dispatch=lambda args: 0)
        titles = [suggestion.display for suggestion in session.engine.palette("vpn", session.palette())]
        self.assertEqual(titles, ["VPN status", "VPN connect", "VPN logs"])
        commands = [suggestion.text for suggestion in session.engine.palette("rangedock desk", session.palette())]
        self.assertEqual(commands, ["rangedock desktop lab"])


class ConsoleSessionTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDocker()
        self.fake.exists = True
        self.fake.running = True
        self.dispatched = []
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        profiles = ProfileStore(Path(folder.name) / "profiles.toml")
        self.session = ConsoleSession(Workbench(self.fake), "lab", tree=command_tree(build_parser()),
                                      dispatch=self.dispatch, profiles=profiles)
        self.session.sources.tools = CATALOG

    def dispatch(self, args):
        self.dispatched.append(args)
        return 0

    def handle(self, line):
        with redirect_stdout(io.StringIO()) as output:
            result = self.session.handle(line)
        return result, output.getvalue()

    def execs(self):
        return [args for args, _, _ in self.fake.calls if args[:2] == ["container", "exec"]]

    def test_catalogued_tool_runs_as_an_argument_vector_in_the_workspace(self):
        self.fake.exit_code = 3
        result, output = self.handle("nmap -sT 'target host'")
        self.assertTrue(result)
        self.assertEqual(self.execs()[-1][-4:], ["rangedock-lab", "nmap", "-sT", "target host"])
        self.assertIn("--workdir", self.execs()[-1])
        self.assertRegex(output, r"\[exit 3 · \d+\.\d\ds\]")

    def test_shell_syntax_and_unknown_commands_use_the_workspace_shell(self):
        self.handle("nmap -sT host | tee scan.txt")
        self.assertEqual(self.execs()[-1][-3:], ["bash", "-c", "nmap -sT host | tee scan.txt"])
        self.handle("ll -a")
        self.assertEqual(self.execs()[-1][-3:], ["bash", "-c", "ll -a"])

    def test_stopped_workspace_is_started_before_running(self):
        self.fake.running = False
        self.handle("nmap --version")
        self.assertIn((["container", "start", "rangedock-lab"], None, False), self.fake.calls)

    def test_cd_keeps_the_resolved_directory_for_later_commands(self):
        self.fake.exec_handler = lambda args: "/workspace/notes"
        self.handle("cd notes")
        self.assertEqual(self.execs()[-1][-3:], ["bash", "-c", "cd notes && pwd"])
        self.assertEqual(self.session.cwd, "/workspace/notes")
        self.fake.exec_handler = None
        self.handle("nmap --version")
        workdir = self.execs()[-1]
        self.assertEqual(workdir[workdir.index("--workdir") + 1], "/workspace/notes")
        with self.assertRaisesRegex(RangeDockError, "single path"):
            self.handle("cd /tmp && rm x")

    def test_rangedock_commands_dispatch_to_the_cli(self):
        self.handle("rangedock vpn profile list")
        self.assertEqual(self.dispatched, [["vpn", "profile", "list"]])
        with self.assertRaisesRegex(RangeDockError, "Already in a console"):
            self.handle("rangedock console other")

    def test_cli_usage_errors_do_not_close_the_console(self):
        self.session.dispatch = lambda args: build_parser().parse_args(args)
        with mock.patch("sys.stderr", io.StringIO()):
            result, output = self.handle("rangedock bogus")
        self.assertTrue(result)
        self.assertIn("[exit 2]", output)

    def test_exit_closes_the_console(self):
        self.assertFalse(self.handle("exit")[0])

    def test_help_for_a_tool_learns_its_options(self):
        self.fake.exec_handler = lambda args: "  -sS  SYN scan\n  --reason  Display reasons\n"
        _, output = self.handle("help nmap")
        self.assertIn("SYN scan", output)
        self.assertEqual(self.session.sources.learned_options["nmap"], ["--reason", "-sS"])
        with self.assertRaisesRegex(RangeDockError, "not in this image's tool manifest"):
            self.handle("help unknown")

    def test_header_shows_workspace_and_vpn_state(self):
        self.fake.vpn = "/vpn/client.ovpn"
        self.fake.vpn_profile = "htb"
        self.fake.exec_handler = vpn_not_running
        self.session.refresh()
        self.assertEqual(self.session.header, "RangeDock · lab · web · running · VPN htb stopped")
        self.assertEqual(self.session.sources.workspaces, ["lab"])


class ToolManifestTests(unittest.TestCase):
    def test_image_manifest_is_preferred(self):
        fake = FakeDocker()
        fake.exists = fake.running = True
        manifest = {"schema": 1, "tools": [{"name": "nmap", "description": "Scanner", "options": [{"flag": "-sT"}]}]}
        fake.exec_handler = lambda args: json.dumps(manifest)
        catalog = workspace_tools(Workbench(fake), "lab")
        self.assertEqual(catalog.source, f"image manifest {MANIFEST_PATH}")
        self.assertEqual(catalog.find("nmap").options, (ToolOption("-sT", ""),))

    def test_older_images_fall_back_to_installed_catalogued_tools(self):
        fake = FakeDocker()
        fake.exists = fake.running = True

        def handler(args):
            if args[-2:] == ["cat", MANIFEST_PATH]:
                raise RangeDockError("No such file or directory")
            return "nmap\nnc\n"
        fake.exec_handler = handler
        catalog = workspace_tools(Workbench(fake), "lab")
        self.assertIn("bundled catalog", catalog.source)
        self.assertEqual(sorted(tool.name for tool in catalog.tools), ["nc", "nmap"])
        self.assertEqual(catalog.find("nc").aliases, ())

    def test_options_are_extracted_from_help_text(self):
        self.assertEqual(options_from_help("Usage: tool [-v] --output=FILE, -x\nsee well-known -"),
                         ["--output=", "-v", "-x"])


class ConsoleStorageTests(unittest.TestCase):
    def test_history_file_skips_no_save_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history"
            history = ConsoleHistory(str(path))
            history.append_string("nmap -sT 10.0.0.1")
            history.append_string("export TOKEN=abc # no-save")
            saved = path.read_text(encoding="utf-8")
        self.assertIn("nmap -sT 10.0.0.1", saved)
        self.assertNotIn("TOKEN", saved)

    def test_last_requires_a_previous_console(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": folder, "APPDATA": folder}):
            with self.assertRaisesRegex(RangeDockError, "No console has been opened"):
                last_workspace()


if __name__ == "__main__":
    unittest.main()
