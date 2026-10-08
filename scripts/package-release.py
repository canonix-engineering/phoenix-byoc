#!/usr/bin/env python3
"""Build a release bundle only from verified images and available source archives."""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).with_name('compliance')))
from verify import verify


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def contained(root, relative):
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Invalid source-relative path: ' + relative)
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Missing source file or path outside source directory: {relative}')
    return path


def sources(required, root, output):
    entries = json.loads((root / 'source-index.json').read_text())['components']
    index = {entry['purl']: entry for entry in entries}
    if len(index) != len(entries):
        raise ValueError('Duplicate source index entries')
    for purl in sorted(required):
        if purl not in index:
            raise ValueError(f'Missing corresponding source for {purl}')
        entry = index[purl]
        if not entry.get('sourceUrl') or not entry.get('reviewedBy') or 'modifications' not in entry:
            raise ValueError(f'Unreviewed corresponding source: {purl}')
        for key in ('archive', 'buildInstructions'):
            path = contained(root, entry[key])
            if sha(path) != entry[key + 'Sha256']:
                raise ValueError(f'Source checksum mismatch: {entry[key]}')
            dest = output / entry[key]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source-index.json').write_text(json.dumps(
        {'schemaVersion': 1, 'components': [index[p] for p in sorted(required)]}, indent=2) + '\n')


def archive(directory, destination):
    with destination.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as tar:
            for path in sorted(directory.rglob('*')):
                if not path.is_file():
                    continue
                info = tar.gettarinfo(str(path), str(path.relative_to(directory)))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o644
                with path.open('rb') as stream:
                    tar.addfile(info, stream)


def package(release_path, source_root, contact, output, verifier=verify):
    root = release_path.parent
    release = yaml.safe_load(release_path.read_text())
    version = release['release']['version']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('Invalid release version')
    if not contact or not re.fullmatch(r'(?:[^\s@]+@[^\s@]+\.[^\s@]+|https://[^\s]+)', contact):
        raise ValueError('A real source-request email or HTTPS URL is required')
    if any(marker in contact.lower() for marker in ('example.', 'change_me', '{{', 'todo')):
        raise ValueError('Placeholder source contact is not a release contact')
    directory = output / ('phoenix-byoc-' + version)
    if directory.exists():
        raise ValueError('Output bundle already exists; use a new output directory')
    policy = json.loads((root / 'compliance/policy.json').read_text())
    directory.mkdir(parents=True)
    required = set()
    notices = [f'# Phoenix BYOC {version} — third-party notices', '']
    inventory = []
    if not release.get('images'):
        raise ValueError('Release image inventory is empty')
    for key, item in release['images'].items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            raise ValueError('Invalid image inventory key: ' + key)
        digest = item.get('digest', '')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError(f'{key}: release image must be pinned to its final digest')
        ref = item['repository'] + '@' + digest
        evidence = directory / 'images' / key
        verifier(ref, policy['certificateIdentityRegexp'], evidence)
        for path in sorted(evidence.glob('*/components.json')):
            components = json.loads(path.read_text())['components']
            required.update(c['purl'] for c in components if c.get('copyleft'))
        for path in sorted(evidence.glob('*/THIRD_PARTY_NOTICES')):
            notices += [f'## {key} — {path.parent.name}', '', path.read_text(), '']
        inventory.append({'image': key, 'ref': ref})
    sources(required, source_root, directory / 'sources')
    template = (root / 'compliance/SOURCE_OFFER.template.md').read_text()
    offer = template.replace('{{RELEASE_VERSION}}', version).replace('{{SOURCE_CONTACT}}', contact)
    if '{{' in offer:
        raise ValueError('Unresolved source-offer template fields')
    (directory / 'SOURCE_OFFER.md').write_text(offer)
    (directory / 'THIRD_PARTY_NOTICES.md').write_text('\n'.join(notices))
    shutil.copyfile(release_path, directory / 'release.yaml')
    (directory / 'image-index.json').write_text(json.dumps(inventory, indent=2) + '\n')
    checksums = ''.join(f'{sha(path)}  {path.relative_to(directory)}\n'
                        for path in sorted(directory.rglob('*')) if path.is_file())
    (directory / 'SHA256SUMS').write_text(checksums)
    destination = output / (directory.name + '-compliance.tar.gz')
    archive(directory, destination)
    destination.with_suffix(destination.suffix + '.sha256').write_text(f'{sha(destination)}  {destination.name}\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=Path(__file__).resolve().parents[1] / 'release.yaml')
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--source-contact')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    contact = args.source_contact or json.loads((args.release.parent / 'compliance/source-offer.json').read_text())['contact']
    print(package(args.release, args.source_root, contact, args.output))
