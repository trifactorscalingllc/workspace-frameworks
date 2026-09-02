#!/usr/bin/env bash
# Syntax — install the machine-wide Plain English reply style for Claude Code (macOS / Linux).
#
#   bash syntax/install.sh              install or refresh (idempotent, additive)
#   bash syntax/install.sh --uninstall  remove everything it added; backups are kept
#
# What it touches, all under the user's home:
#   ~/.claude/output-styles/plain-english.md   symlink -> this repo (a git pull is live)
#   ~/.claude/commands/syntax.md               symlink -> syntax-command.md  (/syntax in chat)
#   ~/.local/bin/syntax                        symlink -> syntax.sh          (terminal switch)
#   ~/.claude/settings.json                    outputStyle + showThinkingSummaries, only if absent
#   ~/.claude/CLAUDE.md                        the rule, between <!-- syntax:begin/end --> markers
#   ~/.gemini/GEMINI.md                        the same rules for Gemini CLI, same markers
# Every file that gets rewritten is first copied to <file>.bak-<stamp>.
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
GEMINI_DIR="$HOME/.gemini"
BIN_DIR="$HOME/.local/bin"
STAMP="$(date +%Y%m%d-%H%M%S)"
STYLE_NAME="Plain English"
BEGIN='<!-- syntax:begin -->'
END='<!-- syntax:end -->'

STYLE_SRC="$HERE/plain-english.md";  STYLE_DST="$CLAUDE_DIR/output-styles/plain-english.md"
CMD_SRC="$HERE/syntax-command.md";   CMD_DST="$CLAUDE_DIR/commands/syntax.md"
CLI_SRC="$HERE/syntax.sh";           CLI_DST="$BIN_DIR/syntax"
SECTION_SRC="$HERE/CLAUDE-section.md"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
GEMINI_MD="$GEMINI_DIR/GEMINI.md"
SETTINGS="$CLAUDE_DIR/settings.json"

say() { printf '  %s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

backup() {  # backup <file>  (no-op if it does not exist)
  if [ -f "$1" ]; then cp -p "$1" "$1.bak-$STAMP"; say "backed up $(basename "$1") -> .bak-$STAMP"; fi
}

link() {  # link <src> <dst>: symlink; replace a stale link; back up and replace a real file
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [ -L "$dst" ]; then
    if [ "$(readlink "$dst")" = "$src" ]; then say "$(basename "$dst") already linked"; return; fi
    cp -P "$dst" "$dst.bak-$STAMP"; say "backed up foreign link $(basename "$dst") -> .bak-$STAMP"; rm "$dst"
  elif [ -d "$dst" ]; then
    die "$dst is a directory; move it aside first"
  elif [ -e "$dst" ]; then
    backup "$dst"; rm "$dst"
  fi
  ln -s "$src" "$dst"; say "linked $dst -> $src"
}

unlink_ours() {  # unlink_ours <dst> <src>: remove only if it is OUR symlink
  if [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]; then rm "$1"; say "removed $1"; fi
}

# settings_patch install|uninstall — edits the two keys, backs up before writing, keeps indent.
settings_patch() {
  python3 - "$SETTINGS" "$1" "$STYLE_NAME" "$STAMP" <<'PY'
import json, re, shutil, sys, pathlib
p = pathlib.Path(sys.argv[1]); mode, style, stamp = sys.argv[2:5]
raw = p.read_text() if p.exists() else '{}'
d = json.loads(raw)
m = re.search(r'\n( +)"', raw); indent = len(m.group(1)) if m else 2
changed = []
if mode == 'install':
    # Only set what is absent: a founder's `syntax off` must survive a re-run.
    if 'outputStyle' not in d:
        d['outputStyle'] = style; changed.append(f'outputStyle = {style}')
    if 'showThinkingSummaries' not in d:
        d['showThinkingSummaries'] = True; changed.append('showThinkingSummaries = true')
else:
    if d.get('outputStyle') in (style, 'default'):   # 'default' == absent; `syntax off` leaves it behind
        del d['outputStyle']; changed.append('outputStyle removed')
    if d.get('showThinkingSummaries') is True:
        del d['showThinkingSummaries']; changed.append('showThinkingSummaries removed')
if changed:
    if p.exists():
        shutil.copy2(p, f'{p}.bak-{stamp}'); print(f'  backed up {p.name} -> .bak-{stamp}')
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp'); tmp.write_text(json.dumps(d, indent=indent, ensure_ascii=False) + '\n'); tmp.replace(p)
    for c in changed: print('  settings.json:', c)
else:
    print('  settings.json already as wanted' if mode == 'install' else '  settings.json had nothing of ours')
PY
}

# upsert_block <file> <block-text-file> — add the block if missing, replace it if it changed, else no-op.
upsert_block() {
  python3 - "$1" "$2" "$BEGIN" "$END" "$STAMP" <<'PY'
import re, shutil, sys, pathlib
p, blockfile = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
b, e, stamp = sys.argv[3], sys.argv[4], sys.argv[5]
block = blockfile.read_text().strip('\n')
if not (block.startswith(b) and block.endswith(e)):
    sys.exit(f'block file {blockfile} must start with {b} and end with {e}')
old = p.read_text() if p.exists() else ''
pat = re.compile(re.escape(b) + r'.*?' + re.escape(e), re.S)
m = pat.search(old)
if m and m.group(0) == block:
    print(f'  {p.name} already current'); sys.exit()
new = pat.sub(lambda _: block, old) if m else (old.rstrip('\n') + ('\n\n' if old.strip() else '') + block + '\n')
if p.exists():
    shutil.copy2(p, f'{p}.bak-{stamp}'); print(f'  backed up {p.name} -> .bak-{stamp}')
p.parent.mkdir(parents=True, exist_ok=True)
tmp = p.with_name(p.name + '.tmp'); tmp.write_text(new if new.endswith('\n') else new + '\n'); tmp.replace(p)
print(f'  {p.name}: {"replaced" if m else "appended"} the Syntax block')
PY
}

# strip_block <file> — remove our block; delete the file if nothing else is left.
strip_block() {
  python3 - "$1" "$BEGIN" "$END" "$STAMP" <<'PY'
import re, shutil, sys, pathlib
p = pathlib.Path(sys.argv[1]); b, e, stamp = sys.argv[2:5]
if not p.exists(): sys.exit()
old = p.read_text()
new = re.sub(r'\n*' + re.escape(b) + r'.*?' + re.escape(e) + r'\n?', '\n', old, flags=re.S)
if new == old: print(f'  {p.name} had no Syntax block'); sys.exit()
shutil.copy2(p, f'{p}.bak-{stamp}'); print(f'  backed up {p.name} -> .bak-{stamp}')
if new.strip():
    tmp = p.with_name(p.name + '.tmp'); tmp.write_text(new.strip('\n') + '\n'); tmp.replace(p); print(f'  {p.name}: removed the Syntax block')
else:
    p.unlink(); print(f'  {p.name}: removed (it held nothing but the Syntax block)')
PY
}

# gemini_block_file — the style body (frontmatter stripped) wrapped in our markers, as a temp file.
gemini_block_file() {
  local tmp; tmp="$(mktemp)"
  {
    echo "$BEGIN"
    echo "# Reply style: Syntax (managed by workspace-frameworks/syntax — edit the repo, not this file)"
    echo
    awk 'BEGIN{fm=0} NR==1 && /^---$/ {fm=1; next} fm==1 && /^---$/ {fm=2; next} fm!=1 {print}' "$STYLE_SRC"
    echo "$END"
  } > "$tmp"
  echo "$tmp"
}

MODE="${1:-install}"
case "$MODE" in
  install|--install) MODE=install ;;
  uninstall|--uninstall) MODE=uninstall ;;
  -h|--help|help) sed -n '2,14p' "$0"; exit 0 ;;
  *) die "unknown argument '$MODE' (use --uninstall or nothing)" ;;
esac
command -v python3 >/dev/null || die "python3 is required"

if [ "$MODE" = install ]; then
  echo "==> Installing Syntax (Plain English reply style) into $CLAUDE_DIR"
  [ -f "$STYLE_SRC" ] || die "missing $STYLE_SRC"
  [ -f "$SECTION_SRC" ] || die "missing $SECTION_SRC"
  chmod +x "$CLI_SRC"
  link "$STYLE_SRC" "$STYLE_DST"
  link "$CMD_SRC" "$CMD_DST"
  link "$CLI_SRC" "$CLI_DST"
  settings_patch install
  upsert_block "$CLAUDE_MD" "$SECTION_SRC"
  if [ -d "$GEMINI_DIR" ]; then gb="$(gemini_block_file)"; upsert_block "$GEMINI_MD" "$gb"; rm -f "$gb"; else say "no $GEMINI_DIR (no Gemini CLI here); skipped GEMINI.md"; fi
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "note: $BIN_DIR is not on PATH; run $CLI_SRC directly or add it" ;; esac
  echo
  echo "Done. New chats use the Plain English style; open chats keep what they started with."
  echo "  syntax status | syntax off | syntax on | syntax thinking summary|full   (or /syntax in a chat)"
  echo "  In VS Code, Ctrl+Alt+F (Focus view) hides tool calls and folds thinking. Once per person."
else
  echo "==> Removing Syntax from $CLAUDE_DIR"
  unlink_ours "$STYLE_DST" "$STYLE_SRC"
  unlink_ours "$CMD_DST" "$CMD_SRC"
  unlink_ours "$CLI_DST" "$CLI_SRC"
  settings_patch uninstall
  strip_block "$CLAUDE_MD"
  strip_block "$GEMINI_MD"
  echo
  echo "Done. Backups (*.bak-$STAMP) were kept next to each file that changed."
fi
