#!/usr/bin/env python3
"""Read-only AgentFS upgrade guards. Configuration is JSON on stdin; never logged."""
import argparse
import json
import os
import re
import subprocess
import sys

ENV = "PHOENIX_OPENSANDBOX_FUSE_IMAGES_JSON"
RESOURCE = "devic.es/fuse"
RELEASE = "fuse-device-plugin"


class AgentFSError(ValueError):
    """Safe diagnostic with no raw configuration or command output."""


def image_list(value):
    if not isinstance(value, list) or any(
        not isinstance(x, str) or not x or any(c.isspace() for c in x)
        for x in value
    ):
        raise AgentFSError("Invalid AgentFS image allowlist; refusing to discard permissions")
    return list(dict.fromkeys(value))


def deployed_images(deployment):
    if not deployment:
        return []
    container = next(c for c in deployment['spec']['template']['spec']['containers']
                     if c['name'] == 'opensandbox')
    setting = next((e for e in container.get('env', []) if e['name'] == ENV), None)
    return [] if setting is None else image_list(json.loads(setting['value']))


def current_image(config):
    image = config['images']['phoenixAgent']
    registry = config.get('imageRegistry', '').rstrip('/')
    repository = registry + '/' + image['name'] if registry else image['repository']
    return repository + ':' + image['tag'] + ('@' + image['digest'] if image.get('digest') else '')


def validate(config):
    fuse = config['services']['opensandbox']['fuse']
    if type(fuse['enabled']) is not bool:
        raise AgentFSError('services.opensandbox.fuse.enabled must be a boolean')
    image_list(fuse['retainedImages'])
    if not fuse['enabled']:
        return
    version = config['versions']['phoenixWorkflowEngine']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or tuple(map(int, version.split('.'))) < (0, 2, 6):
        raise AgentFSError('AgentFS requires phoenixWorkflowEngine chart >=0.2.6; update the release pins first')
    plugin = config['fuseDevicePlugin']
    if type(plugin['install']) is not bool:
        raise AgentFSError('fuseDevicePlugin.install must be a boolean')
    if not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', plugin['namespace']):
        raise AgentFSError('fuseDevicePlugin.namespace must be a Kubernetes namespace name')
    if type(plugin['slotsPerNode']) is not int or plugin['slotsPerNode'] < 1:
        raise AgentFSError('fuseDevicePlugin.slotsPerNode must be a positive integer')
    if plugin['nodeSelector'].get('kubernetes.io/os') != 'linux':
        raise AgentFSError('fuseDevicePlugin.nodeSelector must require kubernetes.io/os: linux')


def tolerates(taint, tolerations):
    return any(
        (not t.get('effect') or t['effect'] == taint['effect']) and
        ((t.get('operator', 'Equal') == 'Exists' and
          (not t.get('key') or t['key'] == taint['key'])) or
         (t.get('operator', 'Equal') == 'Equal' and t.get('key') == taint['key'] and
          t.get('value', '') == taint.get('value', '')))
        for t in tolerations
    )


def candidates(nodes, resource_class):
    selector = resource_class.get('nodeSelector', {})
    tolerations = resource_class.get('tolerations', [])
    return [node for node in nodes if
            node['metadata'].get('labels', {}).get('kubernetes.io/os') == 'linux' and
            all(node['metadata'].get('labels', {}).get(k) == v for k, v in selector.items()) and
            not node.get('spec', {}).get('unschedulable', False) and
            any(c['type'] == 'Ready' and c['status'] == 'True'
                for c in node.get('status', {}).get('conditions', [])) and
            all(tolerates(t, tolerations) for t in node.get('spec', {}).get('taints', [])
                if t['effect'] in ('NoSchedule', 'NoExecute'))]


def check_capacity(config, nodes):
    classes = config['scheduling']['sandboxResourceClasses']
    for name, resource_class in classes.items():
        if resource_class.get('nodeSelector', {}).get('kubernetes.io/os') == 'windows':
            continue
        eligible = candidates(nodes, resource_class)
        if not any(int(n.get('status', {}).get('allocatable', {}).get(RESOURCE, '0')) > 0 for n in eligible):
            raise AgentFSError(f'No Ready schedulable Linux node with {RESOURCE} for sandbox class {name}')


def check_plugin_ownership(config, nodes, daemonsets):
    namespace = config['fuseDevicePlugin']['namespace']
    ours = None
    for ds in daemonsets:
        meta = ds['metadata']
        annotations = meta.get('annotations', {})
        spec = ds['spec']['template']['spec']
        # Recognize the upstream device registration even when the DS is renamed.
        is_fuse = (meta.get('labels', {}).get('app.kubernetes.io/name') == RELEASE or
                   any(v.get('hostPath', {}).get('path') == '/dev/fuse'
                       for v in spec.get('volumes', [])))
        if not is_fuse:
            continue
        if (meta['name'] == RELEASE and meta['namespace'] == namespace and
                annotations.get('meta.helm.sh/release-name') == RELEASE and
                annotations.get('meta.helm.sh/release-namespace') == namespace):
            ours = ds
        else:
            raise AgentFSError('An existing FUSE plugin belongs to another installation; '
                             'set fuseDevicePlugin.install=false to reuse it')
    if ours is None and any(int(n.get('status', {}).get('allocatable', {}).get(RESOURCE, '0')) > 0 for n in nodes):
        raise AgentFSError('Nodes already advertise FUSE; set fuseDevicePlugin.install=false to reuse the existing plugin')


def check_namespace(kubectl, namespace):
    ns = kubectl('get', 'namespace', namespace, '--ignore-not-found', '-o', 'json')
    if ns and ns['metadata'].get('labels', {}).get('pod-security.kubernetes.io/enforce') in ('baseline', 'restricted'):
        raise AgentFSError(f'Namespace {namespace} forbids the permissions needed by AgentFS; '
                         'ask the cluster administrator to review its workload policy')


def run(action, config, namespace, kubectl):
    validate(config)
    if not config['services']['opensandbox']['fuse']['enabled']:
        return []
    if action == 'validate':
        return []
    deployment = kubectl('-n', namespace, 'get', 'deployment',
                         'phoenix-workflow-engine-opensandbox', '--ignore-not-found', '-o', 'json')
    previous = deployed_images(deployment)
    retained = image_list(config['services']['opensandbox']['fuse']['retainedImages'] + previous)
    if action == 'retain':
        return retained
    nodes = kubectl('get', 'nodes', '-o', 'json')['items']
    plugin = config['fuseDevicePlugin']
    check_namespace(kubectl, namespace)
    if plugin['install']:
        check_namespace(kubectl, plugin['namespace'])
        daemonsets = kubectl('get', 'daemonsets', '--all-namespaces', '-o', 'json')['items']
        check_plugin_ownership(config, nodes, daemonsets)
    if action == 'preflight' and plugin['install']:
        return retained  # New plugin has not been installed yet.
    check_capacity(config, nodes)
    if action == 'verify':
        expected = image_list([current_image(config)] + config['services']['opensandbox']['fuse']['retainedImages'] + image_list(json.loads(os.environ.get('PHOENIX_AGENTFS_RETAINED_IMAGES_JSON', '[]'))))
        if not set(expected).issubset(previous):
            raise AgentFSError('Deployed OpenSandbox is missing current or retained AgentFS image permissions')
    return retained


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'preflight', 'retain', 'capacity', 'verify'))
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--context')
    args = parser.parse_args()
    command = ['kubectl', '--request-timeout=30s']
    if args.context:
        command += ['--context', args.context]

    def kubectl(*arguments):
        result = subprocess.run(command + list(arguments), text=True, capture_output=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    try:
        config = json.load(sys.stdin)
        result = run(args.action, config, args.namespace, kubectl)
        if args.action == 'retain':
            print(json.dumps(result))
    except (ValueError, KeyError, TypeError, StopIteration, subprocess.CalledProcessError):
        # Never include subprocess output or configuration values: they may contain credentials.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, AgentFSError) else 'Cannot read or validate AgentFS state; refusing to continue'
        print('ERROR: ' + message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
