import os
import tempfile
import unittest
from pathlib import Path

from rangedock.core import RangeDockError, Workbench
from rangedock.preferences import Preferences, format_value
from test_core import FakeDocker


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.prefs = Preferences(Path(folder.name) / "config.toml")

    def test_defaults_apply_until_overridden(self):
        self.assertTrue(self.prefs.get("console.history"))
        self.assertFalse(self.prefs.get("console.plain"))
        self.assertEqual(self.prefs.get("console.editing"), "emacs")

    def test_set_get_and_reset_round_trip(self):
        self.assertFalse(self.prefs.set("console.history", "off"))
        self.assertFalse(self.prefs.get("console.history"))
        self.assertEqual(self.prefs.set("console.editing", "vi"), "vi")
        # A fresh instance reads the same stored values.
        reloaded = Preferences(self.prefs.path)
        self.assertFalse(reloaded.get("console.history"))
        self.assertEqual(reloaded.get("console.editing"), "vi")
        self.assertTrue(self.prefs.reset("console.history"))
        self.assertTrue(Preferences(self.prefs.path).get("console.history"))

    def test_invalid_values_and_keys_are_rejected(self):
        with self.assertRaisesRegex(RangeDockError, "true or false"):
            self.prefs.set("console.history", "maybe")
        with self.assertRaisesRegex(RangeDockError, "one of"):
            self.prefs.set("console.editing", "nano")
        with self.assertRaisesRegex(RangeDockError, "Unknown setting"):
            self.prefs.set("console.magic", "on")

    def test_stored_file_is_readable_and_typed(self):
        self.prefs.set("console.plain", "true")
        self.prefs.set("console.editing", "vi")
        text = self.prefs.path.read_text(encoding="utf-8")
        self.assertIn("[console]", text)
        self.assertIn("plain = true", text)
        self.assertIn('editing = "vi"', text)

    def test_malformed_stored_values_are_reported(self):
        self.prefs.path.write_text("[console]\nhistory = 'no'\n", encoding="utf-8")
        with self.assertRaisesRegex(RangeDockError, "true or false"):
            self.prefs.get("console.history")
        self.prefs.path.write_text("console = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(RangeDockError, "must be a table"):
            self.prefs.values()
        self.prefs.path.write_text("[console]\nunknown = true\n", encoding="utf-8")
        with self.assertRaisesRegex(RangeDockError, "Unknown setting"):
            self.prefs.values()

    def test_format_value(self):
        self.assertEqual(format_value(True), "true")
        self.assertEqual(format_value("vi"), "vi")

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_stored_file_is_private(self):
        self.prefs.set("console.history", "off")
        self.assertEqual(self.prefs.path.stat().st_mode & 0o777, 0o600)


class VpnStateTests(unittest.TestCase):
    def _bench(self, *, running, pid_ok, log):
        fake = FakeDocker()
        fake.exists = True
        fake.running = running
        fake.vpn = "/vpn/client.ovpn"

        def handler(args):
            if args[-1] == "/run/rangedock-openvpn.pid" and args[-2] == "cat":
                if not pid_ok:
                    raise RangeDockError("No such file")
                return "42"
            if "import os,sys; p=int" in " ".join(args):
                return ""  # process check passes
            if args[-3:-1] == ["sh", "Initialization Sequence Completed|process restarting"] or "grep" in args:
                return log
            return ""
        fake.exec_handler = handler
        return Workbench(fake)

    def test_states(self):
        self.assertEqual(self._bench(running=False, pid_ok=False, log="").vpn_state("lab"), "workspace stopped")
        self.assertEqual(self._bench(running=True, pid_ok=False, log="").vpn_state("lab"), "stopped")
        self.assertEqual(self._bench(running=True, pid_ok=True, log="").vpn_state("lab"), "connecting")
        self.assertEqual(
            self._bench(running=True, pid_ok=True, log="Initialization Sequence Completed").vpn_state("lab"),
            "connected",
        )
        self.assertEqual(
            self._bench(running=True, pid_ok=True, log="process restarting").vpn_state("lab"),
            "connecting",
        )

    def test_status_message_and_profile(self):
        fake = FakeDocker()
        fake.exists = True
        fake.running = True
        fake.vpn = "/vpn/client.ovpn"
        fake.vpn_profile = "htb"
        fake.exec_handler = lambda args: "42" if args[-2:] == ["cat", "/run/rangedock-openvpn.pid"] \
            else ("Initialization Sequence Completed" if "grep" in " ".join(args) else "")
        self.assertEqual(Workbench(fake).vpn_status("lab"), "OpenVPN connected (profile htb)")

    def test_status_requires_a_vpn_config(self):
        fake = FakeDocker()
        fake.exists = True
        with self.assertRaisesRegex(RangeDockError, "no VPN config"):
            Workbench(fake).vpn_status("lab")


if __name__ == "__main__":
    unittest.main()
