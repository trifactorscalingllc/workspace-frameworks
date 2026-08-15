#!/usr/bin/env python3
"""Spin up a new workspace from this one.

    python3 execution/new_workspace.py acme-onboarding
    python3 execution/new_workspace.py "Acme Onboarding" --open
    python3 execution/new_workspace.py client-x --dest ~/projects --no-google

Clones this repo into a sibling folder, points its git remote at this one as
`template` (so it can pull template improvements and cannot accidentally push a
project's commits back), then bootstraps it: venv, dependencies, `.env` with a
fresh token and free port, and Google OAuth files copied across so no second
consent is needed.

The result is independent — its own launchd label, log directory and port — so
it can run at the same time as this one.

Stdlib only, so it works before any venv exists.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def git(*args: str, cwd: Path = TEMPLATE) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def warn_if_dirty() -> None:
    """A clone copies committed state only. Say so before the surprise."""
    dirty = git("status", "--porcelain").stdout.strip()
    if not dirty:
        return
    # Untracked files count too: a clone copies committed state, so anything
    # modified *or* never committed is left behind. Ignored files (.env, .venv,
    # credentials) are absent from this list and handled by bootstrap instead.
    files = [line[3:] for line in dirty.splitlines()]
    print(
        f"  note: {len(files)} uncommitted/untracked file(s) will NOT be copied — "
        f"a clone takes committed state only.\n"
        f"        ({', '.join(files[:4])}{'...' if len(files) > 4 else ''})\n"
        f"        Commit them first if the new workspace should have them."
    )


def open_in_editor(dest: Path) -> None:
    """Open the new workspace in a new VS Code window.

    Inside a VS Code terminal or task, `code` is a shim that talks back to the
    VS Code client — so over Remote-SSH the window opens on the laptop driving
    the session, not on this machine, and the folder opens with the correct
    remote authority. That is why this runs `code` rather than anything local
    like `open`: it follows the session, not the filesystem.

    `-n` forces a new window instead of reusing the current one.
    """
    if not shutil.which("code"):
        print(
            "\n  note: no `code` on PATH, so nothing was opened.\n"
            "        Run this from a VS Code terminal or task and the new\n"
            "        workspace opens on whichever machine is driving the session.\n"
            f"        Otherwise open it yourself: {dest}"
        )
        return

    proc = subprocess.run(["code", "-n", str(dest)], capture_output=True, text=True)
    if proc.returncode == 0:
        print(f"\n  opened {dest.name} in a new VS Code window")
    else:
        print(f"\n  could not open VS Code ({proc.stderr.strip() or 'unknown error'}); "
              f"open it manually: {dest}")


def create(name: str, dest_dir: Path, use_google: bool, open_editor: bool) -> int:
    slug = slugify(name)
    if not slug:
        print(f"'{name}' has no usable characters for a folder name.", file=sys.stderr)
        return 1
    if slug != name:
        print(f"  using folder name: {slug}")

    dest = (dest_dir.expanduser().resolve() / slug)
    if dest.exists():
        print(f"✗ {dest} already exists. Pick another name.", file=sys.stderr)
        return 1
    if not shutil.which("git"):
        print("✗ git is required.", file=sys.stderr)
        return 1

    print(f"\n\033[1m==>\033[0m Creating {dest}")
    warn_if_dirty()

    proc = subprocess.run(
        ["git", "clone", "--quiet", str(TEMPLATE), str(dest)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"✗ clone failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"  cloned from {TEMPLATE.name}")

    # Rename the remote: `origin` pointing at the template invites pushing a
    # project's commits back into it. `template` reads as what it is, and
    # `git pull template main` still brings improvements across.
    git("remote", "rename", "origin", "template", cwd=dest)
    print("  git remote 'origin' renamed to 'template' (no accidental pushes)")

    print(f"\n\033[1m==>\033[0m Bootstrapping")
    cmd = [sys.executable, str(dest / "execution" / "bootstrap.py")]
    cmd += ["--no-google"] if not use_google else ["--from", str(TEMPLATE)]
    rc = subprocess.run(cmd, cwd=dest).returncode
    if rc != 0:
        print(f"\n✗ bootstrap failed in {dest}", file=sys.stderr)
        return rc

    if open_editor:
        open_in_editor(dest)

    print(f"\n{'=' * 60}\n{slug} is ready at:\n  {dest}\n")
    print("In the new window: Explorer is on the left and the editor area is")
    print("clear. Press \033[1mCmd+Shift+Esc\033[0m to open Claude as a tab in the middle.")
    print("VS Code restores that tab on every later open of this workspace, so")
    print("it is a one-time keystroke.\n")
    print(f"To pull later template improvements:  git -C {dest} pull template main")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="workspace name (spaces are fine, they become dashes)")
    ap.add_argument("--dest", default=str(TEMPLATE.parent),
                    help=f"where to create it (default: {TEMPLATE.parent})")
    ap.add_argument("--no-google", action="store_true",
                    help="do not copy Google OAuth files from this workspace")
    ap.add_argument("--open", dest="open_editor", action="store_true",
                    help="open the new workspace in VS Code")
    args = ap.parse_args()

    # Line-buffer our own output. Child processes write to this same stream
    # unbuffered, so block buffering would interleave their output ahead of
    # ours and make the transcript read out of order.
    sys.stdout.reconfigure(line_buffering=True)

    return create(args.name, Path(args.dest), not args.no_google, args.open_editor)


if __name__ == "__main__":
    sys.exit(main())
