# Dataset snapshot

The `snapshot` and `release` jobs of `.github/workflows/publish-site.yml`
publish the desk's dataset: `touchline.duckdb` (contract format 1), its daily
row deltas and a signed manifest. touchline-desk's own `packages/data` writes
them, at the commit in `touchline-desk.sha`, from the same data-home commits
the site bundle was cut from. The JSON data homes stay the system of record.

## Where it goes

`s3://touchline-data-<account>/snapshots/<source>/<scope>/`, one desk publish
folder each, exactly as `touchline index publish` writes it:

```
latest.json                    names the current snapshot (moved last)
manifests/<id>.json  <id>.sig  signed manifest
base/<id>.duckdb.zst           the whole index
deltas/<from>__<to>.duckdb.zst rows that changed since the last snapshot
```

- `source`: `data` (the private homes, main's default) or `samples`
  (`samples/` here), so a sample run never joins the real dataset's history.
- `scope`: `all` (every division and gender, what the desk reads in the
  pilot) and one per division and gender (`d2-men`, `d1-women`, ...), all
  from the workflow's `DIVISIONS` list.

`touchline index fetch <folder>` reads any of them unchanged.

## What a run does

1. `bundle` holds the homes to the contracts and cuts the site bundle.
2. `snapshot` installs only the desk's `packages/data` (`--frozen-lockfile
   --ignore-scripts`), checks the homes out at the bundle's commits, runs
   `check-contracts` on them, then `build.sh` does this for each scope:
   - builds the index (a scope with no games, or a season file the desk can't
     read, stops the run)
   - reads the folder's current `latest.json`, manifest and base, and verifies
     them with the public key
   - publishes the next snapshot with `--kms-key alias/touchline-snapshot-signing`.
     A table that loses rows stops it unless the run says why (`allow_shrink`).
   - checks the manifest names the pinned DuckDB engine
   - verifies the new snapshot through the desk's own fetch, twice: by delta
     from the served one, and from the base alone
   - uploads every new file with `If-None-Match: *`, so nothing published is
     ever replaced, and stages `latest.json`
3. `site` deploys and smoke-checks the live site. It needs `snapshot`, so a
   dataset that does not build, sign and verify keeps the site as it was.
4. `release` runs only when the smoke check passed. `release.sh` writes each
   scope's `latest.json` with `If-Match` on the ETag the snapshot job read
   (`If-None-Match: *` for a first one), after checking its manifest is in the
   bucket. A scope someone else moved meanwhile is left alone and fails the job.

Until `release`, the desk sees nothing new. If a run stops after uploading,
the files it wrote are orphans that no `latest.json` names; the next run
publishes past them.

## Pins

- `touchline-desk.sha`: the desk commit that builds and signs. Bump it in a
  pull request when the desk's `packages/data` changes.
- `duckdb.env`: `NODE_API` must equal the desk's exact `@duckdb/node-api`
  pin and `ENGINE` the engine its manifests name. The app reads only a
  snapshot written by its own engine, so both sides move together.
- `signing-public-key.pem` (once committed): the KMS public key. A run whose
  key differs stops before signing. Each main run prints the key in its
  summary; the desk ships the same key as `SNAPSHOT_PUBLIC_KEY`.

## Signing

ECDSA P-256 over SHA-256 with the KMS key `alias/touchline-snapshot-signing`
(`infra/bootstrap/kms.tf`). KMS signs the digest, so the private key never
reaches a runner, and the desk checks every signature against the key's
public key before using it. Runs off main sign with a throwaway key and
upload nothing.

## Pull requests

The publisher App's key is in the `production` environment, which only main
may use, so a pull request can't read the private touchline-desk and its
snapshot job only says so. Every run on main builds, signs and verifies.
`build.sh` works without a bucket, keeping the folder in `$WORK`; run it twice
to check the delta too:

```bash
node <desk>/packages/data/dist/cli.js keygen /tmp/k   # throwaway key
DESK_CLI=<desk>/packages/data/dist/cli.js HOMES_DIR=<folder with d2-soccer, d1-soccer> \
DIVISIONS="d2 d1" SOURCE=samples WORK=/tmp/snap SIGN=key:/tmp/k.key PUBLIC_KEY=/tmp/k.pub \
ENGINE=v2.0.0 PROVENANCE=local DESK_SHA=local sh snapshot/build.sh
```

## Not yet

- The desk's oracle facts aren't checked here (`--no-oracle`). They describe
  the oracle home, not every scope.
- The number check that compares site figures with the desk's recount is a
  separate step of the plan.
