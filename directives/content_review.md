# Directive: content_review

Match what actually posted on Instagram against the week's plan, fill in
`Done?`, and report what performed.

## Goal

Close the loop the content system has never had. After this runs, the week's
plan reflects reality instead of intent, and the operator knows which posts
earned attention — so the next week is planned on evidence rather than a guess.

## Why this exists

As of 2026-08-15 the tracking columns had **never** been filled: `Done?` blank
on all 21 rows of Week 1, and `A Filmed`/`Assembled`/`Posted` blank on all 40
rows of the reels bank. Posting was happening; recording it was not. Manual
ticking has failed twice, so this directive does it from the platform's own
data and never asks a human to tick anything.

## Inputs

From the webhook payload, all optional:

- `week_sheet_id` — the week to reconcile. Defaults to `CONTENT_WEEK_SHEET_ID`.
- `since` / `until` — ISO dates. Default: the first and last `Date` in the plan.
- `write` — `true` (default) to fill `Done?`. `false` reports without touching
  the sheet.

## Steps

1. Read the plan:

   ```bash
   /Users/tfs/directive-runner/.venv/bin/python execution/tools/read_sheet.py --sheet-id <week_sheet_id> --range 'A1:Z100' --header
   ```

2. Pull what actually posted in that window:

   ```bash
   /Users/tfs/directive-runner/.venv/bin/python execution/tools/ig_posts.py --since <since> --until <until>
   ```

3. **Match posts to plan rows.** There is no shared id, so match on evidence,
   in this order, and stop at the first confident hit:
   1. Same calendar date **and** format — `REELS` product type to a `REEL` row,
      `CAROUSEL_ALBUM` to a `CAROUSEL` row.
   2. Same date, and the post caption contains the row's `CTA` keyword. The CTAs
      are of the form `Comment "QUALIFY" to get ...`, so the trigger word is a
      strong, near-unique signal.
   3. Distinctive phrasing shared between the post caption and the row's
      `Caption` or `Hook / Cover slide`.

   A day has three slots (22:00 REEL, 12:00 and 18:30 CAROUSEL), so posting
   time breaks ties between two carousels on the same date.

   **Never guess.** Report an unmatched post and an unmatched row separately;
   a wrong match writes a false `Done?`, which is worse than a blank one.

4. **Write `Done?`** for confidently matched rows (unless `write` is false),
   using `update_sheet.py` on that single cell — column N, the row's own number.
   Put the permalink in the cell, not just a tick: it makes the row auditable
   and is a link a human can follow.

   Change nothing else. Never write to a row you did not match.

5. **Report performance.** For matched posts give reach, saves, shares, likes
   and comments. Then say the useful things:
   - the best and worst performer of the week, by reach and by saves
   - whether REELs or CAROUSELs did better, on average
   - which `Trigger` system earned the most reach and the most saves
   - any post whose reach is far off the week's median, in either direction

6. Leave a Gmail draft, subject `Content performance — week of <since>`,
   leading with the single most decision-useful line. Include unmatched rows
   (planned, no post found) and unmatched posts (posted, not in the plan).

## Output

- `Done?` filled with permalinks for matched rows.
- A Gmail draft with performance and both unmatched lists.
- Nothing sent. No plan content rewritten.

## Edge cases

- **Instagram not connected** — the run refuses up front with the setup
  command. Nothing else in the system depends on it.
- **Token expiry**: long-lived Meta tokens last ~60 days, so this works for two
  months and then fails all at once. `ig_posts.py` adds a `warning` field under
  14 days; surface that in the draft rather than swallowing it.
- **Insights vary by media type and API version.** `ig_posts.py` degrades to
  `reach` alone rather than failing. A post whose `insights` contains `_error`
  still counts as posted — absence of metrics is not absence of a post.
- **Stories and non-plan posts** will appear as unmatched. That is information,
  not an error: report them, do not force them into rows.
- **Reruns must be safe.** A row already carrying a permalink is done; leave it
  alone rather than rewriting. This directive is expected to run repeatedly
  across the week.
- **Sheets quota**: 60 writes/minute/user. Batch the `Done?` writes into one
  `update_sheet.py` call per contiguous block where possible, rather than 21
  separate calls.
