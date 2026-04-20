"""Custom-resource handler that runs the Alembic migration Fargate task.

The DataStack wires this as the `onEventHandler` of a `cr.Provider`. CDK
invokes us on CREATE and UPDATE with properties containing `ImageDigest`
(the Docker image content hash). We run_task on the migration task def,
wait for it to stop, and raise if the container exited non-zero — which
makes CloudFormation roll the stack back.

DELETE is a no-op: migrations are forward-only and the cluster outlives
individual stack updates.
"""

from __future__ import annotations

import os
from typing import Any

import boto3


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request_type = event.get('RequestType', 'Create')
    physical_id = event.get('PhysicalResourceId') or 'hideandseek-migrations'

    if request_type == 'Delete':
        return {'PhysicalResourceId': physical_id}

    cluster_arn = os.environ['CLUSTER_ARN']
    task_def_arn = os.environ['TASK_DEFINITION_ARN']
    container_name = os.environ['CONTAINER_NAME']
    subnet_ids = [s for s in os.environ['SUBNET_IDS'].split(',') if s]
    security_group_id = os.environ['SECURITY_GROUP_ID']
    assign_public_ip = os.environ.get('ASSIGN_PUBLIC_IP', 'DISABLED')

    ecs = boto3.client('ecs')

    run = ecs.run_task(
        cluster=cluster_arn,
        taskDefinition=task_def_arn,
        launchType='FARGATE',
        count=1,
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': subnet_ids,
                'securityGroups': [security_group_id],
                'assignPublicIp': assign_public_ip,
            },
        },
    )
    failures = run.get('failures', [])
    if failures:
        raise RuntimeError(f'ecs:RunTask failed: {failures}')

    tasks = run.get('tasks', [])
    if not tasks:
        raise RuntimeError('ecs:RunTask returned no tasks')
    task_arn = tasks[0]['taskArn']

    waiter = ecs.get_waiter('tasks_stopped')
    waiter.wait(
        cluster=cluster_arn,
        tasks=[task_arn],
        WaiterConfig={'Delay': 10, 'MaxAttempts': 80},  # up to ~13 minutes
    )

    described = ecs.describe_tasks(cluster=cluster_arn, tasks=[task_arn])
    task = described['tasks'][0]
    containers = {c['name']: c for c in task.get('containers', [])}
    migrate = containers.get(container_name)
    if migrate is None:
        raise RuntimeError(
            f'Container {container_name!r} not found in stopped task; '
            f'stop reason: {task.get("stoppedReason")!r}'
        )

    exit_code = migrate.get('exitCode')
    if exit_code is None or exit_code != 0:
        raise RuntimeError(
            f'Alembic migration task exited non-zero (exitCode={exit_code}); '
            f'stop reason: {task.get("stoppedReason")!r}; '
            f'container reason: {migrate.get("reason")!r}'
        )

    image_digest = event.get('ResourceProperties', {}).get('ImageDigest', 'unknown')
    return {
        'PhysicalResourceId': physical_id,
        'Data': {
            'TaskArn': task_arn,
            'ImageDigest': image_digest,
        },
    }
