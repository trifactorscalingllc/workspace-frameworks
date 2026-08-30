---
description: Apply the DOE framework to this workspace
allowed-tools: Bash
---

Apply the DOE framework to the current workspace.

Run this exactly:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$USERPROFILE/.claude/bin/frame.ps1" doe
```

Then report, briefly:

- What it added (the layer directories and how many files), or
- That the folder was already a DOE workspace and nothing was needed, or
- That it refused, and why.

It refuses — writing nothing — when the folder already has its own
`directives/` or `execution/`. That is correct behaviour, not a failure: merging
into those would restructure the user's folder, which the DOE rules forbid. If
that happens, say so plainly and offer to create a fresh workspace beside it
with `frame "<Name>"` instead. Do not try to work around the refusal.

Do not create any DOE files yourself with Write or Edit. The script is the only
sanctioned path, so that every workspace matches the template and can pull
improvements later with `frame update`.

After a successful conversion, tell the user their mission goes in a directive
(`directives/<slug>.md` — Goal / Inputs / Steps / Output / Edge cases), never in
CLAUDE.md, since CLAUDE.md/AGENTS.md/GEMINI.md are the mirrored DOE operating
instructions and stay as the template ships them.
