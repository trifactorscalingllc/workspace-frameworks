#!/usr/bin/env python3
"""Run a directive by shelling out to the Claude CLI.

This is the only sanctioned way to invoke a model in this repo. It never
imports the Anthropic SDK — doing so would bill the paid API (CLAUDE.md rule 1).

    python execution/run_directive.py <slug> [--payload '{"k": "v"}'] [--tools send_email,read_sheet]
    python execution/run_directive.py <slug> --dry-run

Exit codes: 0 ok, 1 run failed, 2 bad usage / missing directive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import config
from lib.childenv import assert_keyless, build_child_env

# Tool names a directive may be granted. Keep in sync with CLAUDE.md and with
# the scripts that actually exist in execution/tools/.
AVAILABLE_TOOLS = {
    "send_email": "python execution/tools/send_email.py --to <addr> --subject <s> --body <b>",
    "read_sheet": "python execution/tools/read_sheet.py --sheet-id <id> --range <A1:Z>",
    "update_sheet": "python execution/tools/update_sheet.py --sheet-id <id> --range <A1:Z> --values-json <json>",
}


def directive_path(slug: str) -> Path:
    """Resolve a slug to a directive file, refusing anything outside directives/."""
    name = slug if slug.endswith(".md") else f"{slug}.md"
    path = (config.DIRECTIVES_DIR / name).resolve()
    if config.DIRECTIVES_DIR.resolve() not in path.parents:
        raise ValueError(f"directive slug escapes directives/: {slug!r}")
    return path


def validate_tools(tools: list[str]) -> list[str]:
    """Reject anything not in the grant list. Returns the tools unchanged."""
    unknown = [t for t in tools if t not in AVAILABLE_TOOLS]
    if unknown:
        raise ValueError(f"unknown tools: {unknown}. Available: {sorted(AVAILABLE_TOOLS)}")
    return tools


def build_prompt(slug: str, payload: dict | None, tools: list[str]) -> str:
    """Assemble the prompt: the directive itself, plus its payload and tool grant."""
    path = directive_path(slug)
    if not path.exists():
        raise FileNotFoundError(f"no directive at {path}")

    validate_tools(tools)

    parts = [
        f"You are executing the directive `{slug}`. Follow it exactly.",
        "",
        path.read_text(),
    ]

    if tools:
        parts += ["", "## Tools granted for this run", ""]
        parts += [f"- `{t}` — {AVAILABLE_TOOLS[t]}" for t in tools]
        parts += [
            "",
            "Use only these tools. If the directive needs one you were not "
            "granted, stop and report that instead of improvising.",
        ]

    if payload:
        parts += [
            "",
            "## Input payload",
            "",
            "```json",
            json.dumps(payload, indent=2),
            "```",
        ]

    return "\n".join(parts)


def run(
    slug: str,
    payload: dict | None = None,
    tools: list[str] | None = None,
    *,
    timeout: int | None = None,
    allow_billed_api: bool = False,
) -> dict:
    """Execute a directive. Returns a result dict; never raises on run failure."""
    tools = validate_tools(tools or [])
    prompt = build_prompt(slug, payload, tools)

    extra = {"ANTHROPIC_MODEL": config.MODEL}
    if allow_billed_api:
        # Two independent locks, both of which must be opened on purpose: the
        # caller asks, and the environment gate is set. Neither alone suffices.
        if not config.billed_api_gate_open():
            raise RuntimeError(
                "billed-API run requested but the ALLOW_BILLED_API gate is closed. "
                "Runs on this Mac use the claude.ai subscription and must not need "
                "this. Only a host with no Keychain does — set ALLOW_BILLED_API=1 "
                "deliberately if that is genuinely the situation."
            )
        key = config.parked_api_key()
        if not key:
            raise RuntimeError(
                "ALLOW_BILLED_API is set but ANTHROPIC_API_KEY_DISABLED is not, "
                "so there is no key to promote."
            )
        extra["ANTHROPIC_API_KEY"] = key

    env = build_child_env(extra, allow_billed_api=allow_billed_api)
    if not allow_billed_api:
        # Belt and braces: the last thing we do before spawning.
        assert_keyless(env, context=f"run_directive({slug})")

    # Model comes from ANTHROPIC_MODEL in env, not a --model flag (rule 3).
    cmd = ["claude", "-p", prompt]

    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=config.ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout or config.RUN_TIMEOUT,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "slug": slug,
            "error": "claude CLI not found on PATH",
            "duration_s": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "slug": slug,
            "error": f"timed out after {timeout or config.RUN_TIMEOUT}s",
            "duration_s": round(time.time() - started, 1),
        }

    return {
        "ok": proc.returncode == 0,
        "slug": slug,
        "model": config.MODEL,
        "billed_api": allow_billed_api,
        "returncode": proc.returncode,
        "output": proc.stdout.strip(),
        "stderr": proc.stderr.strip()[-4000:],
        "duration_s": round(time.time() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug", help="directive filename without .md, e.g. add_webhook")
    ap.add_argument("--payload", help="JSON object passed to the directive")
    ap.add_argument("--tools", default="", help=f"comma-separated: {','.join(sorted(AVAILABLE_TOOLS))}")
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, spawn nothing")
    ap.add_argument(
        "--allow-billed-api",
        action="store_true",
        help="opt in to paid-API billing; also requires ALLOW_BILLED_API=1 in the env",
    )
    args = ap.parse_args()

    payload = json.loads(args.payload) if args.payload else None
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]

    try:
        if args.dry_run:
            print(build_prompt(args.slug, payload, tools))
            return 0
        result = run(
            args.slug,
            payload,
            tools,
            timeout=args.timeout,
            allow_billed_api=args.allow_billed_api,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(result["output"] or result.get("error", ""))
    if not result["ok"]:
        print(f"\n--- run failed ({result.get('error') or result.get('returncode')}) ---", file=sys.stderr)
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
