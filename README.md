# directive-runner

A 3-layer agent system: Markdown SOPs (`directives/`) describe the work, a model
routes, and deterministic Python (`execution/`) does it. The architecture and
the rules that govern it live in [CLAUDE.md](CLAUDE.md) — read that first;
this file is just setup.

## Setup

```bash
python3 execution/bootstrap.py
```

One command: venv, dependencies, a `.env` with a generated `WEBHOOK_TOKEN` and a
free port, Google OAuth files copied from a sibling workspace if there is one,
then preflight. Run it with system `python3` — it is stdlib-only because it runs
before the venv it creates.

Preflight must pass before you trust the machine. It checks that no billing
variable can reach a child process, and `--probe` proves a keyless spawn answers.

## New workspace from this template

Double-click **`New Workspace.command`** in Finder. It asks for a name, creates
the workspace next to this one, bootstraps it, and opens it in VS Code.

**In VS Code** (including over Remote-SSH, where Finder on your laptop cannot
see the mini's files): `Cmd+Shift+P` -> *Tasks: Run Task* -> **New Workspace**.
It prompts for the name in VS Code itself. The same menu has tasks for
preflight, the receiver, and Google auth status.

Or from a terminal:

```bash
python3 execution/new_workspace.py "Acme Onboarding"        # -> ../acme-onboarding
python3 execution/new_workspace.py client-x --dest ~/projects --open
```

Copies are independent — the launchd label and log directory come from the
folder name and each claims its own port, so several run side by side. Google
OAuth files are copied across, so there is no second consent. The new
workspace's git remote is named `template`, not `origin`: it cannot accidentally
push back, and `git pull template main` still brings improvements over.

A clone carries committed state only, so commit anything the new workspace
should inherit first — it warns you when the template is dirty.

### Google access

Two paths, and the fast one needs nothing:

- **Connectors (no setup).** `drive_search`, `drive_read`, and `gmail_draft` use
  the claude.ai Google OAuth already on this Mac. Headless runs inherit it.
- **Python tools (one-time consent).** `read_sheet`, `update_sheet`, and
  `send_email` need their own OAuth token — and Sheets *writes* have no
  connector equivalent, so this is the only path to them:

  ```bash
  .venv/bin/python execution/setup_google_auth.py --check   # what's missing
  .venv/bin/python execution/setup_google_auth.py           # run the consent flow
  ```

  It prints the exact Google Cloud steps if `credentials.json` isn't there yet.
  Both `credentials.json` and `token.json` are gitignored.

## Run a directive

```bash
.venv/bin/python execution/run_directive.py daily_digest --dry-run
.venv/bin/python execution/run_directive.py daily_digest \
    --payload '{"date":"2026-08-14"}' --tools read_sheet,send_email
```

## Serve webhooks

The receiver runs on this Mac as the logged-in user, under launchd:

```bash
.venv/bin/python execution/install_agent.py            # probe, install, start
.venv/bin/python execution/install_agent.py --status
.venv/bin/python execution/install_agent.py --uninstall
```

It must be a **LaunchAgent**, never a LaunchDaemon — a daemon has no login
keychain and every run fails on auth. Same reason there is no cloud option: a
Linux container would have to bill the paid API. Don't add one.

It binds to loopback. Put a Cloudflare tunnel or a Tailscale **funnel** in front
of it for public access — funnel is public, serve is tailnet-only.

To run it in the foreground while developing:

```bash
.venv/bin/python execution/local_webhook.py --port 8787
```

## Layout

```text
directives/     Layer 1 — SOPs in Markdown. See directives/README.md.
execution/      Layer 3 — deterministic scripts.
  config.py         paths, .env loading, billing-var scrub (import this first)
  run_directive.py  the only sanctioned way to invoke a model
  bootstrap.py      one-command setup for a fresh copy (stdlib only)
  preflight.py      auth + layout audit; --probe spawns a real keyless run
  setup_google_auth.py  one-time Google consent for the Python tools
  local_webhook.py  the receiver (stdlib only, no web framework)
  install_agent.py  installs it as a launchd LaunchAgent
  webhooks.json     slug -> directive mapping
  lib/              childenv, google_auth, notify
  tools/            send_email, read_sheet, update_sheet
.tmp/           Intermediates. Disposable, always regenerated.
```

## The one rule that breaks everything

`ANTHROPIC_API_KEY` in the environment silently switches runs from the
claude.ai subscription to billed API. Never import the Anthropic SDK in
`execution/`, never hand `os.environ` to a subprocess, and always build child
environments with `execution/lib/childenv.py:build_child_env()`.
