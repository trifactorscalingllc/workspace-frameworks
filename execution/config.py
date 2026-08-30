"""Central config: paths, ``.env`` loading, and the billing-var scrub.

Importing this module has a side effect on purpose: it deletes
``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` from the running process. Any
script in ``execution/`` should import it first, before anything that might
spawn a subprocess.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from lib.childenv import disabled_name, scrub_process_env

ROOT = Path(__file__).resolve().parent.parent
EXECUTION_DIR = ROOT / "execution"
DIRECTIVES_DIR = ROOT / "directives"
TMP_DIR = ROOT / ".tmp"
ENV_FILE = ROOT / ".env"

# Absolute, because directive runs inherit launchd's minimal PATH, which has no
# bare `python` at all — telling a run to type `python foo.py` earns exit 127.
# The layout differs by platform: venv puts the interpreter in Scripts/ on
# Windows and bin/ everywhere else. bootstrap.py repeats this two-line check
# rather than importing it, because it runs before the venv it creates exists.
_VENV_BIN = "Scripts" if os.name == "nt" else "bin"
_VENV_PYTHON = ROOT / ".venv" / _VENV_BIN / ("python.exe" if os.name == "nt" else "python")
PYTHON = str(_VENV_PYTHON if _VENV_PYTHON.exists() else sys.executable)

# Resolved, for the same reason PYTHON is absolute. On Windows an npm-installed
# CLI is `claude.cmd`, and CreateProcess appends only `.exe` — it does not read
# PATHEXT — so a bare "claude" raises FileNotFoundError even though
# shutil.which() (which does read PATHEXT) just found it. Every spawn site must
# use this, not the bare name. Falls back to the bare name so a PATH that only
# resolves at spawn time still works.
CLAUDE = shutil.which("claude") or "claude"

CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"
WEBHOOKS_FILE = EXECUTION_DIR / "webhooks.json"

TMP_DIR.mkdir(exist_ok=True)

load_dotenv(ENV_FILE, override=False)

# Whatever the .env or the shell just handed us, it does not survive here.
SCRUBBED = scrub_process_env()


def get(name: str, default: str | None = None) -> str | None:
    """Read a config value from the environment."""
    return os.environ.get(name, default)


def require(name: str) -> str:
    """Read a config value, or fail loudly with a pointer to ``.env``."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to {ENV_FILE} (see .env.example).")
    return value


def parked_api_key() -> str | None:
    """The paid-API key, if one is parked under its disabled name.

    Only the deliberate ``ALLOW_BILLED_API`` path should ever call this.
    """
    return os.environ.get(disabled_name("ANTHROPIC_API_KEY"))


# Model for directive runs. Passed to children as ANTHROPIC_MODEL, never as a
# --model flag (CLAUDE.md rule 3).
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")


def workspace_slug() -> str:
    """A launchd-safe identifier derived from this workspace's folder name.

    Copies of this repo must not share an identity: launchd keys services by
    label, so two workspaces using one label means installing the second
    silently boots out the first and takes over its port. Deriving the label
    from the directory keeps duplicates independent.
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", ROOT.name.lower()).strip("-")
    return slug or "workspace"


# Same value the installer writes into the plist and the receiver reports on
# /health, so a mismatch between the two is impossible.
LAUNCHD_LABEL = f"com.trifactor.{workspace_slug()}"

# Per-workspace, so duplicates do not fight over one socket. bootstrap.py picks
# a free port and writes it here; 8787 is only the single-workspace default.
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8787"))


def billed_api_gate_open() -> bool:
    """True only if someone deliberately set ALLOW_BILLED_API=1.

    Defaults OFF. This is the single opt-in for any future hosted path that
    cannot reach the Keychain; nothing in the local receiver should ever open
    it. Read at call time, not import time, so a test can toggle it.
    """
    return os.environ.get("ALLOW_BILLED_API") == "1"

# Wall-clock ceiling for a single directive run, in seconds.
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT", "900"))
