---
title: Gates and exit codes
description: Every gate's exact assertions and every pipeline script's exit contract, in two tables.
sidebar:
  order: 5
---

Two kinds of deterministic check guard Touchline. A **gate** exits 1 on any
failed assertion, halting its run so nothing downstream reads unproven input.
A **monitor** exits 0 with a verdict in its JSON payload and reserves a
nonzero exit for the one thing worse than a bad measurement: a check that did
not run. The reasoning lives in
[The model declares, the validator decides](../../concepts/gates/); the
founding incident lives in
[Gate after every generative step](../../design/gate-after-every-generative-step/).
This page is the contract.

## Gates

The first six rows live in bash nodes of `workflows/touchline-report.yml`
(the page check is the tail of the `validate-narrative` node); each prints an
ALARM line and exits 1 on any failed assertion, and the run stops there. The
last row is a pipeline command.

| Gate | Where | Asserts |
|---|---|---|
| `validate-research` | `workflows/touchline-report.yml` | Every programme in the digest has `data/research/{season}-{gender}/{conference}/research-{slug}.json`, and each file's `coach` object carries a non-empty `name` and a `status` in `new`, `returning`, or `unknown`. |
| `merge-verified` | `workflows/touchline-report.yml` | Before the deterministic merge: every `verified-{slug}.json` exists, is newer than the digest, has schema `touchline.research-verified/1`, arrays for `findings`, `dropped`, `attested_uncaptured`, and `unswept`, and a `coaches` object holding exactly one entry, keyed by its own slug. |
| `validate-verified` | `workflows/touchline-report.yml` | `verified.json` exists and has the five keys `findings`, `coaches`, `dropped`, `attested_uncaptured`, and `unswept` (the file's `schema` tag is checked per-programme by `merge-verified`); its `coaches` map holds at least one entry per research file that carries a coach object (verify downgrades an unsupported coach to `unknown` but never drops it from the map). |
| `assemble-narrative` | `workflows/touchline-report.yml` | Before assembly: `narrative-core.json` and every opponent card exist and are newer than the digest; the core matches `touchline.report-narrative-core/1` with typed fields; each card matches `touchline.report-narrative-card/1`, its `programme` equal to its slug, `tier` in `benchmark`, `swing`, or `update`, and a watchlist of at most 2 rows bound to the same slug with legal labels. |
| `validate-narrative` | `workflows/touchline-report.yml` | Schema is `touchline.report-narrative/4`; exactly 3 `exec.findings`, each with `evidence` and `meaning` present; 1 to 3 decisions; at least 1 programme card; a non-empty `bottom_line`; an offseason ledger of at most 3; no `dossiers` section; watchlist at most 2 per opponent, none for the focus side, only known programme slugs; and no string anywhere contains the machinery words `digest`, `roster shape`, `roster_shape`, or `verified pool`. |
| `validate-narrative` page check | `workflows/touchline-report.yml` | Word budgets that protect the print layout: `bottom_line` at most 70 words, `landscape` at most 100, `focus.overview` at most 110 (each measured with `wc -w`), and each watchlist `why` at most 90 (measured by word split). The `render` node never runs past a violation. |
| membership validate | `check-membership`, logic in `pipeline/src/membership.py` `validate` | `data/reference/membership.json` has `version` 1 and a `seasons` span; declared conferences include the structural codes `independent` and `non_member`; every window names a declared conference, carries a non-empty `source` citation, and holds integer seasons with `from_season` at most `to_season`, inside the span; per-programme coverage has no gaps ("cover them explicitly with an independent or non_member window") and no overlaps; a window's optional `division` is a non-empty string and each conference-season is all-or-none (every member's window carries a division or none does; a mix is refused naming the conference-season and the odd members); every configured programme is covered and no unknown slug appears. Exits 1 with one line per violation. |

The report workflow's `preflight` refusals (data-home marker, input shape,
collected fixtures) and each loop's mechanical `until_bash` completion check
belong to the same surface; they are documented with their workflows in
[Workflows](../workflows/).

## Script exit contracts

Console scripts from `pipeline/pyproject.toml`. A
blank cell means the script never returns that code.

| Script | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `collect-board` | the coverage manifest was written and describes reality, gaps and all | the manifest write failed | usage: empty `--programmes`, a `--conference` with no letter or digit, or unknown or empty `--layers`; or a refusal before any fetch: a programme with authored membership windows asked for a season none of them covers, named with the season | |
| `build-digest` | digest written | | fixtures missing for the season, or the focus slug unknown | |
| `render-report` | rendered: PDFs written and the HTML intermediates removed, or HTML kept when no Chrome is found | | no digest at the expected path | the Chrome PDF print failed; the HTML that did not print survives |
| `build-profile` | profile written | | the `--findings` file does not exist, or the player has no trace in the season files | |
| `normalize-research` | every research file canonical (also when no research directory exists) | at least one file skipped: invalid JSON, a non-object top level, or a failed round trip | | |
| `check-membership` | `membership.json` valid | load failure or any contract violation | | |
| `migrate-shard` | migrated, or nothing legacy to migrate | refused: `MigrationError`, for example an ambiguous conference | | |
| `probe` | every URL probed | a URL was not absolute HTTP(S), its sport slug named no gender, or its fetch failed | | |

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the workflow these gates stop.
- [Audit the data](../../guides/audit-the-data/): running the audits against a data home.
- [Pipeline CLI](../pipeline-cli/): the flags behind each script named here.

**Understand it**

- [The model declares, the validator decides](../../concepts/gates/): why completion is counted, not claimed.
- [Gate after every generative step](../../design/gate-after-every-generative-step/): the incident that made gates law.
- [Break a gate](../../tutorials/break-a-gate/): fire each ALARM yourself, on a scratch copy.
