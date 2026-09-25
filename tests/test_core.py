import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rangedock.core import (IMAGE, IMAGES, LABEL, PROFILE_LABEL, REMOTE_IMAGES, VPN_LABEL,
                            VPN_PROFILE_LABEL, WORKSPACE_LABEL, RangeDockError, Workbench, valid_name)
from rangedock.tour import run_tour, show_tour


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.exists = False
        self.running = False
        self.managed = True
        self.workspace = ""
        self.profile = "web"
        self.vpn = None
        self.vpn_profile = None
        self.image = IMAGE
        self.platform = "linux"
        self.exec_handler = None
        self.exit_code = 0

    def status(self, args):
        self.calls.append((args, None, True))
        return self.exit_code

    def call(self, args, *, input_text=None, interactive=False):
        self.calls.append((args, input_text, interactive))
        if args[:2] == ["container", "exec"] and self.exec_handler is not None:
            return self.exec_handler(args)
        if args[0] == "version":
            return "29.0"
        if args[0] == "info":
            return self.platform
        if args[:2] == ["image", "inspect"]:
            return "sha256:example"
        if args[:2] == ["container", "create"]:
            self.exists = True
            self.workspace = next(
                value.removeprefix(f"{WORKSPACE_LABEL}=") for value in args
                if value.startswith(f"{WORKSPACE_LABEL}=")
            )
            self.profile = next(value.removeprefix(f"{PROFILE_LABEL}=") for value in args
                                if value.startswith(f"{PROFILE_LABEL}="))
            self.vpn = next((value.removeprefix(f"{VPN_LABEL}=") for value in args
                             if value.startswith(f"{VPN_LABEL}=")), None)
            self.vpn_profile = next((value.removeprefix(f"{VPN_PROFILE_LABEL}=") for value in args
                                     if value.startswith(f"{VPN_PROFILE_LABEL}=")), None)
            self.image = args[-1]
            return "container-id"
        if args[:2] == ["container", "inspect"]:
            if not self.exists:
                raise RangeDockError("No such container")
            return json.dumps({
                "Config": {
                    "Labels": {LABEL: "true" if self.managed else "false", WORKSPACE_LABEL: self.workspace,
                               PROFILE_LABEL: self.profile, **({VPN_LABEL: self.vpn} if self.vpn else {}),
                               **({VPN_PROFILE_LABEL: self.vpn_profile} if self.vpn_profile else {})},
                    "Image": self.image,
                },
                "State": {"Running": self.running, "Status": "running" if self.running else "exited"},
                "Created": "2026-09-25T00:00:00Z",
                "NetworkSettings": {"Ports": {"6080/tcp": [{"HostPort": "49152"}]}},
            })
        if args[:2] == ["container", "ls"]:
            if "--format" in args and args[-1] == "{{.Names}}":
                return "rangedock-lab" if self.exists else ""
            return json.dumps({"Names": "rangedock-lab", "Status": "Up", "Image": IMAGE})
        if args[:2] == ["container", "start"]:
            self.running = True
            return ""
        if args[:2] == ["container", "restart"]:
            self.running = True
            return ""
        if args[:2] == ["container", "stop"]:
            self.running = False
            return ""
        if args[:2] == ["container", "rm"]:
            self.exists = False
            return ""
        return ""


class WorkbenchTests(unittest.TestCase):
    def test_name_validation_rejects_unsafe_names(self):
        for name in ("../other", "lab;echo", "UPPER", "", "a" * 41):
            with self.subTest(name=name), self.assertRaises(RangeDockError):
                valid_name(name)
        self.assertEqual(valid_name("lab-1"), "lab-1")

    def test_create_and_remove_preserve_host_files(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "lab"
            self.assertEqual(bench.create("lab", workspace), workspace.resolve())
            create = next(args for args, _, _ in fake.calls if args[:2] == ["container", "create"])
            self.assertIn(f"{LABEL}=true", create)
            self.assertIn("no-new-privileges", create)
            self.assertNotIn("--privileged", create)
            self.assertIn(f"type=bind,source={workspace.resolve()},target=/workspace", create)
            (workspace / "notes.txt").write_text("keep me", encoding="utf-8")
            bench.remove("lab")
            self.assertEqual((workspace / "notes.txt").read_text(encoding="utf-8"), "keep me")

    def test_refuses_unmanaged_container(self):
        fake = FakeDocker()
        fake.exists = True
        fake.managed = False
        with self.assertRaisesRegex(RangeDockError, "not managed"):
            Workbench(fake).stop("lab")
        with self.assertRaisesRegex(RangeDockError, "not managed"):
            Workbench(fake).open("lab")
        self.assertFalse(any(args[:2] == ["container", "stop"] for args, _, _ in fake.calls))
        self.assertFalse(any(args[:2] == ["container", "exec"] for args, _, _ in fake.calls))

    def test_run_starts_workspace_and_preserves_argv(self):
        fake = FakeDocker()
        fake.exists = True
        bench = Workbench(fake)
        bench.run("lab", ["nmap", "--version"])
        self.assertIn((["container", "start", "rangedock-lab"], None, False), fake.calls)
        self.assertIn((["container", "exec", "rangedock-lab", "nmap", "--version"], None, True), fake.calls)

    def test_open_reuses_workspace_and_rejects_a_different_mount(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "lab"
            bench.open("lab", workspace)
            bench.open("lab", workspace)
            self.assertEqual(sum(args[:2] == ["container", "create"] for args, _, _ in fake.calls), 1)
            self.assertEqual(sum(args[:2] == ["container", "exec"] for args, _, _ in fake.calls), 2)
            with self.assertRaisesRegex(RangeDockError, "already uses"):
                bench.open("lab", Path(folder) / "other")
            self.assertEqual(bench.info("lab")["workspace"], str(workspace.resolve()))

    def test_restart_starts_stopped_or_restarts_running(self):
        fake = FakeDocker()
        fake.exists = True
        bench = Workbench(fake)
        self.assertEqual(bench.restart("lab"), "Started")
        self.assertEqual(bench.restart("lab"), "Restarted")
        self.assertIn((["container", "restart", "rangedock-lab"], None, False), fake.calls)

    def test_doctor_rejects_windows_container_mode(self):
        fake = FakeDocker()
        fake.platform = "windows"
        with self.assertRaisesRegex(RangeDockError, "Linux containers"):
            Workbench(fake).linux_daemon()

    def test_build_uses_bundled_image_without_external_code(self):
        fake = FakeDocker()
        Workbench(fake).build()
        build = next(call for call in fake.calls if call[0][0] == "build")
        self.assertEqual(build[0][:6], ["build", "--pull", "--target", "web", "-t", IMAGE])
        self.assertTrue(build[0][-1].endswith("rangedock"))

    def test_pull_tags_published_image_locally(self):
        fake = FakeDocker()
        Workbench(fake).pull("base")
        self.assertIn((["pull", REMOTE_IMAGES["base"]], None, True), fake.calls)
        self.assertIn((["tag", REMOTE_IMAGES["base"], IMAGES["base"]], None, False), fake.calls)

    def test_desktop_uses_loopback_port(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        with tempfile.TemporaryDirectory() as folder:
            bench.create("lab", Path(folder), profile="desktop")
        create = next(args for args, _, _ in fake.calls if args[:2] == ["container", "create"])
        self.assertIn("127.0.0.1::6080", create)
        self.assertEqual(bench.desktop_url("lab"), "http://127.0.0.1:49152/vnc.html?autoconnect=1")

    def test_vpn_mount_is_read_only_and_capability_is_scoped(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "client.ovpn"
            config.write_text("client\n", encoding="utf-8")
            bench.create("lab", Path(folder) / "workspace", vpn=config)
            create = next(args for args, _, _ in fake.calls if args[:2] == ["container", "create"])
            self.assertIn(f"type=bind,source={config.parent.resolve()},target=/vpn,readonly", create)
            self.assertIn("NET_ADMIN", create)
            self.assertIn("/dev/net/tun:/dev/net/tun", create)
            self.assertNotIn("--privileged", create)
            self.assertEqual(bench.info("lab")["vpn"], str(config.resolve()))

    def test_tour_walkthrough_explains_commands_without_docker(self):
        output = io.StringIO()
        with redirect_stdout(output):
            show_tour("lab")
        self.assertIn("rangedock doctor", output.getvalue())
        self.assertIn("rangedock tour --run --name lab", output.getvalue())

    def test_hands_on_tour_preserves_host_file_and_stops_container(self):
        fake = FakeDocker()
        bench = Workbench(fake)
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "lab"
            with redirect_stdout(io.StringIO()):
                run_tour(bench, "lab", workspace)
            self.assertIn("This file stays on your host", (workspace / "rangedock-tour.txt").read_text())
            self.assertFalse(fake.running)
            cats = [args for args, _, _ in fake.calls if args[:3] == ["container", "exec", "rangedock-lab"] and args[3:] == ["cat", "/workspace/rangedock-tour.txt"]]
            self.assertEqual(len(cats), 2)

    def test_hands_on_tour_refuses_a_nonempty_folder(self):
        fake = FakeDocker()
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            (workspace / "important.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(RangeDockError, "not empty"):
                run_tour(Workbench(fake), "lab", workspace)
            self.assertFalse(fake.calls)


if __name__ == "__main__":
    unittest.main()
