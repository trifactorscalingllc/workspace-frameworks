"""Stream run activity to Slack.

Best-effort by design: a Slack outage must never fail a directive run. If
``SLACK_WEBHOOK_URL`` is unset, every call is a silent no-op.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import config

TIMEOUT = 10


def slack(text: str, *, blocks: list | None = None) -> bool:
    """Post to the incoming webhook. Returns True if Slack accepted it."""
    url = config.get("SLACK_WEBHOOK_URL")
    if not url:
        return False

    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def run_started(slug: str, source: str = "cli") -> None:
    slack(f":rocket: *{slug}* started ({source})")


def run_finished(slug: str, result: dict) -> None:
    if result.get("ok"):
        slack(f":white_check_mark: *{slug}* finished in {result.get('duration_s')}s")
    else:
        detail = result.get("error") or f"rc={result.get('returncode')}"
        slack(f":x: *{slug}* failed — {detail}")
