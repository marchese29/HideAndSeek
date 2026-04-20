#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AppStack } from '../lib/app-stack';
import { DataStack } from '../lib/data-stack';
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
new AppStack(app, 'HideAndSeek-App', { env, network, data });
