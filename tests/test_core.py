import json
import tempfile
import unittest
from pathlib import Path

from rangedock.core import LABEL, IMAGE, RangeDockError, Workbench, valid_name


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.exists = False
        self.running = False
        self.managed = True

    def call(self, args, *, input_text=None, interactive=False):
        self.calls.append((args, input_text, interactive))
        if args[0] == "version":
            return "29.0"
        if args[:2] == ["image", "inspect"]:
            return "sha256:example"
        if args[:2] == ["container", "create"]:
            self.exists = True
            return "container-id"
        if args[:2] == ["container", "inspect"]:
            if not self.exists:
                raise RangeDockError("No such container")
            return json.dumps({
                "Config": {"Labels": {LABEL: "true" if self.managed else "false"}},
                "State": {"Running": self.running},
            })
        if args[:2] == ["container", "start"]:
            self.running = True
            return ""
        if args[:2] == ["container", "stop"]:
            self.running = False
            return ""
        if args[:2] == ["container", "rm"]:
            self.exists = False
            return ""
        if args[:2] == ["container", "ls"]:
            return json.dumps({"Names": "rangedock-lab", "Status": "Up", "Image": IMAGE})
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
        self.assertFalse(any(args[:2] == ["container", "stop"] for args, _, _ in fake.calls))

    def test_run_starts_workspace_and_preserves_argv(self):
        fake = FakeDocker()
        fake.exists = True
        bench = Workbench(fake)
        bench.run("lab", ["nmap", "--version"])
        self.assertIn((["container", "start", "rangedock-lab"], None, False), fake.calls)
        self.assertIn((["container", "exec", "rangedock-lab", "nmap", "--version"], None, True), fake.calls)

    def test_build_uses_bundled_image_without_external_code(self):
        fake = FakeDocker()
        Workbench(fake).build()
        build = next(call for call in fake.calls if call[0][0] == "build")
        self.assertEqual(build[0], ["build", "--pull", "-t", IMAGE, "-"])
        self.assertIn("FROM debian:bookworm-slim", build[1])


if __name__ == "__main__":
    unittest.main()
