#!/usr/bin/env python3
"""measure.py — how verbose are Claude's chat replies on this machine?

Reads the local Claude Code transcripts (~/.claude/projects/*/*.jsonl), groups the
assistant's content blocks by message id (one API response = one turn), and reports:

  turns        assistant turns that contained text
  med words    median words per turn          p90 words   90th percentile
  med lines    median non-empty lines         <=8 lines   share of turns at or under 8 lines
  narration    share of turns whose first line opens with "I'll", "Let me", "First", "Now I"...
  tables       share of turns containing a markdown table
  closing      share of turns whose LAST line is a standalone prose sentence (the closing-line rule,
               added 2026-09-02) rather than a table row, bullet, header or fenced block
  labelled     share of those closing lines that announce themselves ("In short", "TL;DR", a bolded
               lead-in). The rule forbids this, so it should read ~0%

  closing is a floor, not a score. It cannot tell an exempt reply (requested JSON, a file's exact
  contents) from a violation, and it cannot judge whether the sentence carries the point or just
  recaps. Both make the number too low, never too high. Negative control: --compare 2026-09-02,
  before which no such rule existed.

  measure.py                        last 14 days, every session
  measure.py --days 7
  measure.py --compare 2026-09-01T20:00     before = the --days window ending then; after = since then
  measure.py --by entrypoint        break down by how the session was started (cli, vscode, sdk...)
  measure.py --project tom          only sessions whose project dir name contains "tom"
  measure.py --json
  measure.py --self-test            check the closing-line detector against known cases, then exit

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
FENCE = re.compile(r"^\s*(?:```|~~~)")
# structural shapes that are not a sentence: table row, header, quote, bullet, numbered item
NOT_A_SENTENCE = re.compile(r"^\s*(?:\||#|>|[-*+]\s|\d+[.)]\s)")
LABELLED = re.compile(
    r"^\s*(?:\*\*|__)?\s*(?:tl;?\s?dr|in short|in sum(?:mary)?|to sum up|summary|bottom line|net[- ]net|"
    r"one[- ]liner?|one[- ]line version|short version|long story short|the point|key )", re.I)
BOLD_START = re.compile(r"^\s*(?:\*\*|__)")


def closing_line(text):
    """Return (has_closing, is_labelled) for a reply's final line.

    A closing line is the reply's last non-empty line when it is a standalone prose sentence.
    Anything ending in a fenced block, table, bullet, header or a line ending in ":" has none.
    """
    lines = text.splitlines()
    in_fence = False
    last = None          # (index, text) of the last non-empty line outside a fence
    for i, ln in enumerate(lines):
        if FENCE.match(ln):
            in_fence = not in_fence
            last = None  # a fence delimiter is never a closing line, and content resumes after it
            continue
        if in_fence or not ln.strip():
            continue
        last = (i, ln)
    if in_fence or last is None:
        return False, False          # unterminated fence, or the reply ends inside/at one
    if any(l.strip() for l in lines[last[0] + 1:]):
        return False, False          # something non-blank followed it (a closed fence's tail)
    ln = last[1]
    if ln.startswith("    ") or ln.startswith("\t"):
        return False, False          # indented code
    if NOT_A_SENTENCE.match(ln):
        return False, False
    core = ln.strip().rstrip("*_`\"'\u201d\u2019)]")
    if not core or not core.endswith((".", "!", "?")):
        return False, False          # a fragment, a bare link, or a line ending in ":"
    return True, bool(LABELLED.match(ln) or BOLD_START.match(ln))


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
    closings = [closing_line(t["text"]) for t in turns]
    closed = sum(1 for c, _ in closings if c)
    return {
        "turns": n,
        "med_words": int(statistics.median(words)),
        "p90_words": p90,
        "med_lines": int(statistics.median(lines)),
        "le8_lines": sum(1 for x in lines if x <= 8) / n,
        "narration": sum(1 for t in turns if NARRATION.match(t["text"].splitlines()[0])) / n,
        "tables": sum(1 for t in turns if len(TABLE_ROW.findall(t["text"])) >= 2) / n,
        "closing": sum(1 for c, _ in closings if c) / n,
        "labelled": (sum(1 for c, lab in closings if c and lab) / closed) if closed else 0.0,
        "total_words": sum(words),
    }


def fmt_row(label, s):
    if s is None:
        return f"{label:<26}{'—':>7}   (no turns)"
    return (f"{label:<26}{s['turns']:>7}{s['med_words']:>11}{s['p90_words']:>11}{s['med_lines']:>11}"
            f"{s['le8_lines']*100:>10.0f}%{s['narration']*100:>11.0f}%{s['tables']*100:>9.0f}%"
            f"{s['closing']*100:>9.0f}%{s['labelled']*100:>10.0f}%")


HEADER = (f"{'window':<26}{'turns':>7}{'med words':>11}{'p90 words':>11}{'med lines':>11}"
          f"{'<=8 lines':>11}{'narration':>12}{'tables':>10}{'closing':>10}{'labelled':>11}")


SELF_TEST = [
    # (text, expected has_closing, expected labelled)
    ("The token was stale. Rotated it and the run passes now.", True, False),
    ("Fixed.", True, False),
    ("Nothing changed; the file was already correct.", True, False),
    ("Which port should it bind to?", True, False),
    ("**In short:** the token was stale.", True, True),
    ("Done.\n\nTL;DR the cache was the problem.", True, True),
    ("**The receiver now starts clean.**", True, True),
    ("Here is the fix:\n\n```bash\nmake install\n```", False, False),
    ("| port | 8087 |\n| label | runner |", False, False),
    ("Three things broke:\n- auth\n- the port\n- the plist", False, False),
    ("## What changed", False, False),
    ("Run this: ", False, False),
    ("See [the log](https://example.com/log)", False, False),
    ("Opened a fence and never closed it:\n```bash\nls", False, False),
    ("```bash\nls\n```\nThat lists it.", True, False),
]


def self_test():
    bad = 0
    for text, want_c, want_l in SELF_TEST:
        got_c, got_l = closing_line(text)
        ok = (got_c, got_l) == (want_c, want_l)
        bad += not ok
        if not ok:
            print(f"FAIL  closing={got_c} labelled={got_l}  want {want_c}/{want_l}  {text!r}")
    print(f"{len(SELF_TEST) - bad}/{len(SELF_TEST)} closing-line cases pass")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=14, help="window length in days (default 14)")
    ap.add_argument("--compare", metavar="ISO", help="split point: before = --days window ending here, after = since here")
    ap.add_argument("--by", choices=["entrypoint", "project"], help="break the numbers down by this field")
    ap.add_argument("--project", help="only project dirs whose name contains this")
    ap.add_argument("--include-sidechain", action="store_true", help="include subagent turns")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="check the closing-line detector and exit")
    ap.add_argument("--projects-dir", default=os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects"))
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())

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
    print("closing   = last line is a standalone prose sentence (rule added 2026-09-02; --compare 2026-09-02 is its control)")
    print("labelled  = share of those closing lines announcing themselves (In short / TL;DR / bold lead-in) — must be ~0%")


if __name__ == "__main__":
    main()
