# Directive: daily_digest

Summarize a tracking sheet and email the digest. This is the worked example —
copy its shape when writing new directives.

## Goal

The recipient opens one email and knows what changed since yesterday, without
opening the sheet.

## Inputs

From the webhook payload:

- `sheet_id` — the spreadsheet to read. Falls back to `DIGEST_SHEET_ID` in `.env`.
- `range` — A1 range. Defaults to `Sheet1!A1:Z500`.
- `to` — recipient. Falls back to `EMAIL_TO` in `.env`.
- `date` — the day being reported on. Defaults to today.

If neither the payload nor `.env` supplies a sheet or a recipient, stop and
report that. Do not guess a recipient.

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

4. Send it:

   ```bash
   python execution/tools/send_email.py --to <to> \
     --subject 'Daily digest — <date>' --body-file .tmp/digest_<date>.txt
   ```

   Write the body to `.tmp/` first so a failed send can be retried without
   re-summarizing. Use `--dry-run` while iterating.

## Output

- One email to the recipient.
- The rendered body left at `.tmp/digest_<date>.txt` for inspection.

## Edge cases

- **Sheets API quota**: 60 read requests/minute/user. One read per run is fine;
  batch if you ever loop over tabs.
- **Ragged rows**: `read_sheet.py --header` pads short rows, so trailing keys
  come back as `""` rather than going missing. Treat `""` as "not filled in",
  not zero.
- **Gmail first run**: needs a browser consent once, which cannot happen inside
  a webhook. Run any tool from an interactive shell first to mint `token.json`.
- **Duplicate sends**: the run is not idempotent. If the caller retries after a
  timeout the recipient gets two emails — check whether
  `.tmp/digest_<date>.sent` exists before sending, and touch it after.
