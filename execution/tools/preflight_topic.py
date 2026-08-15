#!/usr/bin/env python3
"""Decide whether a topic folder is safe to convert. Default answer: no.

This is the safety gate for the ingest path. It answers one question — *can this
folder be converted without breaking something that depends on it* — and it is
built to refuse. A folder at ``/Users/tfs`` is not an archive; it is usually a
live system with launchd agents pointed at it, processes running out of it, and
sometimes sixteen other folders borrowing from it.

    python execution/tools/preflight_topic.py --path /Users/tfs/slim-bot
    python execution/tools/preflight_topic.py --path /Users/tfs/tom --json

Exit codes: 0 clear, 1 blocked, 2 error. The blocks each print their remedy,
because "no" is only useful when it comes with what would make it yes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401  (import first: scrubs the billing vars)
from lib import topics  # noqa: E402

# Borrowed directories that npm/build tooling can simply recreate. A folder
# symlinking these out is untidy but recoverable; one symlinking its .env or its
# data out is not self-contained in any meaningful sense.
REGENERABLE = frozenset({"node_modules", "dist", "build", ".next", ".cache", "output"})


def _severity_for_outbound(link: dict) -> str:
    name = Path(link["link"]).name
    return "warn" if name in REGENERABLE else "block"


def check(root: Path) -> dict:
    """Run every gate. Returns findings; the caller decides the exit code."""
    findings: list[dict] = []

    def add(severity: str, code: str, summary: str, remedy: str, detail=None) -> None:
        findings.append({
            "severity": severity, "code": code, "summary": summary,
            "remedy": remedy, "detail": detail or [],
        })

    # --- Is this even one topic? ------------------------------------------
    candidates = topics.container_candidates(root)
    if len(candidates) >= 5:
        add("block", "container",
            f"{root.name} holds {len(candidates)} sub-projects — it is a container, "
            "not a topic.",
            "Run preflight against one sub-project instead.",
            candidates[:20])

    # --- Does anything depend on this folder? -----------------------------
    inbound = topics.inbound_symlinks(root)
    if inbound:
        add("block", "dependency_hub",
            f"{len(inbound)} symlink(s) elsewhere point INTO this folder. "
            "Restructuring it breaks the dependents, not this folder.",
            "Give each dependent its own copy of what it borrows, then re-run.",
            [f"{d['link']} -> {d['target']}" for d in inbound[:20]])

    # --- Does this folder depend on anything else? ------------------------
    outbound = topics.outbound_symlinks(root)
    blocking_out = [l for l in outbound if _severity_for_outbound(l) == "block"]
    warning_out = [l for l in outbound if _severity_for_outbound(l) == "warn"]
    if blocking_out:
        add("block", "not_self_contained",
            f"{len(blocking_out)} symlink(s) take config or data from outside this "
            "folder, so it cannot stand on its own.",
            "Replace the borrowed file with a real one before converting.",
            [f"{d['link']} -> {d['target']}" for d in blocking_out[:20]])
    if warning_out:
        add("warn", "borrowed_build_dirs",
            f"{len(warning_out)} regenerable director(ies) are symlinked in from "
            "elsewhere.",
            "Recreate them locally (npm install) in the new workspace; do not copy "
            "the symlink.",
            [f"{d['link']} -> {d['target']}" for d in warning_out[:20]])

    # --- Is anything using it right now? ----------------------------------
    procs = topics.running_processes(root)
    if procs:
        add("block", "live_processes",
            f"{len(procs)} process(es) are running out of this folder. Moving files "
            "under a running process is the corruption case.",
            "Stop them first (launchctl bootout gui/$UID/<label>), then re-run.",
            [f"pid {p['pid']}: {p['command'][:120]}" for p in procs[:15]])

    # --- Is it wired into launchd? ----------------------------------------
    refs = topics.launchd_refs(root)
    if refs:
        add("warn", "launchd_wiring",
            f"{len(refs)} LaunchAgent(s) reference this path. Each is cutover work.",
            "Plan to rewrite or bootout every label listed before retiring the folder.",
            [r["label"] for r in refs[:30]])

    # --- Is it backed up off this disk? -----------------------------------
    git = topics.git_info(root)
    backed_up = bool(git["remote"]) or topics.in_fleet_backup(root)
    if not backed_up:
        add("block", "no_offdisk_backup",
            "No git remote and not in fleet-backup.sh — this folder exists only on "
            "this disk, and this Mac has no Time Machine or APFS snapshots.",
            "Give it a private remote and add it to fleet-backup.sh (Phase 0).",
            [f"git repo: {git['repo']}, remote: {git['remote']}, "
             f"uncommitted: {git['dirty']}"])
    elif git["repo"] and git["dirty"]:
        add("warn", "uncommitted_work",
            f"{git['dirty']} uncommitted file(s) — these are not in the remote yet.",
            "Review and commit before converting, so rollback is real.")

    # --- What does Claude believe about this path? ------------------------
    cstate = topics.claude_state(root)
    if cstate["project_dir"] or cstate["in_claude_json"] or cstate["instruction_files"]:
        bits = []
        if cstate["sessions"]:
            bits.append(f"{cstate['sessions']} session transcript(s)")
        if cstate["in_claude_json"]:
            bits.append("a .claude.json entry")
        if cstate["instruction_files"]:
            bits.append("+".join(cstate["instruction_files"]))
        add("warn", "claude_state",
            "Claude state is keyed to this absolute path: " + ", ".join(bits) + ".",
            "On retirement leave a stub CLAUDE.md pointing at the new workspace. "
            "A stale one is worse than none — it instructs the next agent to work "
            "against a layout that no longer exists.")

    blocks = [f for f in findings if f["severity"] == "block"]
    return {
        "ok": not blocks,
        "path": str(root),
        "verdict": "clear" if not blocks else "blocked",
        "blocks": len(blocks),
        "warnings": len(findings) - len(blocks),
        "findings": findings,
        "git": git,
        "launchd_labels": [r["label"] for r in refs],
        "claude_state": cstate,
    }


def render(report: dict) -> str:
    """Human-readable summary. The model reads this too, so it states remedies."""
    lines = [f"preflight: {report['path']}", ""]
    if report["ok"] and not report["findings"]:
        lines.append("CLEAR — no blocks, no warnings.")
        return "\n".join(lines)

    for finding in report["findings"]:
        mark = "BLOCK" if finding["severity"] == "block" else " WARN"
        lines.append(f"[{mark}] {finding['code']}: {finding['summary']}")
        lines.append(f"        remedy: {finding['remedy']}")
        for item in finding["detail"][:8]:
            lines.append(f"          - {item}")
        extra = len(finding["detail"]) - 8
        if extra > 0:
            lines.append(f"          … and {extra} more")
        lines.append("")

    if report["ok"]:
        lines.append(f"CLEAR to convert, with {report['warnings']} warning(s) to carry.")
    else:
        lines.append(
            f"BLOCKED — {report['blocks']} blocking issue(s). This folder must not be "
            "restructured until they are resolved."
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", required=True, help="topic folder to check")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        root = topics.resolve_topic(args.path)
        report = check(root)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
