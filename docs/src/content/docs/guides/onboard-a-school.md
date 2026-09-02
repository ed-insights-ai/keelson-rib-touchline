---
title: Onboard a school
description: Probe a candidate athletics site read-only, review the drafted schools.toml stanza, and enable collection only after human verification.
sidebar:
  order: 7
---

Onboarding starts with proof, not configuration. The probe fetches the
candidate site, classifies its platform from positive evidence, reports which
data layers it publishes, and drafts a config stanza that arrives disabled.
Nothing is collected until a person has reviewed all of it.

## 1. Probe the site

From the rib checkout:

```bash
uv run --project pipeline probe \
  --url https://{host}/sports/mens-soccer \
  --name "{school-name}" \
  --conference GAC
```

- `--url` is repeatable and must be an absolute HTTP(S) URL. The sport slug
  must start with `mens-` or `womens-`: gender is derived from it, and
  `pipeline/scripts/probe.py` refuses a URL that cannot say which programme
  it names.
- `--name` is the slug-minting name for the matching `--url`, in order, one
  per URL or none. It is the one identity field a person chooses, because
  `programme_slug(name)` keys membership and every coverage cell and never
  changes. Left out, the site's own published name stands in.
- `--seasons` takes `{year}` or `{year}-{year}`; the default walks the
  current year back through 2016.
- `--json` prints the same report machine-readable.

The probe is read-only: it fetches the live site and writes nothing locally.
Exit 0 means every URL was probed; exit 1 means at least one URL failed (an
invalid URL, an underivable gender, or a fetch error, printed to stderr).

## 2. Read the fingerprint, layers, and seasons

`classify_platform` in `pipeline/src/probe.py` returns one of `sidearm`,
`sidearm_legacy`, `statcrew`, or `unknown`, together with the positive
evidence it used: server-rendered SideArm schedule or `li.sidearm-*` markup,
a `sidearmsports` asset or hostname, the SideArm component runtime or events
component, or (for StatCrew) a captioned goals-by-period table and the
custompages title shape. `sidearm_legacy` means
SideArm branding with none of the server-rendered markup the collector needs.
`unknown` carries no evidence at all, and the report prints `Evidence: none`:
the probe never claims a collector it cannot prove.

Below that, `probe_layers` reports `present`, `absent`, or `error` for each
layer (schedule, roster, stats, matches) at the newest candidate season, and
`served_seasons` lists only the seasons the site proved it served: each
schedule page must pass `assert_served_season`
(`pipeline/src/sidearm_live.py`), which requires the final URL path or the
page title to name the requested year. A season makes the list only when the
fetch succeeded, the served page proved the requested year, and the page
carried schedule markup; anything less drops it silently.

## 3. Review the draft stanza

`draft_stanza` renders a `[[schools]]` entry in the house layout that is
deliberately inert:

```toml
[[schools]]
name         = "{school-name}"
abbreviation = "{abbrev}"
conference   = "GAC"
mascot       = "{mascot}"
aliases      = ["{published long name}"]
gender       = "men"
base_url     = "https://{host}/sports/mens-soccer"
years        = [{seasons}]
scraper      = "sidearm"
data_status  = "unverified"
enabled      = false
city         = "{Town, St.}"
identity_accessed = "{probe date}"
```

`derive_identity` (`pipeline/src/probe.py`) fills the identity fields from
what the site says of itself, reading the landing page and the newest served
schedule page: `abbreviation` is the site's own short token when the site
spells it as its whole name ("UIndy", "UIS") or when it is an opaque short
form ("UMSL"), otherwise the initials of the published name; `mascot` is the
tail of the description meta once the published name is removed ("The
official 2026 Men's Soccer schedule for the UIS Prairie Stars"), kept whole
when the hostname spells it; `aliases` are the published long name and every
schedule opponent spelling that contains all the words of `name`, minus any
spelling the collector's identity key already folds onto the name; `city` is
the town the schedule page prints most often on its home rows, AP style,
which the programmes reference (`uv run build-programmes`, tl-891) resolves
to one Gazetteer place, and `identity_accessed` the probe date. A mascot
the site does not publish becomes a comment line, never an empty value.

Check every field against what the site actually shows (the abbreviation in
particular is a draft: initials are a fallback, not a verdict), then paste
the stanza into `pipeline/config/schools.toml`. Human review before
any collection is mandatory: the stanza ships `enabled = false` and
`data_status = "unverified"` precisely so that pasting it changes nothing,
and `pipeline/CLAUDE.md` forbids modifying `config/schools.toml` without
explicit instruction. Conference scope is configuration, not identity: the
probe stamps whatever `--conference` you passed, and pasting the stanza is
you asserting the school belongs there.

## 4. Leave the ordinal alone

`ordinal` is a legacy field from the retired numeric `game_id` namespace.
The live collector never reads it, so a new school leaves it unset (0 means
unassigned), and several existing stanzas legitimately carry none. The one
rule that still holds is uniqueness among the ordinals that are assigned:
`load_schools` in `pipeline/src/config.py` raises on a duplicate, naming
both schools, so the historical ids the field once minted stay unambiguous.

## 5. Cover the programme in membership

Every configured programme must be covered by the data home's
`data/reference/membership.json`, enabled or not: `validate` in
`pipeline/src/membership.py` reports a missing configured programme as an
error. Author the school's membership windows, each with a source citation,
then validate:

```bash
TOUCHLINE_DATA_DIR={data-home} uv run --project pipeline check-membership
```

## 6. Enable after verification

Flip `enabled = true` and promote `data_status` only once you have verified
the source end to end. Then run the first collection.

**What you just exercised:** [Proof before parse](../../concepts/proof-before-parse/),
[Absence is data](../../concepts/absence-is-data/), and
[Conference is configuration](../../design/conference-as-configuration/).

## Related

**Run it**

- [Run a collection](../run-a-collection/): the first collection for the newly enabled school.
- [Pipeline CLI](../../reference/pipeline-cli/): every probe flag and exit code.

**Understand it**

- [Identity](../../concepts/identity/): what a school string must resolve to before it counts.
- [Season is a dimension](../../concepts/season-and-membership/): why membership windows must be authored, not inferred.
