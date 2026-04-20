#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AppStack } from '../lib/app-stack';
import { CdnStack } from '../lib/cdn-stack';
import { DataStack } from '../lib/data-stack';
import { requireEnv } from '../lib/env';
import { NetworkStack } from '../lib/network-stack';

const app = new cdk.App();

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region:
    process.env.CDK_DEFAULT_REGION ??
    process.env.AWS_REGION ??
    'us-west-2',
};

cdk.Tags.of(app).add('Project', 'hideandseek');
cdk.Tags.of(app).add('ManagedBy', 'cdk');

const network = new NetworkStack(app, 'HideAndSeek-Network', { env });
const data = new DataStack(app, 'HideAndSeek-Data', { env, network });
const appStack = new AppStack(app, 'HideAndSeek-App', {
  env,
  network,
  data,
  // crossRegionReferences enables albDnsName to be consumed by CdnStack
  // (us-east-1) via auto-generated SSM parameters.
  crossRegionReferences: true,
});

new CdnStack(app, 'HideAndSeek-Cdn', {
  // CloudFront + ACM-for-CloudFront must live in us-east-1. Route 53 is
  // global so alias records work from here too. No primary-region resources
  // in this stack.
  env: { account: env.account, region: 'us-east-1' },
  crossRegionReferences: true,
  albDnsName: appStack.albDnsName,
  domainName: requireEnv('DOMAIN_NAME'),
  hostedZoneName: requireEnv('HOSTED_ZONE_NAME'),
});
