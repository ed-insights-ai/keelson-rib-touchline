---
title: Build a player profile
description: "Run touchline-player-profile for one player: the deterministic record, research verified at its sources, and a merge that only ever adds."
sidebar:
  order: 6
---

The `touchline-player-profile` workflow builds the accumulated dossier for one
player: the deterministic college record from collected season data, plus
offseason research verified at its sources. The result is one JSON file per
player, schema `touchline.player-profile/1`, under `data/players/`. The
definition is `workflows/touchline-player-profile.yml`.

## Before you start

- A data home whose collected seasons contain the player somewhere: a roster
  row, a statistics line, or a box-score appearance. A name with no trace at
  all is refused (below).
- Live web access for the research stage (`webSearchMode: live`).

## Start the run

```sh
keelson workflow run touchline-player-profile \
  --inputs "player={player}" \
  --inputs programme={programme} \
  --inputs gender={gender} \
  --inputs conference={conference}
```

`player` is the name exactly as published on the roster. In chat: "build a
profile for {player}".

## What runs, in order

1. **preflight** checks the `touchline-data.yaml` marker and the four inputs.
2. **assemble** runs `build-profile` to recompute the deterministic record
   from the season files: identity from the most recent roster listing the
   player, career and keeper lines per season, the per-match appearance
   timeline, and availability flags.
3. **research** works this one player under `prompts/player-profile.md` and
   `prompts/research-protocol.md`: disambiguate first, anchor on official
   pages, and keep confirmed, ruled out, and no indexed mention distinct. It
   writes `data/research/players/{programme}-{player-key}.json`, schema
   `touchline.player-findings/1`.
4. **verify** is the adversary. It re-fetches every finding's URL trying to
   refute the claim as written, rewrites the same file with the survivors, and
   moves each dropped claim into a `dropped` array with a one-line reason.
5. **merge** schema-checks the findings file (rescuing one an agent wrote
   relative to the rib repo instead of the data home), then calls
   `build-profile --findings` to perform the additive upsert and
   `normalize-research` to canonicalize the file. Success prints
   `wrote data/players/{gender}/{programme}/{player-key}.json` and a one-line
   JSON summary of the record; a summary then names the path and anything dropped,
   attested-but-uncaptured, or unswept.

The player key is the lowercased, accent-stripped, hyphenated name
(`player_key` in `pipeline/src/profile.py`).

## The no-trace refusal

`assemble_record` in `pipeline/src/profile.py` raises when the data home holds
no identity, no career line, and no appearance for the name. The
`build-profile` CLI exits 2 and the run stops at assemble:

```
no trace of '{player}' for programme '{programme}' ({gender}) in this data home — check the spelling against the roster
```

The refusal is deliberate: a profile of nothing would let a name typo
masquerade as a person, and the research stage would then go hunting for
someone who does not exist. Fix the spelling against the published roster, or
collect the seasons that would carry the trace.

## Re-runs enrich, never replace

A profile has two layers with different update semantics (`upsert_profile` in
`pipeline/src/profile.py`):

- The **assembled record** is recomputed and replaced on every build. It is
  derived truth, so fresher season files simply produce a fresher record.
- **Verified findings** merge additively, deduplicated on the url-and-text
  pair (`_finding_key`); `attested_uncaptured` and `unswept` append additively
  too, skipping exact duplicates. `first_built` survives from the first run,
  and `updated_at` moves.

So a re-run after a new season, or after better research, only adds. Nothing a
previous run verified is ever silently discarded, and the `touchline-report`
research loop reads these profiles back as findings it does not have to
re-verify.

## Fan out safely

`workflows/touchline-player-profile.yml` declares `mutates_checkout: true`
with `locking: shared`. Per-player runs write disjoint files, so several can
run in parallel against one data home; `shared` keeps them all mutually
exclusive with `touchline-collect`, which takes the exclusive lock
(`mutates_checkout: true` with no `locking` field) because two collects would
race on the same season file. Profile the whole midfield at once, just not
during a collect.

**What you just exercised:**
[Identity](../../concepts/identity/) (identity binding),
[Evidence, not recall](../../concepts/evidence-not-recall/) (evidence
grading), and additive merges at
[The determinism boundary](../../concepts/the-determinism-boundary/).

## Related

**Run it**

- [Run a scouting report](../run-a-report/): the conference-wide sweep that reuses these profiles as pre-verified findings.
- [Pipeline CLI](../../reference/pipeline-cli/): `build-profile` flags and exit codes.

**Understand it**

- [Absence is data](../../concepts/absence-is-data/): availability flags are observed holes with unknown causes, never diagnoses.
- [Research with receipts](../../tutorials/research-with-receipts/): the lab that runs this evidence discipline by hand.
