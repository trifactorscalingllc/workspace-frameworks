---
description: List the available project frameworks and which one fits this work
allowed-tools: Bash
---

List the frameworks available to apply to a workspace.

Run this exactly:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$USERPROFILE/.claude/bin/doe.ps1" list
```

Report what it prints, then — only if the user's current work makes it obvious —
say which one fits and why, in one line. If it is not obvious, ask rather than guess:
applying the wrong framework is additive and harmless to undo, but it wastes the
user's attention.

The distinction that matters: **DOE structures work** (automations, scripts,
anything with steps to run), **IAE structures thinking** (reading sources and
reaching a defensible conclusion). A project can have both — IAE applied to a DOE
workspace adds its layers alongside and parks its rules in `IAE.md`.

If the user is asking about a framework that does not exist yet, do not invent one
on the spot. The rule is that a new framework gets extracted from a project that
already worked, never invented in advance — a skeleton nobody has used is one
nobody maintains, and a stale one instructs the next session to work against a
layout that is no longer right.
