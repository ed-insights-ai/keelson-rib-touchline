# infra

AWS and GitHub foundation for the Touchline pilot: the private data bucket the
collector and publish jobs write, the KMS key that signs snapshots, the public
site on S3 behind CloudFront, and the roles GitHub Actions assumes through
OIDC. No long-lived AWS keys exist anywhere.

| Stack | Applied by | Holds |
| --- | --- | --- |
| [`bootstrap/`](bootstrap/) | Daniel, once, with his signed-in AWS CLI ([RUNBOOK.md](RUNBOOK.md)) | Terraform state bucket, account-wide S3 Block Public Access, GitHub's OIDC provider, the snapshot signing key, the `touchline-infra-deploy` role, the `touchline-publish` and `touchline-publish-site` roles with their trust and boundary, the monthly budget and its alerts |
| [`main/`](main/) | The [Infra workflow](../.github/workflows/infra.yml) on merge to `main`, via `touchline-infra-deploy` | `touchline-data-<account>` bucket, `touchline-site-<account>` bucket and its CloudFront distribution, the inline permissions of the two publish roles |

The GitHub App that pushes season files to the data homes is set up by hand:
[GITHUB_APP.md](GITHUB_APP.md).

## Who can do what

- **`touchline-publish`** (jobs in the `production` environment, on `main`):
  read the data bucket, write `raw/`, `snapshots/base/<scope>/`,
  `snapshots/delta/<scope>/`, `bundles/`, `news/` and `latest.json`, and sign
  with the snapshot key. It cannot delete anything; lifecycle rules do that.
  No access to the site bucket.
- **`touchline-publish-site`** (same environment and branch): list, put and
  delete in the site bucket, and invalidate the site's distribution. No access
  to the data bucket or the key.
- Both publish roles are capped by the `touchline-publish-boundary` policy, so
  a change to `main/` cannot widen them past it.
- **`touchline-infra-deploy`** (jobs in the `infra` environment, on `main`):
  manage the two buckets' configuration, CloudFront, and the publish roles'
  inline permissions. It cannot create roles or change any role's trust or
  boundary, so it cannot make a publish role trust its own jobs. An explicit deny keeps it out of both
  buckets' objects, even through a bucket policy it writes. It can only read
  the signing key's public half: no grants, key policy changes, new keys or
  signing. It cannot attach managed policies, or touch itself, the budget,
  account-wide Block Public Access or the bootstrap state.
- **The signing key** lives in the bootstrap stack, so only Daniel's signed-in
  CLI can change, disable or delete it.
- Every trust policy matches the immutable OIDC subject
  `repo:ed-insights-ai@210274923/keelson-rib-touchline@1328075011:environment:<env>:ref:refs/heads/main`,
  so a pull request, another branch or another repo cannot assume them.

## Divisions and scopes

`main/variables.tf` has one `divisions` list (`d1`, `d2`, `d3`) and one
`genders` list. Snapshot scopes (`d1-men`, `d3-women`, ...), the publish
role's write paths and the site's build folders are all computed from them,
so adding a division is a one-line change.

Data bucket lifecycle, per kind:

| Prefix | Kept |
| --- | --- |
| `raw/` | forever (re-parse, never re-scrape) |
| `snapshots/base/<scope>/` | current version forever; replaced versions 7 days |
| `snapshots/delta/<scope>/` | 45 days |
| `bundles/` | 30 days |
| `news/`, `latest.json` | forever |
| any overwritten version | 7 days |

Bases live at a stable key per scope and are overwritten by each publish, so
the base `latest.json` points at never expires, even through the off-season
when collection stops for months. `latest.json` should record the base's S3
version id, and desk links should include it, so a desk reads exactly the
base that was signed. Deltas use dated keys and age out; a desk whose base is
older than the oldest delta takes the full base.

## The site

The built site (about 2.7 GB, about 4.9 GB with D3) is over GitHub Pages' 1 GB
limit, so it is served from a private S3 bucket through CloudFront:

- **Origin access control.** The bucket keeps Block Public Access on; its
  policy lets only this distribution read.
- **Build folders** (output `site_build_prefixes`): the root division
  (`site_root_division`, default `d2`) at `/` and `/women/`, others at
  `/<div>/` and `/<div>/women/`.
- **URLs.** A viewer-request function serves `/x/` and `/x` from
  `/x/index.html`. Missing pages return the root build's `/404.html` with a
  404 status.
- **Caching.** Pages 5 minutes by default; content-hashed `_astro/` assets a
  year. Deploys invalidate `/*` (one path; the first 1,000 a month are free).
- **Headers.** HSTS, `nosniff`, `X-Frame-Options: DENY`, a strict referrer
  policy. No CSP yet, since Astro islands use inline scripts.
- **PriceClass_100** (North America and Europe edges), the cheapest.
- **Custom domain, optional.** Set `site_domain_names` and
  `site_acm_certificate_arn` (a certificate in us-east-1). Unset, the site is
  at its `cloudfront.net` name (output `site_url`).
- Replaced site files are kept 3 days, then expire.

**For the publish workflow:** upload only files whose content changed (for
example `rclone sync --checksum`). `aws s3 sync` compares timestamps, so after
a fresh build it re-uploads every file, and PUT requests on tens of thousands
of files every day would cost more than everything else here combined.

## Expected cost

| Item | A month |
| --- | --- |
| KMS signing key | $1.00, the only standing charge |
| KMS `Sign` calls (a few a day) | under $0.01 |
| S3 data, in season | about $0.10 to $0.30 (raw HTML not yet measured) |
| S3 site, 2.7 to 4.9 GB plus 3 days of replaced files | about $0.10 to $0.20 |
| Site deploy PUTs, changed files only | cents (see the note above) |
| CloudFront (always-free tier: 1 TB out, 10M requests, 2M function calls) | $0 at pilot traffic |
| S3 state bucket | under $0.01 |
| OIDC provider, IAM roles, budget | $0 |
| **Total** | **about $1.20 to $1.50** |

The budget emails at $4 actual (80% of $5), at $5 forecast, and again at
$10 actual.

## Local checks

```bash
terraform -chdir=infra fmt -recursive -check
terraform -chdir=infra/bootstrap init -backend=false && terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/main init -backend=false && terraform -chdir=infra/main validate
```
