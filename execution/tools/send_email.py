#!/usr/bin/env python3
"""Send email through the Gmail API. Prints JSON on stdout.

    python execution/tools/send_email.py --to a@example.com --subject 'Hi' --body 'text'
    python execution/tools/send_email.py --to a@example.com --subject 'Hi' --body-file out.html --html
    python execution/tools/send_email.py ... --dry-run   # render, send nothing

Sending is outward-facing and irreversible. Directives that email a human
should confirm the recipient list before calling this without --dry-run.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from lib.google_auth import gmail_service  # noqa: E402


def build_message(to: list[str], subject: str, body: str, *, html: bool, cc: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    sender = config.get("EMAIL_FROM")
    if sender:
        msg["From"] = sender

    if html:
        msg.set_content("This message requires an HTML-capable client.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)
    return msg


def send(msg: EmailMessage) -> dict:
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return gmail_service().users().messages().send(userId="me", body={"raw": raw}).execute()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Not required: falls back to EMAIL_TO so a directive can rely on the
    # .env default without needing permission to read .env itself.
    ap.add_argument("--to", default="", help="comma-separated recipients (default: EMAIL_TO)")
    ap.add_argument("--cc", default="", help="comma-separated cc")
    ap.add_argument("--subject", required=True)
    body = ap.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", help="read the body from a file")
    ap.add_argument("--html", action="store_true", help="send the body as HTML")
    ap.add_argument("--dry-run", action="store_true", help="render and print, send nothing")
    args = ap.parse_args()

    to = [a.strip() for a in (args.to or config.get("EMAIL_TO", "")).split(",") if a.strip()]
    cc = [a.strip() for a in args.cc.split(",") if a.strip()]

    if not to:
        print(json.dumps({
            "ok": False,
            "error": "no recipient: pass --to, or set EMAIL_TO in .env",
        }))
        return 1

    try:
        text = Path(args.body_file).read_text() if args.body_file else args.body
        msg = build_message(to, args.subject, text, html=args.html, cc=cc)
        if args.dry_run:
            print(json.dumps({"ok": True, "dry_run": True, "to": to, "cc": cc,
                              "subject": args.subject, "body_chars": len(text)}, indent=2))
            return 0
        resp = send(msg)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps({"ok": True, "message_id": resp.get("id"), "to": to, "cc": cc,
                      "subject": args.subject}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
