---
title: Break a gate
description: "Sabotage a delivered narrative three ways on scratch copies, read the ALARM that catches each break, then trip the coaches-map invariant by hand."
sidebar:
  order: 6
---

Every generative stage of the report workflow ends at a gate: a bash node
that measures the files the model left behind and exits 1 when they break
the contract. In [Run a scouting report](../../guides/run-a-report/) the
gates were something that happened to you. In this lab you lift two of
them out of `workflows/touchline-report.yml` and run them yourself, with
no workflow engine, no model, and no network: just `bash`, `jq`, and files
on disk. Then you break their inputs until every assertion has fired once.

By the end you can:

- run `validate-narrative` and `validate-verified` as plain shell against
  scratch copies of a delivered report
- name the assertion and the limit that catch an oversized `bottom_line`,
  a missing finding, and a machinery word
- explain the coaches-map invariant that makes one deleted coach entry
  fail a run
- state mechanically why no gate asks the model whether it is done

## What you need

- A data home holding a delivered report:
  `data/reports/narrative-{season}-{gender}-{focus}.json` and the research
  layer under `data/research/{season}-{gender}/{conference}/`. No report yet?
  [Run a scouting report](../../guides/run-a-report/) first.
- `jq` and `bash`, plus the `grep` and `wc` every POSIX system ships. The
  gates use nothing else.

## Set up the bench

Every break in this lab happens on a scratch copy. The data home is read
once and never written.

```sh
cd {data-home}
mkdir -p {scratch}/data/reports "{scratch}/data/research/{season}-{gender}/{conference}"
cp "data/reports/narrative-{season}-{gender}-{focus}.json" {scratch}/data/reports/
cp "data/research/{season}-{gender}/{conference}"/research-*.json \
   "data/research/{season}-{gender}/{conference}/verified.json" \
   "{scratch}/data/research/{season}-{gender}/{conference}/"
```

That mirror is complete because the two gates read nothing else:
`validate-narrative` reads only the narrative file, and `validate-verified`
reads only `verified.json` and the `research-*.json` files beside it.

Now open `workflows/touchline-report.yml` and copy the `bash:` body of the
`validate-narrative` node into `{scratch}/validate-narrative.sh`, and the
`validate-verified` body into `{scratch}/validate-verified.sh`. Read them
as you copy: nothing but `jq` filters, a `grep`, `wc -w`, shell
comparisons, and exit codes.

The engine hands a gate its inputs as environment variables, so provide
the same ones:

```sh
cd {scratch}
export KEELSON_INPUTS_season={season}
export KEELSON_INPUTS_gender={gender}
export KEELSON_INPUTS_focus={focus}
```

## 1. Try it: pass first

Sabotage proves nothing unless the gates pass the untouched copies.

```sh
bash validate-narrative.sh && bash validate-verified.sh; echo "exit $?"
```

```
narrative OK: 3 findings, {decisions} decisions, {programmes} programme sections, ledger {ledger}, watchlist {watchlist}
verified OK: {coaches} coach entries carried
exit 0
```

Keep pristine copies for restores between breaks:

```sh
N="data/reports/narrative-{season}-{gender}-{focus}.json"
V="data/research/{season}-{gender}/{conference}/verified.json"
cp "$N" narrative.pristine.json
cp "$V" verified.pristine.json
```

Check yourself: both gates exit 0 before you break anything; verify with
the run command above.

## 2. Try it: bust a word budget

The real limits, from the gate body you just copied: it recounts three
fields with `wc -w` and fails when `exec.bottom_line` exceeds 70 words,
`landscape` exceeds 100, or `focus.overview` exceeds 110. The budgets are
print boundaries: the `narrative-core` prompt calls them "hard print
boundaries the renderer cannot fix", because prose past a budget spills
onto a broken page. Pad the bottom line to 80 neutral words:

```sh
jq '.exec.bottom_line = ([range(80)] | map("filler") | join(" "))' "$N" > "$N.tmp" && mv "$N.tmp" "$N"
bash validate-narrative.sh; echo "exit $?"
```

```
ALARM: page budgets exceeded (bottom_line 80w max 70, landscape {n}w max 100, overview {n}w max 110) — prose past budget breaks the print layout.
exit 1
```

Check yourself: name the comparison that fired, then restore and pass;
verify with:

```sh
grep -- '-gt 70' validate-narrative.sh
cp narrative.pristine.json "$N" && bash validate-narrative.sh; echo "exit $?"
```

## 3. Try it: delete a finding

The executive brief carries exactly three findings. That anatomy is fixed
by the `touchline.report-narrative/4` contract at the top of
`pipeline/src/report.py`, and the gate's test is `-ne 3`: two findings
fail, and so would four. Cut one:

```sh
jq '.exec.findings |= .[0:2]' "$N" > "$N.tmp" && mv "$N.tmp" "$N"
bash validate-narrative.sh; echo "exit $?"
```

```
ALARM: narrative out of contract (findings=2, exactly 3 required; decisions={d} max 3, programmes={p}, bottom_line len={c}).
exit 1
```

Check yourself: find the exact test, restore, pass; verify with:

```sh
grep -- '-ne 3' validate-narrative.sh
cp narrative.pristine.json "$N" && bash validate-narrative.sh; echo "exit $?"
```

## 4. Try it: say a machinery word

The style contract bans the report from naming its own machinery, and the
gate enforces the ban lexically: it flattens every string in the file with
`jq -r '.. | strings'` and greps, case-insensitively, for `digest`,
`roster shape`, `roster_shape`, and `verified pool`. Leak one word into
the landscape:

```sh
jq '.landscape += " per the digest"' "$N" > "$N.tmp" && mv "$N.tmp" "$N"
bash validate-narrative.sh; echo "exit $?"
```

```
ALARM: narrative prose names report machinery 1 time(s) ("digest"/"roster shape"/"verified pool") — banned by the style contract. Rewrite those sentences in plain language.
exit 1
```

Two mechanics worth noticing. The checks run top to bottom and the gate
stops at the first failure, so breaking one thing at a time is the only
way to attribute an ALARM (and it is why Try it 2 padded with a neutral
word). And the grep reads every string in the file, not a "prose" subset:
no model judges intent here, only a pattern over bytes.

Check yourself: read the banned pattern, restore, pass; verify with:

```sh
grep 'verified pool' validate-narrative.sh
cp narrative.pristine.json "$N" && bash validate-narrative.sh; echo "exit $?"
```

## 5. Try it: erase a coach

`validate-verified` first checks that `verified.json` exists and carries
its five required keys, then holds one numeric invariant: the `coaches`
map must carry at least as many entries as there are `research-*.json`
files with a top-level coach object. The verify stage
may downgrade an unsupported coach to "unknown", but it never removes one
from the map, so a shrinking map can only mean lost data. Delete one entry
and watch:

```sh
jq -r '.coaches | keys[]' "$V"        # pick any slug from the list
jq 'del(.coaches["{slug}"])' "$V" > "$V.tmp" && mv "$V.tmp" "$V"
bash validate-verified.sh; echo "exit $?"
```

```
ALARM: verified.json coaches map holds {n-1} entries but {n} research files carry coach objects — verify carries every one (downgraded to "unknown" when unsupported, never dropped from the map).
exit 1
```

Check yourself: find the undercount comparison, restore both files, and
leave the bench green; verify with:

```sh
grep -- '-lt' validate-verified.sh
cp verified.pristine.json "$V" && bash validate-narrative.sh && bash validate-verified.sh; echo "exit $?"
```

## The lesson, stated mechanically

Nothing in this lab consulted a model. You reproduced the gates with
`bash` and `jq` because that is all they are: recounts, string scans, and
comparisons over files on disk, ending in an exit code. The workflow
trusts its generative stages the same way. The research loop ends when an
`until_bash` check counts files and coach objects on disk, and
`validate-research` exists because, as the comment on that node in
`workflows/touchline-report.yml` puts it, the loop's text exit can fire on
a model's say-so. No gate asks the model whether it is done. Every gate
measures what it left behind.

## Next stop

These gates police shape and count after the model writes; the next lab
works the evidence rules that decide what a research file may claim at
all. Read [Evidence, not recall](../../concepts/evidence-not-recall/) on
the way. Next stop: [Research with receipts](../research-with-receipts/).

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the same gates in a live run, and your move when each one stops it.
- [Gates and exit codes](../../reference/gates-and-exit-codes/): every gate, message, and exit code in one table.

**Understand it**

- [Gates](../../concepts/gates/): why a validator follows every generative step.
- [Gate after every generative step](../../design/gate-after-every-generative-step/): the founding incident behind the pattern.
