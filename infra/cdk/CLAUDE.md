# infra/cdk

AWS CDK app (TypeScript) for deploying the HideAndSeek backend. Sibling of the uv Python workspace; **not** a uv workspace member.

## No personal information in this package

**This is a hard rule, not a suggestion.** Nothing personally identifying may appear in any committed file in this directory. That includes:

- AWS account IDs
- Hostnames (e.g. a specific subdomain someone operates)
- Domain names
- Route 53 hosted zone IDs
- Email addresses
- Anything else that ties a committed file to a specific operator

The CDK app must deploy cleanly into **any** AWS account the operator is authenticated against, with **no code edits**. The goal is portability, not secrecy — these values are sometimes technically public, but hardcoding them couples the repo to one deployer.

### How this is enforced in practice

- **Account + region** are read from `CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION` (populated automatically by the CDK CLI from the active AWS credentials), never hardcoded in any stack or `cdk.json`.
- **Domain / hosted zone** values (needed for `wos.9+`) enter via `process.env.*` or CDK context. `cdk.context.json` is gitignored.
- **README commands** prefer the credential-inferring form (`npx cdk bootstrap`, `aws sts get-caller-identity`) over explicit ARNs like `aws://<account>/<region>`.
- If you need to reference a concrete value while debugging, keep it in your shell, not in code or docs.

When reviewing a PR touching this directory, one of the things to check is: does this commit leak anything personal? If yes, refactor to env/context before merging.

## Stack layout

Four stacks, added incrementally:

- `HideAndSeek-Network` (this issue) — VPC, subnets, gateways, security groups.
- `HideAndSeek-Data` (wos.6) — Aurora Serverless v2 + ElastiCache + Secrets Manager.
- `HideAndSeek-Push` (wos.7) — SNS platform applications + delivery-failure SQS.
- `HideAndSeek-App` (wos.8, wos.9) — ECR, ECS cluster + services, ALB, CloudFront, ACM, Route 53 A/AAAA records.

All stacks are prefixed `HideAndSeek-` to avoid collisions with other projects in the same AWS account.

## Cross-stack references

Downstream stacks take the upstream stack **instance** as a constructor prop (e.g. `new DataStack(app, '...', { network })`) and read exposed public readonly fields (`network.vpc`, `network.dbSg`, etc.). CDK synthesizes the necessary CloudFormation `Export` / `ImportValue` entries automatically. Do **not** use SSM parameters or manual exports for this — cross-stack coupling belongs in TypeScript, not runtime AWS state.

## Tagging

Every resource inherits two tags via `Tags.of(app).add(...)` in `bin/app.ts`:

- `Project=hideandseek`
- `ManagedBy=cdk`

Use these tags in verification queries (e.g. `aws ec2 describe-vpcs --filters "Name=tag:Project,Values=hideandseek"`).

## Deploy conventions

See `README.md` for exact commands. One-time bootstrap per account/region is required before first deploy.

## Language + tooling

- TypeScript on AWS CDK v2 (`aws-cdk-lib`). CDK v1 is EOL.
- `npx ts-node` runs the app directly from source; no separate `tsc` build step is needed to `synth` or `deploy`. Use `npx tsc --noEmit` for typecheck-only.
- Node 22+ (`.nvmrc` not committed; rely on whatever the operator has).
