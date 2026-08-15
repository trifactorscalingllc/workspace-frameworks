# Directive: content_week

Review the current week's TFS content plan, flag what is missing or at risk,
and draft next week's plan in the same shape.

## Goal

On any given day the operator can answer three questions without opening a
spreadsheet: **is this week's plan complete, what is at risk in the next 48
hours, and does next week exist yet.** When next week does not exist, this
directive creates it, populated, so the answer becomes yes.

## Inputs

From the webhook payload, all optional:

- `week_sheet_id` — the current week's plan. Defaults to `CONTENT_WEEK_SHEET_ID`
  in `.env`.
- `tracker_sheet_id` — the reels production tracker. Defaults to
  `CONTENT_TRACKER_SHEET_ID` in `.env`.
- `date` — treat this as today. Defaults to today.
- `draft_next_week` — `true` (default) to create next week's sheet when it is
  missing, `false` to report only.

If no week sheet is resolvable from either source, stop and report that.

## The data, as it actually is

The week plan has these 14 columns, in this order:

`Date | Day | Post at | Format | Trigger | System | Angle | Hook / Cover slide |
Panel or Slides | What to record | CTA | Caption | Prompter | Done?`

The observed rhythm is **three posts per day**: one `REEL` at 22:00 ET and two
`CAROUSEL` at 12:00 and 18:30 ET. `Trigger` is a single uppercase keyword that
matches the CTA comment word (QUALIFY, SPEED, PIPELINE, NOSHOW, CHATBOT,
ONBOARD, REVIEWS, MAKE). `System` is the product that trigger belongs to.
`Prompter` is a shell command, present on REEL rows only.

The reels tracker is a separate sheet with production checkboxes:
`A Filmed | B Filmed | C Filmed | Assembled | Posted | Post Date`.

⚠️ **Completion columns are not being filled in.** As of 2026-08-15, `Done?` was
empty on every row of the week plan, and `Posted` was empty across the tracker.
Treat blank as "unknown", **not** as "failed" — reporting 21 misses when nobody
is ticking boxes is noise, not signal. Say once that completion tracking is
unfilled, then move on to what the data does support.

## Steps

1. Read the week plan:

   ```bash
   /Users/tfs/directive-runner/.venv/bin/python execution/tools/read_sheet.py --sheet-id <week_sheet_id> --range 'A1:Z100' --header
   ```

2. **Check the plan's integrity.** These are computable and worth reporting:
   - Every date in the week's range has all three slots (22:00 REEL, 12:00 and
     18:30 CAROUSEL). Report any day that is short or doubled.
   - No row is missing `Hook / Cover slide`, `CTA`, or `Caption`.
   - REEL rows have a `Prompter` command and a `What to record` list.
   - Trigger/System pairs are consistent — the same `Trigger` should always map
     to the same `System`.
   - Count posts per `Trigger` so an over- or under-weighted system is visible.

   - **Verbatim repeats inside the week.** Compare `Hook / Cover slide` and
     `Caption` across rows. The 2026-08-15 run found 7 of 21 posts were
     byte-identical repeats four days apart, because the week is a 4-day cycle
     restarted on day 5. It matters more than it looks: the copy is
     time-stamped ("shipped this month"), so a repeat ages badly. Flag, never
     rewrite — that is a human call.
   - `Angle` was `BUILD` on all 21 rows, so as used it carries no signal. Do not
     report it as a finding unless that changes.

3. **Flag the next 48 hours.** List the REEL rows dated today and tomorrow with
   the scene IDs from `What to record`, so the operator knows what still needs
   filming tonight.

   ⚠️ Do **not** expect the reels tracker to answer this. Verified on
   2026-08-15: the two sheets share no join key. The plan identifies reels by
   `Trigger` + scene IDs; the tracker identifies them by `Reel Title` + `CTA
   Word`, and only one of the eight triggers appears anywhere in it. The tracker
   is an older, different content bank. Attempt the join only where a tracker
   `CTA Word` actually matches a plan `Trigger`, and when it does not, say the
   reel is **untracked** rather than unfilmed. Those are different claims and
   only one of them is true.

4. **Determine whether next week exists.** Compute the next week's date range
   from the current sheet's last date. Search Drive for a sheet whose title
   contains "TFS Content" and that range.

5. **If it does not exist and `draft_next_week` is not false**, create it:

   ```bash
   /Users/tfs/directive-runner/.venv/bin/python execution/tools/create_sheet.py --title 'TFS Content — Week N (D–D Mon YYYY)' \
     --tab Plan --headers-json '<the 14 headers above>' --if-missing
   ```

   Then populate it with `update_sheet.py --append`, following the observed
   pattern: three rows per day, same times and formats, rotating the trigger
   systems so no system repeats two days running and the weakest-covered
   systems from step 2 get more slots. Carry `System`, `CTA` and `Prompter`
   conventions across verbatim — those are stable per trigger. Write real
   `Hook / Cover slide` and `Caption` text; do not leave placeholders.

6. Leave a Gmail draft with the report, subject
   `Content week review — <date>`, and the new sheet's URL if one was created.

## Output

- A Gmail draft summarising integrity, 48-hour risk, and system balance.
- When next week was missing: a new, populated Google Sheet, linked in the draft.
- Nothing sent. Nothing in the current week's plan is modified.

## Edge cases

- **Completion columns blank** — see above. State it once, do not itemise.
- **The tracker does not join to the plan** (see step 3). Until a shared key
  exists — a `Trigger` column in the tracker, or scene IDs in it — production
  status for this week's reels is simply unavailable. Report that as a gap in
  the *system*, not as a list of unfilmed reels.
- **The tracker has damaged copy**: several rows lost their dollar amounts to
  what looks like a bad find/replace (`"What a k System Looks Like Inside"`,
  `"SLAM: ,000/YEAR"`). Mention it once if reading the tracker; do not repair it
  automatically.
- **Never modify the current week's rows.** This directive reports on them and
  writes only to a new sheet. If it looks like a row needs fixing, say so in the
  draft and let a human decide.
- **`--if-missing` needs Drive scope** the Python token does not have, so it
  silently falls through to creating. Before creating, search Drive with the
  connector (`drive_search`) to confirm next week really is absent — that is the
  reliable check, and it prevents a duplicate weekly sheet.
- **Ragged rows**: `read_sheet.py --header` pads short rows, so a trailing empty
  column arrives as `""`. Treat `""` as "not filled in".
- **Sheets API quota**: 60 reads/minute/user. Two reads per run is fine.
- **Idempotency**: creating next week twice is the failure that matters. Always
  do step 4's Drive search before step 5, and if a sheet for that range already
  exists, report its URL instead of creating another.
