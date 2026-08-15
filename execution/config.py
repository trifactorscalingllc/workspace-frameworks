"""Central config: paths, ``.env`` loading, and the billing-var scrub.

Importing this module has a side effect on purpose: it deletes
``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` from the running process. Any
script in ``execution/`` should import it first, before anything that might
spawn a subprocess.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from lib.childenv import disabled_name, scrub_process_env

ROOT = Path(__file__).resolve().parent.parent
EXECUTION_DIR = ROOT / "execution"
DIRECTIVES_DIR = ROOT / "directives"
TMP_DIR = ROOT / ".tmp"
ENV_FILE = ROOT / ".env"

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


def billed_api_gate_open() -> bool:
    """True only if someone deliberately set ALLOW_BILLED_API=1.

    Defaults OFF. This is the single opt-in for any future hosted path that
    cannot reach the Keychain; nothing in the local receiver should ever open
    it. Read at call time, not import time, so a test can toggle it.
    """
    return os.environ.get("ALLOW_BILLED_API") == "1"

# Wall-clock ceiling for a single directive run, in seconds.
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT", "900"))
