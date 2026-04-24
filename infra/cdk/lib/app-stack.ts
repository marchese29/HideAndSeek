import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { DataStack } from './data-stack';
import { NetworkStack } from './network-stack';

export interface AppStackProps extends cdk.StackProps {
  readonly network: NetworkStack;
  readonly data: DataStack;
}

/**
 * Application plane for HideAndSeek.
 *
 * Ships an ECS cluster with three Fargate services (server, worker,
 * reconciler) all running the DataStack-built image with different
 * entrypoints, plus an ALB that fronts the server on the AWS-issued
 * hostname.
 *
 * ALB listens on HTTP :80 (not :443) because the AWS-issued
 * `*.elb.amazonaws.com` hostname can't hold an ACM cert. CdnStack adds
 * CloudFront :443 out front with the custom-domain cert; CloudFront
 * reaches the ALB over HTTP and the :80 SG ingress here is restricted
 * to CloudFront's managed origin-facing prefix list (IPv4) plus `::/0`
 * on IPv6 (no AWS-managed IPv6 prefix list exists for CloudFront
 * origins; see inline notes on the ingress rules).
 */
export class AppStack extends cdk.Stack {
  readonly cluster: ecs.Cluster;
  readonly alb: elbv2.ApplicationLoadBalancer;
  readonly albDnsName: string;
  readonly serverService: ecs.FargateService;
  readonly workerService: ecs.FargateService;
  readonly reconcilerService: ecs.FargateService;

  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const { network, data } = props;
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    // --- ECS cluster ------------------------------------------------------

    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc: network.vpc,
      containerInsightsV2: ecs.ContainerInsights.DISABLED,
    });
    this.cluster = cluster;

    // --- Shared env vars --------------------------------------------------

    // SNS platform-application ARNs are deterministic given the fixed
    // names registered out-of-band (see infra/cdk/README.md "Create SNS
    // platform applications"). Constructing them here — rather than
    // importing — keeps AppStack standalone and avoids coupling to a
    // live AWS lookup at synth time.
    const apnsAppArn = `arn:aws:sns:${region}:${account}:app/APNS/hideandseek-ios`;
    const fcmAppArn = `arn:aws:sns:${region}:${account}:app/GCM/hideandseek-android`;
    const apnsEndpointArnPattern = `arn:aws:sns:${region}:${account}:endpoint/APNS/hideandseek-ios/*`;
    const fcmEndpointArnPattern = `arn:aws:sns:${region}:${account}:endpoint/GCM/hideandseek-android/*`;

    // ElastiCache has no auth in v1 — plain `redis://host:port/db`. The
    // same URL drives both the Celery broker and the SSE pub/sub client;
    // core/redis_client.py treats them as interchangeable.
    const redisUrl = `redis://${data.redisEndpoint}:${data.redisPort}/0`;

    // Common container secrets — Secrets Manager-backed fields from the
    // generated RDS secret. DATABASE_URL is assembled from these in the
    // container entrypoint (same idiom as DataStack's migration task).
    const dbSecrets: Record<string, ecs.Secret> = {
      DB_HOST: ecs.Secret.fromSecretsManager(data.dbSecret, 'host'),
      DB_PORT: ecs.Secret.fromSecretsManager(data.dbSecret, 'port'),
      DB_NAME: ecs.Secret.fromSecretsManager(data.dbSecret, 'dbname'),
      DB_USER: ecs.Secret.fromSecretsManager(data.dbSecret, 'username'),
      DB_PASSWORD: ecs.Secret.fromSecretsManager(data.dbSecret, 'password'),
    };

    const appEnv: Record<string, string> = {
      ENV: 'production',
      CELERY_BROKER_URL: redisUrl,
      REDIS_URL: redisUrl,
      AWS_REGION: region,
      SNS_APNS_APP_ARN: apnsAppArn,
      SNS_FCM_APP_ARN: fcmAppArn,
      S3_BUCKET_NAME: data.photoBucket.bucketName,
    };

    // `uv run` inside the DataStack image lives at /app; each command
    // exports DATABASE_URL from the secret pieces before handing off.
    const buildCommand = (invocation: string): string[] => [
      'export DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME" ' +
        `&& exec ${invocation}`,
    ];

    // --- Per-service task roles ------------------------------------------

    // server task role: registers device tokens (CreatePlatformEndpoint +
    // SetEndpointAttributes for duplicate re-enable), plus Publish for
    // any inline send path. Resources scoped to the two platform apps
    // and their endpoint children only.
    const serverTaskRole = new iam.Role(this, 'ServerTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'HideAndSeek server task role: SNS register + publish',
    });
    serverTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['sns:CreatePlatformEndpoint', 'sns:SetEndpointAttributes', 'sns:GetEndpointAttributes'],
        resources: [apnsAppArn, fcmAppArn],
      }),
    );
    serverTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['sns:Publish'],
        resources: [apnsEndpointArnPattern, fcmEndpointArnPattern],
      }),
    );
    data.photoBucket.grantReadWrite(serverTaskRole);

    // worker task role: Publish-only on endpoints. Worker doesn't
    // register tokens — the server does that inline on device-token POST.
    const workerTaskRole = new iam.Role(this, 'WorkerTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'HideAndSeek worker task role: SNS publish + photo bucket read/write',
    });
    workerTaskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['sns:Publish'],
        resources: [apnsEndpointArnPattern, fcmEndpointArnPattern],
      }),
    );
    data.photoBucket.grantReadWrite(workerTaskRole);

    // reconciler task role: DB + Redis; plus photo-bucket read/write for
    // eventual sweep/cleanup tasks (HideAndSeek-81h) so the service can
    // land without an IAM round-trip later.
    const reconcilerTaskRole = new iam.Role(this, 'ReconcilerTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'HideAndSeek reconciler task role: DB read + Redis enqueue + photo bucket',
    });
    data.photoBucket.grantReadWrite(reconcilerTaskRole);

    // --- Task definitions + containers -----------------------------------

    const serverTaskDef = new ecs.FargateTaskDefinition(this, 'ServerTaskDef', {
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
      taskRole: serverTaskRole,
    });
    const serverLogGroup = new logs.LogGroup(this, 'ServerLogGroup', {
      logGroupName: '/hideandseek/server',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    serverTaskDef.addContainer('Server', {
      containerName: 'Server',
      image: ecs.ContainerImage.fromDockerImageAsset(data.appImage),
      entryPoint: ['/bin/sh', '-c'],
      command: buildCommand('uv run uvicorn hideandseek.main:app --host 0.0.0.0 --port 8000'),
      workingDirectory: '/app',
      portMappings: [{ containerPort: 8000, protocol: ecs.Protocol.TCP }],
      environment: appEnv,
      secrets: dbSecrets,
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: 'server',
        logGroup: serverLogGroup,
      }),
    });

    const workerTaskDef = new ecs.FargateTaskDefinition(this, 'WorkerTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
      taskRole: workerTaskRole,
    });
    const workerLogGroup = new logs.LogGroup(this, 'WorkerLogGroup', {
      logGroupName: '/hideandseek/worker',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    workerTaskDef.addContainer('Worker', {
      containerName: 'Worker',
      image: ecs.ContainerImage.fromDockerImageAsset(data.appImage),
      entryPoint: ['/bin/sh', '-c'],
      command: buildCommand('uv run celery -A hideandseek_worker.celery_app worker'),
      workingDirectory: '/app',
      environment: appEnv,
      secrets: dbSecrets,
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: 'worker',
        logGroup: workerLogGroup,
      }),
    });

    const reconcilerTaskDef = new ecs.FargateTaskDefinition(this, 'ReconcilerTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
      taskRole: reconcilerTaskRole,
    });
    const reconcilerLogGroup = new logs.LogGroup(this, 'ReconcilerLogGroup', {
      logGroupName: '/hideandseek/reconciler',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    // Reconciler doesn't call SNS and doesn't use endpoint ARNs — strip
    // the SNS env vars so a misconfigured code path can't publish from
    // this service. S3_BUCKET_NAME stays: cleanup tasks (HideAndSeek-81h)
    // will need it, and the task role already carries the matching grant.
    const reconcilerEnv: Record<string, string> = {
      ENV: appEnv.ENV,
      CELERY_BROKER_URL: appEnv.CELERY_BROKER_URL,
      REDIS_URL: appEnv.REDIS_URL,
      AWS_REGION: appEnv.AWS_REGION,
      S3_BUCKET_NAME: appEnv.S3_BUCKET_NAME,
    };
    reconcilerTaskDef.addContainer('Reconciler', {
      containerName: 'Reconciler',
      image: ecs.ContainerImage.fromDockerImageAsset(data.appImage),
      entryPoint: ['/bin/sh', '-c'],
      command: buildCommand('uv run python -m hideandseek_reconciler'),
      workingDirectory: '/app',
      environment: reconcilerEnv,
      secrets: dbSecrets,
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: 'reconciler',
        logGroup: reconcilerLogGroup,
      }),
    });

    // --- Fargate services -------------------------------------------------

    // All three services run in the public (dual-stack) subnets with
    // `assignPublicIp: true`. The original plan was isolated subnets with
    // IPv6-only egress via EIGW, but Fargate's control-plane pulls (ECR,
    // Secrets Manager, Logs) hit AWS's default endpoints which resolve
    // to IPv4 only — with no IPv4 egress the task can't start. The cheap
    // options to fix that were (A) 4 interface endpoints at ~$28/mo,
    // (B) a NAT gateway at ~$32/mo, or (C) public subnets with public
    // IPv4 at ~$11/mo (3 × $3.60 IPv4-assignment fee). We took C.
    //
    // Security posture is preserved by the SGs: serverSg ingress is ALB-
    // only on :8000; workerSg + reconcilerSg have no ingress rules at
    // all. A port scan on any task's public IPv4 lands on a closed port.
    this.serverService = new ecs.FargateService(this, 'ServerService', {
      cluster,
      taskDefinition: serverTaskDef,
      desiredCount: 1,
      assignPublicIp: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [network.serverSg],
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      enableExecuteCommand: false,
      // Circuit breaker rolls back a bad deploy automatically, which
      // lets `cdk deploy` fail fast rather than hanging on a task that
      // crashloops.
      circuitBreaker: { rollback: true },
    });

    this.workerService = new ecs.FargateService(this, 'WorkerService', {
      cluster,
      taskDefinition: workerTaskDef,
      desiredCount: 1,
      assignPublicIp: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [network.workerSg],
      minHealthyPercent: 50,
      maxHealthyPercent: 200,
      enableExecuteCommand: false,
      circuitBreaker: { rollback: true },
    });

    // Reconciler must be a singleton — two concurrent reconcilers would
    // double-enqueue timer tasks. min=0/max=100% means ECS stops the old
    // task before starting the new one; the ~30-60s gap is absorbed by
    // the overdue query's `deadline <= now()` filter on the next tick.
    // Graceful shutdown validated by wos.2.
    this.reconcilerService = new ecs.FargateService(this, 'ReconcilerService', {
      cluster,
      taskDefinition: reconcilerTaskDef,
      desiredCount: 1,
      assignPublicIp: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [network.reconcilerSg],
      minHealthyPercent: 0,
      maxHealthyPercent: 100,
      enableExecuteCommand: false,
      circuitBreaker: { rollback: true },
    });

    // --- ALB + listener + target group -----------------------------------

    // The ALB lives in the public dual-stack subnets but emits no public
    // IPv4 address (saves ~$7/mo per AWS's Feb-2024 IPv4 pricing). IPv4
    // clients reach it via CloudFront in wos.9; for this phase, IPv6-only
    // clients hit the AWS-issued hostname directly.
    this.alb = new elbv2.ApplicationLoadBalancer(this, 'Alb', {
      vpc: network.vpc,
      internetFacing: true,
      securityGroup: network.albSg,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      ipAddressType: elbv2.IpAddressType.DUAL_STACK_WITHOUT_PUBLIC_IPV4,
    });
    this.albDnsName = this.alb.loadBalancerDnsName;

    // CloudFront → ALB runs over HTTP. AWS publishes a managed prefix
    // list (`com.amazonaws.global.cloudfront.origin-facing`) with every
    // IPv4 range CloudFront uses to reach origins; referencing it by
    // name here keeps the ALB SG locked down without hardcoding CIDRs
    // that AWS rotates periodically.
    const cloudfrontOriginPrefixList = ec2.PrefixList.fromLookup(this, 'CloudfrontOriginPrefixList', {
      prefixListName: 'com.amazonaws.global.cloudfront.origin-facing',
      // AWS-managed prefix lists are owned by `AWS` (literal); narrowing
      // the filter avoids ever resolving to a customer-managed list with
      // a colliding name in this account.
      ownerId: 'AWS',
    });

    // Defined as standalone CfnSecurityGroupIngress resources in *this*
    // stack (rather than `network.albSg.addIngressRule(...)`) so the
    // rules live in AppStack's template — a future edge/protocol change
    // doesn't ripple into NetworkStack. Same pattern DataStack uses for
    // the migration-task DB ingress.
    new ec2.CfnSecurityGroupIngress(this, 'AlbHttpIngressV4', {
      groupId: network.albSg.securityGroupId,
      ipProtocol: 'tcp',
      fromPort: 80,
      toPort: 80,
      sourcePrefixListId: cloudfrontOriginPrefixList.prefixListId,
      description: 'CloudFront origin: HTTP IPv4',
    });
    // No AWS-managed IPv6 prefix list exists for CloudFront origin-
    // facing addresses. Since the ALB is DUAL_STACK_WITHOUT_PUBLIC_IPV4
    // and CloudFront will connect over IPv6, we accept open ::/0 on :80
    // as the trade-off for not paying the IPv4 assignment fee. The ALB
    // serves the same payload CloudFront does; defense is at the edge.
    new ec2.CfnSecurityGroupIngress(this, 'AlbHttpIngressV6', {
      groupId: network.albSg.securityGroupId,
      ipProtocol: 'tcp',
      fromPort: 80,
      toPort: 80,
      cidrIpv6: '::/0',
      description: 'CloudFront origin: HTTP IPv6 (no managed PL for IPv6)',
    });

    // App SGs in NetworkStack only egress to Aurora:5432 + Redis:6379 on
    // IPv4 (and ::/0 on IPv6). That was fine for the original "IPv6-only
    // via EIGW" design, but option C runs tasks in public subnets where
    // Fargate's control-plane pulls (ECR, Secrets Manager, Logs) hit
    // IPv4-only AWS endpoints. Without :443 outbound on IPv4, the agent
    // can't pull the image or hydrate the DB secret, and the task hangs
    // in PENDING until CloudFormation times out.
    for (const [id, sg] of [
      ['ServerHttpsEgress', network.serverSg],
      ['WorkerHttpsEgress', network.workerSg],
      ['ReconcilerHttpsEgress', network.reconcilerSg],
    ] as const) {
      new ec2.CfnSecurityGroupEgress(this, id, {
        groupId: sg.securityGroupId,
        ipProtocol: 'tcp',
        fromPort: 443,
        toPort: 443,
        cidrIp: '0.0.0.0/0',
        description: 'Fargate agent: ECR / Secrets Manager / Logs / SNS',
      });
    }

    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'ServerTg', {
      vpc: network.vpc,
      protocol: elbv2.ApplicationProtocol.HTTP,
      port: 8000,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        path: '/healthz',
        protocol: elbv2.Protocol.HTTP,
        port: '8000',
        healthyHttpCodes: '200',
        interval: cdk.Duration.seconds(15),
        timeout: cdk.Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });
    this.serverService.attachToApplicationTargetGroup(targetGroup);

    this.alb.addListener('HttpListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

    // --- Outputs ---------------------------------------------------------

    new cdk.CfnOutput(this, 'AlbDnsName', {
      value: this.alb.loadBalancerDnsName,
      description: 'ALB AWS-issued hostname (CloudFront origin; direct HTTP access is open only to the CloudFront prefix list)',
    });
    new cdk.CfnOutput(this, 'ClusterArn', { value: cluster.clusterArn });
    new cdk.CfnOutput(this, 'ServerServiceName', { value: this.serverService.serviceName });
    new cdk.CfnOutput(this, 'WorkerServiceName', { value: this.workerService.serviceName });
    new cdk.CfnOutput(this, 'ReconcilerServiceName', { value: this.reconcilerService.serviceName });
  }
}
