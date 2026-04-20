import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

/**
 * VPC + subnets + gateways + security groups for HideAndSeek.
 *
 * Layout:
 *   VPC 10.0.0.0/16 + Amazon-provided /56 IPv6
 *   - 2 public dual-stack subnets (ALB)           10.0.0.0/24, 10.0.1.0/24
 *   - 2 private dual-stack subnets (Fargate/DB)   10.0.10.0/24, 10.0.11.0/24
 *   - Internet Gateway for public subnets
 *   - Egress-Only Internet Gateway for private IPv6 egress (no NAT)
 *
 * Private subnets are dual-stack because Aurora and ElastiCache need IPv4
 * in-VPC connectivity. Outbound internet traffic from private subnets goes
 * over IPv6 via the Egress-Only IGW — there is no NAT gateway, so there is
 * no public IPv4 egress by design.
 */
export class NetworkStack extends cdk.Stack {
  readonly vpc: ec2.IVpc;
  readonly albSg: ec2.SecurityGroup;
  readonly serverSg: ec2.SecurityGroup;
  readonly workerSg: ec2.SecurityGroup;
  readonly reconcilerSg: ec2.SecurityGroup;
  readonly dbSg: ec2.SecurityGroup;
  readonly redisSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.0.0.0/16'),
      maxAzs: 2,
      natGateways: 0,
      createInternetGateway: true,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
          mapPublicIpOnLaunch: false,
        },
        {
          name: 'private',
          // ISOLATED = no NAT route. We'll add our own IPv6 default route
          // to the Egress-Only IGW below, giving IPv6-only egress.
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });
    this.vpc = vpc;

    // Attach an Amazon-provided /56 IPv6 CIDR to the VPC. The L2 Vpc
    // construct doesn't expose this yet, so we drop to CfnVPCCidrBlock.
    const ipv6Cidr = new ec2.CfnVPCCidrBlock(this, 'Ipv6Cidr', {
      vpcId: vpc.vpcId,
      amazonProvidedIpv6CidrBlock: true,
    });

    // Slice the /56 into /64s, one per subnet. Fn.cidr gives us
    // deterministic subnet CIDRs derived from the VPC's IPv6 block.
    const ipv6Blocks = cdk.Fn.cidr(
      cdk.Fn.select(0, vpc.vpcIpv6CidrBlocks),
      256,
      (128 - 64).toString(),
    );

    const publicSubnets = vpc.publicSubnets;
    const privateSubnets = vpc.isolatedSubnets;
    const allSubnets = [...publicSubnets, ...privateSubnets];

    allSubnets.forEach((subnet, index) => {
      const cfnSubnet = subnet.node.defaultChild as ec2.CfnSubnet;
      cfnSubnet.ipv6CidrBlock = cdk.Fn.select(index, ipv6Blocks);
      cfnSubnet.assignIpv6AddressOnCreation = true;
      cfnSubnet.addDependency(ipv6Cidr);
    });

    // Route IPv6 traffic from public subnets to the Internet Gateway.
    // Public IPv4 default route is already added by the L2 construct.
    publicSubnets.forEach((subnet, index) => {
      new ec2.CfnRoute(this, `PublicIpv6Route${index}`, {
        routeTableId: subnet.routeTable.routeTableId,
        destinationIpv6CidrBlock: '::/0',
        gatewayId: vpc.internetGatewayId,
      });
    });

    // Egress-Only IGW for IPv6 outbound from private subnets.
    const eigw = new ec2.CfnEgressOnlyInternetGateway(this, 'EgressOnlyIgw', {
      vpcId: vpc.vpcId,
    });

    privateSubnets.forEach((subnet, index) => {
      new ec2.CfnRoute(this, `PrivateIpv6Route${index}`, {
        routeTableId: subnet.routeTable.routeTableId,
        destinationIpv6CidrBlock: '::/0',
        egressOnlyInternetGatewayId: eigw.ref,
      });
    });

    // --- Security groups ---

    this.albSg = new ec2.SecurityGroup(this, 'AlbSg', {
      vpc,
      description: 'ALB: public :443 ingress (IPv4 + IPv6)',
      allowAllOutbound: false,
      allowAllIpv6Outbound: false,
    });
    this.albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS IPv4');
    this.albSg.addIngressRule(ec2.Peer.anyIpv6(), ec2.Port.tcp(443), 'HTTPS IPv6');

    this.serverSg = new ec2.SecurityGroup(this, 'ServerSg', {
      vpc,
      description: 'Fargate server: ingress :8000 from ALB only',
      allowAllOutbound: false,
      allowAllIpv6Outbound: true,
    });
    this.serverSg.addIngressRule(this.albSg, ec2.Port.tcp(8000), 'From ALB');

    // Now that serverSg exists, let the ALB egress to it on :8000.
    this.albSg.addEgressRule(this.serverSg, ec2.Port.tcp(8000), 'To server');

    this.workerSg = new ec2.SecurityGroup(this, 'WorkerSg', {
      vpc,
      description: 'Fargate worker: no ingress; IPv6 egress',
      allowAllOutbound: false,
      allowAllIpv6Outbound: true,
    });

    this.reconcilerSg = new ec2.SecurityGroup(this, 'ReconcilerSg', {
      vpc,
      description: 'Fargate reconciler: no ingress; IPv6 egress',
      allowAllOutbound: false,
      allowAllIpv6Outbound: true,
    });

    this.dbSg = new ec2.SecurityGroup(this, 'DbSg', {
      vpc,
      description: 'Aurora: ingress :5432 from app SGs',
      allowAllOutbound: false,
      allowAllIpv6Outbound: false,
    });
    this.dbSg.addIngressRule(this.serverSg, ec2.Port.tcp(5432), 'From server');
    this.dbSg.addIngressRule(this.workerSg, ec2.Port.tcp(5432), 'From worker');
    this.dbSg.addIngressRule(this.reconcilerSg, ec2.Port.tcp(5432), 'From reconciler');

    this.redisSg = new ec2.SecurityGroup(this, 'RedisSg', {
      vpc,
      description: 'ElastiCache Redis: ingress :6379 from app SGs',
      allowAllOutbound: false,
      allowAllIpv6Outbound: false,
    });
    this.redisSg.addIngressRule(this.serverSg, ec2.Port.tcp(6379), 'From server');
    this.redisSg.addIngressRule(this.workerSg, ec2.Port.tcp(6379), 'From worker');
    this.redisSg.addIngressRule(this.reconcilerSg, ec2.Port.tcp(6379), 'From reconciler');

    // App SGs default to IPv6-only egress (allowAllIpv6Outbound), but
    // Aurora is IPv4-only (service limitation) and our Redis is IPv4 by
    // choice (cluster-mode-disabled CfnCacheCluster; see data-stack.ts).
    // Intra-VPC traffic only — no public IP cost, no EIGW involvement.
    for (const sg of [this.serverSg, this.workerSg, this.reconcilerSg]) {
      sg.addEgressRule(this.dbSg, ec2.Port.tcp(5432), 'To Aurora');
      sg.addEgressRule(this.redisSg, ec2.Port.tcp(6379), 'To Redis');
    }

    // --- Outputs ---

    new cdk.CfnOutput(this, 'VpcId', { value: vpc.vpcId });
    new cdk.CfnOutput(this, 'VpcIpv6Cidr', {
      value: cdk.Fn.select(0, vpc.vpcIpv6CidrBlocks),
    });
  }
}
