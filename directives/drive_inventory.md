# Directive: drive_inventory

Report what spreadsheets exist in Google Drive. Read-only; this is the smoke
test that proves the connector path works end to end from a webhook.

## Goal

The caller learns how many Google Sheets are in the Drive and what the most
recently touched ones are, without anyone opening Drive.

## Inputs

From the webhook payload, all optional:

- `query` — narrow the search (e.g. `budget`). Default: all spreadsheets.
- `limit` — how many to name in the output. Default 10.

## Steps

1. Use the Google Drive connector to search for Google Sheets, applying `query`
   if one was given.
2. Count the matches. Name the first `limit` of them, most recent first, with
   their last-modified date when the connector supplies it.
3. Report. Change nothing — this directive has read-only tools by design.

## Output

A short plain-text report: the total count, then the named files. No file is
created, moved, or modified.

## Edge cases

- **No matches** → say so plainly and stop. An empty list is a valid answer.
- **Large Drives** → the connector paginates. Report the count you actually
  observed and say whether it was truncated rather than implying completeness.
- **Permission blocked** → the run was granted `drive_search`/`drive_read` and
  nothing else. If a call is refused, report it; do not try a shell workaround,
  which is blocked too.
- **Sheet *contents*** → `drive_read` returns a Sheet as text/CSV, not cells.
  There is no connector that writes to a Sheet; that still needs the Python
  tools and a Google OAuth `token.json`.
