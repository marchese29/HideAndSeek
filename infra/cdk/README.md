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

# Deploy everything (as more stacks land)
npx cdk deploy --all

# Tear down
npx cdk destroy HideAndSeek-Network
```

**`HideAndSeek-Data` first-deploy note**: the first `cdk deploy HideAndSeek-Data` is slower than the others (usually 3–5 min) because CDK builds the server Docker image, pushes it to ECR, and then the migration custom resource runs one Fargate task to `alembic upgrade head`. Subsequent deploys skip the image build + migration run unless the image digest changes.

## Stacks

| Stack | Ships in | Owns |
|---|---|---|
| `HideAndSeek-Network` | wos.5 (this) | VPC, subnets, gateways, security groups |
| `HideAndSeek-Data` | wos.6 | Aurora Serverless v2, ElastiCache, Secrets |
| `HideAndSeek-Push` | wos.7 | SNS platform apps, SQS delivery-failure queue |
| `HideAndSeek-App` | wos.8 / wos.9 | ECR, ECS cluster + services, ALB, CloudFront, Route 53 records |

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
