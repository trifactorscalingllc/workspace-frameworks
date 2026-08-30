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

# Tool names a directive may be granted.
#
# `allow` is the real enforcement: a non-interactive `claude -p` cannot answer a
# permission prompt, so anything not passed via --allowedTools is simply blocked
# and the run fails having done nothing. The grant in webhooks.json therefore
# becomes an actual capability boundary, not just a line in the prompt.
#
# `needs` names a prerequisite that may not be satisfied yet; run() refuses a
# tool whose prerequisite is missing rather than letting the run discover it.
TOOLS = {
    # --- Python tools (Layer 3 proper: deterministic, testable) --------------
    "send_email": {
        "how": f"{config.PYTHON} execution/tools/send_email.py --to <addr> --subject <s> --body <b> [--html] [--dry-run]",
        "allow": [f"Bash({config.PYTHON} execution/tools/send_email.py:*)"],
        "needs": "google_oauth",
    },
    "read_sheet": {
        "how": f"{config.PYTHON} execution/tools/read_sheet.py --sheet-id <id> --range <A1:Z> [--header]",
        "allow": [f"Bash({config.PYTHON} execution/tools/read_sheet.py:*)"],
        "needs": "google_oauth",
    },
    "update_sheet": {
        "how": f"{config.PYTHON} execution/tools/update_sheet.py --sheet-id <id> --range <A1:Z> --values-json <json> [--append]",
        "allow": [f"Bash({config.PYTHON} execution/tools/update_sheet.py:*)"],
        "needs": "google_oauth",
    },
    "create_sheet": {
        "how": f"{config.PYTHON} execution/tools/create_sheet.py --title <title> [--tab <name>] [--headers-json <json>] [--if-missing]",
        "allow": [f"Bash({config.PYTHON} execution/tools/create_sheet.py:*)"],
        "needs": "google_oauth",
    },
    # --- Topic ingest (local disk only; no Google auth, no network) ----------
    # Ordered the way a run must use them: back up, ask permission, then look.
    "snapshot_topic": {
        "how": (
            f"{config.PYTHON} execution/tools/snapshot_topic.py --path <dir> "
            "| --verify <snapshot> | --list. APFS clone plus a hash manifest. "
            "Always --verify after taking one; an unverified backup is not a backup."
        ),
        "allow": [f"Bash({config.PYTHON} execution/tools/snapshot_topic.py:*)"],
        "needs": None,
    },
    "preflight_topic": {
        "how": (
            f"{config.PYTHON} execution/tools/preflight_topic.py --path <dir> "
            "[--json]. Decides whether a folder is safe to convert; exit 1 means "
            "blocked. Never work around a block — report it and stop."
        ),
        "allow": [f"Bash({config.PYTHON} execution/tools/preflight_topic.py:*)"],
        "needs": None,
    },
    "scan_topic": {
        "how": (
            f"{config.PYTHON} execution/tools/scan_topic.py --path <dir> "
            "[--max-files N]. Read-only, credential-scrubbed inventory written to "
            ".tmp/ingest/<topic>/inventory.json."
        ),
        "allow": [f"Bash({config.PYTHON} execution/tools/scan_topic.py:*)"],
        "needs": None,
    },
    "stage_proposal": {
        "how": (
            f"{config.PYTHON} execution/tools/stage_proposal.py --topic <name> "
            "--part proposal|directive <<'EOF' ... EOF, or --part webhook --slug "
            "<slug> --description <d> --tools <a,b>. The only way an ingest run "
            "can write, and it can only write into .tmp/ingest/<topic>/."
        ),
        "allow": [f"Bash({config.PYTHON} execution/tools/stage_proposal.py:*)"],
        "needs": None,
    },
    # --- Connector tools (the claude.ai Google OAuth already on this Mac) ----
    # These need no credentials.json: the account is already authorized, and a
    # headless child inherits the connectors. Read-only.
    "drive_search": {
        "how": "Use the Google Drive connector to find files by name, type, or recency.",
        "allow": [
            "mcp__claude_ai_Google_Drive__search_files",
            "mcp__claude_ai_Google_Drive__list_recent_files",
            "mcp__claude_ai_Google_Drive__get_file_metadata",
        ],
        "needs": None,
    },
    "drive_read": {
        "how": (
            "Use the Google Drive connector to read a file's contents. A Google "
            "Sheet comes back as text/CSV — parse it rather than assuming cells."
        ),
        "allow": [
            "mcp__claude_ai_Google_Drive__read_file_content",
            "mcp__claude_ai_Google_Drive__download_file_content",
            "mcp__claude_ai_Google_Drive__get_file_metadata",
        ],
        "needs": None,
    },
    "ig_posts": {
        "how": f"{config.PYTHON} execution/tools/ig_posts.py [--since <ISO>] [--until <ISO>] [--limit N] [--no-insights]",
        "allow": [f"Bash({config.PYTHON} execution/tools/ig_posts.py:*)"],
        "needs": "meta_auth",
    },
    "gmail_draft": {
        "how": (
            "Use the Gmail connector to create a DRAFT. It is never sent — a "
            "human opens Gmail and presses send. Say in your report that you "
            "left a draft, not that you emailed anyone."
        ),
        "allow": ["mcp__claude_ai_Gmail__create_draft"],
        "needs": None,
    },
}


def unmet_prerequisite(tool: str) -> str | None:
    """Return a human-readable reason a granted tool cannot run yet, or None."""
    needs = TOOLS[tool].get("needs")
    if needs == "google_oauth" and not config.TOKEN_FILE.exists():
        return (
            f"{tool} needs Google OAuth: {config.TOKEN_FILE.name} is missing. Mint it "
            "once from an interactive shell, or use the connector-backed tools "
            "(drive_search, drive_read), which need no credentials file."
        )
    if needs == "meta_auth" and not (config.get("META_ACCESS_TOKEN") and config.get("IG_USER_ID")):
        return (
            f"{tool} needs Instagram Graph API access. Run "
            "`python execution/setup_meta_auth.py --check`, which prints the exact "
            "Meta console steps. Nothing else in the system depends on this."
        )
    return None


def directive_path(slug: str) -> Path:
    """Resolve a slug to a directive file, refusing anything outside directives/."""
    name = slug if slug.endswith(".md") else f"{slug}.md"
    path = (config.DIRECTIVES_DIR / name).resolve()
    if config.DIRECTIVES_DIR.resolve() not in path.parents:
        raise ValueError(f"directive slug escapes directives/: {slug!r}")
    return path


def validate_tools(tools: list[str]) -> list[str]:
    """Reject anything not in the grant list. Returns the tools unchanged."""
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        raise ValueError(f"unknown tools: {unknown}. Available: {sorted(TOOLS)}")
    return tools


def allowlist_for(tools: list[str]) -> list[str]:
    """The permission rules a run needs, deduplicated and order-stable."""
    rules: list[str] = []
    for tool in tools:
        for rule in TOOLS[tool]["allow"]:
            if rule not in rules:
                rules.append(rule)
    return rules


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
        parts += [f"- `{t}` — {TOOLS[t]['how']}" for t in tools]
        parts += [
            "",
            "These are the only tools you may use, and the only ones you *can* "
            "use — anything else is blocked by the permission system and this "
            "run cannot answer an approval prompt. If the directive needs "
            "something you were not granted, stop and report that instead of "
            "improvising a workaround.",
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

    blocked = [reason for t in tools if (reason := unmet_prerequisite(t))]
    if blocked:
        return {
            "ok": False,
            "slug": slug,
            "error": "granted tools are not usable yet",
            "details": blocked,
            "duration_s": 0.0,
        }

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
    #
    # The prompt goes FIRST: --allowedTools is variadic and will happily eat a
    # trailing prompt as one more tool name.
    #
    # We pass the grant explicitly rather than relying on .claude/settings.json,
    # whose permissions.allow is silently ignored until the workspace has been
    # trusted through an interactive session — a dependency a headless service
    # should not have.
    cmd = [config.CLAUDE, "-p", prompt]
    if allowed := allowlist_for(tools):
        cmd += ["--allowedTools", ",".join(allowed)]

    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=config.ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or config.RUN_TIMEOUT,
            # A webhook run has no console; never let the child inherit one.
            stdin=subprocess.DEVNULL,
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
        "granted_tools": tools,
        "allowed_rules": allowed,
        "returncode": proc.returncode,
        "output": proc.stdout.strip(),
        "stderr": proc.stderr.strip()[-4000:],
        "duration_s": round(time.time() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug", help="directive filename without .md, e.g. add_webhook")
    ap.add_argument("--payload", help="JSON object passed to the directive")
    ap.add_argument("--tools", default="", help=f"comma-separated: {','.join(sorted(TOOLS))}")
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
