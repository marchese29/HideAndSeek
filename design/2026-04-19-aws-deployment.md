# AWS Deployment Design

> Status: **Draft**
> Last updated: 2026-04-19

How the HideAndSeek backend runs on AWS: compute, data, networking, and the service-level code changes required to fit the platform. Target domain: `hideandseek.marchese.dev`. IaC via AWS CDK.

---

## Core Principles

1. **One AWS account, one region** — no multi-region, no cross-account complexity. Start in `us-west-2`.
2. **Managed services where they clearly pay off** — Aurora Serverless v2, ElastiCache, SNS, ALB, CloudFront. Skip managed services that solve problems we don't currently have (e.g. RDS Proxy — see Out of Scope).
3. **IPv6 wherever it's free, dual-stack where users live** — egress from Fargate is IPv6-only (costs $0). Public ingress stays dual-stack via CloudFront because ~50% of end users can't reach an IPv6-only AAAA record today.
4. **No NAT gateway, no interface endpoints** — the biggest "idle fee" in a standard AWS deploy. Replaced by IPv6-only egress via an Egress-Only Internet Gateway.
5. **Scale to zero when idle** — Aurora at 0 ACU, Fargate `desiredCount` can be knocked to 0 for long dev pauses. Billable floor under $40/mo when no one is playing.
6. **Push migrates to SNS** — removes `aioapns` + `firebase-admin` as runtime dependencies, deletes credential management from app code, and removes a class of external-egress bug.

---

## Architecture

### Topology

```
                          Internet (IPv4 + IPv6)
                                  │
                                  ▼
                        ┌──────────────────┐
                        │    CloudFront    │  dualstack edge; free 1 TB/mo out
                        │   hideandseek.   │
                        │   marchese.dev   │
                        └────────┬─────────┘
                                 │ IPv6 origin
                                 ▼
  ┌─ VPC (10.0.0.0/16 + IPv6 /56) ──────────────────────────────────┐
  │                                                                 │
  │  ┌─ Public subnets (AZ-a, AZ-b; dualstack) ─────────────────┐  │
  │  │    ALB  (ipAddressType = dualstack-without-public-ipv4)  │  │
  │  └───────────────────┬──────────────────────────────────────┘  │
  │                      │ VPC-internal                             │
  │  ┌─ Private subnets (AZ-a, AZ-b; IPv6-only) ────────────────┐  │
  │  │                                                          │  │
  │  │   Fargate  server   (desiredCount ≥ 1)                   │  │
  │  │   Fargate  worker   (desiredCount 1–N)                   │  │
  │  │   Fargate  reconciler (desiredCount = 1, singleton)      │  │
  │  │       │                                                  │  │
  │  │       ├──► Aurora Serverless v2 (Postgres + PostGIS)     │  │
  │  │       ├──► ElastiCache Redis                             │  │
  │  │       └──► Egress-Only IGW ──► SNS, ECR, Secrets, Logs   │  │
  │  │                                 (via IPv6 dualstack      │  │
  │  │                                  endpoints)              │  │
  │  └──────────────────────────────────────────────────────────┘  │
  └────────────────────────────────────────────────────────────────┘
```

### Why this shape

| Decision | Rationale |
|---|---|
| CloudFront in front of ALB | Lets ALB be IPv6-only (skip ~$7/mo public-IPv4 fees), gets us dualstack at the edge for free, provides WAF/DDoS at L7 if we ever want it. 1 TB/mo egress is permanently free-tier. |
| IPv6-only egress | Every dep we need (ECR, SNS, Secrets Manager, CloudWatch Logs, Aurora via dual-stack subnet, ElastiCache) supports IPv6 per the [AWS IPv6 support matrix](https://docs.aws.amazon.com/vpc/latest/userguide/aws-ipv6-support.html). Egress-Only IGW is free; skipping NAT saves $32/mo per AZ and beats interface endpoints on cost. |
| Private subnets for Fargate | No public IPs → no $3.60/mo per task IPv4 charge, and SG misconfiguration can't accidentally expose a task. |
| Aurora Serverless v2 min 0 ACU | Idle cost collapses to storage only (~$2/mo). Cold-start latency (~15s after pause) is acceptable — the reconciler poll absorbs it, and interactive requests hit it only on first access after a long idle. |
| ElastiCache (not serverless) | Celery broker + SSE pub/sub need low per-message latency; serverless cache's minimum ($90+/mo) is worse than a `cache.t4g.micro` node ($12/mo). |
| No NAT, no interface endpoints, no RDS Proxy | Each is a managed service that solves a specific problem. We either don't have the problem (NAT), get a cheaper path (IPv6 for endpoints), or haven't hit the scale (Proxy). |

---

## Components

### CloudFront (public ingress)

- Single distribution, origin = the ALB's IPv6 hostname. CloudFront supports IPv6-only origins end-to-end.
- Alternate domain name: `hideandseek.marchese.dev`.
- ACM certificate in `us-east-1` (CloudFront requirement).
- Behaviors:
  - `Default` — forward everything to origin, no caching of mutation endpoints.
  - `/games/*/lobby/events`, `/games/*/hider-state`, `/games/*/seeker-state` — cache policy `CachingDisabled`; origin request policy forwards `X-Player-Id` + `X-Player-Secret` headers (CloudFront strips unknown headers by default); response headers policy leaves origin `Cache-Control` untouched.
- Default timeouts are fine (see "SSE compatibility" below — we heartbeat every 15s).
- HTTP/2 and HTTP/3 on; TLSv1.2 minimum.

### ALB (private ingress target)

- `ipAddressType: dualstack-without-public-ipv4` — the ALB has IPv6 public-facing and internal IPv4 (for target group routing) but no public IPv4. This is the mode specifically designed to avoid the Feb 2024 public-IPv4 fees.
- Single :443 listener forwarding to one target group (the `server` Fargate service).
- Target group health check: `GET /healthz` (new endpoint — see Service Changes).
- Default 60s idle timeout is fine — 15s SSE heartbeat keeps connections warm.
- Security group: ingress from `0.0.0.0/0` and `::/0` on :443. Could be tightened to CloudFront's managed prefix list later.

### Fargate services

Three services in a single ECS cluster. Shared task execution role (ECR pull, Secrets, Logs) and per-service task roles (scoped to the AWS APIs each actually calls — server + worker need SNS, reconciler doesn't).

| Service | Task size | Desired count | Notes |
|---|---|---|---|
| `server` | 0.5 vCPU / 1 GB | 1 (autoscale later) | Behind ALB. Runs `uvicorn` on :8000. |
| `worker` | 0.25 vCPU / 0.5 GB | 1 | Celery worker. No ingress. |
| `reconciler` | 0.25 vCPU / 0.5 GB | **exactly 1** | Polls Postgres every 1s. Deployment strategy must guarantee no overlap (see Service Changes). |

- All services built from the same repo; image tag selects which entrypoint runs.
- `awsvpc` networking, `assignPublicIp: DISABLED`, IPv6 enabled on the ENI.
- CloudWatch Logs via the `awslogs` log driver; retention 30 days.

### Aurora Serverless v2 (Postgres)

- Engine: Aurora PostgreSQL 16 with PostGIS extension.
- Single writer instance, no read replica for v1.
- ACU range: **min 0, max 2** (2 ACU = ~4 GB RAM).
- Storage: auto-scaling, $0.10/GB-mo.
- Subnet group spans the private subnets configured as **dual-stack** (Aurora does not support IPv6-only subnets).
- Credentials in Secrets Manager; task execution role grants read. Secrets Manager automatic rotation enabled (built-in Lambda rotator for RDS).
- PostGIS enabled by the first migration.
- **Connection pooling**: SQLAlchemy `QueuePool` defaults (`pool_size=5, max_overflow=10`) with `pool_pre_ping=True` added to survive Aurora auto-pause. With 3 Fargate tasks that's up to 45 connections steady-state — well within Aurora's limits at this instance size.
- RDS Proxy **not** deployed (see Out of Scope).

### ElastiCache Redis

- Single-node `cache.t4g.micro`, no cluster, no replica.
- IPv6-only subnet group (ElastiCache supports IPv6-only).
- Used for:
  - Celery broker + result backend
  - SSE pub/sub channels (`game:*:lobby:events`, `game:*:hider-events`, `game:*:seeker-events`)
  - Per-channel sequence counters (`game:*:*:seq`)
- No auth token for v1 (in-VPC only, SG-restricted). AUTH + TLS in a later hardening pass.

### SNS Mobile Push

- Two platform applications:
  - `hideandseek-ios` (APNs) — configured with the existing `.p8` key uploaded to SNS (no longer kept on the app filesystem).
  - `hideandseek-android` (FCM) — configured with the FCM service account JSON.
- Each device token becomes an **SNS platform endpoint ARN**; we store that ARN on `DeviceToken` (see Service Changes).
- SNS delivery-failure events route via an SNS topic → SQS → small worker task that marks `DeviceToken` inactive.
- Free tier: 1M mobile push notifications/month, permanent.

### Route 53 + ACM

- The `marchese.dev` Route 53 **hosted zone is created manually out-of-repo**, not by this CDK app. Rationale: `marchese.dev` is shared across multiple projects, so its zone shouldn't be owned by any single project's IaC. Nameserver migration from Squarespace was a one-time setup tracked separately (see HideAndSeek-vrq).
- CDK **imports** the zone (read-only) via `HostedZone.fromLookup({ domainName: hostedZoneName })`. The zone ID is never hardcoded — `fromLookup` resolves it at synth time and caches the result in gitignored `cdk.context.json`. The zone name enters via the `HOSTED_ZONE_NAME` env var.
- CDK manages only the **records inside that zone** that belong to this project (the CloudFront A/AAAA aliases for `hideandseek.marchese.dev`, and the ACM DNS-validation records).
- ACM public cert for `hideandseek.marchese.dev` in `us-east-1`, DNS-validated (free).
- `marchese.me` stays at Squarespace untouched — reserved for home-lab use.

### VPC & Networking

- Custom VPC (not default) so we can enable IPv6 cleanly and shape subnets.
- IPv4 CIDR: `10.0.0.0/16` (kept mostly unused but required by Aurora subnet group and ALB target routing).
- IPv6 CIDR: auto-assigned `/56` from the Amazon pool; subnets get `/64` each.
- Subnets:
  - 2 × public dualstack (for ALB): `10.0.0.0/24`, `10.0.1.0/24` + IPv6 /64s.
  - 2 × private dualstack (for Aurora + ElastiCache + Fargate ENIs): `10.0.10.0/24`, `10.0.11.0/24` + IPv6 /64s.
- Gateways:
  - Internet Gateway — required for the ALB (even without public IPv4 on the ALB, the subnet needs IGW-routable IPv6).
  - Egress-Only Internet Gateway — for Fargate/task IPv6 outbound. Free.
- No NAT Gateway.
- Security groups:
  - `alb-sg` — ingress :443 from anywhere; egress to `server-sg` :8000.
  - `server-sg`, `worker-sg`, `reconciler-sg` — no public ingress; egress anywhere (IPv6).
  - `db-sg` — ingress :5432 from the three app SGs.
  - `redis-sg` — ingress :6379 from the three app SGs.

---

## Service Changes

Concrete app-side work this architecture forces. Each is scoped tightly enough to be its own beads issue.

### 1. Push: replace `ApnsProvider` + `FcmProvider` with `SnsProvider`

Current: `core/src/hideandseek_core/push.py` has two providers wrapping `aioapns` and `firebase-admin`. Worker dispatches by `TokenProvider` on `DeviceToken`.

Target:

- Single `SnsProvider` that calls `sns:Publish` against a platform endpoint ARN. Wire format is SNS's envelope: `{"default": "<msg>", "APNS_SANDBOX": "<apns-payload>", "GCM": "<fcm-payload>"}`. SNS selects the right variant based on the endpoint's parent platform application.
- `DeviceToken` schema:
  - Add `endpoint_arn: str | None` column.
  - Keep `token` and `provider` for debugging / re-provisioning.
- Registration flow (where the client POSTs a device token today):
  - Call `sns:CreatePlatformEndpoint` with the raw token, store the returned ARN.
  - If the token is already registered to a disabled endpoint, re-enable via `SetEndpointAttributes Enabled=true` instead of duplicating.
- Dead-token handling:
  - Subscribe an SQS queue to SNS's delivery-failure topic.
  - Small worker task (new) consumes the queue; on `EndpointDisabled` event, mark the `DeviceToken` inactive.
  - `send_push` task filters inactive tokens.
- Delete `aioapns` and `firebase-admin` from `core/pyproject.toml`. Delete `PushConfig` and `FcmConfig` (replaced by IAM-based access to SNS + platform application ARNs in env).
- `design/2026-02-14-push-notifications.md` stays as the payload/event-catalog reference; update its header note to point at this doc for provider architecture.

### 2. SSE: CloudFront compatibility

Current: `server/src/hideandseek/routers/events.py` uses `sse-starlette` with `ping=15` on all three streams (lobby, hider, seeker).

Target:

- **No timeout bumps needed anywhere.** The 15s ping emits actual bytes every 15 seconds, which keeps CloudFront's origin read timeout (30s default), ALB idle timeout (60s default), and client-side keep-alive all happily within bounds.
- **Response headers** — verify `sse-starlette` emits `Cache-Control: no-cache, no-store` by default; add explicitly if not. `X-Accel-Buffering: no` for documentary clarity.
- **CloudFront origin request policy** must forward `X-Player-Id` and `X-Player-Secret`. Default cache behaviors strip unknown headers.
- **Gap-detection path is load-bearing** — already implemented (per-channel sequence + client reconnect on gap). The CloudFront hop introduces additional drop risk; existing reconnect logic absorbs it.
- **New endpoint**: `GET /healthz` for ALB target health. Returns `200 OK` with no body, no auth, no DB access.

### 3. Reconciler: singleton-safe deployment

Current: `hideandseek-reconciler` polls Postgres every 1s and enqueues Celery tasks. Single process under Docker Compose today.

Target:

- ECS service with `desiredCount: 1`.
- **Deployment config**:
  - `minimumHealthyPercent: 0`
  - `maximumPercent: 100`
  - During deploys, the old task stops before the new one starts. The worst-case gap is 30–60s; the DB-backed overdue query catches up on the next poll.
- **Why not leader election** — reconciler enqueue uses deterministic Celery task IDs, so duplicate enqueue collapses to a single execution anyway. Adding DynamoDB / Redlock for a problem we won't hit at hobby scale isn't worth it.
- **Monitoring**: CloudWatch alarm on "reconciler running count == 0 for > 2 minutes" → SNS email.

### 4. Database migrations

Current: `alembic upgrade head` run against the local docker-compose Postgres.

Target:

- One-shot ECS task defined in CDK, same container image, command override = `alembic upgrade head`.
- Triggered by a CDK custom resource that runs the task synchronously during stack deploy and fails the deploy if migration fails.
- `CREATE EXTENSION postgis` is the first migration.
- **Never migrate on server startup** — avoids the "N tasks race on the same migration on cold start" footgun.

### 5. Environment-specific configuration

- `ENV=production` — already wired into `hideandseek.logging` (JSON to stderr).
- Task environment needs:
  - `DATABASE_URL` — Secrets Manager (injected as `secrets` in task def).
  - `CELERY_BROKER_URL`, `REDIS_URL` — SSM Parameter Store plain values.
  - `SNS_APNS_APP_ARN`, `SNS_FCM_APP_ARN` — platform application ARNs.
  - `AWS_REGION` — provided automatically.
- Secrets that stop living in app code/filesystem: APNs `.p8`, FCM service-account JSON (both move into SNS).

---

## Infrastructure as Code

AWS CDK, written in **TypeScript**. Rationale:
- Constructs library (`aws-cdk-lib/aws-ecs-patterns`, `aws-cdk-lib/aws-cloudfront-origins`) is most mature in TS.
- Keeps the uv Python workspace unburdened.
- CDK repo lives at `infra/cdk/` as a sibling of existing packages (not a uv workspace member).

### Stack structure

One CDK app, split into logical stacks for independent deploy:

1. **`NetworkStack`** — VPC, subnets, IGW, Egress-Only IGW, SGs.
2. **`DataStack`** — Aurora cluster, ElastiCache node, Secrets Manager entries. Depends on Network.
3. **`PushStack`** — SNS platform applications, SQS delivery-failure queue. Independent.
4. **`AppStack`** — ECR repo, ECS cluster, task definitions, services, ALB, CloudFront, Route 53 records, ACM cert. Depends on all three.

### Image build

- Docker images built locally (or in GitHub Actions later) and pushed to ECR.
- CDK `DockerImageAsset` handles build+push on `cdk deploy` for v1. Slow on cold deploy (~10–15 min from laptop) but zero-cost. CI pipeline is a follow-up.

---

## Cost Analysis

Idle (no games, Fargate at desired-count minimums, Aurora paused):

| Line item | Monthly |
|---|---|
| CloudFront | ~$0 (under 1 TB free tier) |
| ALB (no IPv4) | $16 |
| Fargate (1× server, 1× worker, 1× reconciler) | ~$25 |
| Aurora Serverless v2 (0 ACU idle, ~2 GB storage) | ~$2 |
| ElastiCache `cache.t4g.micro` | $12 |
| SNS Mobile Push | $0 (free tier) |
| Route 53 hosted zone (`marchese.dev`, shared across projects) | $0.50 |
| Secrets Manager (2 secrets) | $1 |
| CloudWatch Logs | ~$2 |
| Egress-Only IGW + IPv6 data transfer | $0 |
| **Total** | **~$59/mo** |

Scaled-down dev (Fargate `desiredCount: 0` on all three services while not testing):

| | Monthly |
|---|---|
| Same minus Fargate | **~$34/mo** |

Active day (a handful of games, Aurora at ~0.5 ACU average for 4 hours):

| Additional | Delta |
|---|---|
| Aurora compute (0.5 ACU × 4h × 30d × $0.12) | +$7 |
| Fargate (no change) | +$0 |
| CloudFront egress (nowhere near 1 TB) | +$0 |
| **Active-day total** | **~$66/mo** |

First 12 months on a fresh AWS account drops ALB and ECR costs to ~$0 (~$43/mo idle floor).

---

## Out of Scope / Open Questions

1. **HA** — single-AZ for ElastiCache, single writer for Aurora. Fine for hobby; revisit for real users. Multi-AZ ElastiCache doubles; Aurora reader adds ~$0.12/ACU-hr per reader.
2. **RDS Proxy** — Not deployed v1. Reasoning: SQLAlchemy's default `QueuePool` + `pool_pre_ping=True` handles Aurora auto-pause cleanly at 3-task scale. Proxy becomes worth the ~$15–22/mo when we horizontally scale the API tier or start seeing connection-count issues on Aurora. Adding it later is a pure `DATABASE_URL` swap — zero app-code impact.
3. **CI/CD** — Images built from laptop via CDK for v1. GitHub Actions → ECR pipeline is a follow-up.
4. **Observability** — CloudWatch Logs only. No metrics dashboard, no tracing. Candidates: CloudWatch Embedded Metric Format from `structlog`, or OTel → X-Ray.
5. **Region choice** — `us-west-2` assumed (low latency for Seattle seed data). Revisit if game targets elsewhere.
6. **WAF** — CloudFront supports AWS WAF. Not enabled v1 (+$5/mo base + per-rule fees). Reconsider if we see abuse.
7. **CloudFront caching for `/games/{id}/info`** — static map geometry is heavy, served once per game join. Edge-cacheable but auth model needs thought; skip for now.
8. **Aurora Data API** — rejected. PostGIS types don't round-trip cleanly through Data API JSON, and `sqlalchemy-aurora-data-api` is not first-class.

---

## Implementation Phases

Rough sequencing — each phase is independently deployable/testable.

1. **Domain migration** *(out of scope for this CDK app — one-time manual setup)* — `marchese.dev` hosted zone created by hand in Route 53, Squarespace nameservers pointed at it, propagation verified with `dig NS marchese.dev`. Tracked separately (HideAndSeek-vrq). CDK only imports the zone via `HostedZone.fromLookup`.
2. **Infra plumbing** — NetworkStack + DataStack + PushStack. No app deployed; verify Aurora + Redis + SNS work by hand from a bastion or from `aws` CLI.
3. **App containerization** — Dockerfile per service (or one image with different entrypoints), push to ECR, smoke-test locally against the cloud data plane via port-forward.
4. **Fargate services** — AppStack minus CloudFront: ALB directly on a public AWS-issued hostname. End-to-end test via `curl` and mobile app.
5. **Push migration** — ship `SnsProvider`, migrate `DeviceToken` schema, backfill `endpoint_arn` for existing tokens (script), delete old providers. App work, can land before or after (4).
6. **CloudFront + domain** — attach CloudFront, point `hideandseek.marchese.dev` at it, test SSE end-to-end through the full path.
7. **Monitoring + rotation** — reconciler-count alarm, Secrets Manager rotation for DB password.
