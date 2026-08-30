---
description: Apply the IAE research framework (Identification / Analysis / Evaluation) to this workspace
allowed-tools: Bash
---

Apply the IAE research framework to the current workspace.

Run this exactly:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$USERPROFILE/.claude/bin/doe.ps1" iae
```

Then report, briefly:

- What it added, or
- That IAE was already applied and nothing was needed, or
- That it refused, and why.

It refuses — writing nothing — when the folder already has its own `sources/`,
`analysis/` or `findings/`. That is correct behaviour, not a failure: merging into
those would restructure the user's folder. Say so plainly and offer a fresh
workspace beside it instead. Do not work around the refusal.

If the folder already had a CLAUDE.md (a DOE workspace, say), IAE's rules are
written to `IAE.md` rather than overwriting it. Tell the user, and read `IAE.md`
before doing any research there — otherwise the layers exist with no rules
attached, which looks like success and is not.

Do not create any IAE files yourself with Write or Edit. The script is the only
sanctioned path, so every workspace matches the template and can pull improvements
later with `doe update`.

After it succeeds, explain the discipline in one short paragraph — do not paste the
whole rubric:

- **sources/** — one file per source, each with an id, a locator someone else can
  open, the date accessed, and a reliability tier. No interpretation here.
- **analysis/** — why each source claims what it claims, in your own words, and
  where sources conflict, classified empirical or definitional.
- **findings/** — conclusions, each citing source ids, with a confidence and a
  falsifier: what evidence would change your mind.
- `python3 check_iae.py` verifies the chain holds. It reports and never blocks.

Mention that `sources/COVERAGE.md` is where the search surface is recorded — what
was looked at and what was not — because without it "no source says X" cannot be
told apart from "X is absent from where I happened to look."
