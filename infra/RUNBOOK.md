# Bootstrap runbook

Run once, on Daniel's Mac, with the AWS CLI signed in to the Touchline
account. About 15 minutes. After this, every infrastructure change goes
through a pull request and the Infra workflow.

Commands assume `zsh` and a clone at
`~/source/edinsights/keelson-rib-touchline`.

## 0. Check the tools and the GitHub plan

```bash
# Terraform: infra/.terraform-version pins 1.17.2, which tfenv reads.
cd ~/source/edinsights/keelson-rib-touchline   # after step 3's checkout, or any clone of the branch
tfenv install              # installs the pinned version
terraform version          # should print 1.17.2
# without tfenv: brew tap hashicorp/tap && brew install hashicorp/tap/terraform
aws --version
gh auth status
gh api orgs/ed-insights-ai --jq .plan.name
```

GitHub environments on a private repo need the org on **Team** (or higher).
If the last command prints `free`, stop here and tell Claude: the roles then
need a branch-only trust instead, which is a small change.

## 1. Confirm the AWS account

```bash
export AWS_PROFILE=default      # or the profile you use for Touchline
aws sts get-caller-identity
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo $AWS_ACCOUNT_ID
```

Check the account id is the one you mean to use.

## 2. Check what the account already has

```bash
aws iam list-open-id-connect-providers
aws s3api list-buckets --query 'Buckets[].Name'
```

- If the first list includes `token.actions.githubusercontent.com`, the
  account already has GitHub's OIDC provider (an account can hold only one).
- If the account serves anything public straight from S3 (a website bucket,
  public downloads), account-wide Block Public Access would break it. A fresh
  Touchline account has nothing like that.

## 3. Check out the branch and write your settings

```bash
cd ~/source/edinsights/keelson-rib-touchline
git fetch origin infra/aws-foundation:refs/remotes/origin/infra/aws-foundation
git switch --track origin/infra/aws-foundation
cd infra/bootstrap

cat > terraform.tfvars <<'TFVARS'
budget_email = "YOUR_EMAIL"
# create_oidc_provider        = false   # uncomment if step 2 found the provider
# block_account_public_access = false   # uncomment if step 2 found public S3 use
TFVARS
```

`terraform.tfvars` is loaded automatically by every command below and is
gitignored, so your email stays off GitHub. Keep the file: any later
bootstrap change needs it.

## 4. First apply, with local state

This stack creates the state bucket, so the first run keeps state locally.

```bash
printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

The plan should add **17** resources and change or destroy nothing: the state
bucket and its six settings, account-wide Block Public Access, the OIDC
provider, the snapshot signing key and its alias, the budget, the
`touchline-infra-deploy` role and its policy, the
`touchline-publish-boundary` policy, and the `touchline-publish` and
`touchline-publish-site` roles (with no permissions yet; the Infra workflow
adds those). Each line you uncommented in
`terraform.tfvars` removes one.

## 5. Move the state into the bucket

```bash
rm backend_override.tf tfplan
terraform init -migrate-state -backend-config="bucket=touchline-tfstate-$AWS_ACCOUNT_ID"
# answer "yes" to copy the state
terraform plan       # must say: No changes.
rm -f terraform.tfstate terraform.tfstate.backup
```

## 6. Tell GitHub to put the branch in the OIDC subject

Both roles only trust tokens whose subject names the environment **and**
`refs/heads/main`. GitHub's default subject for environment jobs leaves the
branch out, so set the repo's template:

```bash
gh api -X PUT repos/ed-insights-ai/keelson-rib-touchline/actions/oidc/customization/sub \
  -F use_default=false \
  -f 'include_claim_keys[]=repo' \
  -f 'include_claim_keys[]=context' \
  -f 'include_claim_keys[]=ref'
gh api repos/ed-insights-ai/keelson-rib-touchline/actions/oidc/customization/sub
```

## 7. Create the two environments, main only

```bash
R=repos/ed-insights-ai/keelson-rib-touchline
for env in infra production; do
  gh api -X PUT $R/environments/$env --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
  gh api -X POST $R/environments/$env/deployment-branch-policies -f name=main -f type=branch
  gh variable set AWS_ACCOUNT_ID --env $env --body "$AWS_ACCOUNT_ID" -R ed-insights-ai/keelson-rib-touchline
done
```

Optional: in the repo's Settings, Environments, `infra`, add yourself as a
required reviewer, so each apply waits for your click.

## 8. Merge the pull request

Merging runs the Infra workflow, which applies `infra/main`: the data bucket,
the site bucket and CloudFront distribution, and the two publish roles'
permissions. The distribution takes 5 to 10 minutes to deploy, so the run
takes about that long. Watch it:

```bash
gh run watch -R ed-insights-ai/keelson-rib-touchline \
  $(gh run list -R ed-insights-ai/keelson-rib-touchline -w Infra -L 1 --json databaseId -q '.[0].databaseId')
```

To re-run later without a change: `gh workflow run infra.yml --ref main`.

## 9. Check the result

```bash
aws s3api get-bucket-lifecycle-configuration --bucket touchline-data-$AWS_ACCOUNT_ID --query 'Rules[].ID'
aws kms get-public-key --key-id alias/touchline-snapshot-signing --query 'SigningAlgorithms'
aws iam get-role --role-name touchline-publish --query 'Role.PermissionsBoundary'
aws iam get-role --role-name touchline-publish-site --query 'Role.PermissionsBoundary'
aws budgets describe-budgets --account-id $AWS_ACCOUNT_ID --query 'Budgets[].BudgetName'
aws cloudfront list-distributions --query 'DistributionList.Items[].{id:Id,domain:DomainName,status:Status}'
curl -sI https://$(aws cloudfront list-distributions --query 'DistributionList.Items[0].DomainName' --output text)/ | head -1
```

The last line prints a 404 until the publish workflow uploads the site; that
is expected, and shows CloudFront is serving the site's error page path.

Then tell Claude it is done. The next steps (the GitHub App, then the publish
workflow) pick up from here.

## If something goes wrong

- **The signing key** is permanent: it has `prevent_destroy`, and only this
  bootstrap stack can change it. Changing `signing_key_spec` later means a new
  key and re-signing, so settle the algorithm with the desk's `sign.ts` first.
- **Step 4 fails part way:** fix the cause and run `terraform apply` again; it
  continues from the local state. Do not delete `terraform.tfstate`.
- **Bucket name taken:** names include the account id, so this means the
  bucket already exists in this account. Tell Claude.
- **The workflow cannot assume the role** (`Not authorized to perform
  sts:AssumeRoleWithWebIdentity`): step 6 or 7 is missing, or the run was not
  on `main`.
- **Undo everything:** the buckets and key have `prevent_destroy`; ask Claude
  for the teardown steps rather than forcing a destroy.
