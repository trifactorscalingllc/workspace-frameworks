"""Build a child environment that cannot bill the paid Anthropic API.

The Claude CLI picks its auth mode from the environment and there is no flag
for it:

    ANTHROPIC_API_KEY present  -> billed API      (wrong)
    ANTHROPIC_API_KEY absent   -> Keychain login  (what we want)

So the subscription path is the default, and the whole job is keeping that
variable out of the child environment. Every spawn in this repo must build its
env here. Never hand ``os.environ`` straight to a subprocess.
"""

from __future__ import annotations

import os
from typing import Mapping

# Variables that switch the CLI onto billed-API auth. Stripped unconditionally.
BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# The renamed parking spot for a key that must exist on disk but must never
# reach a child process under its real name.
DISABLED_SUFFIX = "_DISABLED"


class BillingLeak(RuntimeError):
    """A billing variable survived into an environment we were about to spawn."""


def strip_billing_vars(env: dict[str, str]) -> dict[str, str]:
    """Remove every billing variable from ``env`` in place and return it."""
    for var in BILLING_VARS:
        env.pop(var, None)
        # Defensive: a value parked under the disabled name is fine, but a
        # lowercase or whitespace-padded variant is not.
        for key in [k for k in env if k.strip().upper() == var]:
            env.pop(key, None)
    return env


def assert_keyless(env: Mapping[str, str], context: str = "child env") -> None:
    """Raise if any billing variable is present. Call immediately before spawn."""
    leaked = [k for k in env if k.strip().upper() in BILLING_VARS]
    if leaked:
        raise BillingLeak(
            f"{context} still carries {sorted(leaked)}. This would bill the paid "
            f"API instead of the claude.ai subscription. Refusing to spawn."
        )


def build_child_env(
    extra: Mapping[str, str] | None = None,
    *,
    base: Mapping[str, str] | None = None,
    allow_billed_api: bool = False,
) -> dict[str, str]:
    """Return a copy of the environment safe to hand to ``claude -p``.

    ``extra`` is merged last and is itself stripped, so a caller cannot
    reintroduce a key by accident. ``allow_billed_api`` is the single explicit
    escape hatch (see CLAUDE.md rule 5: a daemon with no Keychain access). It
    still requires the key to be supplied deliberately via ``extra``.
    """
    env = dict(os.environ if base is None else base)

    if allow_billed_api:
        # Explicit opt-in: keep whatever the caller passes, but never silently
        # inherit a key from the ambient shell.
        strip_billing_vars(env)
        if extra:
            env.update(extra)
        return env

    strip_billing_vars(env)
    if extra:
        env.update(strip_billing_vars(dict(extra)))
    assert_keyless(env)
    return env


def disabled_name(var: str) -> str:
    """``ANTHROPIC_API_KEY`` -> ``ANTHROPIC_API_KEY_DISABLED``."""
    return f"{var}{DISABLED_SUFFIX}"


def scrub_process_env() -> list[str]:
    """Delete billing vars from *this* process. Returns the names removed.

    Called on import of ``config`` so that even code which ignores
    ``build_child_env`` and calls ``subprocess.run(..., env=os.environ)``
    still cannot leak a key.
    """
    removed = [k for k in list(os.environ) if k.strip().upper() in BILLING_VARS]
    for key in removed:
        del os.environ[key]
    return removed
