# HideAndSeek CDK

AWS CDK app (TypeScript) for deploying the HideAndSeek backend. See `CLAUDE.md` for conventions — in particular, **no personal info is committed here**; account and region come from your active AWS credentials.

## Prerequisites

- Node 22+ and npm
- AWS credentials with sufficient permissions for the resources in the stacks (VPC, IAM, RDS, ElastiCache, ECS, SNS, CloudFront, Route 53). Root is fine for personal accounts; an IAM role is preferable for shared ones.

## Setup

```bash
cd infra/cdk
npm install
```

## One-time per account + region

CDK needs a bootstrap stack (staging bucket, deploy role) in any account/region it deploys to. Run once per new account/region combination:

```bash
npx cdk bootstrap
```

The CLI infers account and region from your active AWS credentials — no explicit ARN needed. Override the region via `AWS_REGION` or `CDK_DEFAULT_REGION` if needed (default is `us-west-2` when nothing is set).

## Daily commands

```bash
# Typecheck only
npx tsc --noEmit

# Synthesize CloudFormation to cdk.out/
npx cdk synth

# Show what a deploy would change
npx cdk diff HideAndSeek-Network

# Deploy a single stack
npx cdk deploy HideAndSeek-Network
npx cdk deploy HideAndSeek-Data
npx cdk deploy HideAndSeek-App

# Deploy everything
npx cdk deploy --all

# Tear down
npx cdk destroy HideAndSeek-App
npx cdk destroy HideAndSeek-Network
```

**`HideAndSeek-Data` first-deploy note**: the first `cdk deploy HideAndSeek-Data` is slower than the others (usually 3–5 min) because CDK builds the server Docker image, pushes it to ECR, and then the migration custom resource runs one Fargate task to `alembic upgrade head`. Subsequent deploys skip the image build + migration run unless the image digest changes.

**`HideAndSeek-App` smoke test**: after deploying AppStack, exercise the AWS-issued ALB hostname over **HTTP :80** (no TLS until `wos.9` adds CloudFront + `hideandseek.marchese.dev`):

```bash
ALB_DNS=$(aws cloudformation describe-stacks --stack-name HideAndSeek-App \
  --query 'Stacks[0].Outputs[?OutputKey==`AlbDnsName`].OutputValue' --output text)
BASE="http://$ALB_DNS"

# 1. ALB → server (health endpoint, no auth)
curl -fsS "$BASE/healthz"

# 2. server → Aurora (requires seeded map data; skip if Aurora is empty)
curl -fsS "$BASE/maps" | jq '.[0].id'

# 3. server → Redis (lobby SSE channel publishes initial game_state)
MAP_ID=$(curl -fsS "$BASE/maps" | jq -r '.[0].id')
RESP=$(curl -fsS -X POST "$BASE/games" -H 'Content-Type: application/json' \
  -d "{\"map_id\":\"$MAP_ID\",\"name\":\"smoke\",\"size\":\"small\"}")
GAME_ID=$(echo "$RESP" | jq -r '.game.id')
PLAYER_ID=$(echo "$RESP" | jq -r '.player_id')
SECRET=$(echo "$RESP" | jq -r '.player_secret')
timeout 3 curl -fsSN "$BASE/games/$GAME_ID/lobby/events" \
  -H "X-Player-Id: $PLAYER_ID" -H "X-Player-Secret: $SECRET" | head -5
```

Follow with `aws logs tail /aws/ecs/.../<service> --since 5m` on each service's log group to confirm startup, and `aws elbv2 describe-target-health --target-group-arn <arn>` to confirm the server target is `healthy`.

## Stacks

| Stack | Ships in | Owns |
|---|---|---|
| `HideAndSeek-Network` | wos.5 | VPC, subnets, gateways, security groups |
| `HideAndSeek-Data` | wos.6 | Aurora Serverless v2, ElastiCache, Secrets |
| `HideAndSeek-App` | wos.8 | ECS cluster + server/worker/reconciler services + ALB (HTTP :80 until wos.9 adds CloudFront + custom domain + :443) |

SNS Mobile Push platform applications (APNs + FCM) are **not** in a CDK stack — `AWS::SNS::PlatformApplication` isn't a native CloudFormation resource type, and the apps are registered once per account/region via `aws sns create-platform-application`. See "Create SNS platform applications" below. The Topic + SQS queue for `EventDeliveryFailure` events is deferred to a later stack (the consumer that sweeps dead device tokens lives there too).

## Create SNS platform applications

One-time setup, per AWS account + region. Run once after credentials are uploaded to Secrets Manager and `infra/cdk/.env` is populated (see `.env.example` for the required variables).

```bash
# Load the env vars referenced below.
set -a; source infra/cdk/.env; set +a

# APNs (iOS). Name + Platform are fixed conventions — AppStack (wos.8)
# constructs the platform-application ARN from them, so match these exactly.
# SNS infers token-based auth from the presence of TeamID + BundleID (no
# explicit "auth method" attribute exists on CreatePlatformApplication).
aws sns create-platform-application \
  --name hideandseek-ios \
  --platform APNS \
  --attributes "$(cat <<EOF
{
  "PlatformCredential": $(aws secretsmanager get-secret-value \
      --secret-id "$APNS_CREDENTIAL_SECRET_ARN" \
      --query SecretString --output text | jq -Rs .),
  "PlatformPrincipal": "$APNS_SIGNING_KEY_ID",
  "ApplePlatformTeamID": "$APNS_TEAM_ID",
  "ApplePlatformBundleID": "$APNS_BUNDLE_ID"
}
EOF
)"

# FCM (Android). A service-account JSON as PlatformCredential tells SNS to
# use FCM HTTP v1 — verify after registration with `get-platform-application-
# attributes` (AuthenticationMethod should read "Token").
aws sns create-platform-application \
  --name hideandseek-android \
  --platform GCM \
  --attributes "$(cat <<EOF
{
  "PlatformCredential": $(aws secretsmanager get-secret-value \
      --secret-id "$FCM_CREDENTIAL_SECRET_ARN" \
      --query SecretString --output text | jq -Rs .)
}
EOF
)"
```

The resulting ARNs have the form `arn:aws:sns:<region>:<account>:app/APNS/hideandseek-ios` and `arn:aws:sns:<region>:<account>:app/GCM/hideandseek-android`. AppStack injects them as `SNS_APNS_APP_ARN` / `SNS_FCM_APP_ARN` env vars on the server + worker containers.

**Credential rotation:** re-run `aws secretsmanager put-secret-value` for the relevant secret, then `aws sns set-platform-application-attributes --platform-application-arn <arn> --attributes PlatformCredential=...` to push the new key to SNS (SNS does not auto-rotate).

**Delivery-failure wiring:** deferred — when the delivery-failure consumer stack lands, that deploy will create an SNS topic and run `aws sns set-platform-application-attributes` to set `EventDeliveryFailure` on both platform apps.

## Verifying a deploy

Every resource is tagged `Project=hideandseek ManagedBy=cdk`. Use those tags in smoke checks:

```bash
aws ec2 describe-vpcs \
  --filters "Name=tag:Project,Values=hideandseek" \
  --query 'Vpcs[].{VpcId:VpcId,CidrBlock:CidrBlock,Ipv6:Ipv6CidrBlockAssociationSet[0].Ipv6CidrBlock}'

aws ec2 describe-subnets \
  --filters "Name=tag:Project,Values=hideandseek" \
  --query 'Subnets[].{Name:Tags[?Key==`Name`]|[0].Value,AZ:AvailabilityZone,V4:CidrBlock,V6:Ipv6CidrBlockAssociationSet[0].Ipv6CidrBlock}'

aws ec2 describe-security-groups \
  --filters "Name=tag:Project,Values=hideandseek" \
  --query 'SecurityGroups[].{Name:GroupName,Id:GroupId}'
```
