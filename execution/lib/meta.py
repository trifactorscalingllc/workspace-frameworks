"""Thin Instagram Graph API client.

Standard library only — one more pip dependency for four GET requests is not
worth it, and `requirements.txt` deliberately stays small.

Auth lives in `.env`:

    META_APP_ID, META_APP_SECRET   used once, to turn a short-lived token long
    META_ACCESS_TOKEN              the long-lived token the tools actually use
    META_TOKEN_EXPIRES             ISO date, so we can warn before it dies
    IG_USER_ID                     the Instagram Business account id

Long-lived user tokens last ~60 days. That expiry is the operational trap here:
everything works for two months and then every run fails at once. `--check`
reports days remaining so it is visible before it bites.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import config

# Pinned deliberately: Meta removes metrics between versions (`impressions` went
# away for newer media types), so an unpinned version silently changes results.
GRAPH_VERSION = config.get("META_GRAPH_VERSION", "v21.0")
BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
TIMEOUT = 30


class MetaError(RuntimeError):
    """A Graph API call failed. Carries the API's own message where possible."""


def token() -> str:
    value = config.get("META_ACCESS_TOKEN", "")
    if not value:
        raise MetaError(
            "META_ACCESS_TOKEN is not set. Run: "
            "python execution/setup_meta_auth.py --check"
        )
    return value


def get(path: str, params: dict | None = None, *, access_token: str | None = None) -> dict:
    """GET a Graph endpoint and return parsed JSON, or raise MetaError."""
    query = dict(params or {})
    query["access_token"] = access_token or token()
    url = f"{BASE}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # Meta puts the useful part in the body, not the status line.
        try:
            detail = json.loads(exc.read()).get("error", {})
            raise MetaError(
                f"{detail.get('type', 'HTTPError')}: {detail.get('message', exc.reason)}"
                + (f" (code {detail['code']})" if detail.get("code") else "")
            ) from None
        except (ValueError, AttributeError):
            raise MetaError(f"HTTP {exc.code}: {exc.reason}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MetaError(str(exc)) from None


def ig_user_id() -> str:
    value = config.get("IG_USER_ID", "")
    if not value:
        raise MetaError(
            "IG_USER_ID is not set. Run: "
            "python execution/setup_meta_auth.py --discover"
        )
    return value


def token_days_left() -> int | None:
    """Days until META_ACCESS_TOKEN expires, or None if unknown."""
    raw = config.get("META_TOKEN_EXPIRES", "")
    if not raw:
        return None
    try:
        expires = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return (expires - datetime.now(timezone.utc)).days
