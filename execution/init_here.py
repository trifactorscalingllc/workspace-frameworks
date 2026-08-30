#!/usr/bin/env python3
"""Convert the folder you are already in into a DOE workspace, additively.

    python3 execution/init_here.py --path /some/existing/folder

`new_workspace.py` creates a workspace from scratch, which does not help when
you have already opened a folder and started work in it. This adds the DOE
layers to that folder instead.

The governing rule is CLAUDE.md's: **never restructure a source folder.**
So this only ever ADDS files. It will not overwrite, move, merge or delete
anything, and it refuses outright — writing nothing — if the folder already has
a `directives/` or `execution/`, rather than trying to reconcile them.

Stdlib only, so it runs before any venv exists.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent

# What makes a folder a DOE workspace. Copied wholesale from the template.
LAYERS = ("directives", "execution")
FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "requirements.txt", ".env.example")
OPTIONAL_DIRS = (".vscode",)

# Never copied: per-workspace state, secrets, or the template's own history.
NEVER = {".git", ".env", ".venv", ".tmp", "credentials.json", "token.json",
         "__pycache__", ".DS_Store"}


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
            shutil.copy2(item, target)
            written += 1
    return written


def merge_gitignore(root: Path) -> None:
    """Append the template's ignore rules that are missing. Never rewrites."""
    src = TEMPLATE / ".gitignore"
    if not src.exists():
        return
    dst = root / ".gitignore"
    wanted = [l.rstrip() for l in src.read_text(encoding="utf-8").splitlines()]
    if not dst.exists():
        dst.write_text("\n".join(wanted) + "\n", encoding="utf-8")
        print("  wrote .gitignore")
        return
    have = {l.strip() for l in dst.read_text(encoding="utf-8").splitlines()}
    missing = [l for l in wanted if l.strip() and not l.startswith("#") and l.strip() not in have]
    if not missing:
        print("  .gitignore already covers the DOE entries")
        return
    with dst.open("a", encoding="utf-8") as fh:
        fh.write("\n# --- added by DOE init ---\n" + "\n".join(missing) + "\n")
    print(f"  appended {len(missing)} rule(s) to your existing .gitignore")


def init(root: Path, run_bootstrap: bool) -> int:
    root = root.expanduser().resolve()
    if root == TEMPLATE:
        print("✗ that is the template itself.", file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f"✗ {root} is not a directory.", file=sys.stderr)
        return 1

    present = [layer for layer in LAYERS if (root / layer).exists()]
    if present:
        already = all((root / m).exists() for m in ("directives", "execution/config.py"))
        if already:
            print(f"{root.name} is already a DOE workspace — nothing to do.")
            return 0
        # Refuse rather than merge. Reconciling someone's existing execution/
        # with the template's is exactly the "restructuring" the rule forbids.
        print(f"✗ {root.name} already has {', '.join(present)}/ but is not a DOE "
              f"workspace.\n"
              f"  Refusing to merge into it — that would restructure your folder.\n"
              f"  Create a fresh workspace beside it instead:\n"
              f"    python3 {TEMPLATE / 'execution' / 'new_workspace.py'} \"{root.name} DOE\"",
              file=sys.stderr)
        return 1

    print(f"\n\033[1m==>\033[0m Adding the DOE layers to {root}")
    written = 0
    for layer in LAYERS:
        written += copy_tree(TEMPLATE / layer, root / layer)
        print(f"  {layer}/")
    for name in FILES:
        src, dst = TEMPLATE / name, root / name
        # AGENTS.md and GEMINI.md are symlinks in the template. Resolve them to
        # real files: a symlink does not survive a copy to a Windows checkout,
        # and the whole point of the trio is that all three agents can read it.
        if not src.exists() or dst.exists():
            continue
        shutil.copy2(src.resolve(), dst, follow_symlinks=True)
        written += 1
    for name in OPTIONAL_DIRS:
        if (TEMPLATE / name).is_dir():
            written += copy_tree(TEMPLATE / name, root / name)
    print(f"  {len(FILES)} instruction/config file(s)")
    merge_gitignore(root)
    print(f"  {written} file(s) added, 0 modified, 0 deleted")

    if not run_bootstrap:
        print(f"\nSkipped bootstrap. Run it when ready:\n"
              f"  python3 execution/bootstrap.py")
        return 0

    print(f"\n\033[1m==>\033[0m Bootstrapping")
    rc = subprocess.run(
        [sys.executable, str(root / "execution" / "bootstrap.py"), "--no-google"],
        cwd=root,
    ).returncode
    if rc != 0:
        print("\n✗ bootstrap failed. The DOE files are in place; fix the error "
              "and rerun `python3 execution/bootstrap.py`.", file=sys.stderr)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=".", help="folder to convert (default: cwd)")
    ap.add_argument("--no-bootstrap", action="store_true",
                    help="copy the DOE files but skip venv/.env setup")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    return init(Path(args.path), not args.no_bootstrap)


if __name__ == "__main__":
    sys.exit(main())
