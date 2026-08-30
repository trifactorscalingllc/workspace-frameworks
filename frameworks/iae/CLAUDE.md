# Agent Instructions — IAE

> Mirrored across CLAUDE.md, AGENTS.md and GEMINI.md so the same instructions load in any
> AI environment.

You are working in an **IAE** workspace: **I**dentification / **A**nalysis / **E**valuation.

This is a research framework. Its sibling, DOE, structures *work* — pushing complexity out of a
probabilistic model into deterministic code. IAE structures *thinking* — what counts as having
understood a source rather than merely having read it.

The failure this exists to prevent is specific: an agent that summarises sources fluently, blends
what a source *claims* with what the agent *concludes*, and produces confident prose nobody can
trace back to evidence. Fluency is not understanding. The three layers exist to keep those apart.

## The three layers

### I — Identification: what the source actually says

One file per source in `sources/`, named `S001-<slug>.md`. Every source carries:

- **id** — `S001`, `S002`… Stable. Everything downstream cites these.
- **locator** — a URL, or a file path with a line or page number. Something another person can
  open. "According to a study" is not a locator.
- **accessed** — the date you read it. Web sources change.
- **tier** — one of `primary-data`, `peer-reviewed`, `official-doc`, `journalism`, `vendor-claim`,
  `forum`, `unknown`. This is not decoration: at Evaluation you must weight a vendor's claim about
  its own product differently from a measurement.
- **claim** — what the source asserts, quoted or closely paraphrased.

**No interpretation belongs in this layer.** Not "this suggests", not "importantly". If you catch
yourself explaining, you are in Analysis. Identification is the evidence base, and its value comes
entirely from being a faithful record of what was said, separate from what you make of it.

**State your search surface** in `sources/COVERAGE.md`: where you looked, what you searched for,
and — the part that matters — what you did **not** cover. Without it, "no source says X" is
ambiguous between *X is false* and *X is absent from the four places I happened to look*. Those
are different claims and only one of them is usually true. If a search was truncated or capped,
say so: a partial sweep that reads as complete is worse than one that admits its limits.

### A — Analysis: why the source says it

Files in `analysis/`. This is the longest layer and the one that carries the work.

Explain, in your own words, *why* the source claims what it claims: the mechanism, the assumptions
it rests on, what would have to be true for it to hold. **Restating the claim is not analysis** —
if your paragraph could be replaced by the quote with no loss, you have contributed nothing. The
checker flags this mechanically; see below.

Then put the sources **in conversation**. Where do they agree, and is the agreement independent or
are they citing each other? Where do they conflict? Every conflict gets classified:

- **empirical** — a measurement or experiment could settle it. Say which one.
- **definitional** — they are using a word to mean different things. Say which word, and what each
  means by it.

Conflict is the most valuable signal in research and the thing a fluent summary destroys. A review
where every source agrees is usually a review that did not look hard enough.

### E — Evaluation: your judgment, and what would overturn it

Files in `findings/`. Each finding carries:

- **statement** — what you conclude.
- **cites** — the source ids it rests on. Every finding cites at least one.
- **confidence** — `high` / `medium` / `low`, and say what drives it.
- **falsifier** — what evidence would change your mind, and whether that test is cheap enough to
  actually run. A conclusion with no falsifier is an opinion wearing a lab coat.

**A new fact may not appear for the first time at Evaluation.** If you need one, it goes into
`sources/` first with a locator. This rule is what keeps the chain intact, and it is the one most
often broken under time pressure.

Record what the evidence *cannot* settle. Open questions are a finding.

## The checker

```bash
python3 check_iae.py
```

Stdlib only, no venv, no dependencies. It **reports and never blocks** — exit code is always 0 —
because rule 6 below is a heuristic and a false positive must never stop real work.

It checks: sources have id/locator/accessed/valid tier · every `[Sxxx]` citation resolves ·
findings have a citation, confidence and falsifier · conflicts are classified · sources collected
but never cited · and Analysis prose that is too similar to the source text it cites.

**What rule 6 can and cannot do.** Measured on real text at threshold 0.45: verbatim restating
scores 0.82 and is caught; genuine analysis scores 0.19 and passes. But a *loose paraphrase* — a
sentence that says nothing new in fresh words — scored 0.16, indistinguishable from real analysis.
So the checker removes the laziest failure, not the subtle one. A clean report is not proof that
you understood anything; it only proves you did not copy. Judgment is still yours.

## Working rules

1. **Read before you write.** Populate `sources/` first. Analysis written from memory of a source
   is analysis of your memory.
2. **One source, one file.** Merging sources into a single notes file destroys traceability, which
   is the whole point.
3. **Quote sparingly and exactly.** A misquote in Identification poisons everything downstream.
4. **Say when you do not know.** "The sources do not settle this" is a valid finding and a more
   useful one than a confident guess.
5. **`.tmp/` is for intermediates** — scratch fetches, raw dumps. Never cite `.tmp/`; if something
   matters, it becomes a source with a locator.
6. **Distinguish absent from false.** "The sources do not mention it" and "the sources contradict
   it" are different findings. Write the one that is true.
7. **Anneal the rules.** When a run goes wrong in a way these instructions did not anticipate, add
   the rule that would have caught it and date it. This file is meant to accumulate.

