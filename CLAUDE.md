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

**Public URL.** The receiver is published through the existing Tailscale funnel:

    https://trifactors-mac-mini-1.tailff8e29.ts.net/runner

Funnel = public (correct for external callers); serve = tailnet-only. The mount
strips the prefix, so `/runner/directive?slug=x` reaches the receiver's
`/directive` route. Routes:

    GET  /runner/health                     unauthenticated, no secrets
    GET  /runner/webhooks                   token required
    POST /runner/directive?slug={slug}      token required
    POST /runner/test-email                 token required

Everything except `/health` requires an `X-Webhook-Token` header matching
`WEBHOOK_TOKEN`; an unset token means 401 rather than an unauthenticated run.
`/webhooks` is authenticated because the catalog names every automation and its
tools. `/health` deliberately reports only ok/model/label — never the workspace
path — because a tunnel proxies from loopback, so the receiver cannot tell a
local caller from the internet.

Do not test public reachability from the mini: Tailscale ingress refuses
hairpin connections from its own node, so even mounts that have worked for
months fail there. Test from a device off the tailnet.

**Available tools for webhooks**

Connector-backed — use the claude.ai Google OAuth already on this Mac, so no
`credentials.json` and no sign-in:

- `drive_search`, `drive_read` — read-only Google Drive. A Sheet reads back as
  text/CSV, not cells.
- `gmail_draft` — leaves a draft in Gmail. It cannot send; sending is a separate
  connector tool that is deliberately not granted. Unattended runs draft, a
  human presses send.

Python-backed (deterministic Layer 3, but need a Google OAuth `token.json`
minted once via `python execution/setup_google_auth.py`): `send_email`,
`read_sheet`, `update_sheet`. A run granted one of these refuses up front, with
instructions, rather than discovering the gap mid-flight. Note `send_email`
really sends — prefer `gmail_draft` in webhook grants, and `--dry-run` while
iterating.

There is no connector that writes to a Sheet. `update_sheet` is the only path,
and it needs the OAuth token.

The grant is enforced, not advisory: `run_directive.py` passes it to the CLI as
`--allowedTools`, and a non-interactive run cannot approve anything else. Do not
rely on `.claude/settings.json` for this — its `permissions.allow` is silently
ignored until the workspace has been trusted interactively, which a headless
service must not depend on. Note the boundary is not a sandbox: trivially-safe
read-only commands (`whoami`) are auto-approved. Network egress, file writes,
and ungranted scripts are blocked.

## Converting an old topic folder into this shape

The folders at `/Users/tfs/` — `arnie`, `tom`, `keenan-bot`, `pb-assistant`,
`projects/` — predate this template. `ingest_topic` inventories one and
**proposes** how it could become a directive plus a webhook. It is propose-only:
it writes to `.tmp/ingest/<topic>/` and nowhere else.

**The rule that governs everything here: never restructure a source folder.**
Conversion is additive. The new workspace is built beside the old folder, which
stays intact and running until a human retires it. This is not caution for its
own sake — an audit on 2026-08-14 found ~95 LaunchAgents and 33 live processes
rooted in those folders, and this Mac has **no Time Machine and no APFS
snapshots**. The only pre-existing backup is `~/Library/Scripts/fleet-backup.sh`,
covering seven repos with GitHub remotes.

The pipeline is three tools, in this order, and skipping one defeats the point:

1. `snapshot_topic.py --path <dir>` then `--verify <snapshot>`. An APFS
   copy-on-write clone into `~/.topic-snapshots/` (0700, because a faithful
   backup contains the folder's `.env`). 3,615 files in 1.2s. **An unverified
   backup is not a backup** — `--verify` re-hashes against the manifest.
2. `preflight_topic.py --path <dir>`. The refusal gate. Exit 1 means blocked;
   report it and stop rather than working around it. It blocks on: other folders
   symlinking *into* this one, this folder borrowing config from elsewhere, live
   processes, container folders, and no off-disk backup.
3. `scan_topic.py --path <dir>`. Read-only, credential-scrubbed inventory.

`apply_ingest.py` promotes a proposal into `directives/` + `webhooks.json`, always
`"enabled": false`, refusing to overwrite a directive or rebind a slug. It is
deliberately **not** in any webhook's tool grant: promotion is a human action.

Three things the audit established, which the tools now encode:

- **`tom` is a dependency hub, not a topic.** 35 symlinks point into it; six
  sibling bots take `node_modules` from `tom/bot/`, and every `tom-agents/*`
  borrows `node_modules`, `output` *and* `.env` from it. Restructuring `tom`
  breaks sixteen other folders. It is not convertible today at any level of care.
- **Credentials live in prose, not just in `.env`.** Seven live GHL keys were
  found written into a `brain/stack.md` as documentation. So redaction is by
  *shape* (high-entropy runs, prefixed-UUID tokens) as well as by filename, and
  is deliberately biased toward over-redaction — a scrubbed inventory is still
  perfectly usable for deciding what a folder does.
- **Claude's own state is keyed to the absolute path.** 47 directories under
  `~/.claude/projects/` and 26 `.claude.json` entries. If a folder is ever
  retired, leave a stub `CLAUDE.md` pointing at the replacement: a stale one is
  worse than a missing one, because it instructs the next agent to work against a
  layout that no longer exists.

## Setting up in a new workspace

This repo is a template. To spin up a new workspace from it, double-click
**`New Workspace.command`** in Finder (it prompts for a name, creates the
folder, bootstraps it, and opens it in VS Code), or:

```bash
python3 execution/new_workspace.py "Acme Onboarding"
```

If you instead copied or cloned the folder by hand, run:

```bash
python3 execution/bootstrap.py
```

That creates the venv, installs dependencies, writes a `.env` with a generated
`WEBHOOK_TOKEN` and a free port, copies Google OAuth files from a sibling
workspace when there is exactly one to copy from, and runs preflight. Use
system `python3` — it is stdlib-only precisely because it runs before the venv
it creates. Then start building; nothing below is required to begin.

Copies are independent by construction: the launchd label and log directory
derive from the folder name, and each workspace gets its own port. Two
workspaces can run at once. The installer refuses, without changing anything,
if another workspace already holds the port.

A new workspace opens primed — Explorer left, Welcome closed, Claude as a tab
in the middle — via a first-launch-only rule in `.vscode/settings.json`. It has
to be first-launch-only: `claude-vscode.editor.open` calls `createPanel()`, so
it always makes a new tab, and VS Code restores the Claude webview on later
opens. Priming needs the folder **trusted** (both extensions declare
`untrustedWorkspaces: false`), and trust is stored by the VS Code client, not
here — so it cannot be pre-set from this machine. Tick *trust the parent
folder* once and every workspace created there inherits it.

The rest of this section is what `bootstrap.py` automates, plus the parts it
cannot do for you. Every step exists because skipping it cost real time — the
notes in *Traps* are failures actually hit, not theory.

### 1. Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Use the venv for everything. A Homebrew Python is externally managed, so a bare
`pip install` fails, and — more importantly — a directive run must call the
interpreter by absolute path (see Traps).

### 2. Prove auth before anything else

```bash
.venv/bin/python execution/preflight.py --probe
```

Must be all-pass. `--probe` spawns a real keyless `claude -p`, which is the only
honest proof that the subscription path works on this machine.

### 3. Google access — pick the path that fits

**Connector path — nothing to set up.** A headless `claude -p` child inherits
the claude.ai connectors of the logged-in account, so `drive_search`,
`drive_read` and `gmail_draft` work immediately: no `credentials.json`, no
consent screen. Prefer this whenever reading is enough.

**Python path — needed only for Sheets *writes*** (no connector can write to a
Sheet) **and for really sending mail**:

```bash
.venv/bin/python execution/setup_google_auth.py --check    # says exactly what is missing
```

It prints the Google Cloud steps when there is no OAuth client. Two things that
are easy to get wrong:

- Create the client as **Desktop app**.
- **Enable the APIs in the same project as the client.** Granted scopes and
  enabled APIs are independent: a project will happily issue a valid Sheets
  token while the Sheets API is switched off, and the failure only appears at
  first use. `--check` probes for this and prints the activation URL.

Then consent. If the person consenting is not sitting at this Mac:

```bash
.venv/bin/python execution/setup_google_auth.py --remote          # prints a link
.venv/bin/python execution/setup_google_auth.py --finish '<url>'  # redeem it
```

The link opens anywhere. After approval the browser lands on
`http://localhost:8765` and **fails to load — that is the expected outcome**.
Google only accepts `localhost`/`127.0.0.1` as a Desktop-client redirect (never
a LAN IP or public host), so on any other device that address points at that
device. The authorization code is in the address bar; `--finish` redeems it.
The code is single-use and expires in minutes.

### 4. Install the receiver

```bash
.venv/bin/python execution/install_agent.py           # probes, installs, starts
.venv/bin/python execution/install_agent.py --status
```

### Traps

**Headless runs cannot answer a permission prompt.** This is the big one. A
`claude -p` child that is not given a tool explicitly cannot use it, and cannot
ask — it simply fails having done nothing. So:

- The grant in `webhooks.json` must reach the CLI as `--allowedTools`.
  `run_directive.py` does this; it is what makes the grant a real boundary.
- **Do not rely on `.claude/settings.json`.** Its `permissions.allow` is
  silently ignored until the workspace has been trusted through an interactive
  session. A headless service must not depend on that. (Trust it anyway if you
  want fewer prompts while working interactively.)
- Put the prompt **before** `--allowedTools`. The flag is variadic and will
  swallow a trailing prompt as one more tool name.
- Pass `stdin=subprocess.DEVNULL`. A webhook run has no console, and an
  inherited stdin makes children behave unpredictably.
- The boundary is a capability limit, not a sandbox: trivially-safe read-only
  commands (`whoami`) are auto-approved. Network egress, file writes, and
  ungranted scripts are blocked.

**launchd's PATH has no bare `python`.** Telling a run to type `python foo.py`
earns exit 127. Use `config.PYTHON`, which is the venv interpreter's absolute
path. Same class of bug for `claude` itself: `install_agent.py` writes an
explicit PATH into the plist, and deliberately does **not** resolve the `claude`
symlink, because its target is version-stamped and would break on the next
update.

**`launchctl bootout` is asynchronous.** Bootstrapping immediately after it
fails with a bare I/O error and leaves nothing running. Wait for the service to
leave the domain first.

**The receiver caches Python, not data.** Directives and `webhooks.json` are
re-read per request, so editing them needs no restart. Anything in `execution/`
is imported once at startup — add a tool to `TOOLS` and the running service
still calls it unknown, which reads like a typo in `webhooks.json` and is not
one. Re-run `install_agent.py` after any Python change.

**Verify a token against what it can actually do.** Checking a send-only Gmail
token with `users().getProfile()` fails, because that needs a *read* scope —
reporting a healthy token as broken. Use the `tokeninfo` endpoint, which needs
no scope and reports what was really granted, and confirm a refresh token
exists or unattended runs die an hour later.

**Drafts, not sends, for anything unattended.** `gmail_draft` cannot send —
only `create_draft` is granted. `send_email` delivers immediately with no human
in the loop; keep it out of webhook grants unless that is genuinely wanted, and
use `--dry-run` while iterating.

## Summary

You sit between human intent (directives) and deterministic execution (Python scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.

Use Claude Opus 5 (`claude-opus-5`) for everything while building — it's the current top-tier model. Webhook runs read it from `ANTHROPIC_MODEL` in `.env`, so change it there rather than hardcoding a model in a script. Model names move fast; if one in this file looks unfamiliar or stale, look it up before assuming it's wrong.