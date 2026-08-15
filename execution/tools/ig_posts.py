#!/usr/bin/env python3
"""Fetch recent Instagram posts with their insights. Prints JSON on stdout.

    python execution/tools/ig_posts.py --since 2026-08-11 --until 2026-08-17
    python execution/tools/ig_posts.py --limit 25 --no-insights

Read-only: it can list and measure, never publish.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.meta import MetaError, get, ig_user_id, token_days_left  # noqa: E402

MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count"
)

# Metric availability differs by media type and moves between API versions, so
# ask for a rich set and degrade rather than failing the whole run. `reach` is
# the one metric present on effectively everything.
METRICS_BY_TYPE = {
    "REELS": ["reach", "saved", "shares", "comments", "likes", "views"],
    "VIDEO": ["reach", "saved", "shares", "views"],
    "CAROUSEL_ALBUM": ["reach", "saved", "shares"],
    "IMAGE": ["reach", "saved", "shares"],
}
FALLBACK_METRICS = ["reach"]


def parse_day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def fetch_media(limit: int) -> list[dict]:
    """Newest-first media list, paging until we have `limit`."""
    out: list[dict] = []
    params = {"fields": MEDIA_FIELDS, "limit": min(limit, 100)}
    path = f"{ig_user_id()}/media"

    while len(out) < limit:
        page = get(path, params)
        out.extend(page.get("data", []))
        after = page.get("paging", {}).get("cursors", {}).get("after")
        if not after or not page.get("data"):
            break
        params = {**params, "after": after}
    return out[:limit]


def fetch_insights(media_id: str, media_type: str, product_type: str) -> dict:
    """Insights for one post. Never raises — a missing metric is not a failure."""
    wanted = METRICS_BY_TYPE.get(
        "REELS" if product_type == "REELS" else media_type, FALLBACK_METRICS
    )
    for metrics in (wanted, FALLBACK_METRICS):
        try:
            data = get(f"{media_id}/insights", {"metric": ",".join(metrics)})
        except MetaError as exc:
            last = str(exc)
            continue
        return {
            row["name"]: (row.get("values") or [{}])[0].get("value")
            for row in data.get("data", [])
        }
    return {"_error": last}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="ISO date, inclusive")
    ap.add_argument("--until", help="ISO date, inclusive")
    ap.add_argument("--limit", type=int, default=50, help="max posts to scan (default 50)")
    ap.add_argument("--no-insights", action="store_true", help="skip the per-post insight calls")
    ap.add_argument("--caption-chars", type=int, default=280,
                    help="truncate captions in the output (default 280)")
    args = ap.parse_args()

    try:
        media = fetch_media(args.limit)
    except MetaError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    since = parse_day(args.since) if args.since else None
    until = parse_day(args.until).replace(hour=23, minute=59, second=59) if args.until else None

    posts = []
    for item in media:
        when = datetime.fromisoformat(item["timestamp"].replace("+0000", "+00:00"))
        if (since and when < since) or (until and when > until):
            continue
        post = {
            "id": item["id"],
            "posted_at": when.isoformat(),
            "date": when.date().isoformat(),
            "media_type": item.get("media_type"),
            "product_type": item.get("media_product_type"),
            "permalink": item.get("permalink"),
            "likes": item.get("like_count"),
            "comments": item.get("comments_count"),
            "caption": (item.get("caption") or "")[: args.caption_chars],
        }
        if not args.no_insights:
            post["insights"] = fetch_insights(
                item["id"], item.get("media_type", ""), item.get("media_product_type", "")
            )
        posts.append(post)

    payload = {
        "ok": True,
        "count": len(posts),
        "scanned": len(media),
        "range": {"since": args.since, "until": args.until},
        "posts": posts,
    }
    if (days := token_days_left()) is not None and days < 14:
        payload["warning"] = f"META_ACCESS_TOKEN expires in {days} days — re-run setup_meta_auth.py"

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
