import hashlib
import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/package-release.py'
spec = importlib.util.spec_from_file_location('package_release', SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'compliance').mkdir()
        (self.root / 'compliance/policy.json').write_text('{"certificateIdentityRegexp":"trusted"}')
        (self.root / 'compliance/SOURCE_OFFER.template.md').write_text('{{RELEASE_VERSION}} {{SOURCE_CONTACT}}')
        (self.root / 'release.yaml').write_text('release:\n  version: 1.2.3\nimages:\n  app:\n'
            '    repository: registry/app\n    digest: sha256:' + 'a' * 64 + '\n')
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'source.tar.gz').write_bytes(b'fixture source archive')
        (self.source / 'BUILD.md').write_text('Fixture build and modification instructions')
        self.purl = 'pkg:generic/fixture@1'
        self.entry = dict(purl=self.purl, sourceUrl='https://upstream.example/fixture/1',
                          reviewedBy='fixture', modifications='none', archive='source.tar.gz',
                          buildInstructions='BUILD.md')
        for key in ('archive', 'buildInstructions'):
            self.entry[key + 'Sha256'] = release.sha(self.source / self.entry[key])
        self.index()

    def index(self, entries=None):
        (self.source / 'source-index.json').write_text(json.dumps({'components': entries or [self.entry]}))

    def verifier(self, ref, identity, output):
        self.assertEqual(identity, 'trusted')
        platform = output / 'linux-amd64'
        platform.mkdir(parents=True)
        (platform / 'components.json').write_text(json.dumps({'components': [{'purl': self.purl, 'copyleft': True}]}))
        (platform / 'THIRD_PARTY_NOTICES').write_text('Fixture upstream notice')
        (output / 'sbom-0.cdx.json').write_text('{"bomFormat":"CycloneDX"}')
        (output / 'attestation-0.json').write_text('{"payload":"fixture"}')

    def package(self, suffix='out'):
        return release.package(self.root / 'release.yaml', self.source, 'https://canonix.ai/',
                               self.root / suffix, verifier=self.verifier)

    def test_bundle_contains_durable_evidence_source_and_checksums(self):
        archive = self.package()
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            for name in ('THIRD_PARTY_NOTICES.md', 'SOURCE_OFFER.md', 'release.yaml', 'SHA256SUMS',
                         'sources/source-index.json', 'sources/source.tar.gz', 'sources/BUILD.md',
                         'images/app/sbom-0.cdx.json', 'images/app/attestation-0.json'):
                self.assertIn(name, names)
            for line in bundle.extractfile('SHA256SUMS').read().decode().splitlines():
                expected, path = line.split('  ', 1)
                self.assertEqual(hashlib.sha256(bundle.extractfile(path).read()).hexdigest(), expected)
        self.assertEqual(archive.read_bytes(), self.package('repeat').read_bytes())

    def test_missing_digest_stops_before_verification(self):
        path = self.root / 'release.yaml'
        path.write_text(path.read_text().replace('sha256:' + 'a' * 64, ''))
        with self.assertRaises((ValueError, TypeError)):
            self.package()

    def test_missing_corresponding_source_blocks_release(self):
        self.entry['purl'] = 'pkg:generic/different@1'
        self.index()
        with self.assertRaisesRegex(ValueError, 'Missing corresponding source'):
            self.package()

    def test_changed_source_archive_blocks_release(self):
        (self.source / 'source.tar.gz').write_bytes(b'wrong version')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.package()

    def test_paths_cannot_escape_bundle(self):
        self.entry['archive'] = '../source/source.tar.gz'
        self.index()
        with self.assertRaisesRegex(ValueError, 'Invalid source-relative'):
            self.package()

    def test_placeholder_contact_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Placeholder'):
            release.package(self.root / 'release.yaml', self.source, 'https://example.com/',
                            self.root / 'out', verifier=self.verifier)


if __name__ == '__main__':
    unittest.main()
