# Directive: add_webhook

Add a new event-driven webhook that runs one directive with scoped tools.

## Goal

Turn a request like "add a webhook that emails me a digest of the leads sheet
every morning" into: a directive file, an entry in `execution/webhooks.json`, a
deployed endpoint, and a passing test call.

## Inputs

- What the webhook should do, in the user's words
- Which existing tools it needs:
  - `drive_search`, `drive_read` — read-only Google Drive through the claude.ai
    connector. Work today; no credentials file, no sign-in.
  - `send_email`, `read_sheet`, `update_sheet` — Python tools. Deterministic,
    but blocked until a Google OAuth `token.json` exists.
- Who or what will call it (cron, Zapier, another service)

## Steps

### 1. Write the directive

Create `directives/<slug>.md`. One webhook maps to exactly one directive. Use
the section order in `directives/README.md`: Goal, Inputs, Steps, Output, Edge
cases. Write it the way you'd brief a mid-level employee — what to do and what
"done" looks like, not Python.

Ask before creating a directive unless the user explicitly told you to. Never
overwrite an existing one without asking.

### 2. Register it

Add an entry to `execution/webhooks.json` under `webhooks`:

```json
"daily_digest": {
  "directive": "daily_digest",
  "description": "Summarize a tracking sheet and email the digest.",
  "tools": ["read_sheet", "send_email"],
  "enabled": true
}
```

Grant the fewest tools that can do the job. This is a real boundary, not a
suggestion: the grant is handed to the CLI as `--allowedTools`, and a
non-interactive run cannot approve anything outside it. An ungranted script,
network call, or file write fails. (Trivially-safe read-only commands like
`whoami` are still auto-approved — treat the grant as a capability limit, not a
sandbox.)

### 3. Test locally before deploying

```bash
python execution/run_directive.py <slug> --dry-run                 # inspect the prompt
python execution/run_directive.py <slug> --payload '{"date":"2026-08-14"}' --tools read_sheet,send_email
```

A local run bills the claude.ai subscription. Fix the directive until this
works — a broken directive fails the same way in the cloud, just slower.

### 4. Serve it from the LaunchAgent

The receiver runs on this Mac as the logged-in user — that is what keeps runs
on the claude.ai subscription. There is no cloud option; do not add one.

```bash
python execution/install_agent.py            # probes, installs, starts
python execution/install_agent.py --status
```

The installer runs `preflight.py --probe` first and refuses to install if it
fails. It writes `~/Library/LaunchAgents/com.trifactor.directive-runner.plist`
with an explicit `PATH` (launchd's default PATH does not include `~/.local/bin`,
where `claude` lives — that omission is the classic "works by hand, fails under
launchd" bug). Logs land in `~/Library/Logs/directive-runner/`.

It must stay a **LaunchAgent**, in the logged-in Aqua session. A system
LaunchDaemon cannot unlock the login keychain and every run fails on auth.

Already-running instance? Re-run the installer; it boots the old one out first.
While iterating on a directive you don't need to restart at all — the receiver
re-reads `webhooks.json` and the directive file on every request.

### 4b. Expose it

It binds to loopback. Put a public tunnel in front:

- Cloudflare tunnel, or
- Tailscale **funnel** — funnel is public; **serve** is tailnet-only and will
  not open for anyone off the network.

Never hand anyone a `localhost`, LAN (`192.168.*`), or Tailscale-IP (`100.*`)
URL, or a file path on this Mac. Confirm the URL actually opens from the public
internet before sending it.

### 5. Test the endpoint

```bash
curl -s "$BASE/webhooks"

curl -s -X POST "$BASE/directive?slug=<slug>" \
  -H "X-Webhook-Token: $WEBHOOK_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"trigger":"manual"}'
```

Confirm the run appears in Slack and the side effect actually happened (mail
delivered, row written). A 200 with no side effect is a failure.

## Output

- `directives/<slug>.md`
- an entry in `execution/webhooks.json`
- a reachable endpoint URL, confirmed by a real call
- the tool grant, stated back to the user

## Edge cases

- **`WEBHOOK_TOKEN` unset** → every POST returns 401. This is deliberate: the
  endpoints fail closed rather than running unauthenticated.
- **Slug collision** → refuse and ask; silently rebinding an existing slug
  redirects live traffic.
- **Directive needs a tool that doesn't exist** → write the script in
  `execution/tools/`, add it to `AVAILABLE_TOOLS` in `run_directive.py`, test it
  standalone, then wire the webhook.
- **Long runs** → the receiver is threaded, so concurrent runs are fine.
  `RUN_TIMEOUT` (default 900s) caps a single run; raise it in `.env` and restart
  the agent. Callers usually give up sooner than that — check the caller's own
  timeout before raising ours.
- **Reboot with no console login** → the login keychain stays locked, so every
  run fails with what looks like an auth error. The fix is to log in at the GUI
  console, not to add an API key. `install_agent.py --status` says this out loud
  when the receiver isn't answering.
- **Caller retries on timeout** → runs are not idempotent by default. If the
  webhook writes anything, say so in the directive's Edge cases and have it
  check for an existing row before appending.
