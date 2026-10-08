#!/usr/bin/env python3
"""Produce final-digest CycloneDX evidence for every runnable platform."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from rootfs import Rootfs


def add_packaged_inventory(document, inventory):
    """Include bundled JS and native wheel libraries invisible to binary scans."""
    components = document.setdefault('components', [])
    known = {item.get('purl') for item in components}
    for item in inventory['components']:
        if item['purl'] in known:
            continue
        component = {'type': 'library', 'name': item['name'], 'version': item['version'],
                     'purl': item['purl'], 'bom-ref': item['purl'],
                     'licenses': [{'license': {'name': value}} for value in item['licenses']],
                     'properties': [{'name': 'phoenix:evidence', 'value': '/licenses/components.json'}]}
        if item.get('sourceUrl'):
            component['externalReferences'] = [{'type': 'distribution', 'url': item['sourceUrl']}]
        if item.get('binarySha256'):
            component['hashes'] = [{'alg': 'SHA-256', 'content': item['binarySha256']}]
        components.append(component)
        known.add(item['purl'])


def run(*args):
    return subprocess.check_output(args, text=True)


def image_targets(ref):
    manifest = json.loads(run('crane', 'manifest', ref))
    if 'manifests' not in manifest:
        return [('image', ref)]
    repository = ref.split('@')[0]
    targets = []
    for item in manifest['manifests']:
        platform = item.get('platform', {})
        if platform.get('os') not in ('linux', 'windows'):
            continue
        name = '-'.join(platform.get(k, '') for k in ('os', 'architecture', 'variant')).rstrip('-')
        if not re.fullmatch(r'(linux|windows)-[a-z0-9_]+(?:-[a-z0-9_]+)?', name):
            raise ValueError('Invalid image platform: ' + name)
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', item['digest']):
            raise ValueError('Unsupported image digest: ' + item['digest'])
        targets.append((name, repository + '@' + item['digest']))
    if not targets or len({name for name, _ in targets}) != len(targets):
        raise ValueError('No unambiguous runnable platforms in manifest')
    return targets


def generate(ref, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    targets = image_targets(ref)
    inventory = []
    children = []
    for platform, child_ref in targets:
        path = output if child_ref == ref else output.with_name(f'{output.stem}-{platform}.json')
        subprocess.run(['syft', 'scan', child_ref, '--exclude', '/licenses/**',
                        '-o', 'cyclonedx-json=' + str(path)], check=True)
        inventory.append({'imageRef': child_ref, 'file': path.name, 'platform': platform})
        child = json.loads(path.read_text())
        with tempfile.TemporaryDirectory(prefix='phoenix-sbom-') as tmp:
            archive = Path(tmp) / 'rootfs.tar'
            subprocess.run(['crane', 'export', child_ref, str(archive)], check=True)
            fs = Rootfs(archive)
            packaged = fs.read('/licenses/components.json')
            if packaged:
                add_packaged_inventory(child, json.loads(packaged))
                path.write_text(json.dumps(child, indent=2) + '\n')
        # Index SBOM preserves each architecture's complete package inventory.
        def prefix_refs(value):
            if isinstance(value, dict):
                return {key: platform + ':' + v if key == 'bom-ref' else prefix_refs(v) for key, v in value.items()}
            if isinstance(value, list):
                return [prefix_refs(v) for v in value]
            return value
        children.append({'type': 'container', 'name': child_ref, 'bom-ref': child_ref,
                         'properties': [{'name': 'phoenix:platform', 'value': platform}],
                         'components': prefix_refs(child.get('components', []))})
    if len(targets) != 1 or targets[0][1] != ref:
        document = {'bomFormat': 'CycloneDX', 'specVersion': '1.6', 'version': 1,
                    'metadata': {'component': {'type': 'container', 'name': ref, 'bom-ref': ref}},
                    'components': children}
        output.write_text(json.dumps(document, indent=2) + '\n')
        inventory.append({'imageRef': ref, 'file': output.name, 'platform': 'index'})
    output.with_name('sbom-targets.json').write_text(json.dumps(inventory, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ref')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if '@sha256:' not in args.ref:
        parser.error('An immutable image digest is required')
    generate(args.ref, args.output)
