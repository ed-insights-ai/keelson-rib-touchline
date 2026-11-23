# Site deploy

The public site is built from touchline-ui and served from a private S3 bucket
behind CloudFront (`infra/main/site.tf`). `.github/workflows/publish-site.yml`
runs the whole step:

1. `uv run check-contracts` over the data homes (samples or the private homes).
2. `pipeline/scripts/cut_bundle.py` cuts each home to the current-season
   bundle the site reads, with a `data/bundle.json` manifest naming the home's
   commit.
3. `site/build.sh` builds touchline-ui at the commit in `touchline-ui.sha`,
   once per division and gender, at the paths they are served from (`/`,
   `/women/`, `/d1/`, `/d1/women/`), and runs touchline-ui's tests and link
   check on each.
4. `site/sync.py` uploads only files whose content changed (MD5 against the
   object's ETag), assets before pages, then deletes what the build dropped.
5. One `/*` CloudFront invalidation, then touchline-ui's `scripts/deployed.ts`
   asks the live site for every sample page and its assets.

## Run it

Actions → Publish site → Run workflow on `main`. `source` is `samples` (the
sample homes) or `data` (the private homes; needs the publisher App installed
on d1-soccer and d2-soccer, see `infra/GITHUB_APP.md`). The repo variable
`SITE_SOURCE` sets the default for runs that do not say. Pull requests that
touch the site build and test the sample site and deploy nothing.

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
