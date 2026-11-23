# Site deploy

The public site is built from touchline-ui and served from a private S3 bucket
behind CloudFront (`infra/main/site.tf`). `.github/workflows/publish-site.yml`
runs the whole step:

1. `uv run check-contracts` over the data homes (samples or the private homes).
2. `pipeline/scripts/cut_bundle.py` cuts each home to the site bundle: every
   season's JSON (the site renders the current season but reads earlier ones
   too), no raw pages, with a `data/bundle.json` manifest naming the home's
   commit and the season to build.
3. `site/build.sh` builds touchline-ui at the commit in `touchline-ui.sha`,
   once per division and gender, at the paths they are served from (`/`,
   `/women/`, `/d1/`, `/d1/women/`), and runs touchline-ui's tests and link
   check on each.
4. `site/sync.py` uploads only files whose content changed (MD5 against the
   object's ETag), assets before pages, then deletes what the build dropped.
5. One `/*` CloudFront invalidation, then touchline-ui's `scripts/deployed.ts`
   asks the live site for every sample page and its assets.

## Run it

It runs daily at 15:47 UTC, 90 minutes after Collect's schedule, while today
(UTC) is on or before the `TOUCHLINE_COLLECT_UNTIL` variable, the same date
Collect stops on. It always reads the data homes' `main` (the Mac's production
data), never Collect's `shadow`, so it does not wait on Collect finishing. Otherwise: Actions → Publish site → Run
workflow on `main`, or merge a change under `site/`. `source` is `data` (the private homes, read with the publisher App,
see `infra/GITHUB_APP.md`; the default) or `samples` (the sample homes). The
repo variable `SITE_SOURCE` overrides the default for runs that do not say.
A dispatch that names the other source (`samples` while the site serves
`data`) builds and gates the site but does not deploy it: it fills that
source's snapshot folder (`snapshots/samples/`) and leaves the live site alone.
To switch what the live site serves, change `SITE_SOURCE`.
Pull requests that touch the site build and test the sample site and deploy
nothing.

## Change what the site runs

touchline-ui is pinned: bump `touchline-ui.sha` to a commit on its main in a
pull request here, which builds and tests it before it can deploy. Journals
are data, not code: a `data` run reads them from touchline-ui main.

## Locally

```bash
(cd pipeline && uv run python -m scripts.cut_bundle --home ../samples/d2-soccer --source-sha local --out /tmp/b/d2-soccer)
(cd pipeline && uv run python -m scripts.cut_bundle --home ../samples/d1-soccer --source-sha local --out /tmp/b/d1-soccer)
TOUCHLINE_CONTRACTS_DIR=$PWD/contracts sh site/build.sh ../touchline-ui /tmp/b https://example.invalid /tmp/smoke.tsv
uv run site/sync.py --dist ../touchline-ui/dist --bucket touchline-site-<account> --dry-run
```
