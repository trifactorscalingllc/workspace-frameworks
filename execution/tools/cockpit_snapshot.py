#!/usr/bin/env python3
"""Collect one JSON snapshot of the TFS business state for the cockpit webview.

Layer 3: deterministic, no LLM, no writes. Emits a single JSON object on stdout so a webview (or
anything else) can render it without knowing how any of the data was obtained.

It does not reimplement any API. Every section shells out to the tool that already owns that
integration -- ig_posts.py for Instagram, read_sheet.py for the sheets -- so there is exactly one
place where each credential and each endpoint lives. That is the whole point of the split: a bug in
the Instagram pagination gets fixed once, in ig_posts.py, and this file inherits it.

Sections degrade independently. A dead Meta token blackens the social panel and leaves tasks alone.
Every section reports its own ok/error so the UI can show which half of the picture is missing
rather than a single blank screen.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

TOOLS = Path(__file__).resolve().parent

# Statuses that mean "finished". Compared case-folded; anything else counts as open.
DONE_WORDS = {"done", "complete", "completed", "shipped", "published", "posted", "closed", "✅"}
# Statuses that mean "actively stuck", worth surfacing above ordinary open work.
BLOCKED_WORDS = {"blocked", "stuck", "waiting", "on hold", "paused"}


def run_tool(args: list[str], timeout: int = 90) -> dict:
    """Run one Layer 3 tool and parse its JSON. Never raises -- returns an error envelope."""
    try:
        proc = subprocess.run(
            [config.PYTHON, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            cwd=str(config.ROOT),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout}s"}
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"ok": False, "error": (proc.stderr or "").strip()[:400] or f"exit {proc.returncode}"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"non-JSON output: {proc.stdout.strip()[:200]}"}


def records(sheet_id: str, cell_range: str) -> dict:
    return run_tool([
        str(TOOLS / "read_sheet.py"),
        "--sheet-id", sheet_id,
        "--range", cell_range,
        "--header",
    ])


def classify(status: str) -> str:
    s = (status or "").strip().casefold()
    if not s:
        return "open"
    if s in DONE_WORDS or any(w in s for w in DONE_WORDS):
        return "done"
    if s in BLOCKED_WORDS or any(w in s for w in BLOCKED_WORDS):
        return "blocked"
    return "open"


def section_tasks() -> dict:
    """Done / open / blocked, from the tracker sheet daily_digest already reports on."""
    sheet_id = config.get("DIGEST_SHEET_ID")
    if not sheet_id:
        return {"ok": False, "error": "DIGEST_SHEET_ID is not set in .env"}

    res = records(sheet_id, "A1:Z500")
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "read_sheet failed")}

    rows = res.get("records") or res.get("values") or []
    done, open_, blocked = [], [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        item = (r.get("Item") or "").strip()
        if not item:
            continue
        entry = {
            "item": item,
            "status": (r.get("Status") or "").strip(),
            "owner": (r.get("Owner") or "").strip(),
            "date": (r.get("Date") or "").strip(),
            "notes": (r.get("Notes") or "").strip()[:200],
        }
        {"done": done, "blocked": blocked, "open": open_}[classify(entry["status"])].append(entry)

    return {
        "ok": True,
        "counts": {"done": len(done), "open": len(open_), "blocked": len(blocked)},
        "done": done[-25:],       # most recent wins; the sheet is append-ordered
        "open": open_[:25],
        "blocked": blocked[:25],
    }


def section_content() -> dict:
    """This week's content calendar and how much of it actually shipped."""
    sheet_id = config.get("CONTENT_WEEK_SHEET_ID")
    if not sheet_id:
        return {"ok": False, "error": "CONTENT_WEEK_SHEET_ID is not set in .env"}

    res = records(sheet_id, "A1:Z200")
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "read_sheet failed")}

    rows = [r for r in (res.get("records") or []) if isinstance(r, dict)]
    slots, shipped = [], 0
    for r in rows:
        # The completion column has been spelled a few ways across revisions of this sheet; accept
        # any of them rather than silently reporting zero shipped.
        done_val = next((r[k] for k in r if k.strip().casefold().rstrip("?") == "done"), "")
        is_done = classify(str(done_val)) == "done" or str(done_val).strip().casefold() in {"y", "yes", "x", "true"}
        if is_done:
            shipped += 1
        slots.append({
            "date": (r.get("Date") or "").strip(),
            "day": (r.get("Day") or "").strip(),
            "post_at": (r.get("Post at") or "").strip(),
            "format": (r.get("Format") or "").strip(),
            "system": (r.get("System") or "").strip(),
            "done": is_done,
        })

    return {"ok": True, "planned": len(slots), "shipped": shipped, "slots": slots[:30]}


def section_social(days: int, insights: bool) -> dict:
    """Real Instagram performance, straight from the tool content_week already depends on.

    Insights are OFF by default and that is a deliberate 50x: ig_posts.py makes one extra Graph
    call per post for them, which measured 30.4s against 0.6s for the same 50 posts. All they buy
    is reach/impressions. Likes and comments -- everything the cockpit actually displays -- come
    back on the plain media fetch. Turn them on only when something on screen needs reach.
    """
    args = [str(TOOLS / "ig_posts.py"), "--limit", "50"]
    if not insights:
        args.append("--no-insights")
    res = run_tool(args, timeout=180)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "ig_posts failed")}

    posts = res.get("posts") or []
    for p in posts:
        p["engagement"] = (p.get("likes") or 0) + (p.get("comments") or 0)
        reach = p.get("reach") or p.get("impressions") or 0
        p["reach"] = reach
        p["engagement_rate"] = round(p["engagement"] / reach * 100, 2) if reach else None

    ranked = sorted(posts, key=lambda p: p["engagement"], reverse=True)
    total_eng = sum(p["engagement"] for p in posts)
    return {
        "ok": True,
        "window_days": days,
        "post_count": len(posts),
        "total_engagement": total_eng,
        "avg_engagement": round(total_eng / len(posts), 1) if posts else 0,
        "top": ranked[:5],
        "recent": posts[:10],
        # ig_posts.py surfaces its own credential expiry warning; carry it through rather than
        # letting the panel look healthy right up until the token dies.
        "warning": res.get("warning"),
    }


def section_inbox(limit: int) -> dict:
    """Live mail, via the read-only gmail_list tool.

    gmail_list owns the scope check and returns a structured refusal when nobody has consented to
    a read scope yet, so this stays a passthrough. Whatever it says about being blocked reaches the
    panel verbatim and is rendered as a call to action rather than an error.
    """
    res = run_tool([str(TOOLS / "gmail_list.py"), "--query", "in:inbox", "--limit", str(limit)])
    if res.get("ok"):
        msgs = res.get("messages") or []
        return {
            "ok": True,
            "count": res.get("count", len(msgs)),
            "unread": res.get("unread", 0),
            # Unread first, then newest — what needs a human rises to the top of the panel.
            "messages": sorted(msgs, key=lambda m: (not m.get("unread"),))[:12],
        }
    return res


def section_health() -> dict:
    """Credential clocks. These are the failures that look like bugs a week later."""
    out = {"ok": True, "items": []}

    expires = config.get("META_TOKEN_EXPIRES")
    if expires:
        try:
            when = datetime.fromisoformat(expires)
            days = (when - datetime.now(timezone.utc)).total_seconds() / 86400
            out["items"].append({
                "name": "Meta / Instagram token",
                "expires_at": expires,
                "days_left": round(days, 1),
                "level": "error" if days <= 0 else "warn" if days < 7 else "ok",
                "remedy": "python execution/setup_meta_auth.py",
            })
        except ValueError:
            out["items"].append({"name": "Meta / Instagram token", "expires_at": expires,
                                 "level": "warn", "remedy": "unparseable META_TOKEN_EXPIRES"})

    try:
        scopes = json.loads(config.TOKEN_FILE.read_text()).get("scopes", [])
        out["items"].append({
            "name": "Google OAuth scopes",
            "detail": ", ".join(s.rsplit("/", 1)[-1] for s in scopes) or "none",
            "level": "warn" if not any("gmail.readonly" in s for s in scopes) else "ok",
            "remedy": "gmail.readonly not granted — inbox panel stays dark until re-consent",
        })
    except Exception:  # noqa: BLE001
        out["items"].append({"name": "Google OAuth", "level": "error", "detail": "token.json missing"})

    return out


def section_next(tasks: dict, content: dict, social: dict, health: dict) -> dict:
    """Deterministic 'where to go next'.

    Rules over data, not a language model. Anything here is defensible by pointing at the row that
    produced it, which is what makes it safe to put in front of a founder. Genuine synthesis is a
    directive's job -- this is the floor, not the ceiling.
    """
    ideas = []

    for item in (health.get("items") or []):
        if item.get("level") in {"warn", "error"} and item.get("remedy"):
            ideas.append({
                "priority": 1 if item["level"] == "error" else 2,
                "title": f"{item['name']} needs attention",
                "why": item.get("detail") or f"expires in {item.get('days_left')} days",
                "action": item["remedy"],
            })

    if tasks.get("ok"):
        for t in tasks.get("blocked", [])[:3]:
            ideas.append({
                "priority": 1,
                "title": f"Unblock: {t['item']}",
                "why": f"status '{t['status']}'" + (f", owner {t['owner']}" if t["owner"] else ""),
                "action": "Decide or reassign — blocked items do not age well.",
            })
        if tasks["counts"]["open"] > 3 * max(tasks["counts"]["done"], 1):
            ideas.append({
                "priority": 3,
                "title": "Open work is outrunning finished work",
                "why": f"{tasks['counts']['open']} open vs {tasks['counts']['done']} done",
                "action": "Close or cut before taking anything new on.",
            })

    if content.get("ok"):
        missing = content["planned"] - content["shipped"]
        if missing > 0:
            ideas.append({
                "priority": 2,
                "title": f"{missing} planned post{'s' if missing != 1 else ''} not shipped",
                "why": f"{content['shipped']}/{content['planned']} of the calendar is done",
                "action": "Run the content_week directive, or cut the slots you will not make.",
            })

    if social.get("ok") and social.get("top"):
        best = social["top"][0]
        ideas.append({
            "priority": 3,
            "title": "Repeat the format that actually worked",
            "why": f"{best.get('engagement')} engagements on {best.get('media_type', 'post')} ({best.get('date')})",
            "action": f"Rebuild this angle for next week: {best.get('permalink', '')}",
        })
        if social.get("post_count", 0) == 0:
            ideas.append({"priority": 2, "title": "Nothing posted in the window",
                          "why": "no posts returned", "action": "Publishing cadence has stopped."})

    ideas.sort(key=lambda i: i["priority"])
    return {"ok": True, "ideas": ideas[:8]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30, help="social lookback window (default 30)")
    ap.add_argument("--inbox-limit", type=int, default=15, help="threads to pull (default 15)")
    ap.add_argument("--insights", action="store_true",
                    help="fetch per-post Instagram insights (reach). ~50x slower; off by default.")
    ap.add_argument("--section", action="append",
                    choices=["tasks", "content", "social", "inbox", "health"],
                    help="collect only these sections (repeatable); default is all")
    args = ap.parse_args()

    want = set(args.section or ["tasks", "content", "social", "inbox", "health"])
    tasks = section_tasks() if "tasks" in want else {"ok": False, "skipped": True}
    content = section_content() if "content" in want else {"ok": False, "skipped": True}
    social = section_social(args.days, args.insights) if "social" in want else {"ok": False, "skipped": True}
    inbox = section_inbox(args.inbox_limit) if "inbox" in want else {"ok": False, "skipped": True}
    health = section_health() if "health" in want else {"ok": True, "items": []}

    print(json.dumps({
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "content": content,
        "social": social,
        "inbox": inbox,
        "health": health,
        "next": section_next(tasks, content, social, health),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
