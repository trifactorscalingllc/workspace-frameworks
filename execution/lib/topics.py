"""Shared analysis for topic folders — the sprawling per-job directories at
``/Users/tfs/`` that predate this template.

Everything here is **read-only against the source**. No function in this module
writes, moves, or deletes anything under a topic root, and there is deliberately
no code path that could. The tools that do write (``snapshot_topic.py``) write
only into their own destination.

Two facts about this machine drive most of the design, both established by audit
rather than assumed:

1. ``/Users/tfs/tom`` is a shared dependency hub. Fifteen ``node_modules``
   symlinks across home point into it, and every ``tom-agents/*`` project also
   borrows ``output`` and — crucially — ``.env`` from it. So a folder's own
   contents do not tell you whether it is safe to touch; you have to look at what
   points *at* it and what it points *out* to.
2. Secrets are everywhere. 28 ``.env`` files sit within three levels of home, and
   ``tom/.env`` alone holds ~37 credentials. A ``.env`` here may be a symlink into
   another folder, so name-matching the link is not enough — resolve first.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

HOME = Path("/Users/tfs")
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CLAUDE_JSON = HOME / ".claude.json"
FLEET_BACKUP = HOME / "Library" / "Scripts" / "fleet-backup.sh"

# Directories never worth walking: huge, regenerable, or not authored here.
PRUNE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt",
    ".cache", ".DS_Store", "chrome-headless-shell", ".terraform",
})

# Files whose *contents* are never read. Matched on the basename of both the
# link and its target, because `tom-agents/*/.env` is a symlink to `tom/.env`
# and resolving is the only way to catch that.
SECRET_BASENAMES = frozenset({
    "token.json", "credentials.json", ".netrc", ".npmrc", ".pypirc",
    "service-account.json", "client_secret.json",
})
SECRET_PATTERNS = (
    re.compile(r"^\.env($|\.)"),        # .env, .env.local, .env.production
    re.compile(r"\.pem$"), re.compile(r"\.key$"), re.compile(r"\.p12$"),
    re.compile(r"\.pfx$"), re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)$"),
)

# Extensions worth reading as text at all. Anything else is recorded by name only.
TEXT_SUFFIXES = frozenset({
    ".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".bash",
    ".zsh", ".sql", ".html", ".css", ".xml", ".plist", ".rb", ".go",
})

# Second line of defence, applied to everything actually read. Over-redaction is
# a non-event; under-redaction writes a live credential into .tmp/.
_REDACTIONS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"),  # discord
    re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----",
               re.DOTALL),
)
# `FOO_API_KEY = "…"` in any syntax. Keeps the name, drops the value — the name
# is a real finding (it tells you which grant the topic needs), the value is not.
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:api[_-]?key|secret|token|password|passwd|credential)"
    r"[A-Za-z0-9_]*)\s*([:=]>?\s*)([\"']?)([^\s\"',;)\}]{8,})\3"
)
REDACTED = "«redacted»"


def redact(text: str) -> tuple[str, int]:
    """Scrub credential-shaped strings. Returns the text and a hit count."""
    hits = 0
    for pattern in _REDACTIONS:
        text, n = pattern.subn(REDACTED, text)
        hits += n
    text, n = _ASSIGNMENT.subn(rf"\1\2\3{REDACTED}\3", text)
    return text, hits + n


def is_secret_file(path: Path) -> bool:
    """True if this file's contents must never be read.

    Checks the link's own name *and* its target's, so a ``.env`` symlinked from
    another folder cannot slip through under a different local name.
    """
    names = [path.name]
    if path.is_symlink():
        try:
            names.append(Path(os.readlink(path)).name)
            names.append(path.resolve().name)
        except OSError:
            pass
    for name in names:
        if name in SECRET_BASENAMES:
            return True
        if any(p.search(name) for p in SECRET_PATTERNS):
            return True
    return False


def env_var_names(path: Path) -> list[str]:
    """Variable *names* from an env-style file. Values are never returned.

    Reading a secret file at all is a deliberate exception: knowing a topic needs
    ``GHL_API_KEY`` and ``DISCORD_BOT_TOKEN`` is what determines its tool grant.
    The split on ``=`` happens before anything is retained, so no value is ever
    held in memory beyond the line it came from.
    """
    names: list[str] = []
    try:
        with path.open("r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name = line.split("=", 1)[0].strip().lstrip("export ").strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    names.append(name)
    except OSError:
        return []
    return sorted(set(names))


# --------------------------------------------------------------------------
# Environment probes — what the rest of the machine believes about this path
# --------------------------------------------------------------------------

def inbound_symlinks(root: Path, search_depth: int = 3) -> list[dict]:
    """Symlinks elsewhere in home that point *into* ``root``.

    This is the check that catches ``tom``: six sibling bots take their
    ``node_modules`` from ``tom/bot/node_modules``. Restructuring a folder with
    inbound links breaks the dependents, not the folder.
    """
    root = root.resolve()
    found: list[dict] = []
    for link in _walk_symlinks(HOME, search_depth):
        try:
            target = Path(os.path.realpath(link))
        except OSError:
            continue
        if target == root or root in target.parents:
            if link.resolve(strict=False) == root or not _is_within(link, root):
                found.append({"link": str(link), "target": str(target)})
    return found


def outbound_symlinks(root: Path) -> list[dict]:
    """Symlinks inside ``root`` that borrow from *another folder in home*.

    Catches ``tom-agents/*``, which take ``node_modules``, ``output`` and
    ``.env`` from ``tom``. A folder that borrows is not self-contained and cannot
    be lifted anywhere on its own.

    Links into system or toolchain paths (``/opt/homebrew``, ``/usr``, …) are
    ignored: every virtualenv points its ``bin/python`` at the real interpreter,
    and reporting that as "borrowing" is noise that buries the real finding.
    """
    root = root.resolve()
    found: list[dict] = []
    for link in _walk_symlinks(root, depth=4):
        try:
            target = Path(os.path.realpath(link))
        except OSError:
            continue
        if _is_within(target, root):
            continue
        if not _is_within(target, HOME):  # toolchain, not another topic
            continue
        found.append({"link": str(link), "target": str(target)})
    return found


def _walk_symlinks(base: Path, depth: int):
    """Yield symlinks under ``base``, without descending into pruned dirs."""
    base = Path(base)
    if not base.is_dir():
        return
    stack = [(base, 0)]
    while stack:
        current, level = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                yield path
            elif entry.is_dir(follow_symlinks=False):
                if entry.name in PRUNE_DIRS or entry.name.startswith(".Trash"):
                    continue
                # Virtualenvs are named anything (.voicevenv, env311); the marker
                # file is what actually identifies one.
                if (path / "pyvenv.cfg").exists():
                    continue
                if level < depth:
                    stack.append((path, level + 1))


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def launchd_refs(root: Path) -> list[dict]:
    """LaunchAgent plists naming this path.

    ~95 plists reference these folders and ~50 point into ``tom``. Each one is a
    thing that must be reworked at cutover, so they are reported by label.
    """
    needle = str(root.resolve())
    refs: list[dict] = []
    if not LAUNCH_AGENTS.is_dir():
        return refs
    for plist in sorted(LAUNCH_AGENTS.glob("*.plist")):
        try:
            text = plist.read_text(errors="replace")
        except OSError:
            continue
        if re.search(rf"{re.escape(needle)}(?![A-Za-z0-9._-])", text):
            refs.append({"label": plist.stem, "plist": str(plist)})
    return refs


def _own_pid_chain() -> set[str]:
    """This process and its ancestors.

    Without this, preflight reports *itself*: the shell running
    ``preflight_topic.py --path /Users/tfs/slim-bot`` has the path in its command
    line. A gate that fires on every folder gets ignored, which is worse than no
    gate at all.
    """
    chain: set[str] = set()
    pid = os.getpid()
    for _ in range(12):  # bounded: a ppid cycle must not hang the check
        chain.add(str(pid))
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                text=True, timeout=5, check=False,
            ).stdout.strip()
            pid = int(out)
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        if pid <= 1:
            break
    return chain


def running_processes(root: Path) -> list[dict]:
    """Processes actually *executing* something out of this folder.

    Moving a file from under a running process is the corruption case, so a hit
    here is disqualifying. But the test has to be narrow enough to be believed:
    matching any command line that merely *mentions* the path catches every tool
    that takes it as an argument, this one included.

    So a process counts only when some argument resolves to an existing **file**
    inside the folder — ``node /Users/tfs/tom/jobs/hook-lab.mjs`` counts,
    ``preflight --path /Users/tfs/tom`` (a directory) does not. Own ancestry is
    excluded outright.

    Known gap: a server started with its cwd inside the folder but launched via a
    relative path is not caught. The launchd check covers most of that case.
    """
    root = root.resolve()
    needle = str(root)
    skip = _own_pid_chain()
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,command="], capture_output=True, text=True,
            timeout=20, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    procs: list[dict] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or needle not in line:
            continue
        pid, _, command = line.partition(" ")
        if pid in skip:
            continue
        for token in re.findall(rf"{re.escape(needle)}[^\s\"']*", command):
            candidate = Path(token.rstrip(",;)"))
            if candidate.is_file():
                procs.append({"pid": pid, "command": command[:200],
                              "executing": str(candidate)})
                break
    return procs


def git_info(root: Path) -> dict:
    """Git state, with an eye on whether it is a real off-disk backup.

    A repo with no remote is not a backup — ``keenan-bot`` looks protected and
    is not: no remote, and 102 uncommitted files.
    """
    if not (root / ".git").exists():
        return {"repo": False, "remote": None, "dirty": None, "head": None}

    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, text=True,
                timeout=30, check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    porcelain = run("status", "--porcelain")
    return {
        "repo": True,
        "remote": run("remote", "get-url", "origin") or None,
        "dirty": len([ln for ln in porcelain.splitlines() if ln.strip()]),
        "head": run("rev-parse", "HEAD") or None,
    }


def in_fleet_backup(root: Path) -> bool:
    """True if ``fleet-backup.sh`` names this path in a backup call."""
    try:
        text = FLEET_BACKUP.read_text(errors="replace")
    except OSError:
        return False
    return bool(re.search(rf"^\s*backup\s+{re.escape(str(root.resolve()))}\s*$",
                          text, re.MULTILINE))


def claude_state(root: Path) -> dict:
    """Claude's own state keyed to this absolute path.

    Restructuring orphans session history and — worse — leaves a ``CLAUDE.md``
    that instructs the next agent to work against a layout that no longer exists.
    Reported so it is carried deliberately rather than silently lost.
    """
    resolved = str(root.resolve())
    slug = resolved.replace("/", "-")
    project_dir = CLAUDE_PROJECTS / slug
    sessions = 0
    if project_dir.is_dir():
        sessions = len(list(project_dir.glob("*.jsonl")))

    has_entry = False
    try:
        data = json.loads(CLAUDE_JSON.read_text())
        has_entry = resolved in data.get("projects", {})
    except (OSError, ValueError):
        pass

    instruction_files = [
        p.name for p in (root / "CLAUDE.md", root / "AGENTS.md", root / "GEMINI.md")
        if p.exists()
    ]
    return {
        "project_dir": str(project_dir) if project_dir.is_dir() else None,
        "sessions": sessions,
        "in_claude_json": has_entry,
        "instruction_files": instruction_files,
    }


def container_candidates(root: Path) -> list[str]:
    """Sub-projects that make ``root`` a container rather than one topic.

    ``projects/`` holds 43 independent projects and ``tom-agents/`` holds 10.
    Treating either as a single topic is the obvious failure, so it is detected
    rather than merely discouraged.
    """
    markers = ("package.json", "pyproject.toml", "requirements.txt", ".env", ".git")
    candidates: list[str] = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False) or entry.name.startswith("."):
            continue
        child = Path(entry.path)
        if any((child / m).exists() for m in markers):
            candidates.append(entry.name)
    return candidates


def dir_size(root: Path) -> int:
    """Apparent size in bytes, skipping pruned dirs and not following symlinks."""
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in PRUNE_DIRS:
                    stack.append(Path(entry.path))
            else:
                try:
                    total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total


def resolve_topic(raw: str) -> Path:
    """Resolve a topic path, refusing anything that is not a real directory.

    Refuses home itself and the filesystem root: a scan of ``/Users/tfs`` would
    walk every project on the machine, and neither is a topic.
    """
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (HOME / raw).resolve()
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    if path in (HOME, Path("/")) or path == Path.home():
        raise ValueError(
            f"{path} is not a topic — it is the whole home directory. "
            "Name a single project folder."
        )
    return path
