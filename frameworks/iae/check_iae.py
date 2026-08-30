#!/usr/bin/env python3
"""Check that this IAE workspace's reasoning is traceable to its evidence.

    python3 check_iae.py [--path DIR] [--similarity 0.45] [--json]

Reports, never blocks: the exit code is always 0. Two reasons. The similarity
rule is a heuristic, and a false positive must never stop real work. And a gate
that blocks gets disabled, which buys nothing.

Stdlib only, deliberately — a research workspace should open instantly, with no
venv and no install step.

What it cannot do: prove you understood anything. It proves your conclusions
trace to sources you actually recorded, and that your analysis is not a copy of
the text it cites. Judgment stays yours.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

TIERS = {"primary-data", "peer-reviewed", "official-doc", "journalism",
         "vendor-claim", "forum", "unknown"}
CONFIDENCES = {"high", "medium", "low"}
CONFLICT_KINDS = {"empirical", "definitional"}

SOURCE_ID = re.compile(r"\bS\d{3,}\b")
# A fenced block or inline code can legitimately contain something that looks
# like a citation; strip those before scanning so examples do not become errors.
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def frontmatter(text: str) -> tuple[dict, str]:
    """Parse a leading --- block. Values stay strings; lists are bracket-split."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[3:end].splitlines():
        line = line.split("#", 1)[0].strip() if not line.strip().startswith("#") else ""
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, text[end + 4:]


def strip_code(text: str) -> str:
    return INLINE_CODE.sub(" ", FENCE.sub(" ", text))


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()


def quoted_text(body: str) -> str:
    """The blockquoted and claim prose of a source — what analysis must not copy."""
    return " ".join(
        line.lstrip("> ").strip()
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, rule: str, where: str, message: str, severity: str = "error") -> None:
        self.items.append({"rule": rule, "where": where, "message": message,
                           "severity": severity})

    @property
    def errors(self) -> int:
        return sum(1 for i in self.items if i["severity"] == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.items if i["severity"] == "warning")


def load_sources(root: Path, rep: Report) -> dict[str, dict]:
    sources: dict[str, dict] = {}
    src_dir = root / "sources"
    if not src_dir.is_dir():
        rep.add("layout", "sources/", "no sources/ directory — is this an IAE workspace?")
        return sources

    for path in sorted(src_dir.glob("*.md")):
        if path.name.upper() == "COVERAGE.MD":
            continue
        rel = f"sources/{path.name}"
        meta, body = frontmatter(path.read_text(encoding="utf-8"))
        sid = str(meta.get("id", "")).strip()

        if not sid:
            rep.add("R1", rel, "no `id` in frontmatter — nothing can cite this source")
            continue
        if sid in sources:
            rep.add("R1", rel, f"duplicate id {sid} (also {sources[sid]['file']})")
            continue
        if not str(meta.get("locator", "")).strip():
            rep.add("R1", rel, f"{sid} has no `locator` — a claim nobody can open is not evidence")
        if not str(meta.get("accessed", "")).strip():
            rep.add("R1", rel, f"{sid} has no `accessed` date")
        tier = str(meta.get("tier", "")).strip()
        if tier not in TIERS:
            rep.add("R1", rel,
                    f"{sid} tier {tier or '(missing)'!r} is not one of {sorted(TIERS)}")
        sources[sid] = {"file": rel, "meta": meta, "body": body,
                        "quoted": quoted_text(body)}
    if not sources:
        rep.add("layout", "sources/", "no sources recorded yet", severity="warning")
    return sources


def check_citations(root: Path, sources: dict, rep: Report) -> set[str]:
    """Every [Sxxx] must resolve. Returns the set of ids actually cited."""
    cited: set[str] = set()
    for sub in ("analysis", "findings"):
        d = root / sub
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            rel = f"{sub}/{path.name}"
            text = strip_code(path.read_text(encoding="utf-8"))
            for sid in SOURCE_ID.findall(text):
                cited.add(sid)
                if sid not in sources:
                    rep.add("R2", rel,
                            f"cites {sid}, which is not in sources/ — a dangling citation "
                            f"reads as evidence and is not")
    return cited


def check_findings(root: Path, sources: dict, rep: Report) -> None:
    d = root / "findings"
    if not d.is_dir():
        return
    for path in sorted(d.glob("*.md")):
        rel = f"findings/{path.name}"
        meta, body = frontmatter(path.read_text(encoding="utf-8"))
        if not meta:
            rep.add("R3", rel, "no frontmatter — needs finding/cites/confidence/falsifier")
            continue

        cites = meta.get("cites") or []
        if isinstance(cites, str):
            cites = SOURCE_ID.findall(cites)
        if not cites:
            rep.add("R3", rel, "cites nothing — a conclusion with no evidence is an opinion")
        for sid in cites:
            if sid not in sources:
                rep.add("R2", rel, f"cites {sid}, which is not in sources/")

        conf = str(meta.get("confidence", "")).strip().lower()
        if conf not in CONFIDENCES:
            rep.add("R3", rel,
                    f"confidence {conf or '(missing)'!r} is not one of {sorted(CONFIDENCES)}")
        if not str(meta.get("falsifier", "")).strip():
            rep.add("R3", rel,
                    "no `falsifier` — say what evidence would change your mind, or this is "
                    "not a finding")


def check_conflicts(root: Path, rep: Report) -> None:
    """A conflict must be classified. An unclassified one is just a shrug."""
    d = root / "analysis"
    if not d.is_dir():
        return
    pattern = re.compile(r"^\s*(?:#{1,6}\s*)?conflict\b(.*)$", re.I)
    for path in sorted(d.glob("*.md")):
        rel = f"analysis/{path.name}"
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, 1):
            m = pattern.match(line)
            if not m:
                continue
            window = " ".join(lines[n - 1:n + 4]).lower()
            if not any(k in window for k in CONFLICT_KINDS):
                rep.add("R4", f"{rel}:{n}",
                        "conflict is not classified empirical or definitional — say which, "
                        "because only one of them is settleable with data")


def check_unused(sources: dict, cited: set[str], rep: Report) -> None:
    for sid, src in sorted(sources.items()):
        if sid not in cited:
            rep.add("R5", src["file"],
                    f"{sid} is recorded but never cited — unfinished reading, or it belongs "
                    f"in the coverage note", severity="warning")


def check_restating(root: Path, sources: dict, threshold: float, rep: Report) -> None:
    """Analysis that is a copy of the text it cites is not analysis.

    Catches copy-shaped restating only. A loose paraphrase that says nothing new
    scores about as low as real analysis, so a clean result here is not evidence
    of understanding — only of not having copied.
    """
    d = root / "analysis"
    if not d.is_dir():
        return
    for path in sorted(d.glob("*.md")):
        rel = f"analysis/{path.name}"
        raw = path.read_text(encoding="utf-8")
        prose = strip_code(raw)
        cites = set(SOURCE_ID.findall(prose))
        if not cites:
            continue
        # Compare paragraph by paragraph: one copied paragraph inside a long
        # file would be diluted to nothing by a whole-file comparison.
        for para in [p.strip() for p in re.split(r"\n\s*\n", prose) if p.strip()]:
            pw = words(para)
            if len(pw) < 25:
                continue
            for sid in cites:
                src = sources.get(sid)
                if not src or not src["quoted"]:
                    continue
                ratio = difflib.SequenceMatcher(None, words(src["quoted"]), pw).ratio()
                if ratio >= threshold:
                    rep.add("R6", rel,
                            f"a paragraph is {ratio:.0%} similar to {sid} — restating the "
                            f"source, not explaining it", severity="warning")
                    break


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=".", help="workspace root (default: cwd)")
    ap.add_argument("--similarity", type=float, default=0.45,
                    help="restating threshold, 0-1 (default: 0.45)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    rep = Report()

    sources = load_sources(root, rep)
    cited = check_citations(root, sources, rep)
    check_findings(root, sources, rep)
    check_conflicts(root, rep)
    check_unused(sources, cited, rep)
    check_restating(root, sources, args.similarity, rep)

    if not (root / "sources" / "COVERAGE.md").exists() and sources:
        rep.add("R7", "sources/COVERAGE.md",
                "no coverage note — without it, 'no source says X' cannot be told apart "
                "from 'X is absent from where I looked'", severity="warning")

    if args.json:
        print(json.dumps({"root": str(root), "sources": len(sources),
                          "cited": len(cited), "items": rep.items}, indent=2))
        return 0

    print(f"\nIAE check — {root.name}")
    print(f"  {len(sources)} source(s), {len(cited)} cited\n")
    if not rep.items:
        print("  no issues found.")
    else:
        for item in rep.items:
            mark = "!" if item["severity"] == "error" else "-"
            print(f"  {mark} [{item['rule']}] {item['where']}")
            print(f"      {item['message']}")
    print(f"\n{rep.errors} error(s), {rep.warnings} warning(s) — reported, not blocking.")
    # Always 0: see the module docstring.
    return 0


if __name__ == "__main__":
    sys.exit(main())
