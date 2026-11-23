# GitHub App setup

One GitHub App replaces personal tokens for every push the pipeline makes: the
season files into `d1-soccer` and `d2-soccer` (and `d3-soccer` when it
exists), and the built site onto `gh-pages` of `touchline-ui` (renamed
`touchline-web` at cutover; the install follows the rename). Daniel does this
by hand, about 10 minutes, after the bootstrap runbook. Its tokens last an
hour and are minted per job, so nothing expires on a calendar.

## 1. Create the App

Open <https://github.com/organizations/ed-insights-ai/settings/apps/new> and set:

| Field | Value |
| --- | --- |
| GitHub App name | `touchline-publisher` (names are global; add `-ed` if taken) |
| Homepage URL | `https://github.com/ed-insights-ai/keelson-rib-touchline` |
| Webhook, Active | **unchecked** |
| Repository permissions, Contents | **Read and write** |
| Repository permissions, Metadata | Read-only (set automatically) |
| Every other permission | No access. In particular not **Workflows**, so the App can never push a workflow file. |
| Where can this GitHub App be installed? | **Only on this account** |

Click **Create GitHub App**. On the next page note the **App ID**, then under
**Private keys** click **Generate a private key**. A `.pem` file downloads.

## 2. Install it on three repos only

On the App's page, **Install App**, `ed-insights-ai`, **Only select
repositories**: `d1-soccer`, `d2-soccer`, `touchline-ui`. Install.

## 3. Store the id and key in the rib's production environment

```bash
R=ed-insights-ai/keelson-rib-touchline
gh variable set TOUCHLINE_APP_ID --env production --body "<App ID>" -R $R
gh secret   set TOUCHLINE_APP_PRIVATE_KEY --env production -R $R < ~/Downloads/touchline-publisher.*.private-key.pem
```

Then move the `.pem` into your password manager and delete it from Downloads.

## 4. Keep the App off the site's main branch

App permissions cannot be limited to one branch, so a ruleset does it: the
App may push `gh-pages`, but `main` of `touchline-ui` takes changes only
through pull requests. On the data homes the App pushes to `main` directly, so
the ruleset there only blocks force-pushes and deletion.

```bash
gh api -X POST repos/ed-insights-ai/touchline-ui/rulesets --input - <<'JSON'
{
  "name": "protect main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false}}
  ]
}
JSON

for repo in d1-soccer d2-soccer; do
  gh api -X POST repos/ed-insights-ai/$repo/rulesets --input - <<'JSON'
{
  "name": "no force-push or delete on main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]
}
JSON
done
```

Rulesets on the private data homes need the org on Team, like the
environments in the runbook.

## How the workflows use it

Each job mints a token for just the repo it pushes to:

```yaml
- uses: actions/create-github-app-token@f418cff399f7aef4c2f0ad47e25ca7a6abbdd6fc # v3.4.0
  id: app
  with:
    app-id: ${{ vars.TOUCHLINE_APP_ID }}
    private-key: ${{ secrets.TOUCHLINE_APP_PRIVATE_KEY }}
    owner: ed-insights-ai
    repositories: d2-soccer
```

When `d3-soccer` exists, add it to the App's installation (step 2) and to the
ruleset loop (step 4).
