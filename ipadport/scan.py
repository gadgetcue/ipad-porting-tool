"""Scan source files for APIs that need attention on iPadOS / iOS."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .detect import Detection, detect
from .rules import RULES, Rule
from .walk import SKIP_DIRS, iter_files, read_text

WEIGHTS = {"blocker": 15, "major": 6, "minor": 1, "info": 0}
STRATEGY_CAP = {"rewrite-ui": 45}  # apps whose whole UI must be rebuilt can't score "easy"
MAX_HITS_PER_RULE = 200


@dataclass
class Finding:
    rule: Rule
    file: str
    line: int
    snippet: str

    def to_dict(self) -> dict:
        return {"rule": self.rule.id, "severity": self.rule.severity, "file": self.file, "line": self.line,
                "snippet": self.snippet, "shimmed": self.rule.shimmed}


@dataclass
class Report:
    root: str
    name: str
    detections: list
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    ipc_channels: dict = field(default_factory=dict)

    @property
    def primary(self) -> Detection | None:
        return self.detections[0] if self.detections else None

    def by_rule(self) -> dict:
        grouped: dict = {}
        for f in self.findings:
            grouped.setdefault(f.rule.id, []).append(f)
        return grouped

    def counts(self) -> dict:
        out = {"blocker": 0, "major": 0, "minor": 0, "info": 0}
        for rule_id, items in self.by_rule().items():
            out[items[0].rule.severity] += 1
        return out

    def score(self) -> int:
        """0-100 portability score. Counted per distinct issue, not per occurrence."""
        penalty = 0
        for items in self.by_rule().values():
            rule = items[0].rule
            weight = WEIGHTS[rule.severity]
            if rule.shimmed:
                weight = min(weight, 1)
            penalty += weight
        score = max(0, 100 - penalty)
        if self.primary:
            score = min(score, STRATEGY_CAP.get(self.primary.strategy, 100))
        return score

    def verdict(self) -> str:
        s = self.score()
        if s >= 85:
            return "Good candidate: should port with little or no code change."
        if s >= 60:
            return "Portable with work: a few features need changes (listed below)."
        if s >= 30:
            return "Significant work: several features have no iOS equivalent or the UI must be rebuilt."
        return "Major rewrite: most of the app depends on desktop-only capabilities."

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "root": self.root,
            "detections": [d.to_dict() for d in self.detections],
            "score": self.score(),
            "verdict": self.verdict(),
            "counts": self.counts(),
            "files_scanned": self.files_scanned,
            "ipc_channels": {k: v for k, v in self.ipc_channels.items()},
            "findings": [f.to_dict() for f in self.findings],
        }


_IPC_MAIN_RE = re.compile(r"""ipcMain\s*\.\s*(handle|on|once|handleOnce)\s*\(\s*['"`]([^'"`]+)['"`]""")
_IPC_RENDERER_RE = re.compile(r"""ipcRenderer\s*\.\s*(invoke|send|sendSync)\s*\(\s*['"`]([^'"`]+)['"`]""")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan(root: Path, name: str | None = None, detections: list | None = None) -> Report:
    from .detect import project_name

    root = Path(root)
    detections = detect(root) if detections is None else detections
    report = Report(root=str(root), name=name or project_name(root), detections=detections)
    hits_per_rule: dict = {}

    lines_cache = None
    for path in iter_files(root, skip_dirs=SKIP_DIRS | {"ipadport"}):
        suffix = path.suffix.lower()
        applicable = [r for r in RULES if suffix in r.extensions]
        if not applicable:
            continue
        text = read_text(path)
        if not text:
            continue
        report.files_scanned += 1
        rel = path.relative_to(root).as_posix()
        for rule in applicable:
            if hits_per_rule.get(rule.id, 0) >= MAX_HITS_PER_RULE:
                continue
            seen_lines = set()
            for m in rule.regex().finditer(text):
                line_no = _line_of(text, m.start())
                if line_no in seen_lines:
                    continue
                seen_lines.add(line_no)
                if lines_cache is None or lines_cache[0] is not path:
                    lines_cache = (path, text.splitlines())
                line = lines_cache[1][line_no - 1] if line_no - 1 < len(lines_cache[1]) else ""
                report.findings.append(Finding(rule, rel, line_no, line.strip()[:160]))
                hits_per_rule[rule.id] = hits_per_rule.get(rule.id, 0) + 1
                if hits_per_rule[rule.id] >= MAX_HITS_PER_RULE:
                    break
        if suffix in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"):
            for m in _IPC_MAIN_RE.finditer(text):
                entry = report.ipc_channels.setdefault(m.group(2), {"kind": m.group(1), "defined_in": [], "used_in": []})
                entry["kind"] = m.group(1)
                entry["defined_in"].append(f"{rel}:{_line_of(text, m.start())}")
                entry.setdefault("source", _extract_handler(text, m.end()))
            for m in _IPC_RENDERER_RE.finditer(text):
                entry = report.ipc_channels.setdefault(m.group(2), {"kind": None, "defined_in": [], "used_in": []})
                entry["used_in"].append(f"{rel}:{_line_of(text, m.start())}")

    severity_order = {"blocker": 0, "major": 1, "minor": 2, "info": 3}
    report.findings.sort(key=lambda f: (severity_order[f.rule.severity], f.rule.id, f.file, f.line))
    return report


def _extract_handler(text: str, start: int, max_chars: int = 1200) -> str:
    """Return the source of the handler that follows an ipcMain.handle('x', ...) call, best effort."""
    depth = 1  # we're inside the call's opening parenthesis
    i = start
    in_str = None
    while i < len(text) and i - start < max_chars * 4:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "'\"`":
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = text[start:i].lstrip(", \n\t")
    if len(body) > max_chars:
        body = body[:max_chars] + "\n/* ...truncated... */"
    return body
