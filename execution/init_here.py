#!/usr/bin/env python3
"""Apply a framework to the folder you are already in, additively.

    python3 execution/init_here.py                      # DOE (the default)
    python3 execution/init_here.py --framework iae      # research framework
    python3 execution/init_here.py --list               # what is available

`new_workspace.py` creates a workspace from scratch, which does not help when
you have already opened a folder and started work in it. This adds a framework's
layers to that folder instead.

The governing rule is CLAUDE.md's: **never restructure a source folder.**
So this only ever ADDS files. It will not overwrite, move, merge or delete
anything, and it refuses outright — writing nothing — if the folder already has
a directory the framework wants to own, rather than trying to reconcile them.

Frameworks other than DOE live in `frameworks/<name>/` and describe themselves
in a `framework.json`, so adding one needs no change to this file.

Stdlib only, so it runs before any venv exists.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent
FRAMEWORKS_DIR = TEMPLATE / "frameworks"

# DOE is the repo root itself rather than an entry under frameworks/, because
# five existing clones and new_workspace.py depend on that layout. It is
# described here in the same shape a framework.json produces, so init() has one
# code path rather than a special case.
DOE = {
    "name": "doe",
    "title": "DOE — Directives / Orchestration / Execution",
    "description": "Automation and ops. Markdown SOPs, a model that routes, deterministic Python.",
    "source": TEMPLATE,
    "dirs": ("directives", "execution"),
    "files": ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "requirements.txt", ".env.example"),
    "optional_dirs": (".vscode",),
    "markers": ("directives", "execution/config.py"),
    "bootstrap": True,
}

# Never copied: per-workspace state, secrets, the template's own history, or a
# framework's self-description and its test fixtures.
NEVER = {".git", ".env", ".venv", ".tmp", "credentials.json", "token.json",
         "__pycache__", ".DS_Store", "framework.json", "fixtures"}


def available() -> list[dict]:
    """DOE plus every frameworks/<name>/framework.json that parses."""
    out = [DOE]
    if FRAMEWORKS_DIR.is_dir():
        for entry in sorted(FRAMEWORKS_DIR.iterdir()):
            manifest = entry / "framework.json"
            if not manifest.is_file():
                continue
            try:
                spec = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  warning: skipping {entry.name} — {exc}", file=sys.stderr)
                continue
            spec["source"] = entry
            # A framework copies its whole subtree, so its owned directories are
            # simply whatever top-level directories it ships.
            spec["dirs"] = tuple(sorted(
                p.name for p in entry.iterdir()
                if p.is_dir() and p.name not in NEVER
            ))
            # Loose top-level files (instructions, the checker) go through the
            # same code path as DOE's, so the displaced-instructions handling
            # below applies to every framework rather than only to DOE.
            spec["files"] = tuple(sorted(
                p.name for p in entry.iterdir()
                if p.is_file() and p.name not in NEVER
            ))
            spec.setdefault("markers", spec["dirs"])
            spec.setdefault("bootstrap", False)
            out.append(spec)
    return out


def resolve(name: str) -> dict | None:
    for spec in available():
        if spec["name"] == name:
            return spec
    return None


def copy_tree(src: Path, dst: Path) -> int:
    """Copy src into dst, skipping NEVER entries. Returns files written."""
    written = 0
    for item in src.rglob("*"):
        if any(part in NEVER for part in item.relative_to(src).parts):
            continue
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            # Additive means additive: an existing file is left exactly as is.
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # follow_symlinks resolves AGENTS.md/GEMINI.md to real files — a
            # symlink does not survive a Windows checkout.
            shutil.copy2(item, target, follow_symlinks=True)
            written += 1
    return written


def merge_gitignore(root: Path) -> int:
    """Append the template's ignore rules that are missing. Never rewrites.

    Read from the repo root, not the framework: the ignore rules (.env, .venv,
    credentials) are workspace-wide and every framework wants them.
    """
    src = TEMPLATE / ".gitignore"
    if not src.exists():
        return 0
    dst = root / ".gitignore"
    wanted = [l.rstrip() for l in src.read_text(encoding="utf-8").splitlines()]
    if not dst.exists():
        dst.write_text("\n".join(wanted) + "\n", encoding="utf-8")
        print("  wrote .gitignore")
        return 0
    have = {l.strip() for l in dst.read_text(encoding="utf-8").splitlines()}
    missing = [l for l in wanted if l.strip() and not l.startswith("#") and l.strip() not in have]
    if not missing:
        print("  .gitignore already covers the framework entries")
        return 0
    with dst.open("a", encoding="utf-8") as fh:
        fh.write("\n# --- added by framework init ---\n" + "\n".join(missing) + "\n")
    print(f"  appended {len(missing)} rule(s) to your existing .gitignore")
    return 1


def init(root: Path, spec: dict, run_bootstrap: bool) -> int:
    root = root.expanduser().resolve()
    source = spec["source"]
    name = spec["name"]

    if root == TEMPLATE or root == source or FRAMEWORKS_DIR in root.parents:
        print("✗ that is the template itself.", file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f"✗ {root} is not a directory.", file=sys.stderr)
        return 1

    if all((root / m).exists() for m in spec["markers"]):
        print(f"{root.name} already has {name} applied — nothing to do.")
        return 0

    # Refuse rather than merge. Reconciling someone's existing directory with
    # the framework's is exactly the restructuring the rule forbids.
    clash = [d for d in spec["dirs"] if (root / d).exists()]
    if clash:
        print(f"✗ {root.name} already has {', '.join(f'{c}/' for c in clash)} but is not "
              f"a {name} workspace.\n"
              f"  Refusing to merge into it — that would restructure your folder.\n"
              f"  Create a fresh workspace beside it instead:\n"
              f"    python3 {TEMPLATE / 'execution' / 'new_workspace.py'} \"{root.name} {name}\"",
              file=sys.stderr)
        return 1

    print(f"\n\033[1m==>\033[0m Applying {name} to {root}")
    written = 0
    for layer in spec["dirs"]:
        written += copy_tree(source / layer, root / layer)
        print(f"  {layer}/")
    instructions = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
    displaced = False
    for fname in spec.get("files", ()):
        src, dst = source / fname, root / fname
        if not src.exists():
            continue
        if dst.exists():
            # Another framework already owns the instruction trio. Additive means
            # we do not overwrite it — but silently dropping this framework's
            # rules would leave the layers in place with nothing explaining them,
            # which looks like success and is not. Park them under the framework
            # name instead.
            if fname in instructions and not (root / f"{name.upper()}.md").exists():
                shutil.copy2((source / "CLAUDE.md").resolve(), root / f"{name.upper()}.md",
                             follow_symlinks=True)
                written += 1
                displaced = True
            continue
        shutil.copy2(src.resolve(), dst, follow_symlinks=True)
        written += 1
    for fname in spec.get("optional_dirs", ()):
        if (source / fname).is_dir():
            written += copy_tree(source / fname, root / fname)
    touched = merge_gitignore(root)
    print(f"  {written} file(s) added, {touched} modified, 0 deleted")
    if displaced:
        print(f"\n  note: this folder already had a CLAUDE.md, which was left untouched.\n"
              f"        {name}'s instructions are in {name.upper()}.md — read them, or the\n"
              f"        layers above have no rules attached to them.")

    if not spec.get("bootstrap"):
        check = spec.get("check")
        if check:
            print(f"\nCheck your work any time with:\n  python3 {check}")
        return 0

    if not run_bootstrap:
        print("\nSkipped bootstrap. Run it when ready:\n  python3 execution/bootstrap.py")
        return 0

    print("\n\033[1m==>\033[0m Bootstrapping")
    rc = subprocess.run(
        [sys.executable, str(root / "execution" / "bootstrap.py"), "--no-google"],
        cwd=root,
    ).returncode
    if rc != 0:
        print("\n✗ bootstrap failed. The files are in place; fix the error "
              "and rerun `python3 execution/bootstrap.py`.", file=sys.stderr)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=".", help="folder to convert (default: cwd)")
    ap.add_argument("--framework", default="doe", help="which framework to apply (default: doe)")
    ap.add_argument("--list", action="store_true", help="list available frameworks and exit")
    ap.add_argument("--no-bootstrap", action="store_true",
                    help="copy the files but skip venv/.env setup (doe only)")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    if args.list:
        print("\nAvailable frameworks:\n")
        for spec in available():
            print(f"  {spec['name']:<8} {spec.get('title', '')}")
            if spec.get("description"):
                print(f"           {spec['description']}")
            if spec.get("use_when"):
                print(f"           Use when: {spec['use_when']}")
            print()
        return 0

    spec = resolve(args.framework)
    if not spec:
        names = ", ".join(s["name"] for s in available())
        print(f"✗ no framework named {args.framework!r}. Available: {names}", file=sys.stderr)
        return 1

    return init(Path(args.path), spec, not args.no_bootstrap)


if __name__ == "__main__":
    sys.exit(main())
