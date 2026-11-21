"""Read and write Electron .asar archives (pure Python, no Node needed).

Format: a Chromium "Pickle" header followed by the file data.

    uint32  4                   (size of the next field)
    uint32  header_pickle_size
    uint32  header_payload_size
    uint32  json_length
    bytes   json  (+ padding to 4 bytes)
    ...     file contents; entry offsets are relative to 8 + header_pickle_size
"""

from __future__ import annotations

import json
import os
import shutil
import struct
from pathlib import Path


class AsarError(Exception):
    pass


def read_header(archive: Path) -> tuple[dict, int]:
    with open(archive, "rb") as fh:
        prefix = fh.read(16)
        if len(prefix) < 16:
            raise AsarError("File is too small to be an asar archive")
        size_field, header_pickle_size, _payload, json_len = struct.unpack("<IIII", prefix)
        if size_field != 4 or json_len > header_pickle_size:
            raise AsarError("Not an asar archive (bad header)")
        raw = fh.read(json_len)
    try:
        header = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise AsarError(f"Corrupt asar header: {exc}") from exc
    return header, 8 + header_pickle_size


def _safe_join(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise AsarError(f"Refusing to extract outside the output folder: {rel}")
    return target


def extract(archive: Path, out_dir: Path) -> int:
    """Extract every file. Returns the number of files written."""
    archive = Path(archive)
    out_dir = Path(out_dir)
    header, data_offset = read_header(archive)
    unpacked_dir = Path(str(archive) + ".unpacked")
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(archive, "rb") as fh:
        def walk(node: dict, rel: str) -> None:
            nonlocal count
            for name, entry in (node.get("files") or {}).items():
                if "/" in name or "\\" in name or name in ("..", "."):
                    raise AsarError(f"Unsafe entry name: {name!r}")
                child_rel = f"{rel}/{name}" if rel else name
                target = _safe_join(out_dir, child_rel)
                if "files" in entry:
                    target.mkdir(parents=True, exist_ok=True)
                    walk(entry, child_rel)
                elif "link" in entry:
                    continue  # symlinks are skipped for safety
                elif entry.get("unpacked"):
                    src = unpacked_dir / child_rel
                    if src.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, target)
                        count += 1
                else:
                    size = int(entry.get("size", 0))
                    offset = int(entry.get("offset", 0))
                    fh.seek(data_offset + offset)
                    data = fh.read(size)
                    if len(data) != size:
                        raise AsarError(f"Truncated data for {child_rel}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    if entry.get("executable"):
                        os.chmod(target, 0o755)
                    count += 1

        walk(header, "")
    return count


def pack(src_dir: Path, archive: Path) -> None:
    """Create an asar archive from a folder (used by the tests; compatible with @electron/asar)."""
    src_dir = Path(src_dir)
    blobs: list[bytes] = []
    offset = 0

    def build(directory: Path) -> dict:
        nonlocal offset
        files = {}
        for child in sorted(directory.iterdir()):
            if child.is_dir():
                files[child.name] = build(child)
            else:
                data = child.read_bytes()
                files[child.name] = {"size": len(data), "offset": str(offset)}
                blobs.append(data)
                offset += len(data)
        return {"files": files}

    header = json.dumps(build(src_dir), separators=(",", ":")).encode("utf-8")
    padding = (4 - len(header) % 4) % 4
    payload = struct.pack("<I", len(header)) + header + b"\0" * padding
    header_pickle = struct.pack("<I", len(payload)) + payload
    with open(archive, "wb") as fh:
        fh.write(struct.pack("<II", 4, len(header_pickle)))
        fh.write(header_pickle)
        for blob in blobs:
            fh.write(blob)
