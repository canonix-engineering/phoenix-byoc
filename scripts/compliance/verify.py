#!/usr/bin/env python3
"""Fail-closed verification of image license evidence and signed SBOM subjects."""
import argparse
import base64
import json
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from evidence import image_targets
from rootfs import Rootfs
from policy import first_party, dependency_group

ISSUER = 'https://token.actions.githubusercontent.com'
PREDICATE = 'https://cyclonedx.org/bom'
DEFAULT_IDENTITY = r'^https://github\.com/canonix-engineering/[^/]+/\.github/workflows/[^@]+@(?:refs/(heads|tags|pull)/.+|[a-f0-9]{40})$'


def read_envelopes(text):
    # Cosign prints one JSON envelope per verified attestation, not one array.
    decoder, envelopes = json.JSONDecoder(), []
    remaining = text.strip()
    while remaining:
        value, end = decoder.raw_decode(remaining)
        envelopes.extend(value if isinstance(value, list) else [value])
        remaining = remaining[end:].lstrip()
    return envelopes


def verified_predicates(envelopes, expected_digest):
    if isinstance(envelopes, dict):
        envelopes = [envelopes]
    results = []
    for envelope in envelopes:
        statement = json.loads(base64.b64decode(envelope['payload'], validate=True))
        if statement.get('predicateType') != PREDICATE:
            continue
        if not any(subject.get('digest', {}).get('sha256') == expected_digest.removeprefix('sha256:')
                   for subject in statement.get('subject', [])):
            continue
        predicate = statement.get('predicate', {})
        if predicate.get('bomFormat') == 'CycloneDX' and predicate.get('components'):
            results.append(predicate)
    if not results:
        raise ValueError('No verified CycloneDX predicate for the expected image digest')
    return results


def check_licenses(fs):
    notices = fs.read('/licenses/THIRD_PARTY_NOTICES')
    if not notices.strip():
        raise ValueError('Missing /licenses/THIRD_PARTY_NOTICES')
    inventory = json.loads(fs.read('/licenses/components.json'))
    if inventory.get('schemaVersion') != 1 or not inventory.get('components'):
        raise ValueError('Empty or unsupported license inventory')
    for item in inventory['components']:
        if item.get('scope') == 'dependency-group':
            if not dependency_group(item, fs):
                raise ValueError('Invalid dependency-only package exemption')
            continue
        if item.get('scope') == 'first-party':
            if not first_party(item):
                raise ValueError('Unrecognized first-party exemption')
            continue
        if item.get('unresolved'):
            raise ValueError(f"Unresolved license evidence: {item['purl']}: {item['unresolved']}")
        if not item.get('licenses') or any(value in ('UNKNOWN', 'NOASSERTION', '') for value in item['licenses']):
            raise ValueError(f"Unresolved license identifier: {item['purl']}")
        if not item.get('licenseFiles'):
            raise ValueError(f"Missing license texts: {item['purl']}")
        for path in item['licenseFiles']:
            if not path.startswith('texts/') or '..' in Path(path).parts or not fs.read('/licenses/' + path):
                raise ValueError(f'Missing or invalid license file: {path}')
            if hashlib.sha256(fs.read('/licenses/' + path).encode()).hexdigest() != Path(path).stem:
                raise ValueError(f'License checksum mismatch: {path}')
        copyleft = any(re.search(r'(?i)(MPL|LGPL|GPL|AGPL)', value) for value in item['licenses'])
        if copyleft != item.get('copyleft'):
            raise ValueError(f"Inconsistent copyleft classification: {item['purl']}")
        if copyleft and not item.get('sourceUrl'):
            raise ValueError(f"Missing corresponding-source location: {item['purl']}")
    return notices, inventory


def verify(ref, identity, output=None):
    targets = image_targets(ref)
    refs = list(dict.fromkeys([ref] + [child for _, child in targets]))
    if output:
        output.mkdir(parents=True, exist_ok=True)
    verified = {}
    for index, target in enumerate(refs):
        text = subprocess.check_output(['cosign', 'verify-attestation', '--type', 'cyclonedx',
            '--certificate-identity-regexp', identity, '--certificate-oidc-issuer', ISSUER, target], text=True)
        envelopes = read_envelopes(text)
        predicates = verified_predicates(envelopes, target.rsplit('@', 1)[1])
        verified[target] = predicates[-1]
        if output:
            (output / f'attestation-{index}.json').write_text(text)
            (output / f'sbom-{index}.cdx.json').write_text(json.dumps(predicates[-1], indent=2) + '\n')
    for platform, child_ref in targets:
        with tempfile.TemporaryDirectory(prefix='phoenix-license-verify-') as tmp:
            archive = Path(tmp) / 'rootfs.tar'
            subprocess.run(['crane', 'export', child_ref, str(archive)], check=True)
            fs = Rootfs(archive)
            notices, inventory = check_licenses(fs)
            def purls(components):
                result = set()
                for component in components:
                    if component.get('purl'):
                        result.add(component['purl'])
                    result.update(purls(component.get('components', [])))
                return result
            sbom_purls = purls(verified[child_ref].get('components', []))
            inventory_purls = {c['purl'] for c in inventory['components']}
            missing = sbom_purls - inventory_purls
            if missing:
                raise ValueError('SBOM components missing attribution: ' + ', '.join(sorted(missing)))
            if inventory_purls - sbom_purls:
                raise ValueError('License inventory components missing from signed SBOM: ' +
                                 ', '.join(sorted(inventory_purls - sbom_purls)))
            if output:
                directory = output / platform
                directory.mkdir(parents=True, exist_ok=True)
                (directory / 'THIRD_PARTY_NOTICES').write_text(notices)
                (directory / 'components.json').write_text(json.dumps(inventory, indent=2) + '\n')
                for item in inventory['components']:
                    for path in item['licenseFiles']:
                        target = directory / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(fs.read('/licenses/' + path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ref')
    parser.add_argument('--identity', default=DEFAULT_IDENTITY)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if '@sha256:' not in args.ref:
        parser.error('An immutable image digest is required')
    verify(args.ref, args.identity, args.output)
