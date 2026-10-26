import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('agentfs', ROOT / 'scripts/agentfs.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def config():
    return {
        'services': {'opensandbox': {'fuse': {'enabled': True, 'retainedImages': []}}},
        'versions': {'phoenixWorkflowEngine': '0.2.6'},
        'images': {'phoenixAgent': {'name': 'phoenix-agent', 'repository': 'source/agent',
                                  'tag': 'C', 'digest': 'sha256:ccc'}},
        'imageRegistry': '',
        'fuseDevicePlugin': {'install': False, 'namespace': 'phoenix-system',
                             'slotsPerNode': 64, 'nodeSelector': {'kubernetes.io/os': 'linux'}},
        'scheduling': {'sandboxResourceClasses': {'default': {'nodeSelector': {'pool': 'sandbox'}}}},
    }


def deployment(images):
    return {'spec': {'template': {'spec': {'containers': [{'name': 'opensandbox', 'env': [
        {'name': a.ENV, 'value': json.dumps(images)}]}]}}}}


def node(fuse=64, pool='sandbox'):
    return {'metadata': {'name': 'linux-node', 'labels': {'kubernetes.io/os': 'linux', 'pool': pool}},
            'spec': {}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                                  'allocatable': {a.RESOURCE: str(fuse)}}}


def plugin(namespace='phoenix-system', owned=True):
    return {'metadata': {'name': a.RELEASE, 'namespace': namespace,
                         'labels': {'app.kubernetes.io/name': a.RELEASE},
                         'annotations': {'meta.helm.sh/release-name': a.RELEASE,
                                         'meta.helm.sh/release-namespace': namespace} if owned else {}},
            'spec': {'template': {'spec': {}}}}


class AgentFSTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"PHOENIX_AGENTFS_RETAINED_IMAGES_JSON": "[]"})
        env.start()
        self.addCleanup(env.stop)
        self.config = config()
        self.live = deployment(['source/agent:A', 'source/agent:B'])
        self.nodes = [node()]
        self.daemonsets = []
        self.namespace = None
        self.calls = []

    def kubectl(self, *args):
        self.calls.append(args)
        if 'deployment' in args:
            return self.live
        if 'nodes' in args:
            return {'items': self.nodes}
        if 'daemonsets' in args:
            return {'items': self.daemonsets}
        if 'namespace' in args:
            return self.namespace
        self.fail('Unexpected cluster operation: ' + str(args))

    def run_action(self, action):
        return a.run(action, self.config, 'phoenix', self.kubectl)

    def test_upgrade_chain_and_rollback_retain_all_images(self):
        self.config['services']['opensandbox']['fuse']['retainedImages'] = ['manual:image']
        retained = self.run_action('retain')
        self.assertEqual(retained, ['manual:image', 'source/agent:A', 'source/agent:B'])
        self.live = deployment(retained + [a.current_image(self.config)])
        self.config['images']['phoenixAgent']['tag'] = 'A'
        self.assertIn('source/agent:C@sha256:ccc', self.run_action('retain'))
        self.assertIn('source/agent:A', self.run_action('retain'))

    def test_fresh_and_pre_agentfs_install(self):
        self.live = None
        self.assertEqual(self.run_action('retain'), [])
        self.live = deployment([])
        self.live['spec']['template']['spec']['containers'][0]['env'] = []
        self.assertEqual(self.run_action('retain'), [])

    def test_corrupt_or_indirect_allowlist_fails_closed(self):
        for value in ('bad json', '{}', '[""]', '[42]', '["bad image"]'):
            self.live['spec']['template']['spec']['containers'][0]['env'][0]['value'] = value
            with self.assertRaises((ValueError, KeyError)):
                self.run_action('retain')
        self.live['spec']['template']['spec']['containers'][0]['env'][0] = {
            'name': a.ENV, 'valueFrom': {'secretKeyRef': {'name': 'x', 'key': 'x'}}}
        with self.assertRaises(KeyError):
            self.run_action('retain')

    def test_read_error_is_not_empty_list(self):
        with self.assertRaises(subprocess.CalledProcessError):
            a.run('retain', self.config, 'phoenix', lambda *args: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, 'kubectl')))

    def test_old_engine_chart_rejected_before_cluster_read(self):
        self.config['versions']['phoenixWorkflowEngine'] = '0.2.5'
        with self.assertRaisesRegex(ValueError, 'chart >=0.2.6'):
            self.run_action('preflight')
        self.assertFalse(self.calls)

    def test_reuse_needs_fuse_on_eligible_nodes(self):
        self.run_action('preflight')
        self.assertFalse(any('daemonsets' in call for call in self.calls))
        for nodes in ([node(0)], [node(pool='other')], []):
            self.nodes = nodes
            with self.assertRaisesRegex(ValueError, 'sandbox class default'):
                self.run_action('preflight')

    def test_taints_readiness_and_cordoned_nodes(self):
        for change in ('taint', 'not_ready', 'cordon'):
            n = node()
            if change == 'taint':
                n['spec']['taints'] = [{'key': 'sandbox', 'effect': 'NoSchedule'}]
            elif change == 'not_ready':
                n['status']['conditions'][0]['status'] = 'False'
            else:
                n['spec']['unschedulable'] = True
            self.nodes = [n]
            with self.assertRaises(ValueError):
                self.run_action('capacity')
        self.nodes = [node()]
        self.nodes[0]['spec']['taints'] = [{'key': 'sandbox', 'effect': 'NoSchedule'}]
        self.config['scheduling']['sandboxResourceClasses']['default']['tolerations'] = [
            {'key': 'sandbox', 'operator': 'Exists'}]
        self.run_action('capacity')

    def test_managed_plugin_first_install_then_capacity_gate(self):
        self.config['fuseDevicePlugin']['install'] = True
        self.nodes = [node(0)]
        self.run_action('preflight')
        with self.assertRaises(ValueError):
            self.run_action('capacity')
        self.nodes = [node()]
        self.daemonsets = [plugin()]
        self.run_action('capacity')

    def test_existing_unowned_plugin_is_never_adopted(self):
        self.config['fuseDevicePlugin']['install'] = True
        for daemonsets in ([], [plugin('kube-system')], [plugin(owned=False)]):
            self.daemonsets = daemonsets
            with self.assertRaisesRegex(ValueError, 'install=false'):
                self.run_action('preflight')
        # Detect other providers even before they have advertised capacity.
        self.nodes = [node(0)]
        self.daemonsets = [plugin('kube-system')]
        with self.assertRaises(ValueError):
            self.run_action('preflight')

    def test_namespace_restrictions_are_reported_not_changed(self):
        self.namespace = {'metadata': {'labels': {'pod-security.kubernetes.io/enforce': 'restricted'}}}
        with self.assertRaisesRegex(ValueError, 'workload policy'):
            self.run_action('preflight')
        self.assertFalse(any('patch' in call or 'apply' in call for call in self.calls))

    def test_verify_current_mirrored_image_and_retained_permissions(self):
        self.config['imageRegistry'] = 'customer.example/phoenix/'
        current = a.current_image(self.config)
        self.assertEqual(current, 'customer.example/phoenix/phoenix-agent:C@sha256:ccc')
        self.live = deployment([current])
        self.run_action('verify')
        with patch.dict(os.environ, {'PHOENIX_AGENTFS_RETAINED_IMAGES_JSON': '["source/agent:A"]'}):
            with self.assertRaisesRegex(ValueError, 'missing current or retained'):
                self.run_action('verify')
            self.live = deployment([current, 'source/agent:A'])
            self.run_action('verify')

    def test_disabled_release_is_offline_and_inert(self):
        self.config['services']['opensandbox']['fuse']['enabled'] = False
        self.config['versions']['phoenixWorkflowEngine'] = '0.2.5'
        self.run_action('preflight')
        self.assertFalse(self.calls)

    def test_cli_errors_do_not_log_configuration(self):
        self.config['secrets'] = {'token': 'never-print-this-token'}
        self.config['versions']['phoenixWorkflowEngine'] = '0.2.5'
        result = subprocess.run(['python3', str(ROOT / 'scripts/agentfs.py'), 'validate',
                                 '--namespace', 'phoenix'], input=json.dumps(self.config),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('never-print-this-token', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
