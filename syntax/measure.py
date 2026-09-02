#!/usr/bin/env python3
"""measure.py — how verbose are Claude's chat replies on this machine?

Reads the local Claude Code transcripts (~/.claude/projects/*/*.jsonl), groups the
assistant's content blocks by message id (one API response = one turn), and reports:

  turns        assistant turns that contained text
  med words    median words per turn          p90 words   90th percentile
  med lines    median non-empty lines         <=8 lines   share of turns at or under 8 lines
  narration    share of turns whose first line opens with "I'll", "Let me", "First", "Now I"...
  tables       share of turns containing a markdown table

  measure.py                        last 14 days, every session
  measure.py --days 7
  measure.py --compare 2026-09-01T20:00     before = the --days window ending then; after = since then
  measure.py --by entrypoint        break down by how the session was started (cli, vscode, sdk...)
  measure.py --project tom          only sessions whose project dir name contains "tom"
  measure.py --json

Sidechains (subagents) are excluded: they talk to Claude, not to you. Times without a
timezone are read as local time.
"""
import argparse, glob, json, os, re, statistics, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

NARRATION = re.compile(
    r"^\s*(?:\*\*)?(?:I['’]ll\b|I will\b|Let me\b|Let['’]s\b|First,? I\b|Now,? I\b|Next,? I\b|"
    r"I['’]m going to\b|I am going to\b|Here['’]s what I['’]ll\b|Before I\b|I need to\b|I['’]m about to\b)", re.I)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)


def parse_ts(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def load_turns(projects_dir, since, until, project_filter, include_sidechain):
    """Yield one dict per assistant turn (message id) with text, ts, entrypoint, project."""
    turns = {}
    order = []
    for path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        proj = os.path.basename(os.path.dirname(path))
        if project_filter and project_filter not in proj:
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        except OSError:
            continue
        if mtime < since:  # file untouched since before the window: nothing in it can be inside
            continue
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                if '"type":"assistant"' not in line and '"type": "assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                if d.get("isSidechain") and not include_sidechain:
                    continue
                ts = parse_ts(d.get("timestamp"))
                if ts is None or ts < since or ts >= until:
                    continue
                msg = d.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if not texts:
                    continue
                key = msg.get("id") or d.get("uuid")
                t = turns.get(key)
                if t is None:
                    t = turns[key] = {"texts": [], "ts": ts, "entrypoint": d.get("entrypoint") or "?", "project": proj}
                    order.append(key)
                t["texts"].extend(texts)
    for key in order:
        t = turns[key]
        t["text"] = "\n".join(t.pop("texts")).strip()
        if t["text"]:
            yield t


def stats(turns):
    if not turns:
        return None
    words = sorted(len(t["text"].split()) for t in turns)
    lines = sorted(sum(1 for ln in t["text"].splitlines() if ln.strip()) for t in turns)
    n = len(turns)
    p90 = words[min(n - 1, int(round(0.9 * (n - 1))))]
    return {
        "turns": n,
        "med_words": int(statistics.median(words)),
        "p90_words": p90,
        "med_lines": int(statistics.median(lines)),
        "le8_lines": sum(1 for x in lines if x <= 8) / n,
        "narration": sum(1 for t in turns if NARRATION.match(t["text"].splitlines()[0])) / n,
        "tables": sum(1 for t in turns if len(TABLE_ROW.findall(t["text"])) >= 2) / n,
        "total_words": sum(words),
    }


def fmt_row(label, s):
    if s is None:
        return f"{label:<26}{'—':>7}   (no turns)"
    return (f"{label:<26}{s['turns']:>7}{s['med_words']:>11}{s['p90_words']:>11}{s['med_lines']:>11}"
            f"{s['le8_lines']*100:>10.0f}%{s['narration']*100:>11.0f}%{s['tables']*100:>9.0f}%")


HEADER = f"{'window':<26}{'turns':>7}{'med words':>11}{'p90 words':>11}{'med lines':>11}{'<=8 lines':>11}{'narration':>12}{'tables':>10}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=14, help="window length in days (default 14)")
    ap.add_argument("--compare", metavar="ISO", help="split point: before = --days window ending here, after = since here")
    ap.add_argument("--by", choices=["entrypoint", "project"], help="break the numbers down by this field")
    ap.add_argument("--project", help="only project dirs whose name contains this")
    ap.add_argument("--include-sidechain", action="store_true", help="include subagent turns")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--projects-dir", default=os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects"))
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    if a.compare:
        split = parse_ts(a.compare)
        if split is None:
            sys.exit(f"could not parse --compare {a.compare!r}")
        windows = [(f"before ({a.days:g}d to split)", split - timedelta(days=a.days), split),
                   ("after (since split)", split, now)]
    else:
        windows = [(f"last {a.days:g} days", now - timedelta(days=a.days), now)]

    out = {}
    for label, since, until in windows:
        turns = list(load_turns(a.projects_dir, since, until, a.project, a.include_sidechain))
        if a.by:
            groups = defaultdict(list)
            for t in turns:
                groups[t[a.by]].append(t)
            out[label] = {"all": stats(turns), **{k: stats(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}}
        else:
            out[label] = stats(turns)

    if a.json:
        print(json.dumps(out, indent=2))
        return
    print(HEADER)
    for label, s in out.items():
        if a.by:
            print(fmt_row(label, s["all"]))
            for k, v in s.items():
                if k != "all":
                    print(fmt_row(f"  {k}", v))
        else:
            print(fmt_row(label, s))
    print()
    print("narration = first line opens with I'll / Let me / First / Now I ...   tables = 2+ markdown table rows")


if __name__ == "__main__":
    main()
