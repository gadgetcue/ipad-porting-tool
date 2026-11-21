"""Work out what kind of desktop app a folder contains and how it should be ported."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .walk import iter_files, read_text

# Strategies
WEB_WRAPPER = "web-wrapper"        # generate a WKWebView iPad/iPhone app around the web content
SWIFT_MULTIPLATFORM = "swift"      # add an iOS target to the existing Swift sources + compat shim
NATIVE_TOOLCHAIN = "toolchain"     # the framework already supports iOS; follow its steps
REWRITE_UI = "rewrite-ui"          # keep the logic, write a new touch UI

BINARY_SUFFIXES = {".exe", ".msi", ".dmg", ".pkg", ".msix", ".appx", ".dll", ".dylib", ".so", ".ipa"}


@dataclass
class Detection:
    kind: str
    label: str
    strategy: str
    confidence: float
    evidence: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "strategy": self.strategy,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "details": self.details,
        }


class NotSourceCodeError(Exception):
    """Raised when the input is a compiled app rather than a source project."""


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _deps(pkg: dict) -> dict:
    out = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        out.update(pkg.get(key) or {})
    return out


def check_is_source(root: Path) -> None:
    """Refuse compiled binaries with an explanation (an Electron .app bundle is the exception)."""
    if root.is_file():
        if root.suffix.lower() in BINARY_SUFFIXES or root.suffix.lower() == ".app":
            raise NotSourceCodeError(
                f"{root.name} is a compiled program. iOS cannot run Mac or Windows binaries, so ipadport "
                "works from source code. If this is an Electron app, extract it with "
                "`ipadport extract <app> --out <dir>` and port the extracted source."
            )
        if root.suffix.lower() == ".asar":
            raise NotSourceCodeError(
                f"{root.name} is an Electron archive. Run `ipadport extract {root} --out <dir>` first."
            )
        raise NotSourceCodeError(f"{root} is a file. Point ipadport at the app's project folder.")
    if root.suffix.lower() == ".app" and (root / "Contents").is_dir():
        if find_asar(root):
            raise NotSourceCodeError(
                f"{root.name} is a compiled Electron app. Run `ipadport extract \"{root}\" --out <dir>` "
                "to recover its JavaScript source, then port that folder."
            )
        raise NotSourceCodeError(
            f"{root.name} is a compiled Mac app. Compiled apps cannot be converted to iOS; you need the "
            "app's source code (or ask the developer whether an iPad version exists)."
        )


def find_asar(root: Path) -> Path | None:
    for candidate in (
        root / "Contents" / "Resources" / "app.asar",   # macOS .app
        root / "resources" / "app.asar",                 # Windows install folder
        root / "app.asar",
    ):
        if candidate.is_file():
            return candidate
    return None


def detect(root: Path) -> list[Detection]:
    """Return detections sorted by confidence (best first)."""
    root = Path(root)
    check_is_source(root)
    found: list[Detection] = []

    pkg_path = root / "package.json"
    pkg = _load_json(pkg_path) if pkg_path.is_file() else {}
    deps = _deps(pkg)

    # --- JavaScript families -------------------------------------------------------------
    if "electron" in deps:
        found.append(Detection("electron", "Electron app", WEB_WRAPPER, 0.95,
                               ["package.json depends on electron"], {"main": pkg.get("main", "main.js")}))
    tauri_conf = next((p for p in (root / "src-tauri" / "tauri.conf.json", root / "src-tauri" / "tauri.conf.json5")
                       if p.is_file()), None)
    if tauri_conf:
        found.append(Detection("tauri", "Tauri app", NATIVE_TOOLCHAIN, 0.95, [str(tauri_conf.relative_to(root))]))
    if "react-native" in deps or "react-native-macos" in deps or "react-native-windows" in deps:
        found.append(Detection("react-native", "React Native app", NATIVE_TOOLCHAIN, 0.9,
                               ["package.json depends on react-native"]))
    if pkg and not found:
        web_markers = [d for d in ("react", "vue", "svelte", "@angular/core", "vite", "next", "preact",
                                   "solid-js", "lit", "webpack", "parcel") if d in deps]
        if web_markers or any((root / c / "index.html").is_file() for c in ("", "public", "src", "dist", "build")):
            found.append(Detection("web", "Web app", WEB_WRAPPER, 0.8,
                                   [f"package.json uses {', '.join(web_markers) or 'web tooling'}"]))
    if not pkg and (root / "index.html").is_file():
        found.append(Detection("web", "Static web app", WEB_WRAPPER, 0.75, ["index.html at project root"]))

    # --- Flutter -------------------------------------------------------------------------
    pubspec = root / "pubspec.yaml"
    if pubspec.is_file() and re.search(r"^\s*flutter\s*:", read_text(pubspec), re.M):
        found.append(Detection("flutter", "Flutter app", NATIVE_TOOLCHAIN, 0.95, ["pubspec.yaml uses flutter"],
                               {"has_ios_folder": (root / "ios").is_dir()}))

    # --- Walk source files once for the remaining kinds --------------------------------------
    counts = {"swift_appkit": 0, "swift_swiftui": 0, "swift_uikit": 0, "swift": 0, "objc": 0,
              "cs": 0, "cpp": 0, "win32": 0, "qt": 0}
    csproj_text = ""
    xcodeprojs = []
    for path in iter_files(root, include_dirs=True):
        name = path.name
        suffix = path.suffix.lower()
        if suffix == ".xcodeproj":
            xcodeprojs.append(path.relative_to(root).as_posix())
            continue
        if path.is_dir():
            continue
        if suffix == ".swift":
            counts["swift"] += 1
            text = read_text(path, limit=20000)
            if re.search(r"^\s*import\s+(AppKit|Cocoa)\b", text, re.M):
                counts["swift_appkit"] += 1
            if re.search(r"^\s*import\s+SwiftUI\b", text, re.M):
                counts["swift_swiftui"] += 1
            if re.search(r"^\s*import\s+UIKit\b", text, re.M):
                counts["swift_uikit"] += 1
        elif suffix in (".m", ".mm"):
            counts["objc"] += 1
            if "Cocoa/Cocoa.h" in read_text(path, limit=8000) or "AppKit/AppKit.h" in read_text(path, limit=8000):
                counts["swift_appkit"] += 1
        elif suffix in (".csproj", ".fsproj", ".vbproj"):
            counts["cs"] += 1
            csproj_text += read_text(path, limit=50000)
        elif suffix in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"):
            counts["cpp"] += 1
            text = read_text(path, limit=8000)
            if re.search(r"#\s*include\s*[<\"](windows|afx\w*|atl\w*)\.h", text):
                counts["win32"] += 1
            if re.search(r"#\s*include\s*<Q[A-Z]\w+>", text):
                counts["qt"] += 1
        elif suffix in (".pro", ".qml") or (name == "CMakeLists.txt" and re.search(r"find_package\s*\(\s*Qt[56]?",
                                                                                         read_text(path))):
            counts["qt"] += 1

    if counts["swift"] or counts["objc"] or xcodeprojs or (root / "Package.swift").is_file():
        if counts["swift_appkit"]:
            label, conf = "macOS app (AppKit / Cocoa)", 0.9
            if counts["swift_swiftui"]:
                label = "macOS app (SwiftUI + AppKit)"
        elif counts["swift_swiftui"]:
            label, conf = "SwiftUI app", 0.9
        else:
            label, conf = "Swift project", 0.6
        found.append(Detection("swift", label, SWIFT_MULTIPLATFORM, conf,
                               [f"{counts['swift']} Swift files, {counts['swift_appkit']} use AppKit, "
                                f"{counts['swift_swiftui']} use SwiftUI"] + [f"Xcode project {x}" for x in xcodeprojs[:3]],
                               {"appkit_files": counts["swift_appkit"], "swiftui_files": counts["swift_swiftui"],
                                "already_ios": counts["swift_uikit"] > 0 and counts["swift_appkit"] == 0}))

    if counts["cs"]:
        if re.search(r"<UseMaui>\s*true", csproj_text, re.I):
            found.append(Detection("dotnet-maui", ".NET MAUI app", NATIVE_TOOLCHAIN, 0.95, ["UseMaui in project file"]))
        elif re.search(r"Avalonia", csproj_text):
            found.append(Detection("dotnet-avalonia", "Avalonia app", NATIVE_TOOLCHAIN, 0.9, ["Avalonia package reference"]))
        elif re.search(r"<UseWPF>\s*true", csproj_text, re.I):
            found.append(Detection("dotnet-wpf", "WPF app (.NET)", REWRITE_UI, 0.95, ["UseWPF in project file"]))
        elif re.search(r"<UseWindowsForms>\s*true", csproj_text, re.I):
            found.append(Detection("dotnet-winforms", "Windows Forms app (.NET)", REWRITE_UI, 0.95,
                                   ["UseWindowsForms in project file"]))
        else:
            found.append(Detection("dotnet", ".NET project", REWRITE_UI, 0.6, [f"{counts['cs']} project files"]))

    if counts["qt"]:
        found.append(Detection("qt", "Qt app", NATIVE_TOOLCHAIN, 0.85, [f"{counts['qt']} Qt files"]))
    elif counts["win32"]:
        found.append(Detection("win32", "Native Windows app (Win32/MFC, C/C++)", REWRITE_UI, 0.85,
                               [f"{counts['win32']} files include Windows headers"]))
    elif counts["cpp"] and not found:
        found.append(Detection("cpp", "C/C++ project", REWRITE_UI, 0.5, [f"{counts['cpp']} C/C++ files"]))

    found.sort(key=lambda d: d.confidence, reverse=True)
    return found


# --------------------------------------------------------------------------------------------
# Web content discovery (used by the web wrapper generator)

_LOADFILE_RE = re.compile(
    r"""loadFile\(\s*(?:path\.(?:join|resolve)\(\s*__dirname\s*,\s*)?['"`]([^'"`]+)['"`]""")
_LOADURL_FILE_RE = re.compile(r"""loadURL\(\s*[`'"]file://\$\{__dirname\}/([^`'"]+)[`'"]""")
_PRELOAD_RE = re.compile(
    r"""preload\s*:\s*(?:path\.(?:join|resolve)\(\s*__dirname\s*,\s*)?['"`]([^'"`]+)['"`]""")


def electron_entry(root: Path, main_rel: str) -> dict:
    """Find the HTML file and preload script an Electron main process loads."""
    info = {"html": None, "preload": None}
    main_path = (root / main_rel)
    if main_path.is_dir():
        main_path = main_path / "index.js"
    if not main_path.is_file():
        return info
    text = read_text(main_path)
    base = main_path.parent
    m = _LOADFILE_RE.search(text) or _LOADURL_FILE_RE.search(text)
    if m:
        candidate = (base / m.group(1)).resolve()
        if candidate.is_file():
            info["html"] = candidate
    p = _PRELOAD_RE.search(text)
    if p:
        candidate = (base / p.group(1)).resolve()
        if candidate.is_file():
            info["preload"] = candidate
    return info


def find_web_root(root: Path, kind: str, details: dict | None = None) -> tuple[Path | None, str, Path | None]:
    """Return (web_root_dir, entry_html_relative, preload_script)."""
    details = details or {}
    preload = None
    if kind == "electron":
        info = electron_entry(root, details.get("main", "main.js"))
        preload = info["preload"]
        html = info["html"]
        if html is not None:
            # A built bundle (dist/) next to the HTML wins over a dev-server HTML.
            return html.parent, html.name, preload
    tauri_conf = root / "src-tauri" / "tauri.conf.json"
    if tauri_conf.is_file():
        conf = _load_json(tauri_conf)
        build = conf.get("build", {})
        dist = build.get("frontendDist") or build.get("distDir")
        if isinstance(dist, str) and not dist.startswith("http"):
            d = (tauri_conf.parent / dist).resolve()
            if (d / "index.html").is_file():
                return d, "index.html", None
    for candidate in ("dist", "build", "out", "www", "public", "renderer", "src/renderer", "app", "src", ""):
        d = root / candidate if candidate else root
        if (d / "index.html").is_file():
            return d.resolve(), "index.html", preload
    return None, "index.html", preload


def needs_build(root: Path, web_root: Path | None) -> bool:
    """True if the HTML looks like an un-built bundler entry (e.g. Vite's /src/main.tsx)."""
    if web_root is None:
        return True
    index = web_root / "index.html"
    if not index.is_file():
        return False
    text = read_text(index)
    return bool(re.search(r"""<script[^>]+src=["']/?src/[^"']+\.(tsx?|jsx)["']""", text))


def project_name(root: Path) -> str:
    pkg = _load_json(root / "package.json") if (root / "package.json").is_file() else {}
    name = pkg.get("productName") or pkg.get("name")
    if not name:
        pubspec = root / "pubspec.yaml"
        if pubspec.is_file():
            m = re.search(r"^name:\s*(\S+)", read_text(pubspec), re.M)
            name = m.group(1) if m else None
    if not name:
        name = os.path.basename(os.path.abspath(root))
    return str(name).split("/")[-1]


def project_version(root: Path) -> str:
    pkg = _load_json(root / "package.json") if (root / "package.json").is_file() else {}
    version = str(pkg.get("version") or "1.0.0")
    m = re.match(r"^\d+(\.\d+){0,2}", version)
    return m.group(0) if m else "1.0.0"
