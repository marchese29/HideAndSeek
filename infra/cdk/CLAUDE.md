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
- **Deploy-time env vars** (secret ARNs, developer IDs, bundle IDs) live in `infra/cdk/.env` — gitignored. A committed `infra/cdk/.env.example` documents which vars each stack reads. Load before deploys: `set -a; source infra/cdk/.env; set +a`.
- **README commands** prefer the credential-inferring form (`npx cdk bootstrap`, `aws sts get-caller-identity`) over explicit ARNs like `aws://<account>/<region>`.
- If you need to reference a concrete value while debugging, keep it in your shell, not in code or docs.

When reviewing a PR touching this directory, one of the things to check is: does this commit leak anything personal? If yes, refactor to env/context before merging.

## Stack layout

Three stacks, added incrementally:

- `HideAndSeek-Network` — VPC, subnets, gateways, security groups.
- `HideAndSeek-Data` — Aurora Serverless v2 + ElastiCache + Secrets Manager + the shared `DockerImageAsset`.
- `HideAndSeek-App` — ECS cluster + server/worker/reconciler Fargate services + ALB. Reuses `DataStack.appImage`. CloudFront, ACM, Route 53 A/AAAA records land in `wos.9`.

All stacks are prefixed `HideAndSeek-` to avoid collisions with other projects in the same AWS account.

SNS Mobile Push platform applications (APNs + FCM) are **not** managed by CDK: `AWS::SNS::PlatformApplication` is not a native CloudFormation resource type, so the two apps are created once per account/region via `aws sns create-platform-application` (see `README.md`). AppStack constructs their ARNs deterministically from fixed names (`hideandseek-ios`, `hideandseek-android`) + `account` + `region` and injects them as `SNS_APNS_APP_ARN` / `SNS_FCM_APP_ARN` on the server + worker task definitions. The SNS Topic + SQS queue for `EventDeliveryFailure` events is deferred to the consumer stack that will sweep dead device tokens.

## Cross-stack references

Downstream stacks take the upstream stack **instance** as a constructor prop (e.g. `new DataStack(app, '...', { network })`) and read exposed public readonly fields (`network.vpc`, `network.dbSg`, etc.). CDK synthesizes the necessary CloudFormation `Export` / `ImportValue` entries automatically. Do **not** use SSM parameters or manual exports for this — cross-stack coupling belongs in TypeScript, not runtime AWS state.

## Tagging

Every resource inherits two tags via `Tags.of(app).add(...)` in `bin/app.ts`:

- `Project=hideandseek`
- `ManagedBy=cdk`

Use these tags in verification queries (e.g. `aws ec2 describe-vpcs --filters "Name=tag:Project,Values=hideandseek"`).

## Deploy conventions

See `README.md` for exact commands. One-time bootstrap per account/region is required before first deploy.

## AppStack — services, sizing, listener

Three `FargateTaskDefinition`s + three `FargateService`s on a shared `ecs.Cluster`. All three containers run the same image (`DataStack.appImage`) with different shell commands; server exposes :8000, worker/reconciler have no port mapping.

| Service | cpu / memoryMiB | desiredCount | deploy % (min/max) | SG (from NetworkStack) | Invocation |
|---|---|---|---|---|---|
| `ServerService` | 512 / 1024 | 1 | 100 / 200 | `serverSg` | `uvicorn hideandseek.main:app --host 0.0.0.0 --port 8000` |
| `WorkerService` | 256 / 512 | 1 | 50 / 200 | `workerSg` | `celery -A hideandseek_worker.celery_app worker` |
| `ReconcilerService` | 256 / 512 | 1 | **0 / 100** | `reconcilerSg` | `python -m hideandseek_reconciler` |

The reconciler's 0/100 config is the singleton-safe deploy strategy from the design doc: ECS stops the old task before starting the new one, accepting a 30–60s scheduling gap that the overdue query catches on the next tick. The gap is safe because reconciler SIGTERM handling was audited in `wos.2`. Server + worker use standard rolling deploys.

Per-service task roles (defined inline in AppStack):
- `ServerTaskRole` — `sns:CreatePlatformEndpoint`, `sns:SetEndpointAttributes`, `sns:GetEndpointAttributes` on the two platform-application ARNs; `sns:Publish` on endpoint-ARN children.
- `WorkerTaskRole` — `sns:Publish` on endpoint-ARN children only (worker doesn't register tokens).
- `ReconcilerTaskRole` — no extra permissions beyond the default exec role (DB access flows through the Secrets Manager-backed `DATABASE_URL`; Redis is in-VPC, no AWS API calls).

### Networking: public subnets + `assignPublicIp`

All three services run in the **public** dual-stack subnets with `assignPublicIp: true`, not the isolated ones. The original design was "isolated subnets + EIGW for IPv6-only egress", but Fargate's control plane (ECR, Secrets Manager, CloudWatch Logs) only advertises IPv4 endpoints for those APIs — so with no IPv4 egress route, task image pulls and secret hydration time out and the task hangs in `PENDING` until CloudFormation gives up. Cheap fixes for isolated subnets were 4× interface endpoints (~$28/mo) or a NAT gateway (~$32/mo). Public subnets with `assignPublicIp: true` cost ~$11/mo (3 × $3.60 IPv4-assignment fee) and keep the same security posture: `serverSg` ingress is ALB-only on :8000; `workerSg` / `reconcilerSg` have no ingress rules at all, so a port scan on any task IP lands on a closed port.

NetworkStack's app SGs only allow IPv4 egress to Aurora:5432 and Redis:6379 by default. AppStack adds `:443/tcp → 0.0.0.0/0` egress via `CfnSecurityGroupEgress` on each app SG so the Fargate agent can reach ECR / Secrets Manager / Logs, and so the app containers can publish to SNS. IPv6 egress on these SGs is wide-open (`::/0`) from NetworkStack.

IPv6 on Fargate ENIs is controlled entirely by the account-level ECS `dualStackIPv6` setting (`aws ecs put-account-setting --name dualStackIPv6 --value enabled`) plus subnet-level `AssignIpv6AddressOnCreation=true`. The CloudFormation `AWS::ECS::Service` schema has no per-service IPv6 toggle — attempting a `NetworkConfiguration.AwsvpcConfiguration.AssignIpv6Address` override fails with `extraneous key [AssignIpv6Address] is not permitted`.

### ALB listener port — :80 in wos.8, :443 in wos.9

The ALB is `dualstack-without-public-ipv4` (avoids the Feb-2024 public-IPv4 fees). For `wos.8` the single listener is **HTTP :80**, not :443, because the AWS-issued hostname (`*.elb.amazonaws.com`) can't carry an ACM cert and we don't own a Route 53 zone yet (that's `wos.9`). AppStack adds a temporary :80 ingress rule on `network.albSg` (NetworkStack only allows :443); `wos.9` drops that rule when it swaps the listener to :443 behind a CloudFront distribution at `hideandseek.marchese.dev`.

## DataStack — migration runner pattern

DataStack (`lib/data-stack.ts`) ships the database, the cache, and the code that migrates the database *during deploy*. The migration runner is part of DataStack (not AppStack) so that by the time AppStack brings up ECS services, the schema is already at `head`.

The pattern:
1. `ecr_assets.DockerImageAsset` builds the server image from the repo root `server/Dockerfile`. The image ships Alembic + `alembic/` already (see `server/Dockerfile` `COPY alembic.ini`/`alembic/`). AppStack will reuse this same image asset — CDK de-duplicates by content hash.
2. A `FargateTaskDefinition` runs `uv run alembic upgrade head` with the DB secret exposed as `DATABASE_URL`.
3. A Lambda-backed `CustomResource` (`lambda/run-migrations/index.py`) calls `ecs.run_task()` + `get_waiter('tasks_stopped').wait()` and reads the container's exit code. Non-zero → the custom resource fails → CloudFormation rolls back.
4. The custom resource's `PhysicalResourceId` is keyed to the Docker image digest, so any code change that rebuilds the image re-runs migrations. Idempotent deploys (no image change) skip the migration task.

## Language + tooling

- TypeScript on AWS CDK v2 (`aws-cdk-lib`). CDK v1 is EOL.
- `npx ts-node` runs the app directly from source; no separate `tsc` build step is needed to `synth` or `deploy`. Use `npx tsc --noEmit` for typecheck-only.
- Node 22+ (`.nvmrc` not committed; rely on whatever the operator has).
