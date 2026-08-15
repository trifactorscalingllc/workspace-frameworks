# Agent Instructions

> This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment.

You operate within a 3-layer architecture that separates concerns to maximize reliability. LLMs are probabilistic, whereas most business logic is deterministic and requires consistency. This system fixes that mismatch.

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**
- Basically just SOPs written in Markdown, live in `directives/`
- Define the goals, inputs, tools/scripts to use, outputs, and edge cases
- Natural language instructions, like you'd give a mid-level employee

**Layer 2: Orchestration (Decision making)**
- This is you. Your job: intelligent routing.
- Read directives, call execution tools in the right order, handle errors, ask for clarification, update directives with learnings
- You're the glue between intent and execution. E.g you don't try scraping websites yourself—you read `directives/scrape_website.md` and come up with inputs/outputs and then run `execution/scrape_single_site.py`

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `execution/`
- Environment variables, api tokens, etc are stored in `.env`
- Handle API calls, data processing, file operations, database interactions
- Reliable, testable, fast. Use scripts instead of manual work.

**Why this works:** if you do everything yourself, errors compound. 90% accuracy per step = 59% success over 5 steps. The solution is push complexity into deterministic code. That way you just focus on decision-making.

## Operating Principles

**1. Check for tools first**
Before writing a script, check `execution/` per your directive. Only create new scripts if none exist.

**2. Self-anneal when things break**
- Read error message and stack trace
- Fix the script and test it again (unless it uses paid tokens/credits/etc—in which case you check w user first)
- Update the directive with what you learned (API limits, timing, edge cases)
- Example: you hit an API rate limit → you then look into API → find a batch endpoint that would fix → rewrite script to accommodate → test → update directive.

**3. Update directives as you learn**
Directives are living documents. When you discover API constraints, better approaches, common errors, or timing expectations—update the directive. But don't create or overwrite directives without asking unless explicitly told to. Directives are your instruction set and must be preserved (and improved upon over time, not extemporaneously used and then discarded).

## Auth — do not break this

Directive runs must bill the **claude.ai subscription**, not the paid API.

The CLI picks its auth mode from the environment, and there is no flag for it:

- `ANTHROPIC_API_KEY` present → billed API (wrong)
- `ANTHROPIC_API_KEY` absent → Keychain subscription login (what we want)

So the subscription path is simply the default, and the entire job is keeping
that variable out of the child environment. Rules that follow from this:

1. Never call the Anthropic SDK from `execution/`. Runs shell out to `claude -p`.
   Reintroducing `import anthropic` silently reintroduces billing.
2. Every spawn builds its env with `execution/lib/childenv.py:build_child_env()`,
   which strips `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` and raises if
   either survives. Never pass `os.environ` straight to a subprocess.
3. Choose the model with the `ANTHROPIC_MODEL` env var, never a `--model` flag.
4. The key never lives in `.env` under its real name. It is stored renamed as
   `ANTHROPIC_API_KEY_DISABLED`, and `config.py` deletes the real name from the
   process on load anyway.
5. Runs need Keychain access, so they run as the logged-in user. A daemon under
   another user, or any sandbox without Keychain, is the *only* case that
   legitimately needs a key — and that choice must be explicit, never a default.
6. Operational failure mode: if this Mac reboots and nobody logs in at the GUI console,
   the login keychain stays locked and every headless run fails with an auth error until
   someone logs in. The symptom looks like broken auth; the cause is a locked keychain.
   Verified working over Remote-SSH on 2026-08-14 with the console session logged in.

`python execution/preflight.py --probe` audits all of this and proves a keyless
spawn works. Run it before trusting a new machine or after changing shell config.

## Self-annealing loop

Errors are learning opportunities. When something breaks:
1. Fix it
2. Update the tool
3. Test tool, make sure it works
4. Update directive to include new flow
5. System is now stronger

## File Organization

**Deliverables vs Intermediates:**
- **Deliverables**: Google Sheets, Google Slides, or other cloud-based outputs that the user can access
- **Intermediates**: Temporary files needed during processing

**Directory structure:**
- `.tmp/` - All intermediate files (dossiers, scraped data, temp exports). Never commit, always regenerated.
- `execution/` - Python scripts (the deterministic tools)
- `directives/` - SOPs in Markdown (the instruction set)
- `.env` - Environment variables and API keys
- `credentials.json`, `token.json` - Google OAuth credentials (required files, in `.gitignore`)

**Key principle:** Local files are only for processing. Deliverables live in cloud services (Google Sheets, Slides, etc.) where the user can access them. Everything in `.tmp/` can be deleted and regenerated.

## Event-driven runs (local receiver)

Webhook/event-driven execution runs on this Mac as the logged-in user, so runs keep
the subscription login. Each webhook maps to exactly one directive with scoped tool access.

⚠️ **Do not reintroduce Modal.** Modal containers are Linux sandboxes with no Keychain,
no OAuth profile, and no `claude` CLI — a Modal-hosted run *must* bill the paid API,
which defeats the entire auth design above. The receiver is installed as a launchd
**LaunchAgent** in the logged-in (Aqua) session; a system LaunchDaemon has no Keychain
access and will fail.

Keep an `ALLOW_BILLED_API=1` gate, defaulting OFF, as the deliberate opt-in for any
future hosted path.

Every POST requires an `X-Webhook-Token` header matching `WEBHOOK_TOKEN`. If that variable is unset the endpoints return 401 rather than running unauthenticated. The read-only `GET /webhooks` and `GET /health` routes are unauthenticated.

**Available tools for webhooks**

Connector-backed (use the claude.ai Google OAuth already on this Mac — no
`credentials.json`, no sign-in): `drive_search`, `drive_read`. Read-only.

Python-backed (deterministic Layer 3, but need a Google OAuth `token.json`
minted once from an interactive shell): `send_email`, `read_sheet`,
`update_sheet`. A run granted one of these refuses up front, with instructions,
rather than discovering the gap mid-flight.

The grant is enforced, not advisory: `run_directive.py` passes it to the CLI as
`--allowedTools`, and a non-interactive run cannot approve anything else. Do not
rely on `.claude/settings.json` for this — its `permissions.allow` is silently
ignored until the workspace has been trusted interactively, which a headless
service must not depend on. Note the boundary is not a sandbox: trivially-safe
read-only commands (`whoami`) are auto-approved. Network egress, file writes,
and ungranted scripts are blocked.

**All webhook activity streams to Slack in real-time.**

## Summary

You sit between human intent (directives) and deterministic execution (Python scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.

Use Claude Opus 5 (`claude-opus-5`) for everything while building — it's the current top-tier model. Webhook runs read it from `ANTHROPIC_MODEL` in `.env`, so change it there rather than hardcoding a model in a script. Model names move fast; if one in this file looks unfamiliar or stale, look it up before assuming it's wrong.