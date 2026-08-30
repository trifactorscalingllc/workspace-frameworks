#!/usr/bin/env python3
"""Check that every outcome claimed here is backed by a measurement of its start.

    python3 check_bpo.py [--path DIR] [--stale-days 14] [--json]

Reports, never blocks: the exit code is always 0. A gate that blocks gets
disabled, and some of these are judgement calls a person should overrule.

Stdlib only — a delivery workspace should open instantly, with no venv.

What it cannot do: judge whether your work caused the change. It verifies the
arithmetic of the claim — that a before and an after exist, measure the same
thing in the same unit, and sit on the right side of the work. Causation is
yours to argue in `confounders`, honestly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

BASELINE_ID = re.compile(r"\bB\d{3,}\b")
WORK_ID = re.compile(r"\bW\d{3,}\b")
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")

TODAY = dt.date.today()


def frontmatter(text: str) -> tuple[dict, str]:
    """Parse a leading --- block. Values stay strings; lists are bracket-split."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[3:end].splitlines():
        if line.strip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        # Strip a trailing inline comment, but not a '#' inside a quoted value.
        value = value.split("  #", 1)[0].strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, text[end + 4:]


def as_date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def norm(value: str) -> str:
    """Loose comparison for metric/unit: case and spacing must not matter."""
    return re.sub(r"\s+", " ", str(value).strip().lower())


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


def load_baselines(root: Path, rep: Report) -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = root / "baseline"
    if not d.is_dir():
        rep.add("layout", "baseline/", "no baseline/ directory — is this a BPO workspace?")
        return out

    for path in sorted(d.glob("*.md")):
        rel = f"baseline/{path.name}"
        meta, _ = frontmatter(path.read_text(encoding="utf-8"))
        bid = str(meta.get("id", "")).strip()
        if not bid:
            rep.add("R1", rel, "no `id` — nothing can cite this baseline")
            continue
        if bid in out:
            rep.add("R1", rel, f"duplicate id {bid} (also {out[bid]['file']})")
            continue
        for field in ("metric", "value", "unit", "measured", "source"):
            if not str(meta.get(field, "")).strip():
                rep.add("R1", rel, f"{bid} has no `{field}`")
        measured = as_date(meta.get("measured", ""))
        if meta.get("measured") and not measured:
            rep.add("R1", rel, f"{bid} `measured` is not an ISO date (YYYY-MM-DD)")
        if str(meta.get("value", "")).strip().lower() == "unknown":
            rep.add("R1", rel,
                    f"{bid} has no recorded starting value — you may do the work, but you "
                    f"cannot later claim a change in this metric", severity="warning")
        out[bid] = {"file": rel, "meta": meta, "measured": measured}
    if not out:
        rep.add("layout", "baseline/", "no baselines recorded yet", severity="warning")
    return out


def load_work(root: Path, rep: Report) -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = root / "work"
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.md")):
        rel = f"work/{path.name}"
        meta, _ = frontmatter(path.read_text(encoding="utf-8"))
        wid = str(meta.get("id", "")).strip()
        if not wid:
            rep.add("R7", rel, "no `id` — an outcome cannot credit this work")
            continue
        started = as_date(meta.get("started", ""))
        if not started:
            rep.add("R7", rel,
                    f"{wid} has no valid `started` date — without it, a baseline cannot be "
                    f"shown to predate the work")
        out[wid] = {"file": rel, "meta": meta, "started": started,
                    "completed": as_date(meta.get("completed", ""))}
    return out


def check_proofs(root: Path, baselines: dict, work: dict, stale_days: int,
                 rep: Report) -> set[str]:
    used: set[str] = set()
    d = root / "proof"
    if not d.is_dir():
        rep.add("layout", "proof/", "no proof/ directory", severity="warning")
        return used

    for path in sorted(d.glob("*.md")):
        rel = f"proof/{path.name}"
        meta, _ = frontmatter(path.read_text(encoding="utf-8"))
        if not meta:
            rep.add("R2", rel, "no frontmatter — needs outcome/baseline/value/unit/measured/"
                               "cites/confounders")
            continue

        bid = str(meta.get("baseline", "")).strip()
        if not bid:
            rep.add("R2", rel,
                    "cites no baseline — an outcome with no measured starting point is a "
                    "claim, not a result")
            base = None
        elif bid not in baselines:
            rep.add("R2", rel, f"cites {bid}, which is not in baseline/")
            base = None
        else:
            used.add(bid)
            base = baselines[bid]

        # R3 — the goalpost check. Redefining the metric or the unit between the
        # two readings makes the comparison meaningless while still looking fine.
        if base:
            bmeta = base["meta"]
            for field in ("metric", "unit"):
                before, after = norm(bmeta.get(field, "")), norm(meta.get(field, ""))
                if field == "metric" and not after:
                    # A proof may inherit the metric name from its baseline.
                    continue
                if before and after and before != after:
                    rep.add("R3", rel,
                            f"{field} changed between {bid} and this proof "
                            f"({bmeta.get(field)!r} -> {meta.get(field)!r}) — that is a "
                            f"different measurement, not a result")

        post = as_date(meta.get("measured", ""))
        if not post:
            rep.add("R2", rel, "no valid `measured` date for the post-measurement")

        cites = meta.get("cites") or []
        if isinstance(cites, str):
            cites = WORK_ID.findall(cites)
        if not cites:
            rep.add("R2", rel, "credits no work items", severity="warning")
        for wid in cites:
            if wid not in work:
                rep.add("R2", rel, f"credits {wid}, which is not in work/")

        # R4 — the contamination check. A baseline taken after the work began is
        # a mid-flight reading; comparing against it understates or invents change.
        if base and base["measured"]:
            contaminated = str(base["meta"].get("contaminated", "")).strip().lower() == "true"
            for wid in cites:
                started = work.get(wid, {}).get("started")
                if started and base["measured"] > started and not contaminated:
                    rep.add("R4", rel,
                            f"baseline {bid} was measured {base['measured']} but {wid} started "
                            f"{started} — that is a mid-flight reading, not a baseline. Mark it "
                            f"contaminated: true or re-scope the claim")
                if started and post and post < started:
                    rep.add("R5", rel,
                            f"post-measurement {post} predates {wid} starting {started}")

        # R5 — freshness. A result measured long ago is not evidence of today.
        if post:
            age = (TODAY - post).days
            if age > stale_days:
                rep.add("R5", rel,
                        f"post-measurement is {age} days old (limit {stale_days}) — say when it "
                        f"was taken, or re-measure before reporting it", severity="warning")

        # R6 — confounders. Required, because the honest version of an outcome
        # always has some, and a report with none reads as a sales document.
        if not str(meta.get("confounders", "")).strip():
            rep.add("R6", rel,
                    "no `confounders` — name what else could explain this change, or say "
                    "'none identified' and why")
    return used


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=".", help="workspace root (default: cwd)")
    ap.add_argument("--stale-days", type=int, default=14,
                    help="flag a post-measurement older than this (default: 14)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    rep = Report()

    baselines = load_baselines(root, rep)
    work = load_work(root, rep)
    used = check_proofs(root, baselines, work, args.stale_days, rep)

    # R8 — measured but never claimed. Usually unfinished reporting.
    for bid, base in sorted(baselines.items()):
        if bid not in used:
            rep.add("R8", base["file"],
                    f"{bid} was measured but no proof cites it", severity="warning")

    if args.json:
        print(json.dumps({"root": str(root), "baselines": len(baselines),
                          "work": len(work), "claimed": len(used),
                          "items": rep.items}, indent=2))
        return 0

    print(f"\nBPO check — {root.name}")
    print(f"  {len(baselines)} baseline(s), {len(work)} work item(s), {len(used)} claimed\n")
    if not rep.items:
        print("  no issues found.")
    else:
        for item in rep.items:
            mark = "!" if item["severity"] == "error" else "-"
            print(f"  {mark} [{item['rule']}] {item['where']}")
            print(f"      {item['message']}")
    print(f"\n{rep.errors} error(s), {rep.warnings} warning(s) — reported, not blocking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
