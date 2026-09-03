---
title: "Capstone: scout a season"
description: Run the full touchline-report workflow for a real focus programme, trace one finding end to end, recompute the print against the archive, and audit the analysis you did not write.
sidebar:
  order: 8
---

Every lab on this rail isolated one layer. The capstone runs the whole
machine: the `touchline-report` workflow, against a real data home, for a
real focus programme, the rib's deepest task. The mechanics live in
[Run a scouting report](../../guides/run-a-report/) and this page deliberately adds
nothing to them. What it adds is interrogation: while the loops run you
follow one finding through its whole life, and after the render you prove
the printed numbers instead of trusting them.

By the end you can:

- start a full report run and confirm each stage's output by schema tag,
  not by the transcript's say-so
- follow one finding from claim to print, or to an honest grave, through
  the verify pass and the insight filter
- recompute printed numbers back through the digest to the archived HTML
  they were parsed from
- read a run's remainder: `dropped`, `attested_uncaptured`, `unswept`
- write a run summary in which every claim carries an evidence label the
  renderer itself accepts

You need a data home holding both the `{season}` and `{previous-season}`
season files (one collect fills one season, so run collect once per
season) and the prerequisites in the guide's "Before you start". The run
writes durable research into
`data/research/` and the deliverable into `data/reports/`; that is the
intended write path, so no scratch copy is needed. The examples below use
`{focus}` where the first deployment used `harding` in the GAC.

## 1. Try it: watch the filesystem, not the transcript

Start the run exactly as the guide shows, from the data home. While the
research loop runs, watch files land, one programme per iteration, the
focus programme first and then alphabetical:

```sh
ls data/research/{season}-{gender}/{conference}/
```

The loop's honest exit is mechanical: an `until_bash` check in
`workflows/touchline-report.yml` counts research files carrying a
`coach` object against the digest's programme count. The model can also
end the stage early by replying ALL RESEARCHED on its own say-so, which
is exactly why the `validate-research` gate recounts and fails the run
if any programme lacks a file or a coach object.

**Check yourself**: every research file declares the same schema tag;
verify with this command:

```sh
jq -r '.schema' data/research/{season}-{gender}/{conference}/research-*.json | sort -u
```

Exactly one line: `touchline.research/1`.

## 2. Try it: follow one finding to print or to a grave

Open the focus programme's research file and pick one entry:

```sh
jq '.findings[0]' data/research/{season}-{gender}/{conference}/research-{focus}.json
```

Read its load-bearing parts: `text` is the claim, `url` is the single page
that must support it (the one-finding-one-page rule in
`prompts/research-protocol.md`), `date` dates it, and `confidence` is the
source grade, `high` or `medium`. Grade and verdict are different axes:
the grade says what kind of page carried the claim, and the verify loop
now decides the verdict by re-fetching that URL and trying to refute it.
A survivor passes into `verified-{focus}.json` unchanged; a casualty lands
in `dropped` with its reason.

Print is a third, separate threshold. The insight filter in
`prompts/style-contract.md` scores each surviving insight 0 to 10: 7 and
up enters the main report, 5 to 6 earns a compact card line or a
watchlist profile, below 5 is cut (major news bypasses the filter
entirely). Surviving verification does not entitle a finding to ink.

**Check yourself**: after `merge-verified`, the claim sits in exactly one
of the two arrays; verify with this command:

```sh
jq --arg t "{finding-text}" \
  '{kept: ([.findings[] | select(.text == $t)] | length),
    dropped: ([.dropped[] | select(.text == $t)] | length)}' \
  data/research/{season}-{gender}/{conference}/verified.json
```

One count is 1, the other 0. If kept, probe the assembled narrative for
its citation; verify with this command:

```sh
jq -r '[.. | .url? // empty] | .[]' \
  data/reports/narrative-{season}-{gender}-{focus}.json | grep -cF "{finding-url}"
```

Zero is a legal answer: the filter cut it. What would be illegal is prose
that leans on the claim without carrying the citation.

## 3. Try it: read what the run refused

The merged `data/research/{season}-{gender}/{conference}/verified.json` is the honest
remainder of the sweep. Read all of it: every `dropped` reason, every
`unswept` entry (a surface the sweep could not read, with why), and every
`attested_uncaptured` claim, the dead-letter bucket that never reaches
report prose in any form and surfaces only in the run's closing summary
for a human to capture or discard. Notice what refusal never does: a
coach the verifier could not support is downgraded to `unknown`, but the
`validate-verified` gate insists the entry stays in the `coaches` map.

**Check yourself**: the merged file carries the remainder as typed
arrays; verify with this command:

```sh
jq -e '(.dropped | type == "array") and (.attested_uncaptured | type == "array")
  and (.unswept | type == "array")' data/research/{season}-{gender}/{conference}/verified.json
```

Prints `true`, exit code 0.

## 4. Try it: check the print against the archive

Open `data/reports/preseason-{season}-{gender}-{focus}.pdf`. Pick three
printed figures: the focus side's last-season overall record (printed
W-L-T), one bar of the goals-by-minute chart, and that chart's own
coverage note ("N of M matches with a held box score"). Every one must
recompute from the digest, because `pipeline/src/digest.py` holds the
boundary: if a figure is not in the digest, the report cannot say it.

```sh
jq --arg f "{focus}" '.programmes[$f].last_season
  | {record: "\(.overall.wins)-\(.overall.losses)-\(.overall.draws)",
     bands: .patterns.goals_by_minute,
     coverage: "\(.patterns.matches_counted) of \(.patterns.played_total)"}' \
  data/scratch/digest-{season}-{gender}-{focus}.json
```

Then go one layer deeper. The digest's `sources` map names every season
file it read with its collection date (the same ledger the appendix PDF
prints), and those files were parsed from pages archived verbatim by
`write_raw_pages` in `pipeline/src/sidearm_live.py`, so any parse can be
redone offline. Pick one final from the record you just recomputed and
find it on the archived schedule page.

**Check yourself**: all three figures match the print digit for digit,
and the archived page still carries the final you traced; verify with
this command:

```sh
grep -ci "{opponent}" data/raw_html/{focus}/{previous-season}-{gender}-schedule.html
```

A nonzero count: the claim on the page walks back to HTML on disk.

## 5. Try it: audit the analysis you did not write

You now hold a report you did not hand-write. Auditing it is the
capstone's real skill, and the report's own honesty device is the tool:
the evidence label. Verify the label set before using it, because it is
code, not convention; `LABEL_NAMES` in `pipeline/src/report.py` maps
`observed`, `projected`, `signal`, and `judgment` to the printed chips
(`signal` renders as "Unverified signal", `judgment` as "Scouting
judgment"). Verify with this command, using the pipeline directory the
run's `resolve-pipeline` node printed:

```sh
grep -A 5 '^LABEL_NAMES' {pipeline-dir}/src/report.py
```

Now write `data/scratch/run-summary.md`: one page, every claim a `- `
list line ending with its label in brackets. Cover at least what the run
verified, dropped, and left unswept (from `verified.json`, stated exactly,
never softened); your three recomputed figures; the printed claim you
judge strongest and weakest, with why; and anything in
`attested_uncaptured` a human should chase. Label honestly: a figure you
recomputed is `[observed]`, a pattern whose cause nobody verified is
`[signal]`, your own read is `[judgment]`, and nothing gets to be
unlabeled.

**Check yourself**: every claim line carries a legal label; verify with
this command:

```sh
grep -E '^- ' data/scratch/run-summary.md \
  | grep -cvE '\[(observed|projected|signal|judgment)\]$'
```

Prints 0.

## End of the rail

You have now done by hand what the gates do mechanically: demanded a
receipt for every claim, recomputed the numbers, and labeled your own
judgment as judgment. The rail ends here, so hand yourself back to
[the syllabus](../syllabus/): its competency map names the concept
behind each mechanism you just exercised and the operator surface that
uses it daily, and its other reading paths rerun this ground from the
operator's side and from the AI-system side.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the mechanics this lab
  deliberately does not restate.
- [Gates and exit codes](../../reference/gates-and-exit-codes/): every
  ALARM this run can print, in one table.

**Understand it**

- [Evidence, not recall](../../concepts/evidence-not-recall/): the
  standard your finding just lived or died by.
- [The determinism boundary](../../concepts/the-determinism-boundary/):
  why the numbers recompute and the prose does not.
- [The syllabus](../syllabus/): the competency map this rail completes.
