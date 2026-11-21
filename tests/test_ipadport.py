import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from ipadport import asar
from ipadport.cli import main
from ipadport.detect import NotSourceCodeError, detect
from ipadport.generate import GenerateError, Options, generate
from ipadport.scan import scan

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "electron-notes"
NODE = shutil.which("node")


def write(base: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content))
    return base


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class DetectTests(TempDirTest):
    def kind(self, files):
        root = write(self.tmp / "p", files)
        found = detect(root)
        return found[0].kind if found else None

    def test_electron(self):
        self.assertEqual(detect(EXAMPLE)[0].kind, "electron")

    def test_web(self):
        self.assertEqual(self.kind({"package.json": '{"dependencies": {"react": "18"}}', "public/index.html": "<html>"}), "web")

    def test_static_site(self):
        self.assertEqual(self.kind({"index.html": "<html></html>"}), "web")

    def test_swift_appkit(self):
        d = detect(write(self.tmp / "p", {"App/Main.swift": "import AppKit\nimport SwiftUI\n"}))[0]
        self.assertEqual((d.kind, d.strategy), ("swift", "swift"))
        self.assertIn("AppKit", d.label)

    def test_flutter(self):
        self.assertEqual(self.kind({"pubspec.yaml": "name: x\nflutter:\n  uses-material-design: true\n"}), "flutter")

    def test_wpf(self):
        self.assertEqual(self.kind({"App.csproj": "<Project><PropertyGroup><UseWPF>true</UseWPF></PropertyGroup></Project>"}),
                         "dotnet-wpf")

    def test_maui(self):
        self.assertEqual(self.kind({"App.csproj": "<UseMaui>true</UseMaui>"}), "dotnet-maui")

    def test_win32(self):
        self.assertEqual(self.kind({"main.cpp": "#include <windows.h>\nint WinMain(){}"}), "win32")

    def test_qt(self):
        self.assertEqual(self.kind({"main.cpp": "#include <QApplication>\n", "app.pro": "QT += widgets"}), "qt")

    def test_tauri(self):
        self.assertEqual(self.kind({"package.json": "{}", "src-tauri/tauri.conf.json": "{}"}), "tauri")

    def test_refuses_binaries(self):
        exe = self.tmp / "Setup.exe"
        exe.write_bytes(b"MZ")
        with self.assertRaises(NotSourceCodeError):
            detect(exe)
        app = self.tmp / "Thing.app" / "Contents" / "MacOS"
        app.mkdir(parents=True)
        with self.assertRaises(NotSourceCodeError):
            detect(self.tmp / "Thing.app")


class ScanTests(TempDirTest):
    def test_example_findings(self):
        report = scan(EXAMPLE)
        ids = {f.rule.id for f in report.findings}
        self.assertIn("electron-ipc-main", ids)
        self.assertIn("electron-ipc", ids)
        self.assertEqual(sorted(report.ipc_channels), ["notes:export", "notes:load", "notes:save"])
        self.assertGreaterEqual(report.score(), 80)
        # ported handlers in ipadport/ are not reported as issues
        self.assertFalse(any(f.file.startswith("ipadport/") for f in report.findings))

    def test_blockers_lower_score(self):
        root = write(self.tmp / "p", {
            "package.json": '{"main": "main.js", "dependencies": {"electron": "1"}}',
            "main.js": "const cp = require('child_process');\nnew Tray('x');\nconst { autoUpdater } = require('electron');\n",
        })
        report = scan(root)
        self.assertEqual(report.counts()["blocker"], 3)
        self.assertLess(report.score(), 60)

    def test_swift_rules(self):
        root = write(self.tmp / "p", {"A.swift": "import AppKit\nlet p = Process()\nlet c = NSColor.red\nlet s = NSStatusBar.system\n"})
        ids = {f.rule.id for f in scan(root).findings}
        self.assertTrue({"swift-appkit", "swift-process", "swift-appkit-types", "swift-statusbar"} <= ids)

    def test_rewrite_ui_is_capped(self):
        root = write(self.tmp / "p", {"App.csproj": "<UseWPF>true</UseWPF>"})
        self.assertLessEqual(scan(root).score(), 45)

    def test_json_report(self):
        data = json.loads(json.dumps(scan(EXAMPLE).to_dict()))
        self.assertEqual(data["detections"][0]["kind"], "electron")


class GenerateTests(TempDirTest):
    def test_electron_example(self):
        out = self.tmp / "out"
        result = generate(EXAMPLE, scan(EXAMPLE), Options(out=out))
        self.assertEqual(result["target"], "NotesExample")
        for rel in ["project.yml", "Sources/App.swift", "Sources/NativeBridge.swift", "web/index.html",
                    "BundleResources/ipadport-shim.js", "BundleResources/ipc-handlers.js", "BundleResources/preload.js",
                    "PORTING_PLAN.md"]:
            self.assertTrue((out / rel).is_file(), rel)
        yml = (out / "project.yml").read_text()
        self.assertIn('TARGETED_DEVICE_FAMILY: "1,2"', yml)
        self.assertIn("UIApplicationSupportsMultipleScenes: true", yml)
        # The example ships its own ported handlers, which must be used instead of stubs.
        self.assertIn("notes:save", (out / "BundleResources/ipc-handlers.js").read_text())
        self.assertNotIn("__", (out / "Sources/AppConfig.swift").read_text().replace("__IPADPORT", ""))
        self.assertIn('"electron": true', (out / "BundleResources/ipadport-shim.js").read_text())

    def test_stubs_generated(self):
        root = self.tmp / "app"
        shutil.copytree(EXAMPLE, root)
        shutil.rmtree(root / "ipadport")
        out = self.tmp / "out"
        generate(root, scan(root), Options(out=out))
        stubs = (out / "BundleResources/ipc-handlers.js").read_text()
        for ch in ("notes:load", "notes:save", "notes:export"):
            self.assertIn(f'"{ch}": function', stubs)
        self.assertIn("main.js:", stubs)

    @unittest.skipUnless(NODE, "node not installed")
    def test_generated_js_is_valid(self):
        root = self.tmp / "app"
        shutil.copytree(EXAMPLE, root)
        shutil.rmtree(root / "ipadport")
        out = self.tmp / "out"
        generate(root, scan(root), Options(out=out))
        for js in (out / "BundleResources").glob("*.js"):
            subprocess.run([NODE, "--check", str(js)], check=True)

    def test_static_site_and_refuses_non_empty_out(self):
        root = write(self.tmp / "site", {"index.html": "<html><body>Hi</body></html>", "app.js": "window.open('x')"})
        out = root / "ipad-port"
        generate(root, scan(root), Options(out=out))
        self.assertTrue((out / "web" / "app.js").is_file())
        self.assertFalse((out / "web" / "ipad-port").exists())
        # Re-running into a folder ipadport made is fine; a foreign non-empty folder is not.
        generate(root, scan(root), Options(out=out))
        other = write(self.tmp / "other", {"keep.txt": "x"})
        with self.assertRaises(GenerateError):
            generate(root, scan(root), Options(out=other))

    def test_unbuilt_vite_is_refused(self):
        root = write(self.tmp / "vite", {"package.json": '{"dependencies": {"vite": "5"}}',
                                         "index.html": '<script type="module" src="/src/main.tsx"></script>'})
        with self.assertRaises(GenerateError):
            generate(root, scan(root), Options(out=self.tmp / "out"))

    def test_remote_url(self):
        root = write(self.tmp / "r", {"index.html": "<html>"})
        out = self.tmp / "out"
        generate(root, scan(root), Options(out=out, remote_url="https://example.com/app"))
        self.assertIn('"https://example.com/app"', (out / "Sources/AppConfig.swift").read_text())

    def test_swift_target(self):
        root = write(self.tmp / "mac", {"MacApp/App.swift": "import SwiftUI\nimport AppKit\n@main struct A: App {}\n",
                                        "MacAppTests/T.swift": "import XCTest"})
        out = self.tmp / "out"
        result = generate(root, scan(root), Options(out=out))
        self.assertEqual(result["strategy"], "swift")
        yml = (out / "project.yml").read_text()
        self.assertIn("MacApp", yml)
        self.assertNotIn("MacAppTests\"", yml)
        self.assertTrue((out / "PlatformCompat.swift").is_file())

    def test_plan_only_for_wpf(self):
        root = write(self.tmp / "wpf", {"App.csproj": "<UseWPF>true</UseWPF>",
                                        "Main.cs": "using Microsoft.Win32;\nRegistry.CurrentUser.OpenSubKey(\"x\");"})
        out = self.tmp / "out"
        result = generate(root, scan(root), Options(out=out))
        self.assertEqual(result["files"], ["PORTING_PLAN.md"])
        self.assertIn("Windows registry", (out / "PORTING_PLAN.md").read_text())


class AsarTests(TempDirTest):
    def test_roundtrip_and_cli_extract(self):
        src = write(self.tmp / "src", {"package.json": '{"main":"main.js","dependencies":{"electron":"1"}}',
                                       "main.js": "win.loadFile('index.html')", "index.html": "<html>", "lib/a.js": "1"})
        bundle = self.tmp / "My.app" / "Contents" / "Resources"
        bundle.mkdir(parents=True)
        asar.pack(src, bundle / "app.asar")
        with self.assertRaises(NotSourceCodeError):
            detect(self.tmp / "My.app")
        out = self.tmp / "extracted"
        self.assertEqual(main(["extract", str(self.tmp / "My.app"), "--out", str(out)]), 0)
        self.assertEqual((out / "lib" / "a.js").read_text(), "1")
        self.assertEqual(detect(out)[0].kind, "electron")

    def test_rejects_path_traversal(self):
        import struct
        header = json.dumps({"files": {"..": {"files": {"x": {"size": 1, "offset": "0"}}}}}).encode()
        pad = (4 - len(header) % 4) % 4
        payload = struct.pack("<I", len(header)) + header + b"\0" * pad
        pickle = struct.pack("<I", len(payload)) + payload
        bad = self.tmp / "bad.asar"
        bad.write_bytes(struct.pack("<II", 4, len(pickle)) + pickle + b"x")
        with self.assertRaises(asar.AsarError):
            asar.extract(bad, self.tmp / "o")


class CliTests(TempDirTest):
    def test_analyze_and_fail_on(self):
        out = self.tmp / "r.md"
        self.assertEqual(main(["analyze", str(EXAMPLE), "-o", str(out)]), 0)
        self.assertIn("Porting plan", out.read_text())
        self.assertEqual(main(["analyze", str(EXAMPLE), "--format", "json", "--fail-on", "major"]), 3)

    def test_binary_exit_code(self):
        exe = self.tmp / "a.exe"
        exe.write_bytes(b"MZ")
        self.assertEqual(main(["analyze", str(exe)]), 2)


@unittest.skipUnless(NODE, "node not installed")
class BrowserTests(TempDirTest):
    """Runs the generated JS layer of the Electron example in Chromium with a mock native bridge."""

    def test_example_runs(self):
        check = subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True)
        if check.returncode != 0:
            self.skipTest("playwright not installed")
        out = self.tmp / "out"
        generate(EXAMPLE, scan(EXAMPLE), Options(out=out))
        proc = subprocess.run([NODE, str(ROOT / "tests" / "browser" / "run.js"), str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("FAIL", proc.stdout)


if __name__ == "__main__":
    unittest.main()
