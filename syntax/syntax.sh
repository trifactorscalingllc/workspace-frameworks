#!/usr/bin/env bash
# syntax — the machine-wide reply-style switch for Claude Code.
# Edits ~/.claude/settings.json only. A change applies to the next new chat.
#
#   syntax                      status
#   syntax on | off             Plain English style on / back to the default style
#   syntax thinking summary     condensed reasoning shown (the default Syntax sets)
#   syntax thinking full        the full reasoning transcript shown again
set -euo pipefail
SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }

cmd="${1:-status}"; sub="${2:-}"
case "$cmd" in
  status|on|off) ;;
  thinking)
    case "$sub" in summary|full) ;; *) usage; exit 2 ;; esac ;;
  thinking-summary) cmd=thinking; sub=summary ;;
  thinking-full)    cmd=thinking; sub=full ;;
  -h|--help|help) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

python3 - "$SETTINGS" "$cmd" "$sub" <<'PY'
import json, re, shutil, sys, pathlib
p = pathlib.Path(sys.argv[1]); cmd, sub = sys.argv[2], sys.argv[3]
raw = p.read_text() if p.exists() else '{}'
d = json.loads(raw)
m = re.search(r'\n( +)"', raw); indent = len(m.group(1)) if m else 2
before = json.dumps(d, sort_keys=True)
if cmd == 'on':
    d['outputStyle'] = 'Plain English'
elif cmd == 'off':
    d['outputStyle'] = 'default'
elif cmd == 'thinking':
    if sub == 'summary': d['showThinkingSummaries'] = True
    else: d.pop('showThinkingSummaries', None)
changed = json.dumps(d, sort_keys=True) != before
if changed:
    if p.exists(): shutil.copy2(p, f'{p}.bak-syntax')   # one rolling backup for the toggle
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp'); tmp.write_text(json.dumps(d, indent=indent, ensure_ascii=False) + '\n'); tmp.replace(p)
style = d.get('outputStyle', 'default')
state = 'on' if style == 'Plain English' else ('off' if style == 'default' else f'other ({style})')
think = 'summary' if d.get('showThinkingSummaries') is True else 'full'
tail = ' · takes effect on the next new chat' if changed else ''
print(f'Syntax: {state} · thinking: {think}{tail}')
PY
