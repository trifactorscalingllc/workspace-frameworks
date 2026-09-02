<!-- syntax:begin -->
## Reply style = Syntax (Evan 2026-09-01 — machine-wide, every workspace)
Every Claude chat on this machine runs the **Plain English** output style (`~/.claude/output-styles/plain-english.md`,
source `syntax/` in `trifactorscalingllc/workspace-frameworks`) with summarized thinking. Answer first, under 8 lines,
numbers in tables, no narration, one question at most. It is a CHAT rule: documents, reports, emails, posts and plans
keep their own brief; Discord follows `brain/discord-style.md`; a skill's own output format wins. When asked to
"explain" / "walk me through" / "long version", go long.
Off, smallest first: say "long version" · `/output-style` → Default (this chat only) · `"outputStyle": "default"` in a
project's `.claude/settings.json` · `--settings '{"outputStyle":"default"}'` on a spawned session · `syntax off`
(whole machine; `frame syntax off` on Windows). `syntax status` or `/syntax` shows the state. Changes apply to the
next new chat. Full spec and nuance table: `syntax/SYNTAX.md`. Never edit the installed file; edit the repo and push.
<!-- syntax:end -->
