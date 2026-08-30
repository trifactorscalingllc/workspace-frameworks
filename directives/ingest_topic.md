# Directive: ingest_topic

Inventory one topic folder and **propose** how it could become a directive plus a
runnable webhook. Propose only — this directive changes nothing outside `.tmp/`.

## Goal

Someone can point at a folder like `/Users/tfs/slim-bot` and get back a written
answer to three questions: **is it safe to touch, what does it actually do, and
what would it look like in this template's shape.** The deliverable is a
proposal a human reads and decides on — not a converted folder.

The folders this runs against are live systems, not archives. On 2026-08-15 the
audit found ~95 LaunchAgents and 33 running processes rooted in them. So the
governing rule, which overrides anything else in this file:

> **Never restructure a source folder.** Conversion is additive: the new
> workspace is built beside the old folder, which stays intact and running until
> a human retires it. Nothing here moves, edits or deletes anything under the
> topic root.

## Inputs

From the webhook payload:

- `path` — the topic folder. Required. An absolute path, or a name resolved
  under `/Users/tfs`.
- `max_files` — inventory cap. Default 4000. `arnie` is 2,821 files, so a cap is
  the difference between a usable inventory and a wall of noise.
- `snapshot` — `true` (default) to take a verified backup first, `false` only
  when the caller has already taken one.

If `path` is missing or is not a directory, stop and say so. Do not guess a
folder.

## Steps

### 1. Back it up, and prove the backup

```bash
/Users/tfs/directive-runner/.venv/bin/python execution/tools/snapshot_topic.py --path <path>
/Users/tfs/directive-runner/.venv/bin/python execution/tools/snapshot_topic.py --verify <snapshot-dir>
```

This Mac has **no Time Machine and no APFS snapshots** — verified 2026-08-15.
The only other backup is `fleet-backup.sh`, covering seven repos. So the
snapshot is often the only copy that exists. `--verify` re-hashes the clone
against its manifest; a snapshot that reports anything but `intact` means stop.

The clone is an APFS copy-on-write clone: 3,615 files in 1.2s, sharing blocks
rather than duplicating them.

### 2. Ask whether this folder may be converted at all

```bash
/Users/tfs/directive-runner/.venv/bin/python execution/tools/preflight_topic.py --path <path>
```

**Exit 1 means blocked. Report the blocks and stop.** Do not look for a way
around them, and do not proceed to step 3 with a "just inventorying, it's
read-only" rationale — the point of the gate is that the human sees the blocker
before anyone invests in a proposal.

Each block prints its own remedy. The five that fire in practice:

- `dependency_hub` — other folders symlink *into* this one. `tom` has 35 such
  links; restructuring it breaks sixteen other folders, not itself.
- `not_self_contained` — this folder borrows config or data from elsewhere.
  Every `tom-agents/*` project symlinks its `.env` to `tom/.env`.
- `absolute_path_coupling` — it hard-codes `/Users/tfs/<other>` in executable
  code. No symlink is involved, so the symlink checks pass while the folder is
  still not liftable: `academy-assistant` imports three modules from
  `/Users/tfs/shared/`, and `arnie` reads a Groq key out of
  `/Users/tfs/.config/watch/.env`. Mentions in prose or comments are a warning,
  not a block — only executable references break when a folder moves.
- `live_processes` — something is executing out of the folder right now.
- `container` — it holds N sub-projects (`projects/` has 43). Re-run against one.
- `no_offdisk_backup` — no git remote and not in `fleet-backup.sh`.

Warnings are carried into the proposal, not silenced. Two matter most at cutover:
`launchd_wiring` (every active label has to be rewritten or booted out) and
`launchd_paused` — `academy-assistant` has two `com.tfs.*.plist.paused` files, so
`launchctl list` shows nothing while the wiring sits one rename from live. Never
read "nothing loaded" as "nothing wired".

### 3. Inventory it

```bash
/Users/tfs/directive-runner/.venv/bin/python execution/tools/scan_topic.py --path <path> [--max-files N]
```

Writes `.tmp/ingest/<topic>/inventory.json`. Read that, not the folder — the
scanner is the only thing that should open these files, because it is the thing
that scrubs them. Credential values are replaced with `«redacted»` before
anything reaches you; secret files are never opened for content at all, only for
their variable *names*.

If `truncated.files` is non-zero, say so in the proposal. A capped inventory
that reads as complete is worse than one that admits its limits.

### 4. Decide the relationship — and be willing to say no

Pick exactly one verdict. Most folders are `wrap` or `mirror`; `migrate` is rare.

| Verdict | When |
|---|---|
| `wrap` | The folder keeps running as-is; a directive adds a review or report surface over it. **The default.** |
| `mirror` | Only the knowledge is worth moving. Write the SOP, leave the code. |
| `migrate` | Genuinely request/response shaped, self-contained, and small. |
| `no-fit` | It is a long-running process — a Discord bot, a server. Not webhook-shaped. |

`no-fit` is a successful outcome, not a failure. Forcing a persistent process
into a request/response directive is how this goes wrong. Use `triggers` in the
inventory as evidence: a `discord` or `http` trigger with no `cron` is almost
never `migrate`.

### 5. Write the proposal to `.tmp/ingest/<topic>/`

Use `stage_proposal.py` — it is the only write tool in this grant, and it can
only write these three filenames into `.tmp/ingest/<topic>/`. **Nothing goes into
`directives/` or `webhooks.json`; that is step 6, and a human does it.**

```bash
/Users/tfs/directive-runner/.venv/bin/python execution/tools/stage_proposal.py \
  --topic <topic> --part proposal <<'EOF'
# Proposal: <topic>
...
EOF
```

Three parts:

- `--part proposal` → the verdict and why; what the folder does; the preflight
  blocks and warnings verbatim; the proposed tool grant with a line justifying
  each tool; **leftovers**, meaning everything in the folder with no home in this
  template, named explicitly so nobody assumes it came across; and the cutover
  checklist, including every launchd label — **paused ones included**.
- `--part directive` → a full directive draft in the shape
  `directives/README.md` specifies. Real content, no placeholders.
- `--part webhook --slug <s> --description <d> --tools <a,b> --verdict <v>` →
  grant the fewest tools that can do the job. Tool names are validated here, so
  an invented one fails now rather than at promotion.

For a `no-fit` verdict, write `--part proposal` and stop: there is nothing to
promote, and a directive draft for a job that should not be a directive is worse
than none.

You may propose more than one directive, or none. A folder does not owe you
exactly one job.

### 6. Hand it back

Report the verdict, where the proposal is, and the exact command a human runs to
promote it — noting that they should read `proposal.md` first:

```bash
python execution/tools/apply_ingest.py --topic <topic> --dry-run
python execution/tools/apply_ingest.py --topic <topic>
```

`apply_ingest` is deliberately **not** in any webhook's tool grant. Promotion is
a human action.

## Output

- A verified snapshot under `/Users/tfs/.topic-snapshots/`
- `.tmp/ingest/<topic>/` — `inventory.json`, `proposal.md`,
  `proposed_directive.md`, `proposed_webhook.json`
- A report stating the verdict, the blocks, and the promotion command
- **No change to `directives/`, `webhooks.json`, or the source folder**

## Edge cases

- **Blocked at preflight** — report and stop. This is the common outcome and it
  is the tool working, not failing.
- **`tom` and anything hanging off it** — not convertible at any level of care
  today: 35 inbound symlinks, ~45 LaunchAgents, 34 live processes, and 2,059
  Claude session transcripts keyed to its path. Untangling it is a separate
  project. Say that plainly rather than proposing a partial conversion.
- **Credentials in prose.** The audit found seven live GHL credentials written
  into a `brain/stack.md` as documentation. The scanner redacts by shape as well
  as by filename, but if you ever see something key-shaped that was *not*
  redacted, stop and report it — do not copy it into the proposal.
- **A `.env` that is a symlink** — every `tom-agents/*` borrows `tom/.env` and
  its ~37 credentials. The scanner resolves before matching, so contents stay
  unread, but preflight blocks these folders anyway: a folder that cannot supply
  its own config cannot be lifted anywhere.
- **Claude state is keyed to the absolute path.** 47 directories under
  `~/.claude/projects/` and 26 `.claude.json` entries. If a folder is ever
  retired, leave a stub `CLAUDE.md` pointing at the replacement. A stale
  `CLAUDE.md` is worse than a missing one — it actively instructs the next agent
  to work against a layout that no longer exists.
- **Truncated inventory** — always disclose. See step 3.
- **Idempotency** — re-running is safe: the scan overwrites its own inventory and
  `apply_ingest` refuses to overwrite a directive or rebind a slug. Snapshots are
  timestamped, so repeated runs accumulate; prune old ones by hand.
- **Never `--force` a snapshot** to get past the free-space guard without saying
  so in the report. The guard budgets for the clone fully diverging.
