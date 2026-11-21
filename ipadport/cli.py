"""Command-line interface: ipadport analyze | port | extract | rules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .asar import AsarError, extract
from .detect import NotSourceCodeError, find_asar
from .generate import GenerateError, Options, generate
from .report import to_json, to_markdown, to_text
from .rules import RULES, SEVERITIES
from .scan import scan


def _cmd_analyze(args) -> int:
    report = scan(Path(args.path))
    fmt = args.format
    if fmt == "auto":
        fmt = "markdown" if args.output and str(args.output).endswith(".md") else (
            "json" if args.output and str(args.output).endswith(".json") else "text")
    text = {"text": to_text, "markdown": to_markdown, "json": to_json}[fmt](report)
    if args.output:
        Path(args.output).write_text(text)
        print(f"Wrote {args.output}")
    else:
        sys.stdout.write(text)
    if args.fail_on:
        order = list(SEVERITIES)
        limit = order.index(args.fail_on)
        if any(order.index(f.rule.severity) <= limit for f in report.findings):
            return 3
    return 0


def _cmd_port(args) -> int:
    root = Path(args.path)
    out = Path(args.out) if args.out else root / "ipad-port"
    report = scan(root)
    opts = Options(out=out, name=args.name, bundle_id=args.bundle_id, team_id=args.team_id or "",
                   web_root=Path(args.web_root) if args.web_root else None, entry=args.entry,
                   remote_url=args.remote_url, viewport=args.viewport, content_mode=args.content_mode,
                   edge_to_edge=args.edge_to_edge, inspectable=not args.no_inspector,
                   allow_unbuilt=args.allow_unbuilt, force=args.force, deployment_target=args.ios)
    result = generate(root, report, opts)
    print(result["message"])
    print(f"Output: {result['out']}")
    for f in result.get("files", []):
        print(f"  + {f}")
    for w in result.get("warnings", []):
        print(f"  ! {w}")
    print(f"Portability score: {report.score()}/100. {report.verdict()}")
    if result["strategy"] in ("web-wrapper", "swift"):
        print("\nNext, on a Mac with Xcode:\n  brew install xcodegen\n"
              f"  cd \"{result['out']}\" && xcodegen generate && open *.xcodeproj")
    print("See PORTING_PLAN.md in the output folder for everything that needs attention.")
    return 0


def _cmd_extract(args) -> int:
    src = Path(args.path)
    archive = src if src.suffix == ".asar" and src.is_file() else find_asar(src)
    if archive is None:
        print(f"No app.asar found in {src}. Only Electron apps ship their source this way; other compiled "
              "apps cannot be converted.", file=sys.stderr)
        return 2
    count = extract(archive, Path(args.out))
    print(f"Extracted {count} files from {archive} to {args.out}")
    print("Only port apps you own or have permission to modify. Next:  ipadport port " + str(args.out))
    return 0


def _cmd_rules(args) -> int:
    for rule in RULES:
        flag = " (auto-handled)" if rule.shimmed else ""
        print(f"{rule.severity:8} {rule.id:28} {rule.title}{flag}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ipadport",
                                description="Port Mac and Windows app source code to adaptive iPad and iPhone apps.")
    p.add_argument("--version", action="version", version=f"ipadport {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Detect the project type and list everything that needs attention on iOS.")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--format", choices=["auto", "text", "markdown", "json"], default="auto")
    a.add_argument("-o", "--output", help="Write the report to a file (.md / .json picks the format).")
    a.add_argument("--fail-on", choices=list(SEVERITIES), help="Exit with code 3 if an issue this severe is found (CI).")
    a.set_defaults(func=_cmd_analyze)

    g = sub.add_parser("port", help="Generate the iPad/iPhone project (or a porting plan).")
    g.add_argument("path", nargs="?", default=".")
    g.add_argument("-o", "--out", help="Output folder (default: <path>/ipad-port).")
    g.add_argument("--name", help="App name (default: from package.json or the folder name).")
    g.add_argument("--bundle-id", help="Bundle identifier (default: com.example.<name>).")
    g.add_argument("--team-id", help="Apple developer team ID for signing.")
    g.add_argument("--web-root", help="Folder with the built web app (contains index.html).")
    g.add_argument("--entry", help="Entry HTML file inside the web root (default: index.html).")
    g.add_argument("--remote-url", help="Wrap a hosted web app URL instead of bundling files.")
    g.add_argument("--viewport", choices=["device", "desktop", "keep", "force"], default="device",
                   help="device: add a responsive viewport if the page has none (default); desktop: 1024px wide "
                        "layout; keep: never touch it; force: always use the responsive viewport.")
    g.add_argument("--content-mode", choices=["recommended", "mobile", "desktop"], default="recommended",
                   help="Which layout to request from websites (affects user agent).")
    g.add_argument("--edge-to-edge", action="store_true", help="Draw under the status bar and home indicator.")
    g.add_argument("--no-inspector", action="store_true", help="Disable Safari Web Inspector in the app.")
    g.add_argument("--allow-unbuilt", action="store_true", help="Skip the check for an un-built bundler entry.")
    g.add_argument("--ios", default="16.0", help="Minimum iOS / iPadOS version (default 16.0).")
    g.add_argument("--force", action="store_true", help="Overwrite a non-empty output folder.")
    g.set_defaults(func=_cmd_port)

    e = sub.add_parser("extract", help="Recover the JavaScript source of an installed Electron app (.app or folder).")
    e.add_argument("path")
    e.add_argument("-o", "--out", required=True)
    e.set_defaults(func=_cmd_extract)

    r = sub.add_parser("rules", help="List every compatibility rule.")
    r.set_defaults(func=_cmd_rules)
    return p


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotSourceCodeError as exc:
        print(f"ipadport: {exc}", file=sys.stderr)
        return 2
    except (GenerateError, AsarError, FileNotFoundError) as exc:
        print(f"ipadport: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
