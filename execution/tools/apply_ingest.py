#!/usr/bin/env python3
"""Promote a staged ingest proposal into a real directive and webhook entry.

The deliberate second step. ``scan_topic.py`` and the ``ingest_topic`` directive
only ever write into ``.tmp/ingest/<topic>/``; nothing reaches ``directives/`` or
``webhooks.json`` until a human has read the proposal and run this.

    python execution/tools/apply_ingest.py --topic slim-bot --dry-run
    python execution/tools/apply_ingest.py --topic slim-bot

Three refusals are hard-coded, because each is a way this could quietly destroy
work that already exists:

* an existing ``directives/<slug>.md`` is never overwritten
* an existing slug in ``webhooks.json`` is never rebound — that would silently
  redirect live traffic
* the entry always lands ``"enabled": false``; arming it stays a hand edit

This tool never reads, writes, moves or deletes anything in the source folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  (import first: scrubs the billing vars)
import run_directive  # noqa: E402

STAGED_DIRECTIVE = "proposed_directive.md"
STAGED_WEBHOOK = "proposed_webhook.json"


def load_proposal(topic: str) -> tuple[Path, str, dict]:
    stage = config.TMP_DIR / "ingest" / topic
    directive_file = stage / STAGED_DIRECTIVE
    webhook_file = stage / STAGED_WEBHOOK

    if not directive_file.is_file():
        raise RuntimeError(
            f"no staged directive at {directive_file}. Run the ingest_topic "
            "directive for this topic first."
        )
    if not webhook_file.is_file():
        raise RuntimeError(f"no staged webhook entry at {webhook_file}")

    entry = json.loads(webhook_file.read_text())
    if not isinstance(entry, dict) or "slug" not in entry:
        raise RuntimeError(f"{webhook_file} must be an object with a 'slug' key")
    return stage, directive_file.read_text(), entry


def apply(topic: str, dry_run: bool) -> dict:
    stage, directive_text, entry = load_proposal(topic)
    slug = entry["slug"]
    if not slug.replace("_", "").isalnum():
        raise RuntimeError(f"slug must be alphanumeric/underscore: {slug!r}")

    target = run_directive.directive_path(slug)
    if target.exists():
        raise RuntimeError(
            f"refusing: {target} already exists. Directives are the instruction "
            "set, not scratch paper — merge by hand or choose another slug."
        )

    catalog = json.loads(config.WEBHOOKS_FILE.read_text())
    hooks = catalog.setdefault("webhooks", {})
    if slug in hooks:
        raise RuntimeError(
            f"refusing: slug {slug!r} is already registered. Rebinding it would "
            "redirect live traffic to a different directive."
        )

    tools = entry.get("tools", [])
    run_directive.validate_tools(tools)  # unknown tool names fail here, not at run time

    new_entry = {
        "directive": slug,
        "description": entry.get("description", f"Ingested from {topic}."),
        "tools": tools,
        # Never armed on creation. A mis-scoped grant that is also live is the
        # failure this whole path exists to avoid.
        "enabled": False,
    }

    if dry_run:
        return {
            "ok": True, "dry_run": True, "slug": slug,
            "would_write": str(target), "entry": new_entry,
            "directive_bytes": len(directive_text),
        }

    target.write_text(directive_text)
    hooks[slug] = new_entry
    config.WEBHOOKS_FILE.write_text(json.dumps(catalog, indent=2) + "\n")

    return {
        "ok": True, "slug": slug, "directive": str(target),
        "webhooks_file": str(config.WEBHOOKS_FILE), "entry": new_entry,
        "next": [
            f"review {target}",
            f"test: {config.PYTHON} execution/run_directive.py {slug} --dry-run",
            "set enabled=true in execution/webhooks.json by hand when satisfied",
            f"{config.PYTHON} execution/install_agent.py   # restart the receiver",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--topic", required=True,
                    help="the staged topic name under .tmp/ingest/")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be written, change nothing")
    args = ap.parse_args()

    try:
        result = apply(args.topic, args.dry_run)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
