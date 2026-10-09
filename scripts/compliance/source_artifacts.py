#!/usr/bin/env python3
"""Keep source archives beside the image and bind their digest with OIDC signing."""
import argparse
import base64
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from source_archives import source_bundle
from verify import ISSUER, read_envelopes

PREDICATE = 'https://canonix.ai/attestations/corresponding-source/v1'
ARTIFACT = 'application/vnd.canonix.corresponding-source.v1'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_file(root, name):
    path = root / name
    if Path(name).is_absolute() or '..' in Path(name).parts or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Invalid source evidence path: ' + name)
    return path


def assemble(source_root, destination):
    files, entries = {}, {}
    for index in sorted(source_root.glob('*/source-index.json')):
        platform = index.parent.name
        for entry in json.loads(index.read_text())['components']:
            if entry['purl'] in entries:
                continue
            entry = dict(entry)
            for key in ('archive', 'buildInstructions'):
                path = safe_file(index.parent, entry[key])
                if sha(path) != entry[key + 'Sha256']:
                    raise ValueError('Source checksum mismatch: ' + str(path))
                target = platform + '/' + entry[key]
                files[target] = path.read_bytes()
                entry[key] = target
            entries[entry['purl']] = entry
    if not list(source_root.glob('*/source-index.json')):
        raise ValueError('No source evidence to attach')
    files['source-index.json'] = (json.dumps({'schemaVersion': 1, 'components': list(entries.values())}, indent=2) + '\n').encode()
    source_bundle(files, destination, 'corresponding-source', '', 'Source build instructions are in the index.\n')
    return destination / 'corresponding-source.tar.gz'


def publish(ref, root):
    repository = ref.split('@')[0]
    with tempfile.TemporaryDirectory(prefix='phoenix-source-artifact-') as tmp:
        archive = assemble(root, Path(tmp))
        descriptor = json.loads(subprocess.check_output(['oras', 'attach', '--format', 'json',
            '--artifact-type', ARTIFACT, ref, archive.name + ':application/gzip'], cwd=tmp, text=True))
        digest = descriptor.get('digest') or descriptor.get('manifest', {}).get('digest')
        if not digest or not re.fullmatch('sha256:[a-f0-9]{64}', digest):
            raise ValueError('oras did not return a source artifact digest')
        predicate = Path(tmp) / 'predicate.json'
        predicate.write_text(json.dumps({'schemaVersion': 1, 'artifactDigest': digest,
            'archiveSha256': sha(archive), 'filename': archive.name}))
        subprocess.run(['cosign', 'attest', '--yes', '--type', PREDICATE,
                        '--predicate', str(predicate), ref], check=True)


def download(ref, identity, output):
    text = subprocess.check_output(['cosign', 'verify-attestation', '--type', PREDICATE,
        '--certificate-identity-regexp', identity, '--certificate-oidc-issuer', ISSUER, ref], text=True)
    predicates = []
    for envelope in read_envelopes(text):
        statement = json.loads(base64.b64decode(envelope['payload'], validate=True))
        if statement.get('predicateType') == PREDICATE and any(
                s.get('digest', {}).get('sha256') == ref.rsplit('@sha256:', 1)[1] for s in statement.get('subject', [])):
            predicates.append(statement['predicate'])
    if not predicates:
        raise ValueError('No verified source attestation for image digest')
    predicate = predicates[-1]
    digest = predicate['artifactDigest']
    if not re.fullmatch('sha256:[a-f0-9]{64}', digest) or predicate.get('filename') != 'corresponding-source.tar.gz':
        raise ValueError('Invalid signed source artifact descriptor')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='phoenix-source-download-') as tmp:
        subprocess.run(['oras', 'pull', ref.split('@')[0] + '@' + digest, '-o', tmp], check=True)
        archive = safe_file(Path(tmp), predicate['filename'])
        if sha(archive) != predicate['archiveSha256']:
            raise ValueError('Signed source archive checksum mismatch')
        with tarfile.open(archive) as tar:
            # Our source bundles contain regular files only. Refuse links even
            # when tarfile's data filter would consider them locally safe.
            for member in tar:
                if not member.isfile() or member.name.startswith('/') or '..' in Path(member.name).parts:
                    raise ValueError('Invalid source archive member')
            tar.extractall(output, filter='data')
    (output / 'source-attestation.json').write_text(text)
    return json.loads((output / 'source-index.json').read_text())['components']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ref')
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    publish(args.ref, args.source_root)
