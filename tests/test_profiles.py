import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from rangedock.cli import main
from rangedock.config import config_dir, read_toml, toml_string
from rangedock.core import VPN_PROFILE_LABEL, RangeDockError, Workbench
from rangedock.profiles import ProfileStore
from test_core import FakeDocker

SECRET = "-----BEGIN PRIVATE KEY-----\nsecret-material\n"


def write_config(folder: Path, name: str = "client.ovpn") -> Path:
    config = folder / name
    config.write_text(f"client\n<key>\n{SECRET}</key>\n", encoding="utf-8")
    return config


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.store = ProfileStore(self.folder / "config" / "profiles.toml")
        self.config = write_config(self.folder)

    def test_add_list_show_and_remove_round_trip(self):
        profile = self.store.add("htb", self.config)
        self.assertEqual(profile.config, self.config.resolve())
        self.assertEqual(profile.config_dir, self.config.resolve().parent)
        self.assertEqual(self.store.names(), ["htb"])
        self.assertEqual(self.store.get("htb"), profile)
        saved = read_toml(self.store.path)["vpn"]["htb"]
        self.assertEqual(saved, {"type": "openvpn", "config": self.config.resolve().as_posix(),
                                 "config_dir": self.config.resolve().parent.as_posix()})
        self.assertEqual(self.store.remove("htb"), profile)
        self.assertEqual(self.store.list(), [])

    def test_profile_file_holds_paths_not_key_material(self):
        self.store.add("htb", self.config)
        self.assertNotIn("secret-material", self.store.path.read_text(encoding="utf-8"))

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_profile_file_is_private(self):
        self.store.add("htb", self.config)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.path.parent.stat().st_mode & 0o777, 0o700)

    def test_remove_leaves_source_files_untouched(self):
        (self.folder / "auth.txt").write_text("user\npass\n", encoding="utf-8")
        self.store.add("htb", self.config)
        self.store.remove("htb")
        self.assertIn("secret-material", self.config.read_text(encoding="utf-8"))
        self.assertTrue((self.folder / "auth.txt").is_file())

    def test_invalid_profiles_are_rejected_without_writing(self):
        (self.folder / "notes.txt").write_text("x", encoding="utf-8")
        cases = [
            ("bad extension", "htb", self.folder / "notes.txt", "must be an OpenVPN"),
            ("missing config", "htb", self.folder / "missing.ovpn", "not found"),
            ("invalid name", "HTB", self.config, "Name must"),
        ]
        for label, name, config, message in cases:
            with self.subTest(label), self.assertRaisesRegex(RangeDockError, message):
                self.store.add(name, config)
        self.assertFalse(self.store.path.exists())

    def test_duplicate_name_is_rejected(self):
        self.store.add("htb", self.config)
        with self.assertRaisesRegex(RangeDockError, "already exists"):
            self.store.add("htb", write_config(self.folder, "other.ovpn"))

    def test_unknown_profile_has_actionable_error(self):
        with self.assertRaisesRegex(RangeDockError, "vpn profile add htb"):
            self.store.get("htb")

    def test_resolve_rejects_a_profile_whose_file_disappeared(self):
        self.store.add("htb", self.config)
        self.config.unlink()
        self.assertFalse(self.store.get("htb").available)
        with self.assertRaisesRegex(RangeDockError, "cannot be used"):
            self.store.resolve("htb")

    def test_malformed_files_produce_clear_errors(self):
        self.store.path.parent.mkdir(parents=True)
        cases = {
            "vpn = [": "Invalid TOML",
            "vpn = 1": "'vpn' must be a table",
            "[vpn.htb]\ntype = 'openvpn'": "needs a 'config' path",
            "[vpn.htb]\ntype = 'wireguard'\nconfig = '/x.conf'": "unsupported type",
            "[vpn.HTB]\nconfig = '/x.ovpn'": "bad VPN profile name",
        }
        for text, message in cases.items():
            self.store.path.write_text(text, encoding="utf-8")
            with self.subTest(text), self.assertRaisesRegex(RangeDockError, message):
                self.store.list()


class ConfigTests(unittest.TestCase):
    def test_toml_strings_round_trip(self):
        for value in ["C:\\Users\\alice\\vpn\\client.ovpn", 'quote " mark', "tab\tnew\nline\x7f", "café"]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "value.toml"
                path.write_text(f"value = {toml_string(value)}\n", encoding="utf-8")
                self.assertEqual(read_toml(path)["value"], value)

    def test_windows_config_dir_uses_appdata(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"APPDATA": "C:/Users/alice/AppData/Roaming"}):
            self.assertEqual(config_dir(), Path("C:/Users/alice/AppData/Roaming") / "RangeDock")

    @unittest.skipIf(sys.platform == "win32", "XDG paths")
    def test_posix_config_dir_follows_xdg_and_ignores_relative_values(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}):
            self.assertEqual(config_dir(), Path("/tmp/xdg/rangedock"))
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            self.assertEqual(config_dir(), Path.home() / ".config" / "rangedock")


class ProfileWorkspaceTests(unittest.TestCase):
    def test_profile_workspace_mounts_read_only_and_records_the_name(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        with tempfile.TemporaryDirectory() as folder:
            config = write_config(Path(folder))
            bench.create("lab", Path(folder) / "workspace", vpn=config, vpn_profile="htb")
            create = next(args for args, _, _ in fake.calls if args[:2] == ["container", "create"])
            self.assertIn(f"type=bind,source={config.resolve().parent},target=/vpn,readonly", create)
            self.assertIn(f"{VPN_PROFILE_LABEL}=htb", create)
            self.assertEqual(bench.info("lab")["vpn_profile"], "htb")
            self.assertEqual(bench.vpn_status("lab"), "workspace stopped (profile htb)")
            bench.check_vpn_profile("lab", "htb", config)
            with self.assertRaisesRegex(RangeDockError, "does not use VPN profile"):
                bench.check_vpn_profile("lab", "other", write_config(Path(folder), "other.ovpn"))

    def test_bad_vpn_config_fails_before_any_docker_call(self):
        fake = FakeDocker()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RangeDockError, "not found"):
                Workbench(fake).create("lab", Path(folder), vpn=Path(folder) / "missing.ovpn")
        self.assertEqual(fake.calls, [])


class ProfileCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        environment = {"XDG_CONFIG_HOME": str(self.folder / "xdg"), "APPDATA": str(self.folder / "appdata")}
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = write_config(self.folder)

    def run_cli(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_profile_commands_work_without_docker_and_never_print_keys(self):
        with mock.patch("rangedock.core.subprocess.run", side_effect=AssertionError("Docker was called")):
            self.assertEqual(self.run_cli("vpn", "profile", "add", "htb", "--config", str(self.config))[:2],
                             (0, "Saved VPN profile 'htb'.\n"))
            code, listed, _ = self.run_cli("vpn", "profile", "list")
            self.assertEqual(code, 0)
            self.assertRegex(listed, r"htb\s+openvpn\s+ready")
            code, shown, _ = self.run_cli("vpn", "profile", "show", "htb")
            self.assertIn("(read-only)", shown)
            code, removed, _ = self.run_cli("vpn", "profile", "remove", "htb")
            self.assertIn("Files were not changed", removed)
        for output in (listed, shown, removed):
            self.assertNotIn("secret-material", output)
        self.assertTrue(self.config.is_file())

    def test_missing_profile_file_is_reported_as_a_warning(self):
        self.run_cli("vpn", "profile", "add", "htb", "--config", str(self.config))
        self.config.unlink()
        code, listed, warnings = self.run_cli("vpn", "profile", "list")
        self.assertEqual(code, 0)
        self.assertIn("missing", listed)
        self.assertIn("warning", warnings)

    def test_unknown_profile_stops_create_before_docker(self):
        with mock.patch("rangedock.core.subprocess.run", side_effect=AssertionError("Docker was called")):
            code, _, errors = self.run_cli("create", "lab", "--vpn-profile", "htb")
        self.assertEqual(code, 1)
        self.assertIn("does not exist", errors)


if __name__ == "__main__":
    unittest.main()
