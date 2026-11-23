# infra

AWS and GitHub foundation for the Touchline pilot: the private data bucket the
collector and publish jobs write, the KMS key that signs snapshots, and the
roles GitHub Actions assumes through OIDC. No long-lived AWS keys exist
anywhere.

| Stack | Applied by | Holds |
| --- | --- | --- |
| [`bootstrap/`](bootstrap/) | Daniel, once, with his signed-in AWS CLI ([RUNBOOK.md](RUNBOOK.md)) | Terraform state bucket, GitHub's OIDC provider, the `touchline-infra-deploy` role, the boundary for publish roles, the $5 monthly budget |
| [`main/`](main/) | The [Infra workflow](../.github/workflows/infra.yml) on merge to `main`, via `touchline-infra-deploy` | `touchline-data-<account>` bucket and its lifecycle rules, the snapshot signing key, the `touchline-publish` role |

The GitHub App that pushes to the data homes and `gh-pages` is set up by hand:
[GITHUB_APP.md](GITHUB_APP.md).

## Who can do what

- **`touchline-publish`** (jobs in the `production` environment, on `main`):
  read the bucket, write `raw/`, `snapshots/base/<scope>/`,
  `snapshots/delta/<scope>/`, `site/`, `news/` and `latest.json`, and sign with
  the snapshot key. It cannot delete anything; lifecycle rules do that. It is
  capped by the `touchline-publish-boundary` policy, so a change to `main/`
  cannot widen it past that.
- **`touchline-infra-deploy`** (jobs in the `infra` environment, on `main`):
  manage the data bucket's configuration (not its objects), KMS keys tagged
  `project=touchline`, and `touchline-publish*` roles that carry the boundary.
  It cannot sign, attach managed policies, or touch itself, the budget or the
  bootstrap state.
- Both trust policies match the OIDC subject
  `repo:ed-insights-ai/keelson-rib-touchline:environment:<env>:ref:refs/heads/main`,
  so a pull request, another branch or another repo cannot assume them.

## Divisions and scopes

`main/variables.tf` has one `divisions` list (`d1`, `d2`, `d3`) and one
`genders` list. Snapshot scopes (`d1-men`, `d3-women`, ...) and the publish
role's write paths are computed from them, so adding a division is a one-line
change. Lifecycle rules are per kind, not per scope:

| Prefix | Kept |
| --- | --- |
| `raw/` | forever (re-parse, never re-scrape) |
| `snapshots/base/<scope>/` | current version forever; replaced versions 7 days |
| `snapshots/delta/<scope>/` | 45 days |
| `site/` | 30 days |
| `news/`, `latest.json` | forever |
| any overwritten version | 7 days |

Bases live at a stable key per scope and are overwritten by each publish, so
the base `latest.json` points at never expires, even through the off-season
when collection stops for months. `latest.json` should record the base's S3
version id, and desk links should include it, so a desk reads exactly the
base that was signed. Deltas use dated keys and age out; a desk whose base is
older than the oldest delta takes the full base.

## Expected cost

| Item | A month |
| --- | --- |
| KMS signing key | $1.00, the only standing charge |
| KMS `Sign` calls (a few a day) | under $0.01 |
| S3 data, in season | about $0.10 to $0.30 (raw HTML not yet measured) |
| S3 state bucket | under $0.01 |
| OIDC provider, IAM roles | $0 |
| AWS Budgets (first two budgets) | $0 |
| **Total** | **about $1.10 to $1.30** |

The budget emails at 80% of $5 actual and at 100% forecast. Data transfer out
to desks is free up to 100 GB a month.

## Local checks

```bash
terraform -chdir=infra fmt -recursive -check
terraform -chdir=infra/bootstrap init -backend=false && terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/main init -backend=false && terraform -chdir=infra/main validate
```
