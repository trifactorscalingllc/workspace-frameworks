# Directive: daily_digest

Summarize a tracking sheet and leave the digest as a Gmail draft. This is the
worked example — copy its shape when writing new directives.

## Goal

The reader opens one draft, sees what changed since yesterday without opening
the sheet, and presses send if they want it delivered.

Drafting rather than sending is deliberate: this runs unattended on a webhook,
and nothing should leave the building without a human glancing at it first.

## Inputs

From the webhook payload:

- `sheet_id` — the spreadsheet to read. Falls back to `DIGEST_SHEET_ID` in `.env`.
- `range` — A1 range. Defaults to `Tracker!A1:Z500`.
- `to` — draft recipient. Falls back to `EMAIL_TO` in `.env`; if both are empty,
  address the draft to the account owner. A draft is never delivered, so an
  imperfect recipient is a nuisance rather than a mistake.
- `date` — the day being reported on. Defaults to today.

If neither the payload nor `.env` supplies a sheet, stop and report that.

## Steps

1. Read the sheet, treating row 1 as headers:

   ```bash
   python execution/tools/read_sheet.py --sheet-id <sheet_id> --range '<range>' --header
   ```

2. If `row_count` is 0 or 1 (headers only), send nothing and report "no rows".
   An empty digest is noise.

3. Summarize the records: totals, what changed since the last run if the sheet
   carries a date column, and anything that looks stuck or anomalous. Keep it
   under ~200 words. Lead with the number that matters.

4. Create the draft with the `gmail_draft` tool, subject
   `Daily digest — <date>`. Say in your report that you left a draft; do not
   claim anyone was emailed.

## Output

- One Gmail draft, unsent, waiting for a human.
- Nothing delivered. This directive has no tool that can send.

## Edge cases

- **Sheets API quota**: 60 read requests/minute/user. One read per run is fine;
  batch if you ever loop over tabs.
- **Ragged rows**: `read_sheet.py --header` pads short rows, so trailing keys
  come back as `""` rather than going missing. Treat `""` as "not filled in",
  not zero.
- **Duplicate drafts**: the run is not idempotent. A caller that retries after a
  timeout leaves two drafts. Harmless — nothing was sent — but say so in the
  report rather than letting the reader assume one.
- **Wanting it to actually send**: swap the grant to `send_email` in
  `webhooks.json`. Understand what that changes: `send_email` delivers
  immediately, unattended, with no human in the loop. The draft path exists
  because that is usually the wrong default for a webhook.
