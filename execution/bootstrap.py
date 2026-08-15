#!/usr/bin/env python3
"""Turn a fresh copy of this repo into a working workspace, in one command.

    python3 execution/bootstrap.py

Creates the venv, installs dependencies, writes a `.env` with a freshly
generated `WEBHOOK_TOKEN` and a free `WEBHOOK_PORT`, optionally copies Google
OAuth files from a sibling workspace so you skip the consent flow, then runs
preflight.

Deliberately stdlib-only and does NOT import `config`: it runs before the venv
exists, so anything needing `python-dotenv` would fail on the first line.

Options:
    --from PATH     copy Google OAuth files from this workspace
    --no-google     skip the Google step entirely
    --port N        use this port instead of picking a free one
    --force-env     rewrite .env even if it already exists
"""

from __future__ import annotations

import argparse
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "bin" / "python"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
GOOGLE_FILES = ("credentials.json", "token.json")

# Ports launchd services here tend to land on; start above the common default.
PORT_RANGE = range(8787, 8850)


def step(msg: str) -> None:
    print(f"\n\033[1m==>\033[0m {msg}", flush=True)


def free_port(preferred: int | None = None) -> int:
    """First port nothing is listening on. Deterministic, so reruns are stable."""
    candidates = [preferred] if preferred else list(PORT_RANGE)
    for port in candidates:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"no free port in {PORT_RANGE.start}-{PORT_RANGE.stop}")


def ensure_venv() -> None:
    if VENV_PYTHON.exists():
        print(f"  venv already present: {VENV}")
    else:
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        print(f"  created {VENV}")

    subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")],
        check=True,
    )
    print("  dependencies installed")


def write_env(port: int, force: bool) -> None:
    if ENV_FILE.exists() and not force:
        text = ENV_FILE.read_text()
        changed = False

        if not re.search(r"^WEBHOOK_TOKEN=\S", text, re.M):
            text = re.sub(r"^WEBHOOK_TOKEN=.*$",
                          f"WEBHOOK_TOKEN={secrets.token_urlsafe(32)}", text, flags=re.M)
            changed = True
            print("  filled in a missing WEBHOOK_TOKEN")

        if not re.search(r"^WEBHOOK_PORT=\S", text, re.M):
            text = re.sub(r"^WEBHOOK_PORT=.*$", f"WEBHOOK_PORT={port}", text, flags=re.M)
            changed = True
            print(f"  set WEBHOOK_PORT={port}")

        ENV_FILE.write_text(text) if changed else print("  .env already complete — left alone")
        return

    text = ENV_EXAMPLE.read_text()
    text = re.sub(r"^WEBHOOK_TOKEN=.*$", f"WEBHOOK_TOKEN={secrets.token_urlsafe(32)}", text, flags=re.M)
    text = re.sub(r"^WEBHOOK_PORT=.*$", f"WEBHOOK_PORT={port}", text, flags=re.M)
    ENV_FILE.write_text(text)
    ENV_FILE.chmod(0o600)
    print(f"  wrote {ENV_FILE} (token generated, port {port})")


def find_donor(explicit: str | None) -> Path | None:
    """A sibling workspace already holding Google OAuth files."""
    if explicit:
        donor = Path(explicit).expanduser().resolve()
        if not all((donor / f).exists() for f in GOOGLE_FILES):
            print(f"  {donor} has no Google OAuth files — skipping", file=sys.stderr)
            return None
        return donor

    donors = [
        sibling
        for sibling in sorted(ROOT.parent.iterdir())
        if sibling.is_dir()
        and sibling != ROOT
        and all((sibling / f).exists() for f in GOOGLE_FILES)
    ]
    if not donors:
        return None
    if len(donors) > 1:
        print(f"  several workspaces have Google files: {[d.name for d in donors]}")
        print("  not guessing — rerun with --from <path> to choose one")
        return None
    return donors[0]


def copy_google(donor: Path | None) -> None:
    have = [f for f in GOOGLE_FILES if (ROOT / f).exists()]
    if len(have) == len(GOOGLE_FILES):
        print("  Google OAuth files already present")
        return
    if donor is None:
        # Deliberately does not claim "no donor found" — find_donor may have
        # found several and declined to pick, and it already said so.
        print("  continuing without Google OAuth files. Connector tools")
        print("  (drive_search, drive_read, gmail_draft) work without them.")
        print("  For Sheets writes or real sends, run:")
        print("    .venv/bin/python execution/setup_google_auth.py --check")
        return

    for name in GOOGLE_FILES:
        target = ROOT / name
        if target.exists():
            continue
        shutil.copy2(donor / name, target)
        target.chmod(0o600)
        print(f"  copied {name} from {donor.name}")
    print("  same OAuth client, so no new consent is needed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="donor", help="workspace to copy Google OAuth files from")
    ap.add_argument("--no-google", action="store_true", help="skip the Google step")
    ap.add_argument("--port", type=int, help="use this port instead of picking a free one")
    ap.add_argument("--force-env", action="store_true", help="rewrite .env even if present")
    args = ap.parse_args()

    print(f"Bootstrapping {ROOT.name}  ({ROOT})")

    step("Python environment")
    ensure_venv()

    step("Configuration")
    port = free_port(args.port)
    write_env(port, args.force_env)

    step("Google access")
    if args.no_google:
        print("  skipped (--no-google)")
    else:
        copy_google(find_donor(args.donor))

    step("Preflight")
    rc = subprocess.run(
        [str(VENV_PYTHON), str(ROOT / "execution" / "preflight.py")], cwd=ROOT
    ).returncode

    print("\n" + "=" * 60)
    if rc == 0:
        print(f"Ready. This workspace is independent of any other copy:\n"
              f"  service label : com.trifactor.{re.sub(r'[^a-z0-9-]+', '-', ROOT.name.lower()).strip('-')}\n"
              f"  port          : {port}\n"
              f"\nStart the receiver whenever you need webhooks:\n"
              f"  .venv/bin/python execution/install_agent.py\n"
              f"\nYou do not need it to start building — just describe what you want.")
    else:
        print("Preflight failed. Fix that before relying on this workspace.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
