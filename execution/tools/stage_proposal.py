#!/usr/bin/env python3
"""Write one part of an ingest proposal into ``.tmp/ingest/<topic>/``.

The ``ingest_topic`` directive has to produce prose — a verdict, a directive
draft — but a headless run holds no general write tool, and granting one would
let it write anywhere in the workspace. This is the narrow alternative: the only
directory it can write to is ``.tmp/ingest/<topic>/``, and the only filenames it
can produce are the three a proposal consists of.

Content arrives on stdin, so the caller uses a heredoc:

    python execution/tools/stage_proposal.py --topic slim-bot --part proposal <<'EOF'
    # Proposal: slim-bot
    ...
    EOF

    python execution/tools/stage_proposal.py --topic slim-bot --part directive <<'EOF'
    # Directive: slim_review
    ...
    EOF

    python execution/tools/stage_proposal.py --topic slim-bot --part webhook \
        --slug slim_review --description 'Weekly review' --tools drive_search,gmail_draft

Nothing here can touch `directives/`, `webhooks.json`, or a source folder —
promotion is `apply_ingest.py`, run by a human.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  (import first: scrubs the billing vars)
import run_directive  # noqa: E402
from lib import topics  # noqa: E402

PARTS = {
    "proposal": "proposal.md",
    "directive": "proposed_directive.md",
    "webhook": "proposed_webhook.json",
}
VERDICTS = ("wrap", "mirror", "migrate", "no-fit")


def stage_dir(topic: str) -> Path:
    """Resolve the staging directory, refusing anything outside .tmp/ingest/."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", topic):
        raise ValueError(f"topic must be a plain folder name, got {topic!r}")
    base = (config.TMP_DIR / "ingest").resolve()
    target = (base / topic).resolve()
    if base not in target.parents:
        raise ValueError(f"topic escapes .tmp/ingest/: {topic!r}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_part(topic: str, part: str, body: str, args) -> dict:
    out_dir = stage_dir(topic)
    path = out_dir / PARTS[part]

    if part == "webhook":
        if not args.slug:
            raise ValueError("--slug is required for --part webhook")
        if not re.fullmatch(r"[a-z0-9_]+", args.slug):
            raise ValueError(f"slug must be lowercase alphanumeric/underscore: {args.slug!r}")
        tools = [t.strip() for t in (args.tools or "").split(",") if t.strip()]
        # Fail here rather than at promotion: an invented tool name that only
        # surfaces in apply_ingest wastes the whole run.
        run_directive.validate_tools(tools)
        payload = {
            "slug": args.slug,
            "description": args.description or f"Ingested from {topic}.",
            "tools": tools,
            "verdict": args.verdict,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return {"ok": True, "wrote": str(path), "entry": payload}

    if not body.strip():
        raise ValueError(f"--part {part} needs content on stdin")

    # Last line of defence: staged prose is written by a model that has been
    # reading a topic folder, so it gets the same scrub as the inventory.
    clean, hits = topics.redact(body)
    path.write_text(clean)
    return {
        "ok": True, "wrote": str(path), "bytes": len(clean),
        "redactions_applied": hits,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--topic", required=True)
    ap.add_argument("--part", required=True, choices=sorted(PARTS))
    ap.add_argument("--verdict", choices=VERDICTS,
                    help="relationship verdict; recorded in the webhook part")
    ap.add_argument("--slug", help="proposed webhook slug (--part webhook)")
    ap.add_argument("--description", help="one-line description (--part webhook)")
    ap.add_argument("--tools", help="comma-separated grant (--part webhook)")
    args = ap.parse_args()

    try:
        body = "" if args.part == "webhook" or sys.stdin.isatty() else sys.stdin.read()
        result = write_part(args.topic, args.part, body, args)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
