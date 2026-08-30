#!/usr/bin/env python3
"""List recent Gmail threads as JSON. Read-only — this tool cannot send, draft, label or delete.

Deliberately separate from send_email.py. That one delivers immediately with no human in the loop
and has no business being in the same grant as a reader; keeping them apart means a webhook can be
handed "look at the inbox" without also being handed "mail the world".

Refuses cleanly when the workspace token lacks a Gmail read scope, because the honest failure is
"nobody consented to this yet", not a 403 from four frames inside googleapiclient.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from lib.google_auth import GMAIL_READ_SCOPES, can_read_gmail, gmail_service, granted_scopes  # noqa: E402

REMEDY = (
    "Re-consent with a Gmail read scope: "
    "`.venv/bin/python execution/setup_google_auth.py --remote`, open the printed link, approve, "
    "then `--finish '<url>'` with the address the browser lands on. "
    "gmail.readonly is already in SCOPES."
)


def header(payload: dict, name: str) -> str:
    for h in (payload.get("headers") or []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def snippet_of(msg: dict) -> str:
    return (msg.get("snippet") or "").strip()


def age(iso: str) -> str:
    """Human age, because '2h' reads faster than a timestamp on a dashboard."""
    try:
        when = parsedate_to_datetime(iso)
    except (TypeError, ValueError):
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    mins = (datetime.now(timezone.utc) - when).total_seconds() / 60
    if mins < 60:
        return f"{int(mins)}m"
    if mins < 60 * 24:
        return f"{int(mins // 60)}h"
    return f"{int(mins // 1440)}d"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--query", default="in:inbox", help="Gmail search query (default 'in:inbox')")
    ap.add_argument("--limit", type=int, default=15, help="max threads (default 15)")
    ap.add_argument("--snippet-chars", type=int, default=140)
    args = ap.parse_args()

    if not can_read_gmail():
        print(json.dumps({
            "ok": False,
            "blocked": True,
            "reason": "no_gmail_read_scope",
            "granted_scopes": granted_scopes(),
            "needs_one_of": list(GMAIL_READ_SCOPES),
            "remedy": REMEDY,
        }, indent=2))
        return 0  # a known, explained gap is not a crash — the caller renders the remedy

    try:
        svc = gmail_service()
        listing = svc.users().messages().list(
            userId="me", q=args.query, maxResults=max(1, min(args.limit, 100)),
        ).execute()
    except Exception as exc:  # noqa: BLE001 - surface any API failure as data, never a traceback
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, indent=2))
        return 1

    out = []
    for ref in (listing.get("messages") or []):
        try:
            msg = svc.users().messages().get(
                userId="me", id=ref["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
        except Exception:  # noqa: BLE001 - one unreadable message must not sink the list
            continue
        payload = msg.get("payload") or {}
        name, addr = parseaddr(header(payload, "From"))
        labels = msg.get("labelIds") or []
        out.append({
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "from_name": name or addr,
            "from_email": addr,
            "subject": header(payload, "Subject") or "(no subject)",
            "date": header(payload, "Date"),
            "age": age(header(payload, "Date")),
            "unread": "UNREAD" in labels,
            "starred": "STARRED" in labels,
            "snippet": snippet_of(msg)[:args.snippet_chars],
        })

    print(json.dumps({
        "ok": True,
        "query": args.query,
        "count": len(out),
        "unread": sum(1 for m in out if m["unread"]),
        "messages": out,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
