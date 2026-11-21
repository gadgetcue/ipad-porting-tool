"""File walking helpers shared by the detector and the scanner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "Pods", "Carthage", ".build", "DerivedData",
    "build", "dist", "out", ".next", ".nuxt", ".svelte-kit", ".dart_tool", ".gradle", "bin", "obj",
    ".venv", "venv", "__pycache__", "target", ".idea", ".vscode", "vendor", "coverage", "ipad-port",
    ".expo", "release", "releases",
}
MAX_FILE_BYTES = 2_000_000


def iter_files(root: Path, include_dirs: bool = False, skip_dirs: set | None = None) -> Iterator[Path]:
    """Yield source files under root, skipping dependency and build folders."""
    skip = SKIP_DIRS if skip_dirs is None else skip_dirs
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in sorted(dirnames):
            if d in skip or (d.startswith(".") and d not in (".github",)):
                continue
            if d.endswith(".xcodeproj") or d.endswith(".xcworkspace"):
                if include_dirs:
                    yield Path(dirpath) / d
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            yield Path(dirpath) / f


def read_text(path: Path, limit: int | None = None) -> str:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit) if limit else fh.read()
    except OSError:
        return ""
