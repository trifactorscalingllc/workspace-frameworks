#!/usr/bin/env python3
"""Read-only inventory of a topic folder, scrubbed of credentials.

Layer 3 for the ingest path: it turns a sprawling folder into a structured,
capped, secret-free JSON summary that the orchestration layer can reason about
without ever seeing a live key.

    python execution/tools/scan_topic.py --path /Users/tfs/slim-bot
    python execution/tools/scan_topic.py --path /Users/tfs/arnie --max-files 800

**Strictly read-only against the source.** Files are opened ``'r'`` only; there
is no code path here that writes, moves or deletes anything under the scanned
root. Output goes to ``.tmp/ingest/<topic>/inventory.json``.

Secrets get two independent defences, because one is not enough:

1. A skiplist of credential-bearing filenames whose *contents* are never read.
   Matched after resolving symlinks — ``tom-agents/*/.env`` is a symlink to
   ``tom/.env`` and its ~37 credentials, so matching the link name alone would
   miss it. Variable *names* are still recorded: knowing a topic needs
   ``GHL_API_KEY`` is what determines its tool grant, and the name carries that
   without the value.
2. A redaction pass over everything actually read, for the key hardcoded in
   ``index.mjs`` that no skiplist can anticipate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  (import first: scrubs the billing vars)
from lib import topics  # noqa: E402

DEFAULT_MAX_FILES = 4000
DEFAULT_MAX_FILE_BYTES = 200_000
DEFAULT_MAX_TOTAL_BYTES = 4_000_000
EXCERPT_LINES = 60

ENTRYPOINT_STEMS = frozenset({"index", "main", "app", "server", "cli", "run", "bot"})
DOC_SUFFIXES = frozenset({".md", ".txt", ".rst"})
CONFIG_NAMES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "Makefile",
    "docker-compose.yml", "Dockerfile", "tsconfig.json", ".eslintrc.json",
})

# How this topic gets triggered today. This is what decides whether it is
# webhook-shaped at all, so it is detected rather than guessed.
TRIGGER_SIGNS = (
    ("cron", re.compile(r"cron\.schedule|node-cron|croniter|schedule\.every|APScheduler")),
    ("launchd", re.compile(r"StartCalendarInterval|StartInterval|LaunchAgents")),
    ("discord", re.compile(r"discord\.js|interactionCreate|messageCreate|Client\(\{")),
    ("http", re.compile(r"express\(\)|fastify|app\.(get|post)\(|FastAPI|@app\.route")),
    ("webhook", re.compile(r"webhook|/hooks?/|X-Hub-Signature")),
    ("gmail", re.compile(r"gmail|googleapis.*gmail|smtplib")),
    ("sheets", re.compile(r"spreadsheets|googleapis.*sheets|gspread")),
    ("openai_or_claude", re.compile(r"anthropic|openai|claude-|gpt-4|ANTHROPIC_")),
)


def classify(path: Path) -> str:
    name, suffix = path.name, path.suffix.lower()
    if topics.is_secret_file(path):
        return "secret"
    if suffix in DOC_SUFFIXES:
        return "doc"
    if name in CONFIG_NAMES or suffix in {".plist", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        return "config"
    if suffix in {".py", ".mjs", ".js", ".cjs", ".ts", ".sh", ".bash", ".rb", ".go"}:
        return "entrypoint" if path.stem.lower() in ENTRYPOINT_STEMS else "script"
    if suffix == ".json":
        return "config"
    if suffix in {".csv", ".tsv", ".db", ".sqlite", ".sqlite3", ".jsonl"}:
        return "data"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov", ".mp3", ".wav", ".pdf"}:
        return "asset"
    return "other"


def scan(root: Path, max_files: int, max_file_bytes: int, max_total: int) -> dict:
    files: list[dict] = []
    secrets: list[dict] = []
    triggers: dict[str, list[str]] = {}
    redaction_hits = 0
    total_read = 0
    truncated = {"files": 0, "bytes_skipped": 0, "unread_large": 0}
    seen_files = 0

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            rel = str(path.relative_to(root))

            if entry.is_symlink():
                # Never traverse a link: following one would walk straight out of
                # this folder and into tom's 28G (and its credentials).
                try:
                    target = os.readlink(path)
                except OSError:
                    target = "<unreadable>"
                files.append({"path": rel, "kind": "symlink", "target": target})
                continue

            if entry.is_dir(follow_symlinks=False):
                if entry.name in topics.PRUNE_DIRS or (path / "pyvenv.cfg").exists():
                    continue
                stack.append(path)
                continue

            seen_files += 1
            if seen_files > max_files:
                truncated["files"] += 1
                continue

            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue

            kind = classify(path)
            record = {"path": rel, "kind": kind, "size": size}

            if kind == "secret":
                names = topics.env_var_names(path)
                secrets.append({
                    "path": rel, "size": size, "var_names": names,
                    "symlink_target": (os.path.realpath(path)
                                       if path.is_symlink() else None),
                })
                record["var_names"] = names
                record["contents_read"] = False
                files.append(record)
                continue

            readable = (path.suffix.lower() in topics.TEXT_SUFFIXES
                        or path.name in CONFIG_NAMES)
            if readable and size <= max_file_bytes and total_read < max_total:
                try:
                    raw = path.read_text(errors="replace")
                except OSError:
                    raw = ""
                clean, hits = topics.redact(raw)
                redaction_hits += hits
                total_read += len(clean)

                for label, pattern in TRIGGER_SIGNS:
                    if pattern.search(clean):
                        triggers.setdefault(label, []).append(rel)

                lines = clean.splitlines()
                record["excerpt"] = "\n".join(lines[:EXCERPT_LINES])
                record["lines"] = len(lines)
                if len(lines) > EXCERPT_LINES:
                    record["excerpt_truncated"] = True
                if hits:
                    record["redactions"] = hits
            elif readable:
                truncated["unread_large"] += 1
                truncated["bytes_skipped"] += size

            files.append(record)

    by_kind: dict[str, int] = {}
    for record in files:
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1

    return {
        "ok": True,
        "path": str(root),
        "topic": root.name,
        "counts": {"files_seen": seen_files, "files_recorded": len(files), **by_kind},
        "truncated": truncated,
        "triggers": {k: v[:10] for k, v in triggers.items()},
        "secret_files": secrets,
        "redactions_applied": redaction_hits,
        "git": topics.git_info(root),
        "launchd_labels": [r["label"] for r in topics.launchd_refs(root)],
        "claude_state": topics.claude_state(root),
        "files": files,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", required=True, help="topic folder to inventory")
    ap.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    ap.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    ap.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    ap.add_argument("--stdout", action="store_true",
                    help="print the full inventory instead of a summary")
    args = ap.parse_args()

    try:
        root = topics.resolve_topic(args.path)
        report = scan(root, args.max_files, args.max_file_bytes, args.max_total_bytes)

        out_dir = config.TMP_DIR / "ingest" / root.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "inventory.json"
        out_path.write_text(json.dumps(report, indent=2))
        report["inventory_path"] = str(out_path)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    if args.stdout:
        print(json.dumps(report, indent=2))
    else:
        summary = {k: v for k, v in report.items() if k != "files"}
        summary["secret_files"] = [
            {"path": s["path"], "var_count": len(s["var_names"]),
             "symlink_target": s["symlink_target"]}
            for s in report["secret_files"]
        ]
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
