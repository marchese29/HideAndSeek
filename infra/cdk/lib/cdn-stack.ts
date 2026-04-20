import * as cdk from 'aws-cdk-lib';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import { Construct } from 'constructs';

export interface CdnStackProps extends cdk.StackProps {
  /**
   * AWS-issued DNS name of the origin ALB (e.g. the dual-stack hostname from
   * AppStack). Cross-region reference handles the import.
   */
  readonly albDnsName: string;

  /** Fully-qualified domain the app serves on (e.g. `app.example.dev`). */
  readonly domainName: string;

  /**
   * Apex zone that `domainName` lives in (e.g. `example.dev`). Must already
   * exist as an authoritative Route 53 hosted zone in this AWS account.
   */
  readonly hostedZoneName: string;
}

/**
 * Public edge + TLS termination + DNS for HideAndSeek.
 *
 * Deploys to us-east-1 regardless of the primary region: ACM certs for
 * CloudFront must live in us-east-1, and Route 53 is global so the alias
 * records can live in the same stack. This sidesteps crossRegionReferences
 * for the resources inside this stack; the only cross-region hop is the
 * `albDnsName` import from AppStack.
 *
 * CloudFront → ALB runs over HTTP :80. Confining the ALB SG to CloudFront's
 * managed origin-facing prefix list (IPv4) is done in AppStack; the IPv6
 * equivalent stays `::/0` because AWS doesn't publish a CloudFront-origin
 * IPv6 prefix list and the ALB is IPv6-only on the public side.
 */
export class CdnStack extends cdk.Stack {
  readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: CdnStackProps) {
    super(scope, id, props);

    const { albDnsName, domainName, hostedZoneName } = props;

    const zone = route53.HostedZone.fromLookup(this, 'Zone', {
      domainName: hostedZoneName,
    });

    const certificate = new acm.Certificate(this, 'Certificate', {
      domainName,
      validation: acm.CertificateValidation.fromDns(zone),
    });

    // CloudFront strips unknown headers by default. The allow-list is
    // deliberately narrow — only the two custom auth headers the API
    // expects, plus all query strings. Cookies aren't used.
    const originRequestPolicy = new cloudfront.OriginRequestPolicy(this, 'ApiOriginRequestPolicy', {
      originRequestPolicyName: 'HideAndSeek-ApiOrigin',
      comment: 'Forward auth headers + query strings to the API origin',
      headerBehavior: cloudfront.OriginRequestHeaderBehavior.allowList(
        'X-Player-Id',
        'X-Player-Secret',
      ),
      queryStringBehavior: cloudfront.OriginRequestQueryStringBehavior.all(),
      cookieBehavior: cloudfront.OriginRequestCookieBehavior.none(),
    });

    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      domainNames: [domainName],
      certificate,
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
      // PRICE_CLASS_100 (NA + Europe). Hobby-scale trade-off: PRICE_CLASS_ALL
      // adds ~5 extra edge regions with per-region egress charges.
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      defaultBehavior: {
        origin: new origins.HttpOrigin(albDnsName, {
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
          httpPort: 80,
          // The ALB is DUAL_STACK_WITHOUT_PUBLIC_IPV4 — its public hostname
          // resolves to AAAA records only. CloudFront's origin connection
          // defaults to IPv4, which would 502 here; DUALSTACK lets CloudFront
          // fall through to the IPv6 address.
          ipAddressType: cloudfront.OriginIpAddressType.DUALSTACK,
          // SSE streams stay open for the lobby connection lifetime. 60s is
          // CloudFront's default maximum and enough for the keepalive cadence
          // the server emits; raising it further requires an AWS support
          // request and isn't needed here.
          readTimeout: cdk.Duration.seconds(60),
        }),
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        // Compression off — the API emits JSON or text/event-stream; SSE
        // streams aren't on CloudFront's compressible-content-type list
        // anyway, and JSON payloads here are small enough that the CPU +
        // latency of gzip isn't worth it.
        compress: false,
      },
    });

    const aliasTarget = route53.RecordTarget.fromAlias(
      new targets.CloudFrontTarget(this.distribution),
    );

    new route53.ARecord(this, 'AliasA', {
      zone,
      recordName: domainName,
      target: aliasTarget,
    });
    new route53.AaaaRecord(this, 'AliasAaaa', {
      zone,
      recordName: domainName,
      target: aliasTarget,
    });

    new cdk.CfnOutput(this, 'DistributionDomainName', {
      value: this.distribution.distributionDomainName,
      description: 'CloudFront distribution domain (*.cloudfront.net)',
    });
    new cdk.CfnOutput(this, 'PublicUrl', {
      value: `https://${domainName}`,
      description: 'Public HTTPS URL for the API',
    });
  }
}
