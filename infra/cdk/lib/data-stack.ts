import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elasticache from 'aws-cdk-lib/aws-elasticache';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { NetworkStack } from './network-stack';

export interface DataStackProps extends cdk.StackProps {
  readonly network: NetworkStack;
}

/**
 * Data plane for HideAndSeek.
 *
 * Ships three things: (1) Aurora Serverless v2 Postgres 16 with PostGIS,
 * (2) ElastiCache Redis on a single cache.t4g.micro node, and (3) a one-shot
 * Fargate task — wrapped in a CloudFormation custom resource — that runs
 * `alembic upgrade head` against the cluster during deploy. AppStack reuses
 * the same Docker image asset for the server, so schema is always at head
 * before app containers come up.
 */
export class DataStack extends cdk.Stack {
  readonly cluster: rds.DatabaseCluster;
  readonly dbSecret: secretsmanager.ISecret;
  readonly redis: elasticache.CfnCacheCluster;
  readonly redisEndpoint: string;
  readonly redisPort: string;
  readonly appImage: ecr_assets.DockerImageAsset;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    const { network } = props;

    // --- Aurora Serverless v2 PostgreSQL 16 (+ PostGIS via migration) -----

    const cluster = new rds.DatabaseCluster(this, 'AuroraCluster', {
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_6,
      }),
      vpc: network.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [network.dbSg],
      writer: rds.ClusterInstance.serverlessV2('Writer'),
      // Scale-to-zero: Aurora auto-pauses when min=0, saving ACU-hours on a
      // hobby-scale deploy. The SQLAlchemy engine uses `pool_pre_ping=True`
      // so pooled connections survive the auto-resume.
      serverlessV2MinCapacity: 0,
      serverlessV2MaxCapacity: 2,
      defaultDatabaseName: 'hideandseek',
      credentials: rds.Credentials.fromGeneratedSecret('hideandseek'),
      storageEncrypted: true,
      backup: { retention: cdk.Duration.days(7) },
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
      deletionProtection: true,
    });
    // TODO(wos.6-followup): cluster.addRotationSingleUser() creates a rotator
    // Lambda SG that tries to add an ingress rule on network.dbSg — which
    // lives in NetworkStack — creating a Network->Data cycle. Add rotation
    // back either by moving dbSg into DataStack or by wiring the ingress rule
    // via a standalone CfnSecurityGroupIngress resource defined in DataStack.

    if (!cluster.secret) {
      throw new Error('DatabaseCluster.secret missing — expected fromGeneratedSecret to populate it');
    }
    this.cluster = cluster;
    this.dbSecret = cluster.secret;

    // --- ElastiCache Redis (cache.t4g.micro, single node) ------------------

    const redisSubnetGroup = new elasticache.CfnSubnetGroup(this, 'RedisSubnetGroup', {
      description: 'HideAndSeek Redis subnet group (private subnets)',
      subnetIds: network.vpc.isolatedSubnets.map((s) => s.subnetId),
    });

    // Plain IPv4 Redis. The NetworkStack's IPv6-only egress posture is
    // about *public internet* egress (no NAT gateway, via egress-only IGW);
    // intra-VPC IPv4 traffic doesn't touch that path and doesn't cost a
    // public IP. Getting IPv6 Redis would require cluster-mode-enabled
    // (sharded) replication groups and a redis-py → redis-cluster client
    // swap across server/worker/reconciler — out of scope for wos.6.
    const redis = new elasticache.CfnCacheCluster(this, 'Redis', {
      engine: 'redis',
      engineVersion: '7.1',
      cacheNodeType: 'cache.t4g.micro',
      numCacheNodes: 1,
      vpcSecurityGroupIds: [network.redisSg.securityGroupId],
      cacheSubnetGroupName: redisSubnetGroup.ref,
    });
    redis.addDependency(redisSubnetGroup);
    this.redis = redis;
    this.redisEndpoint = redis.attrRedisEndpointAddress;
    this.redisPort = redis.attrRedisEndpointPort;

    // --- One-shot migration runner (ECS Fargate + Lambda-backed CR) --------

    const migrationCluster = new ecs.Cluster(this, 'MigrationCluster', {
      vpc: network.vpc,
      containerInsightsV2: ecs.ContainerInsights.DISABLED,
    });

    // Shared server image. AppStack (wos.8) will instantiate the same
    // DockerImageAsset and CDK de-duplicates by content hash, so the
    // Docker build only happens once per deploy.
    // ARM64 / Graviton across the board: matches Apple Silicon dev hosts
    // (no cross-compile, no buildx dependency) and is ~20% cheaper than
    // x86 Fargate. Python + SQLAlchemy + boto3 + Celery all run natively.
    this.appImage = new ecr_assets.DockerImageAsset(this, 'AppImage', {
      directory: path.join(__dirname, '..', '..', '..'),
      file: 'server/Dockerfile',
      platform: ecr_assets.Platform.LINUX_ARM64,
    });

    const migrationTaskDef = new ecs.FargateTaskDefinition(this, 'MigrationTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    // The generated RDS cluster secret is a JSON blob with fields host/port/
    // dbname/username/password. Compose DATABASE_URL at runtime via a shell
    // entrypoint so the psycopg dialect prefix lands on the URL alembic uses.
    migrationTaskDef.addContainer('Migrate', {
      containerName: 'Migrate',
      image: ecs.ContainerImage.fromDockerImageAsset(this.appImage),
      entryPoint: ['/bin/sh', '-c'],
      command: [
        'export DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME" && exec uv run alembic upgrade head',
      ],
      workingDirectory: '/app',
      secrets: {
        DB_HOST: ecs.Secret.fromSecretsManager(this.dbSecret, 'host'),
        DB_PORT: ecs.Secret.fromSecretsManager(this.dbSecret, 'port'),
        DB_NAME: ecs.Secret.fromSecretsManager(this.dbSecret, 'dbname'),
        DB_USER: ecs.Secret.fromSecretsManager(this.dbSecret, 'username'),
        DB_PASSWORD: ecs.Secret.fromSecretsManager(this.dbSecret, 'password'),
      },
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: 'migrate',
        logRetention: logs.RetentionDays.ONE_MONTH,
      }),
    });

    // Secrets + awslogs both require the execution role; by this point
    // addContainer has instantiated it, so both grants are safe.
    this.dbSecret.grantRead(migrationTaskDef.executionRole!);
    this.dbSecret.grantRead(migrationTaskDef.taskRole);

    // Dedicated SG for the migration task with unrestricted egress. The task
    // runs in a *public* subnet with an ephemeral public IPv4 (see Lambda
    // config below) because our private subnets are IPv6-only-egress and ECR
    // only answers on IPv4. `allowAllOutbound: true` covers the three
    // outbound paths it needs: ECR (image pull), CloudWatch Logs (container
    // logs), Secrets Manager (DB creds), and Aurora over the VPC's IPv4 CIDR.
    // No ingress — nothing ever connects *to* a one-shot migration task.
    const migrationSg = new ec2.SecurityGroup(this, 'MigrationSg', {
      vpc: network.vpc,
      description: 'HideAndSeek migration one-shot task: egress-only (IPv4 + IPv6)',
      allowAllOutbound: true,
    });

    // Aurora's dbSg lives in NetworkStack and trusts serverSg/workerSg/
    // reconcilerSg. Grant migrationSg the same :5432 access via a standalone
    // CfnSecurityGroupIngress resource in *this* stack — that's Data→Network
    // (we already depend on network), not the reverse, so no SG cycle.
    new ec2.CfnSecurityGroupIngress(this, 'DbIngressFromMigrationSg', {
      groupId: network.dbSg.securityGroupId,
      sourceSecurityGroupId: migrationSg.securityGroupId,
      ipProtocol: 'tcp',
      fromPort: 5432,
      toPort: 5432,
      description: 'From migration task',
    });

    // Lambda that invokes run_task + waits for exit. The CDK custom resource
    // calls this on CREATE/UPDATE; DELETE is a no-op (migrations are
    // forward-only and the cluster outlives individual stack updates).
    const runMigrationsFn = new lambda.Function(this, 'RunMigrationsFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda', 'run-migrations')),
      timeout: cdk.Duration.minutes(15),
      memorySize: 256,
      environment: {
        CLUSTER_ARN: migrationCluster.clusterArn,
        TASK_DEFINITION_ARN: migrationTaskDef.taskDefinitionArn,
        CONTAINER_NAME: 'Migrate',
        // Public subnets + assignPublicIp=ENABLED give the task a temporary
        // public IPv4 so it can reach ECR/Logs/Secrets without NAT or VPC
        // endpoints. Cost is ~$0.005/hr per IP — rounding error for a
        // 2-minute migration. See README for the tradeoff vs VPC endpoints.
        SUBNET_IDS: network.vpc.publicSubnets.map((s) => s.subnetId).join(','),
        SECURITY_GROUP_ID: migrationSg.securityGroupId,
        ASSIGN_PUBLIC_IP: 'ENABLED',
      },
    });
    runMigrationsFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['ecs:RunTask'],
        resources: [migrationTaskDef.taskDefinitionArn],
        conditions: {
          ArnEquals: { 'ecs:cluster': migrationCluster.clusterArn },
        },
      }),
    );
    runMigrationsFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['ecs:DescribeTasks'],
        resources: ['*'],
        conditions: {
          ArnEquals: { 'ecs:cluster': migrationCluster.clusterArn },
        },
      }),
    );
    runMigrationsFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['iam:PassRole'],
        resources: [
          migrationTaskDef.taskRole.roleArn,
          migrationTaskDef.executionRole!.roleArn,
        ],
      }),
    );
    runMigrationsFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['logs:GetLogEvents', 'logs:DescribeLogStreams'],
        resources: ['*'],
      }),
    );

    const provider = new cr.Provider(this, 'RunMigrationsProvider', {
      onEventHandler: runMigrationsFn,
      logRetention: logs.RetentionDays.ONE_MONTH,
    });

    const runMigrations = new cdk.CustomResource(this, 'RunMigrations', {
      serviceToken: provider.serviceToken,
      properties: {
        // Re-run migrations whenever the image digest changes (i.e. when
        // alembic/ or models/ source changes rebuild the server image).
        ImageDigest: this.appImage.imageTag,
      },
    });
    runMigrations.node.addDependency(cluster);
    runMigrations.node.addDependency(redis);

    // --- Outputs ---------------------------------------------------------

    new cdk.CfnOutput(this, 'ClusterEndpoint', {
      value: cluster.clusterEndpoint.hostname,
      description: 'Aurora Serverless v2 writer endpoint hostname',
    });
    new cdk.CfnOutput(this, 'DbSecretArn', {
      value: this.dbSecret.secretArn,
      description: 'Secrets Manager ARN for the Aurora master credential',
    });
    new cdk.CfnOutput(this, 'RedisEndpoint', {
      value: `${this.redisEndpoint}:${this.redisPort}`,
      description: 'ElastiCache Redis primary endpoint (host:port)',
    });
  }
}
