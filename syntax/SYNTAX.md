# Syntax — the machine-wide plain-English reply style

Syntax makes every Claude Code chat on a machine answer in short, plain English and show
condensed reasoning. It is **not a workspace framework**: DOE, IAE and BPO shape a *project*,
Syntax shapes how Claude *talks to you*, everywhere, in every present and future workspace.
It is installed once per machine into the user's Claude config and versioned in this repo.

Decided 2026-09-01 (Evan). Source of truth for the rules: [plain-english.md](plain-english.md).

## How it works

| Piece | Where it lands | What it does |
|---|---|---|
| `plain-english.md` | `~/.claude/output-styles/plain-english.md` (symlink on mac, copy on Windows) | A Claude Code **output style**. Its text is inserted into every system prompt and re-stated as a reminder on **every turn** |
| `"outputStyle": "Plain English"` | `~/.claude/settings.json` (user scope) | Selects the style for every workspace on the machine |
| `"showThinkingSummaries": true` | `~/.claude/settings.json` | The API returns condensed thinking; the VS Code extension passes `--thinking-display summarized` to the CLI it spawns. The model still thinks in full |
| `CLAUDE-section.md` | appended to `~/.claude/CLAUDE.md` between `<!-- syntax:begin/end -->` | Documents the rule and the off switches where the fleet rules live |
| `/syntax` | `~/.claude/commands/syntax.md` | Status / on / off from inside a chat |
| `syntax` (mac) · `frame syntax` (Windows) | `~/.local/bin/syntax` · `frame.ps1` | Same switch from a terminal |
| `~/.gemini/GEMINI.md` | Gemini CLI global context | The same rules for Gemini failover sessions (partial, see gaps) |

Install: `bash syntax/install.sh` on a mac; `frame update` on Windows (its installer runs the Syntax step).
Uninstall: `bash syntax/install.sh --uninstall`. Backups of every touched file are kept as `.bak-<stamp>`.

Settings precedence, lowest to highest: user `~/.claude/settings.json` → project `.claude/settings.json` →
project `.claude/settings.local.json` → `--settings` flag on a spawn → managed policy.

## The rules, and the nuances they had to cover

| Situation | Rule | Why it needs saying |
|---|---|---|
| Default reply | Answer first, under 8 lines | The whole point |
| Numbers / comparisons | Table, never prose | Already a fleet rule; repeated because it is the #1 source of verbosity |
| Chart vs table | Chart only when the *shape* of the data is the point (trend, distribution) and a table cannot show it. Render with the media engine, deliver as a public link | Charts are slow and mostly decorative. Discord CDN links expire in ~24h, so a durable chart needs a funneled host |
| Clarifying question | Only when different answers change the work. One question, alone on the last line. Otherwise state the assumption and proceed | Stops both over-asking and silent wrong assumptions |
| "Explain" / "walk me through" / "long version" | Explicit override: go long, use headers | Terse must never fight a direct request |
| Errors | First line says it failed; error in a fenced block; then what was tried | Failures are the one place detail is owed |
| Destructive or irreversible action | Always state exactly what will change, then wait | Brevity must not skip the confirmation |
| Radical candor | Unchanged. "You're doing this wrong" is still line one | Terse is not agreeable |
| Code-change report | What changed, where (links), how to revert | The standing-consent rule needs the after-report |
| Client-facing artifacts (docs, emails, reports, posts) | The style does **not** apply. brand.md, house voice, the skill's brief win | Without this line "under 8 lines" bleeds into a client report |
| Skills with their own format (morning-brief, gut-check, client-report) | The skill wins | A specific instruction beats a general one |
| Plan mode, plan files | Plans are artifacts; as complete as they need to be | Same bleed risk |
| Discord output | `brain/discord-style.md` wins (no emoji, bold numbers, gold) | The chat-side ✅/⚠️ markers would otherwise conflict |
| Links | Fleet rule: public HTTPS only, markdown links | Unchanged |
| Between tool calls | Silent, or one line with the finding | Pairs with VS Code Focus view, which hides mid-turn text anyway |

## Where it applies, and where it must not

| Surface | Covered by | Status |
|---|---|---|
| VS Code chats on the machine, any workspace, any user of that login | user settings + per-turn reminder | on |
| CLI and every Remote Control chat | same | on |
| Bots' headless `claude -p` sessions that use tools | same; `discord-style.md` still binding | on; per-process off exists (below) |
| `claude-bare.mjs` one-shots (classifier, scorer, JSON) | **not** covered: it passes `--setting-sources ''` | correct; must stay that way |
| Subagents (Agent tool) | not covered; the style is main-thread only | fine, they report to Claude, not to you |
| A second machine (a laptop) | its own install from this repo | one run per machine |
| Gemini CLI | `~/.gemini/GEMINI.md` | partial: Antigravity (`agy`) only walks `GEMINI.md` from cwd up to the repo root, not the home dir |
| Claude Desktop, claude.ai web and mobile | nothing reaches those prompts | out of reach; say so, do not promise |

## The reasoning half

- `showThinkingSummaries: true` shortens what is *shown*, not what the model *does*. No quality loss.
- **VS Code Focus view** (Ctrl+Alt+F, or `claudeCode.focusView`) hides tool calls, mid-turn text and folds
  thinking, leaving prompts and final replies. It is an application-scope setting on the founder's own
  VS Code: once per person, then every workspace. It cannot be pushed from another machine.
- Do **not** use the chat panel's "Thinking" toggle to hide reasoning. It turns thinking *off*, which lowers
  quality. Focus view plus summaries is the right pair.
- Leave `alwaysThinkingEnabled`, `MAX_THINKING_TOKENS` and `effortLevel` alone.

## Off switches, smallest to largest

| Scope | How | Effect |
|---|---|---|
| One reply | Say "long version" or "explain fully" | The style yields by design |
| One chat | `/output-style` (or `/config`) and pick Default | That chat only |
| One project | `"outputStyle": "default"` in `<project>/.claude/settings.json` | Project beats user |
| One process or bot | Spawn with `--settings '{"outputStyle":"default"}'` | Flag beats project and user; a one-line change in that bot's spawn |
| Whole machine | `syntax off` (mac) · `frame syntax off` (Windows) | Sets `outputStyle` to default. `syntax on` restores |
| Reasoning display | `syntax thinking full` | Removes `showThinkingSummaries`. `syntax thinking summary` restores |
| VS Code view | Ctrl+Alt+F again | Focus view off |
| Everything | `install.sh --uninstall` | Removes the symlinks, the two keys, the CLAUDE.md and GEMINI.md blocks, the command. Backups stay |

Open chats keep the prompt they started with. Every switch takes effect on the next new conversation.
A re-run of the installer never flips a machine that was switched off: it only sets keys that are absent.

## Changing the rules

Edit [plain-english.md](plain-english.md) here, commit, push to `origin`. The mac follows a symlink, so a
`git pull` is live for the next new chat. A laptop gets the copy on its next `frame update`. Keep the file
short: it rides in every prompt. Never edit the installed copy under `~/.claude/output-styles/` directly.

## Measuring it

`python3 syntax/measure.py` reads the local transcripts and reports, per assistant turn: median words,
share of turns under 8 lines, share opening with narration ("I'll…", "Let me…"), share using a table.
`--compare <ISO time>` prints before/after around the install. Take the baseline **before** installing.

## Known gaps (2026-09-01)

1. The mac has no general installer for the frameworks' `~/.claude` pieces (commands, hook); Windows has
   `Install-Frameworks.ps1`. `syntax/install.sh` is the first mac-side installer piece; parity is a follow-up.
2. Gemini parity is partial (see the surfaces table). Full parity needs a pointer in the DOE template's
   CLAUDE.md, which the fleet rule says stays as shipped. Founder call.
3. Bot-only off is a spawn flag. On the mini the 15 spawners that parse the model's reply as structured data
   (tom/jobs fleet-doctor, grade-checker, hook-lab, canva-edit, the two carousel jobs; shared/ canva-composer,
   canva-editor, cc-canva-composer, call-recorder, tune, fathom-ingest; Dionet wins + testimonials; PB wins) pass
   `--settings '{"outputStyle":"default"}'`. Keep the flag when touching those spawn arrays. Free-text bot
   replies (Discord, SMS, console) stay on Plain English on purpose.
4. The harness's own "say what you are about to do" line may survive as one preamble line. `measure.py` shows it.
5. `frame list` and `init_here.py --list` do not show Syntax, on purpose. `/frameworks` mentions it in one line.
