#!/usr/bin/env python3
"""Audit the auth setup and prove a keyless spawn works.

    python execution/preflight.py            # static checks only
    python execution/preflight.py --probe    # also spawn a real keyless run

Run it before trusting a new machine, or after changing shell config.
Exit codes: 0 all pass, 1 a check failed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import config
from lib.childenv import BILLING_VARS, build_child_env, disabled_name

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
_MARK = {PASS: "\033[32m✓\033[0m", FAIL: "\033[31m✗\033[0m", WARN: "\033[33m!\033[0m"}

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    print(f"  {_MARK[status]} {name}" + (f" — {detail}" if detail else ""))


def check_process_clean() -> None:
    """After importing config, this process must carry no billing vars."""
    leaked = [v for v in BILLING_VARS if v in os.environ]
    if leaked:
        check("process env is keyless", FAIL, f"still set: {leaked}")
    else:
        note = f"scrubbed {config.SCRUBBED}" if config.SCRUBBED else "nothing to scrub"
        check("process env is keyless", PASS, note)


def check_env_file() -> None:
    """.env must not hold the key under its real name (CLAUDE.md rule 4)."""
    if not config.ENV_FILE.exists():
        check(".env exists", WARN, "not found — copy .env.example to .env")
        return
    text = config.ENV_FILE.read_text()
    bad = [
        v for v in BILLING_VARS
        if re.search(rf"^\s*(export\s+)?{v}\s*=", text, re.MULTILINE)
    ]
    if bad:
        check(".env has no real key names", FAIL, f"rename {bad} to *_DISABLED")
    else:
        parked = config.parked_api_key()
        check(
            ".env has no real key names",
            PASS,
            f"key parked as {disabled_name('ANTHROPIC_API_KEY')}" if parked else "no key on disk",
        )


def check_shell_config() -> None:
    """A shell rc that exports the key will poison every interactive run."""
    home = Path.home()
    rcs = [home / n for n in (".zshrc", ".zshenv", ".zprofile", ".bash_profile", ".bashrc", ".profile")]
    offenders = []
    for rc in rcs:
        if not rc.exists():
            continue
        try:
            text = rc.read_text()
        except OSError:
            continue
        for var in BILLING_VARS:
            if re.search(rf"^\s*export\s+{var}\s*=", text, re.MULTILINE):
                offenders.append(f"{rc.name}:{var}")
    if offenders:
        check("shell rc files are clean", WARN, f"exports found: {offenders}")
    else:
        check("shell rc files are clean", PASS)


def check_no_sdk_imports() -> None:
    """execution/ must never import the Anthropic SDK (CLAUDE.md rule 1)."""
    pattern = re.compile(r"^\s*(import\s+anthropic|from\s+anthropic\s+import)", re.MULTILINE)
    hits = [
        str(p.relative_to(config.ROOT))
        for p in config.EXECUTION_DIR.rglob("*.py")
        if pattern.search(p.read_text())
    ]
    if hits:
        check("no anthropic SDK imports", FAIL, f"found in {hits}")
    else:
        check("no anthropic SDK imports", PASS)


def check_no_model_flags() -> None:
    """Model selection goes through ANTHROPIC_MODEL, never --model (rule 3)."""
    # Built at runtime so this file's own source does not trip the check.
    needle = "--" + "model"
    hits = []
    for p in config.EXECUTION_DIR.rglob("*.py"):
        for line in p.read_text().splitlines():
            if f'"{needle}"' in line or f"'{needle}'" in line:
                hits.append(str(p.relative_to(config.ROOT)))
                break
    if hits:
        check("no --model flags", FAIL, f"found in {hits}")
    else:
        check("no --model flags", PASS, f"model={config.MODEL}")


def check_builder_strips() -> None:
    """build_child_env must drop a key even when one is planted in the base env."""
    planted = {"ANTHROPIC_API_KEY": "sk-planted", "ANTHROPIC_AUTH_TOKEN": "tok", "PATH": os.environ["PATH"]}
    try:
        env = build_child_env(base=planted)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the audit
        check("build_child_env strips planted key", FAIL, str(exc))
        return
    leaked = [v for v in BILLING_VARS if v in env]
    check(
        "build_child_env strips planted key",
        FAIL if leaked else PASS,
        f"leaked {leaked}" if leaked else "",
    )

    # And it must refuse to smuggle one back in via `extra`.
    env2 = build_child_env({"ANTHROPIC_API_KEY": "sk-smuggled"}, base=planted)
    check(
        "build_child_env rejects smuggled key",
        FAIL if "ANTHROPIC_API_KEY" in env2 else PASS,
    )


def check_billed_api_gate() -> None:
    """The gate defaults OFF. On this Mac it should never be open."""
    if config.billed_api_gate_open():
        check(
            "billed-API gate",
            WARN,
            "OPEN (ALLOW_BILLED_API=1) — runs may bill the paid API. Unset it "
            "unless this host genuinely has no Keychain.",
        )
    else:
        check("billed-API gate", PASS, "closed (default)")


def check_no_modal() -> None:
    """Modal containers have no Keychain, so a hosted run must bill the API."""
    pattern = re.compile(r"^\s*(import\s+modal|from\s+modal\s+import)", re.MULTILINE)
    hits = [
        str(p.relative_to(config.ROOT))
        for p in config.EXECUTION_DIR.rglob("*.py")
        if pattern.search(p.read_text())
    ]
    if hits:
        check("no Modal receivers", FAIL, f"found in {hits} — see CLAUDE.md")
    else:
        check("no Modal receivers", PASS)


def check_cli_present() -> None:
    try:
        proc = subprocess.run(
            [config.CLAUDE, "--version"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        check("claude CLI on PATH", PASS if proc.returncode == 0 else FAIL, proc.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        check("claude CLI on PATH", FAIL, str(exc))


def check_layout() -> None:
    missing = [
        str(p.relative_to(config.ROOT))
        for p in (config.DIRECTIVES_DIR, config.EXECUTION_DIR, config.WEBHOOKS_FILE)
        if not p.exists()
    ]
    check("repo layout", FAIL if missing else PASS, f"missing {missing}" if missing else "")


def probe_keyless_spawn(timeout: int = 180) -> None:
    """Spawn a real keyless run and confirm the subscription answered."""
    env = build_child_env({"ANTHROPIC_MODEL": config.MODEL})
    try:
        proc = subprocess.run(
            [config.CLAUDE, "-p", "Reply with exactly: PREFLIGHT_OK"],
            cwd=config.ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        check("keyless spawn answers", FAIL, str(exc))
        return

    out = proc.stdout.strip()
    if proc.returncode != 0:
        check("keyless spawn answers", FAIL, (proc.stderr.strip() or f"rc={proc.returncode}")[:300])
    elif "PREFLIGHT_OK" in out:
        check("keyless spawn answers", PASS, f"model={config.MODEL}")
    else:
        check("keyless spawn answers", WARN, f"unexpected reply: {out[:120]!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="also spawn a real keyless run")
    args = ap.parse_args()

    print("\nPreflight — auth and layout\n")
    check_process_clean()
    check_env_file()
    check_shell_config()
    check_no_sdk_imports()
    check_no_model_flags()
    check_no_modal()
    check_billed_api_gate()
    check_builder_strips()
    check_cli_present()
    check_layout()

    if args.probe:
        print("\nProbe — live keyless spawn\n")
        probe_keyless_spawn()
    else:
        print("\n  (run with --probe to prove a keyless spawn works)")

    failed = [n for n, s, _ in results if s == FAIL]
    warned = [n for n, s, _ in results if s == WARN]
    print(f"\n{len(results) - len(failed) - len(warned)} passed, {len(warned)} warned, {len(failed)} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
