---
description: Syntax, the machine-wide Plain English reply style — status, on, off, thinking summary|full
allowed-tools: Bash
---

Manage Syntax, the machine-wide reply style (the Plain English output style plus summarized thinking).

Run this exactly, passing the user's words through (no words = status):

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$USERPROFILE/.claude/bin/frame.ps1" syntax $ARGUMENTS
```

Report the single line it prints and nothing else. Valid words: `status`, `on`, `off`,
`thinking summary`, `thinking full`. A change applies to the next new chat, not this one; say so once.

To change the rules themselves, edit `syntax/plain-english.md` in the workspace-frameworks repo and push;
`frame update` brings the new copy down. Never edit `%USERPROFILE%\.claude\output-styles\plain-english.md`
directly. The full spec is `syntax/SYNTAX.md` in the registry (`%USERPROFILE%\.frameworks`).
