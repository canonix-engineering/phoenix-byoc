"""Release invariants: frozen sources, partial combinations, review and delivery."""
import argparse
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

spec = importlib.util.spec_from_file_location('release_ops', Path(__file__).resolve().parents[1] / 'scripts/release_ops.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
IMAGE = {'repository': '526563839763.dkr.ecr.us-east-1.amazonaws.com/image',
         'tag': 'sha-' + 'a' * 40, 'digest': 'sha256:' + 'b' * 64}


class ReleaseTests(unittest.TestCase):
    def test_service_selection_rejects_unknown_duplicate_and_empty(self):
        self.assertEqual(ops.groups('web,engine'), ['web', 'engine'])
        for value in ('', 'web,web', 'web,unknown', 'web, engine'):
            with self.assertRaises(ValueError):
                ops.groups(value)

    def test_version_cannot_be_path_or_shell_expression(self):
        for value in ('../1.2.3', '1.2.3;true', '01.2.3', '1.2.3-rc.1'):
            with self.assertRaises(ValueError):
                ops.version(value)

    def test_latest_same_commit_ci_must_be_green(self):
        def build(i, status):
            return dict(id=i, head_sha='a' * 40, event='push', head_branch='preview',
                        status='completed', conclusion=status, html_url=f'https://ci/{i}', run_attempt=1)
        with patch.object(ops, 'api', return_value={'workflow_runs': [build(1, 'success'), build(2, 'failure')]}):
            with self.assertRaisesRegex(ValueError, 'latest same-SHA'):
                ops.successful_ci('repo', 'a' * 40)

    def test_exact_sha_main_build_is_accepted(self):
        item = dict(id=1, head_sha='a' * 40, event='push', head_branch='main',
                    status='completed', conclusion='success', html_url='https://ci/1', run_attempt=2)
        with patch.object(ops, 'api', return_value={'workflow_runs': [item]}):
            self.assertEqual(ops.successful_ci('repo', 'a' * 40)['head_branch'], 'main')
            with self.assertRaises(ValueError):
                ops.successful_ci('repo', 'c' * 40)

    def deployment(self):
        deployment = {'metadata': {'name': 'app', 'generation': 2},
                      'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'app'}},
                               'template': {'spec': {'containers': [{'name': 'app', 'image': ops.ref(IMAGE)}]}}},
                      'status': dict(observedGeneration=2, replicas=1, updatedReplicas=1, readyReplicas=1, availableReplicas=1)}
        pod = {'metadata': {'labels': {'app': 'app'}},
               'status': {'containerStatuses': [{'name': 'app', 'ready': True, 'imageID': 'registry/app@' + IMAGE['digest']}]}}
        return deployment, pod

    def test_rollout_requires_current_generation_and_no_old_replicas(self):
        deployment, pod = self.deployment()
        self.assertEqual(ops.deployment_check(deployment, IMAGE, [pod])['replicas'], 1)
        for key, value in [('observedGeneration', 1), ('replicas', 2), ('updatedReplicas', 0)]:
            changed = copy.deepcopy(deployment)
            changed['status'][key] = value
            with self.assertRaises(ValueError):
                ops.deployment_check(changed, IMAGE, [pod])

    def test_live_pod_digest_not_just_deployment_tag(self):
        deployment, pod = self.deployment()
        child = 'sha256:' + 'c' * 64
        pod['status']['containerStatuses'][0]['imageID'] = 'registry/app@' + child
        with self.assertRaises(ValueError):
            ops.deployment_check(deployment, IMAGE, [pod])
        ops.deployment_check(deployment, IMAGE, [pod], {IMAGE['digest'], child})

    def test_review_hash_covers_install_and_upgrade_but_not_review_record(self):
        files = {'release.yaml': b'version: 1', 'scripts/install.sh': b'install', 'UPGRADE.md': b'first'}
        digest = ops.input_hash(files)
        files['.release/1.0.0/review.json'] = b'approved'
        self.assertEqual(digest, ops.input_hash(files))
        files['UPGRADE.md'] = b'changed'
        self.assertNotEqual(digest, ops.input_hash(files))

    def candidate(self):
        release = {'release': {'version': '1.0.1', 'channel': 'stable'},
                   'images': {key: dict(IMAGE) for _, keys in ops.GROUPS.values() for key in keys}}
        plan = {'version': '1.0.1', 'blockers': [], 'baseTag': 'v1.0.0', 'baseCommit': 'a' * 40,
                'services': {group: {'images': {key: dict(IMAGE) for key in keys}} for group, (_, keys) in ops.GROUPS.items()}}
        files = {'release.yaml': yaml.safe_dump(release).encode(), '.release/1.0.1/plan.json': json.dumps(plan).encode()}
        review = {'inputSha256': ops.input_hash(files), 'planSha256': ops.sha256(files['.release/1.0.1/plan.json']),
                  'compatibility': 'Reviewed exact service combination.', 'chartsAndValues': 'Reviewed all required chart values.',
                  'upgradeInstructions': 'Reviewed upgrade steps for this baseline.',
                  'customerRegistryAccess': 'Existing customer policy reviewed for all image repositories.',
                  'customerChanges': 'Updated the selected applications.',
                  'validationEvidence': ['https://example.test/actions/runs/123'], 'criticalChanges': False,
                  'rehearsal': {'performed': False, 'reason': 'Ordinary compatible image update; no critical changes.', 'evidence': ''}}
        return release, files, plan, review

    def test_review_rejects_changed_retained_service(self):
        release, files, plan, review = self.candidate()
        ops.check_review(release, files, plan, review)
        release['images']['phoenixAgent']['tag'] = 'sha-' + 'c' * 40
        with self.assertRaisesRegex(ValueError, 'outside frozen snapshot'):
            ops.check_review(release, files, plan, review)

    def test_critical_changes_cannot_skip_rehearsal(self):
        release, files, plan, review = self.candidate()
        review['criticalChanges'] = True
        with self.assertRaisesRegex(ValueError, 'Critical changes'):
            ops.check_review(release, files, plan, review)

    def test_new_blocker_and_changed_plan_reject_publication(self):
        release, files, plan, review = self.candidate()
        plan['blockers'] = ['Preview stale']
        with self.assertRaises(ValueError):
            ops.check_review(release, files, plan, review)
        plan['blockers'] = []
        files['.release/1.0.1/plan.json'] += b'\n'
        with self.assertRaisesRegex(ValueError, 'plan changed'):
            ops.check_review(release, files, plan, review)

    def test_archive_rejects_symlink(self):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w') as archive:
            member = tarfile.TarInfo('secret-link')
            member.type, member.linkname = tarfile.SYMTYPE, '/outside/secret'
            archive.addfile(member)
        with patch.object(ops, 'run', return_value=raw.getvalue()):
            with self.assertRaisesRegex(ValueError, 'Unsafe archive'):
                ops.archive_files('a' * 40)

    def test_package_deterministic_checksums_modes_and_qualification(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                def git(*args):
                    return subprocess.check_output(['git', *args], text=True).strip()
                git('init', '-q')
                git('config', 'user.email', 'test@example.invalid')
                git('config', 'user.name', 'Test')
                Path('UPGRADE.md').write_text('Old 1.0.0 upgrade')
                git('add', '.')
                git('commit', '-qm', 'baseline')
                baseline = git('rev-parse', 'HEAD')
                release, files, plan, review = self.candidate()
                plan['baseCommit'] = baseline
                files['.release/1.0.1/plan.json'] = json.dumps(plan).encode()
                files['UPGRADE.md'] = b'Upgrade from 1.0.0 to 1.0.1'
                files['docs/releases/1.0.1.md'] = b'Release 1.0.1'
                files['scripts/install.sh'] = b'#!/bin/sh\nexit 0\n'
                for name, data in files.items():
                    Path(name).parent.mkdir(parents=True, exist_ok=True)
                    Path(name).write_bytes(data)
                Path('scripts/install.sh').chmod(0o755)
                review['inputSha256'] = ops.input_hash(files)
                review['planSha256'] = ops.sha256(files['.release/1.0.1/plan.json'])
                ops.save('.release/1.0.1/review.json', review)
                git('add', '.')
                git('commit', '-qm', 'candidate')
                with tempfile.TemporaryDirectory() as artifacts:
                    evidence = Path(artifacts) / 'evidence'
                    ops.save(evidence / 'chart-index.json', {'remoteCharts': []})
                    rendered = Path(artifacts) / 'render.yaml'
                    rendered.write_text('kind: Pod\nspec:\n  containers:\n    - image: example/helper@sha256:abc\n')
                    for i in range(2):
                        ops.save(evidence / 'verification.json', {'inputSha256': review['inputSha256'], 'checkedAt': str(i)})
                        ops.package(argparse.Namespace(evidence=str(evidence), rendered=str(rendered), output=str(Path(artifacts) / str(i))))
                    first = Path(artifacts) / '0'
                    second = Path(artifacts) / '1'
                    for name in first.iterdir():
                        self.assertEqual(name.read_bytes(), (second / name.name).read_bytes(), name.name)
                    with tarfile.open(first / 'phoenix-byoc-1.0.1.tar.gz') as archive:
                        prefix = 'phoenix-byoc-1.0.1/'
                        self.assertEqual(archive.getmember(prefix + 'scripts/install.sh').mode, 0o755)
                        for line in archive.extractfile(prefix + 'SHA256SUMS').read().decode().splitlines():
                            digest, name = line.split('  ', 1)
                            self.assertEqual(digest, ops.sha256(archive.extractfile(prefix + name).read()))
                        self.assertFalse(any('/.release/' in m.name for m in archive))
                    self.assertFalse(ops.load(first / 'DELIVERY.json')['byocUpgradeRehearsalPerformed'])
                    self.assertEqual(ops.load(first / 'image-index.json')['additionalDeploymentImages'],
                                     [{'reference': 'example/helper@sha256:abc'}])
                    ops.verify_delivery(first, '1.0.1', git('rev-parse', 'HEAD'))
                    (first / 'UPGRADE.md').write_text('corrupt asset')
                    with self.assertRaisesRegex(ValueError, 'Archive/asset mismatch'):
                        ops.verify_delivery(first, '1.0.1', git('rev-parse', 'HEAD'))
            finally:
                os.chdir(original)

    def test_prepare_partial_keeps_baseline_and_refuses_implicit_refreeze(self):
        original = Path.cwd()
        release, _, _, _ = self.candidate()
        release['release']['version'] = '1.0.0'
        import base64
        def api(endpoint):
            if endpoint.endswith('/releases/latest'):
                return {'tag_name': 'v1.0.0', 'draft': False, 'prerelease': False}
            if '/contents/release.yaml?' in endpoint:
                return {'content': base64.b64encode(yaml.safe_dump(release).encode()).decode()}
            return {'sha': 'c' * 40, 'commit': {'tree': {'sha': 'd' * 40}}}
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                Path('release.yaml').write_text(yaml.safe_dump(release))
                with patch.object(ops, 'api', side_effect=api), patch.object(ops, 'successful_ci', return_value={'html_url': 'https://ci/1'}), \
                        patch.object(ops, 'ecr_digest', return_value='sha256:' + 'e' * 64) as resolve, \
                        patch.object(ops, 'preview_check', return_value={'checks': ['web']}):
                    args = argparse.Namespace(version='1.0.1', services='web', context='test-context')
                    ops.prepare(args)
                    updated = yaml.safe_load(Path('release.yaml').read_text())
                    self.assertEqual(updated['images']['phoenixAgent'], release['images']['phoenixAgent'])
                    self.assertEqual(updated['images']['phoenixWorkflowEngine'], release['images']['phoenixWorkflowEngine'])
                    self.assertEqual(updated['images']['phoenixWeb']['tag'], 'sha-' + 'c' * 40)
                    self.assertEqual(resolve.call_count, 2)
                    with self.assertRaisesRegex(ValueError, 'already frozen'):
                        ops.prepare(args)
            finally:
                os.chdir(original)

    def test_refresh_adds_only_requested_service_and_invalidates_review(self):
        original = Path.cwd()
        release, _, plan, review = self.candidate()
        plan['selectedServices'] = ['web']
        for group, entry in plan['services'].items():
            entry['selected'] = group == 'web'
            if entry['selected']:
                entry.update(repository='phoenix-web', previewCommit='a' * 40)
        def api(endpoint):
            if endpoint.endswith('/releases/latest'):
                return {'tag_name': 'v1.0.0'}
            return {'sha': 'c' * 40, 'commit': {'tree': {'sha': 'd' * 40}}}
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                Path('release.yaml').write_text(yaml.safe_dump(release))
                ops.save('.release/1.0.1/plan.json', plan)
                ops.save('.release/1.0.1/review.json', review)
                with patch.object(ops, 'api', side_effect=api), patch.object(ops, 'successful_ci', return_value={}), \
                        patch.object(ops, 'ecr_digest', return_value=IMAGE['digest']), \
                        patch.object(ops, 'preview_check', return_value={'checks': []}):
                    ops.refresh(argparse.Namespace(command='refresh', services='agents', context='test'))
                updated = yaml.safe_load(Path('release.yaml').read_text())
                self.assertEqual(updated['images']['phoenixWeb'], release['images']['phoenixWeb'])
                self.assertEqual(updated['images']['phoenixAgent']['tag'], 'sha-' + 'c' * 40)
                snapshot = ops.load('.release/1.0.1/plan.json')
                self.assertEqual(snapshot['selectedServices'], ['web', 'agents'])
                self.assertEqual(ops.load('.release/1.0.1/review.json')['inputSha256'], '')
                self.assertIsNone(ops.load('.release/1.0.1/review.json')['criticalChanges'])
            finally:
                os.chdir(original)


if __name__ == '__main__':
    unittest.main()
