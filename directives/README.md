# Directives

Layer 1 of the architecture: SOPs in Markdown. One file per job, named for its
slug (`daily_digest.md` → slug `daily_digest`).

Directives are the instruction set, not scratch paper. Improve them over time;
don't overwrite or discard them. Ask before creating or replacing one unless
you were explicitly told to.

## Shape

```markdown
# Directive: <slug>

One line on what this accomplishes.

## Goal
What "done" looks like, in outcomes, not steps.

## Inputs
What arrives in the payload, and what to do when a field is missing.

## Steps
Numbered. Name the exact script to call, with its flags.

## Output
The deliverable. Cloud-hosted (Sheet, Doc, email) — not a local file.

## Edge cases
Rate limits, empty inputs, partial failures, retries, timing.
```

## Writing rules

- Address a mid-level employee: clear intent, no Python.
- Name scripts explicitly — `python execution/tools/read_sheet.py --sheet-id ...`.
  Checking `execution/` for an existing tool comes before writing a new one.
- Put every constraint you learn the hard way into **Edge cases**. That section
  is where the system anneals: an API limit discovered at 2am belongs here, not
  in someone's memory.
- Deliverables live in cloud services the user can open. `.tmp/` is for
  intermediates and is disposable.
- If a link ends up in front of a person, it must be publicly reachable — no
  `localhost`, LAN IPs, Tailscale IPs, or mini file paths.

## Running one

```bash
python execution/run_directive.py <slug> --dry-run
python execution/run_directive.py <slug> --payload '{"k":"v"}' --tools read_sheet,send_email
```
