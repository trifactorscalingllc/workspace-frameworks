#!/bin/bash
# Double-click this in Finder to spin up a new workspace from this template.
#
# Asks for a name in a normal macOS dialog, creates the folder next to this one,
# bootstraps it, and opens it in VS Code. Also runnable from a terminal.
#
# Finder launches .command files with an arbitrary working directory, so resolve
# everything from this file's own location rather than assuming.

set -euo pipefail
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TEMPLATE"

# GUI prompt when one is available (double-click), plain read otherwise (ssh).
NAME=""
if command -v osascript >/dev/null 2>&1; then
  NAME=$(osascript -e 'text returned of (display dialog "Name for the new workspace:" default answer "" with title "New Directive Workspace" buttons {"Cancel", "Create"} default button "Create")' 2>/dev/null || true)
fi

if [ -z "$NAME" ]; then
  # Cancelled, or no GUI. Fall back to asking on the terminal.
  if [ -t 0 ]; then
    read -r -p "Name for the new workspace (blank to cancel): " NAME
  fi
fi

if [ -z "$NAME" ]; then
  echo "Cancelled — nothing was created."
  exit 0
fi

python3 "$TEMPLATE/execution/new_workspace.py" "$NAME" --open
STATUS=$?

# Keep the Terminal window readable when launched from Finder.
if [ ! -t 1 ] || [ -n "${TERM_PROGRAM:-}" ]; then
  echo
  read -r -p "Press Return to close..." _ || true
fi

exit $STATUS
