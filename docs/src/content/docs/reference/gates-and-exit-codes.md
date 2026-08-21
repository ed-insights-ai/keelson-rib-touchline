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
last three are pipeline commands.

| Gate | Where | Asserts |
|---|---|---|
| `validate-research` | `workflows/touchline-report.yml` | Every programme in the digest has `data/research/{season}-{gender}/research-{slug}.json`, and each file's `coach` object carries a non-empty `name` and a `status` in `new`, `returning`, or `unknown`. |
| `merge-verified` | `workflows/touchline-report.yml` | Before the deterministic merge: every `verified-{slug}.json` exists, is newer than the digest, has schema `touchline.research-verified/1`, arrays for `findings`, `dropped`, `attested_uncaptured`, and `unswept`, and a `coaches` object holding exactly one entry, keyed by its own slug. |
| `validate-verified` | `workflows/touchline-report.yml` | `verified.json` exists and has the five keys `findings`, `coaches`, `dropped`, `attested_uncaptured`, and `unswept` (the file's `schema` tag is checked per-programme by `merge-verified`); its `coaches` map holds at least one entry per research file that carries a coach object (verify downgrades an unsupported coach to `unknown` but never drops it from the map). |
| `assemble-narrative` | `workflows/touchline-report.yml` | Before assembly: `narrative-core.json` and every opponent card exist and are newer than the digest; the core matches `touchline.report-narrative-core/1` with typed fields; each card matches `touchline.report-narrative-card/1`, its `programme` equal to its slug, `tier` in `benchmark`, `swing`, or `update`, and a watchlist of at most 2 rows bound to the same slug with legal labels. |
| `validate-narrative` | `workflows/touchline-report.yml` | Schema is `touchline.report-narrative/4`; exactly 3 `exec.findings`, each with `evidence` and `meaning` present; 1 to 3 decisions; at least 1 programme card; a non-empty `bottom_line`; an offseason ledger of at most 3; no `dossiers` section; watchlist at most 2 per opponent, none for the focus side, only known programme slugs; and no string anywhere contains the machinery words `digest`, `roster shape`, `roster_shape`, or `verified pool`. |
| `validate-narrative` page check | `workflows/touchline-report.yml` | Word budgets that protect the print layout: `bottom_line` at most 70 words, `landscape` at most 100, `focus.overview` at most 110 (each measured with `wc -w`), and each watchlist `why` at most 90 (measured by word split). The `render` node never runs past a violation. |
| membership validate | `check-membership`, logic in `pipeline/src/membership.py` `validate` | `data/reference/membership.json` has `version` 1 and a `seasons` span; declared conferences include the structural codes `independent` and `non_member`; every window names a declared conference, carries a non-empty `source` citation, and holds integer seasons with `from_season` at most `to_season`, inside the span; per-programme coverage has no gaps ("cover them explicitly with an independent or non_member window") and no overlaps; every configured programme is covered and no unknown slug appears. Exits 1 with one line per violation. |
| conference audit | `pipeline/scripts/conference_audit.py` | Recomputes `is_conference_game` independently and compares it to the stored flags. The verdict rides the `ok` below `warn` below `alarm` lattice, raised only through `_raise_verdict`: `warn` when stored flags are NULL, `alarm` on disagreements, standing violations, or unresolved identities. The verdict travels in the one-line JSON payload, not the exit code: the audit exits 0 whenever it ran, and 1 only when the query or audit itself raised (the `CHECK DID NOT RUN` payload). |
| caption audit | `pipeline/scripts/check_sidearm_captions.py` | Re-parses every cached SideArm page, matches parsed players to stored rows on the composite key `PLAYER_KEYS`, and classifies each stored game by goalie-caption attribution into `aligned`, `swapped`, `ambiguous`, `unmatched`, or `missing_pages`. Exits 1 unless every game is `aligned`; prints its JSON report either way. No console entry in `pipeline/pyproject.toml`; it audits the population of the caption-swap bug. |

The report workflow's `preflight` refusals (data-home marker, input shape,
collected fixtures) and each loop's mechanical `until_bash` completion check
belong to the same surface; they are documented with their workflows in
[Workflows](../workflows/).

## Script exit contracts

Console scripts from `pipeline/pyproject.toml`, plus the caption audit. A
blank cell means the script never returns that code.

| Script | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `scrape` | every discovered game parsed and saved | partial or rejected run: any game failed, or discovery rejected a school season | `--school` matched no enabled school | |
| `collect-board` | the coverage manifest was written and describes reality, gaps and all | the manifest write failed | usage: empty `--programmes`, a `--conference` with no letter or digit, or unknown or empty `--layers` | |
| `export-board` | fixtures written | no merged archive at `data/structured/all/games.parquet` (run `reparse` first), or the season holds zero fixtures (unmatched opponent names are reported, never fatal) | usage: empty `--programmes`, or a `--conference` with no letter or digit | |
| `build-digest` | digest written | | fixtures missing for the season, or the focus slug unknown | |
| `render-report` | rendered: PDFs written and the HTML intermediates removed, or HTML kept when no Chrome is found | | no digest at the expected path | the Chrome PDF print failed; the HTML that did not print survives |
| `build-profile` | profile written | | the `--findings` file does not exist, or the player has no trace in the season files | |
| `normalize-research` | every research file canonical (also when no research directory exists) | at least one file skipped: invalid JSON, a non-object top level, or a failed round trip | | |
| `build-canon` | artifact valid: written, or checked with `--check` | database or file error, or any validation error | | |
| `check-membership` | `membership.json` valid | load failure or any contract violation | | |
| `conference-audit` | the audit ran; the verdict (`ok`, `warn`, or `alarm`) is in the JSON payload | the check did not run: the query or audit raised | | |
| `migrate-shard` | migrated, or nothing legacy to migrate | refused: `MigrationError`, for example an ambiguous conference | | |
| `probe` | every URL probed | a URL was not absolute HTTP(S), its sport slug named no gender, or its fetch failed | | |
| `load-db` | loaded | nothing under `data/structured/` | | |
| `export` | merged parquet files copied | no merged archive at `data/structured/all/`, or nothing exported | | |
| `check_sidearm_captions` | every stored SideArm game aligned | any game swapped, ambiguous, unmatched, or missing its cached pages | | |

Three scripts carry no coded contract and are omitted above. `reparse` and
`audit` exit 0 on success and nonzero only through an unhandled exception;
`audit` prints PASS and FAIL acceptance lines but always exits 0 when it runs.
`pipeline-run` chains `scrape`, `load-db`, `export`, and `audit`, propagating
a failing step's own code; it tolerates only the `export` step's refusal on an
empty archive.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the workflow these gates stop.
- [Audit the data](../../guides/audit-the-data/): running the audits against a data home.
- [Pipeline CLI](../pipeline-cli/): the flags behind each script named here.

**Understand it**

- [The model declares, the validator decides](../../concepts/gates/): why completion is counted, not claimed.
- [Gate after every generative step](../../design/gate-after-every-generative-step/): the incident that made gates law.
- [Break a gate](../../tutorials/break-a-gate/): fire each ALARM yourself, on a scratch copy.
