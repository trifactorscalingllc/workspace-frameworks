---
description: Apply the BPO delivery framework (Baseline / Proof / Outcome) to this workspace
allowed-tools: Bash
---

Apply the BPO delivery framework to the current workspace.

Run this exactly:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$USERPROFILE/.claude/bin/frame.ps1" bpo
```

Then report, briefly:

- What it added, or
- That BPO was already applied and nothing was needed, or
- That it refused, and why.

It refuses — writing nothing — when the folder already has its own `baseline/`,
`work/` or `proof/`. That is correct behaviour, not a failure. Say so plainly and
offer a fresh workspace beside it instead. Do not work around the refusal.

If the folder already had a CLAUDE.md, BPO's rules are written to `BPO.md` rather
than overwriting it. Say so, and read `BPO.md` before doing delivery work there.

Do not create any BPO files yourself with Write or Edit. The script is the only
sanctioned path.

After it succeeds, explain the discipline in one short paragraph — do not paste the
whole rubric:

- **baseline/** — one file per metric, measured **before** the work starts, with the
  exact metric name, value, unit, date, and a source someone could re-pull.
- **work/** — what was actually done, dated. Facts, not impact claims.
- **proof/** — the outcome, citing its baseline, measured on the **same metric and
  unit**, plus `confounders`: what else could explain the change.
- `python3 check_bpo.py` verifies the claim holds up. It reports and never blocks.

Then say the one thing that matters most: **take the baseline before touching
anything.** The most common way this goes wrong is starting work and measuring
later — at which point no honest before-number exists and the checker will say so.
If there is genuinely no prior data, record the baseline with `value: unknown` so
the gap is visible now rather than discovered in a client report.

If the user is already mid-project with no baseline, do not invent one. Tell them
what they can still legitimately claim (that the work shipped, on what date) and
what they cannot (a measured change), and record the baseline as contaminated with
the reason.
