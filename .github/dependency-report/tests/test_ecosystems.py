import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("report", ROOT / "report.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
from go_modules import go_packages
from python_packages import uv_packages, requirement_rows


class EcosystemTests(unittest.TestCase):
    def test_go_require_blocks_single_lines_replacements_and_private_modules(self):
        rows = go_packages(
            "go.mod",
            """module app
require example.org/a v1.0.0
require (
 example.org/b v2.0.0 // indirect
 github.com/canonix-engineering/private v0.1.0
)
replace (
 example.org/a => example.org/fork v1.1.0
 example.org/b v2.0.0 => ../local
)
""",
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["lookupName"], "example.org/fork")
        self.assertEqual(rows[0]["version"], "v1.1.0")
        self.assertEqual(rows[1]["scope"], "transitive")
        self.assertFalse(rows[1]["public"])
        self.assertFalse(rows[2]["public"])

    def test_go_license_lookup_uses_effective_replacement_and_only_license_fields(self):
        rows = go_packages(
            "go.mod", "require example.org/a v1.0.0\nreplace example.org/a => example.org/b v1.2.0"
        )
        urls = []

        def fetch(url):
            urls.append(url)
            return {"licenses": ["MPL-2.0"], "advisoryKeys": [{"id": "DO-NOT-REPORT"}]}

        self.assertEqual(r.enrich_licenses(rows, fetch), [])
        self.assertIn("example.org%2Fb/versions/v1.2.0", urls[0])
        self.assertEqual(rows[0]["license"], "MPL-2.0")
        self.assertNotIn("DO-NOT-REPORT", json.dumps(rows))

    def test_uv_direct_optional_transitive_private_and_multiple_versions(self):
        rows = uv_packages(
            "uv.lock",
            """version = 1
[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "direct" }]
[package.optional-dependencies]
dev = [{ name = "pytest" }]
[[package]]
name = "direct"
version = "1.0.0"
source = {registry = "https://pypi.org/simple"}
[[package]]
name = "pytest"
version = "8.0.0"
source = {registry = "https://pypi.org/simple"}
[[package]]
name = "nested"
version = "2.0.0"
source = {git = "https://private.test/repo"}
[[package]]
name = "direct"
version = "1.1.0"
source = {registry = "https://pypi.org/simple"}
""",
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["id"] for row in rows}), 4)
        self.assertEqual(rows[1]["scope"], "direct")
        self.assertFalse(rows[2]["public"])
        self.assertEqual(rows[2]["scope"], "transitive")

    def test_requirements_pins_markers_hashes_and_unresolved_specs(self):
        rows, errors = requirement_rows(
            "requirements.txt",
            'PyYAML==6.0.2 ; python_version >= "3.11"\nfoo>=1\n-r other.txt\nbar==1.0 --hash=sha256:abc',
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "pyyaml")
        self.assertEqual(len(errors), 2)
        self.assertFalse(rows[1]["public"])
        self.assertTrue(rows[2]["public"])
        rows, errors = requirement_rows(
            "requirements.txt", "--index-url https://private.test\nprivate==1.0"
        )
        self.assertFalse(rows[0]["public"])

    def test_python_license_expression_and_classifier_fallback(self):
        rows, _ = requirement_rows("requirements.txt", "one==1.0\ntwo==1.0")

        def fetch(url):
            if "/one/" in url:
                return {"info": {"license_expression": "MIT OR Apache-2.0", "license": "wrong"}}
            return {
                "info": {
                    "license": "x" * 300,
                    "classifiers": ["License :: OSI Approved :: BSD License"],
                }
            }

        self.assertEqual(r.enrich_licenses(rows, fetch), [])
        self.assertEqual(rows[0]["license"], "MIT OR Apache-2.0")
        self.assertEqual(rows[1]["license"], "BSD License")

    def test_source_versions_follow_docker_args_and_missing_values_are_errors(self):
        config = json.dumps(
            {
                "sourceDependencies": [
                    {
                        "name": "native",
                        "versionFile": "docker/app.Dockerfile",
                        "versionArg": "NATIVE_TAG",
                        "source": "https://example.org/native",
                        "license": "MIT",
                    }
                ]
            }
        )
        rows, refs, errors = r.inventory(
            {
                ".github/dependency-report.json": config,
                "docker/app.Dockerfile": "ARG NATIVE_TAG=v1.0\nFROM alpine:3.21",
            }
        )
        self.assertFalse(errors)
        self.assertEqual(rows[0]["version"], "v1.0")
        self.assertEqual(refs[0]["value"], "alpine:3.21")
        _, _, errors = r.inventory(
            {
                ".github/dependency-report.json": config,
                "docker/app.Dockerfile": "ARG NATIVE_TAG=$OTHER",
            }
        )
        self.assertTrue(errors)

    def test_infrastructure_reference_labels_preserve_image_identity(self):
        _, refs, errors = r.inventory(
            {"release.yaml": 'images:\n  web:\n    tag: "v1"\n  worker:\n    tag: "v2"'}
        )
        self.assertFalse(errors)
        self.assertEqual(
            [row["value"] for row in refs], ['images.web.tag: "v1"', 'images.worker.tag: "v2"']
        )

    def test_reference_only_report_never_claims_license_pass(self):
        report = dict(
            headPackages=[],
            basePackages=[],
            changes=[],
            errors=[],
            referenceChanges=[],
            baseSha="a" * 40,
            headSha="b" * 40,
            generatedAt="now",
            referencesOnly=True,
        )
        body = r.render(report)
        self.assertIn("REFERENCES ONLY", body)
        self.assertNotIn("✅ PASS", body)

    def test_pyproject_change_without_uv_change_is_incomplete(self):
        class API:
            def snapshot(self, sha):
                return {"uv.lock": "version = 1"}, {"pyproject.toml": sha}

        report = r.analyze(
            API(), {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}}, lambda url: {}
        )
        self.assertTrue(any("Manifest changed" in error for error in report["errors"]))

    def test_new_report_config_can_inventory_existing_source_dependencies_in_base(self):
        config = json.dumps(
            {
                "sourceDependencies": [
                    {
                        "name": "native",
                        "versionFile": "Dockerfile",
                        "versionArg": "TAG",
                        "source": "https://example.org/native",
                        "license": "MIT",
                    }
                ]
            }
        )

        class API:
            def snapshot(self, sha):
                files = {"Dockerfile": "ARG TAG=v1"}
                if sha == "b" * 40:
                    files[".github/dependency-report.json"] = config
                return files, {}

        report = r.analyze(
            API(), {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}}, lambda url: {}
        )
        self.assertEqual(report["changes"], [])
        self.assertEqual(len(report["basePackages"]), 1)
