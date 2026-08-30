# Agent Instructions — BPO

> Mirrored across CLAUDE.md, AGENTS.md and GEMINI.md so the same instructions load in any
> AI environment.

You are working in a **BPO** workspace: **B**aseline / **P**roof / **O**utcome.

This is a delivery framework. Its siblings: DOE structures *work*, IAE structures *thinking about
sources*. BPO structures *what you are allowed to claim you achieved*.

The failure it exists to prevent is the most expensive one in client work: reporting an outcome
that nobody measured the start of. It is almost never a lie. It is a number nobody wrote down
before, a metric that quietly changed definition halfway through, or a real improvement that had
three causes and got reported as one. All of those survive a careful reading of the report and
collapse the first time a client checks.

**The rule everything else serves: you cannot claim a change you did not measure the start of.**

## The three layers

### B — Baseline: what was true before you touched it

One file per metric in `baseline/`, named `B001-<metric>.md`. Every baseline carries:

- **id** — `B001`, `B002`… Stable. Every outcome cites one.
- **metric** — the exact thing measured, named precisely. "Leads" is not a metric. "Typeform
  submissions that reached the qualified stage" is.
- **value** and **unit** — the number, and what it counts.
- **measured** — the date you took it.
- **source** — where the number came from, specifically enough that someone else could pull it
  again: a dashboard, an API call, a query. "From the CRM" is not a source.
- **method** — how it was computed, if there is any choice involved. Date range, filters,
  what was excluded.

**Take the baseline before the work starts.** A baseline measured after you began is not a
baseline, it is a mid-flight reading, and the checker fails it against the work's start date. If
you inherited a job already in progress, say so in the baseline file and mark it
`contaminated: true` rather than pretending.

**If a metric has no baseline, you may still do the work — you just may not later claim a change
in it.** Record it as a baseline of unknown value with `value: unknown` so the gap is visible
rather than discovered at reporting time.

### W — Work: what you actually did

Files in `work/`, named `W001-<slug>.md`, each with an id, `started`, `completed`, and a plain
summary. This layer is the least glamorous and the one that makes attribution possible: an
outcome cites the work items it credits, and a reader can see whether the work plausibly explains
the change.

Keep it factual. This is not a place to argue for impact — that happens at Proof, where it has to
survive the numbers.

### O — Proof: the outcome, and what else could explain it

Files in `proof/`. Each carries:

- **outcome** — one line on what changed.
- **baseline** — the `Bxxx` it is measured against.
- **value** and **unit** — the post-measurement. **The same metric and the same unit as the
  baseline.** Changing either between the two readings is moving the goalposts, and the checker
  treats it as an error rather than a rounding difference.
- **measured** — when you took the post-measurement. Stale numbers get flagged: a result measured
  six weeks ago is not evidence of today.
- **cites** — the work ids you are crediting.
- **confounders** — what else could explain this change. **Required.** Seasonality, a price
  change, another vendor's campaign, a platform algorithm shift, a single large customer. If you
  genuinely believe there are none, write "none identified, and here is why" — but write it.

Then say plainly how much of the change you are claiming. "Submissions doubled, and we shipped
the new form in that window" is honest. "We doubled submissions" is a claim about causation that
a baseline and a date cannot support on their own.

## The checker

```bash
python3 check_bpo.py
```

Stdlib only, no venv. It **reports and never blocks** — exit code is always 0. It checks:

1. Baselines have id, metric, value, unit, measured date and source.
2. Every `Bxxx` an outcome cites exists.
3. **Metric and unit match** between a baseline and its proof — the goalpost check.
4. **The baseline predates the work it is credited to** — the contamination check.
5. The post-measure is after the work started, and not older than the staleness window.
6. Every outcome names confounders.
7. Work items have dates.
8. Baselines measured but never used in any proof.

Rules 3 and 4 are the ones worth having. A dangling citation is embarrassing; a silently redefined
metric or a baseline taken after the work began produces a report that is wrong in a way nobody
catches until a client does.

**What it cannot do:** judge whether your work actually caused the change. It verifies the
arithmetic of the claim — that a before and an after exist, measure the same thing, and sit on the
right side of the work. Causation is yours to argue, in the confounders section, honestly.

## Working rules

1. **Baseline first, always.** The single most common way this goes wrong is starting work and
   measuring later. Take the reading before you touch anything, even if it is rough.
2. **Name the metric so precisely it is boring.** Most disputes about results are actually
   disputes about definitions.
3. **Record the source well enough to re-pull it.** A number you cannot reproduce in six months
   is not proof, and a renewal conversation is exactly six months later.
4. **A flat or negative result is a finding.** Report it. A framework that only records wins is a
   marketing document, and everyone can tell.
5. **State freshness on every number.** Never present a stale reading as current — say when it
   was taken.
6. **`.tmp/` is for intermediates.** Never cite it; if a number matters, it becomes a baseline or
   a proof with a source.
7. **Anneal the rules.** When a run goes wrong in a way these instructions did not anticipate,
   add the rule that would have caught it and date it.
