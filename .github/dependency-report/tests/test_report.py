import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("report", ROOT / "report.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def npm(version="1.0.0", license="MIT"):
    return json.dumps(
        {
            "lockfileVersion": 3,
            "packages": {
                "": {"dependencies": {"direct": "^1.0.0"}},
                "frontend": {"devDependencies": {"workspace-dev": "2.0.0"}},
                "node_modules/direct": {
                    "version": version,
                    "license": license,
                    "resolved": "https://registry.npmjs.org/direct/-/direct.tgz",
                },
                "node_modules/direct/node_modules/nested": {
                    "version": "1.1.0",
                    "license": "BSD-3-Clause",
                    "resolved": "https://registry.npmjs.org/nested/-/nested.tgz",
                },
                "node_modules/workspace-dev": {"version": "2.0.0", "license": "MIT"},
                "node_modules/local": {"link": True, "resolved": "shared"},
            },
        }
    )


RUBY = """GIT
  remote: https://example.test/private.git
  revision: abc123
  specs:
    private-gem (1.0.0)

GEM
  remote: https://rubygems.org/
  specs:
    rails (8.0.0)
      rack (~> 3)
    rack (3.0.0)
    native (2.0.0-x86_64-linux-gnu)
    native (2.0.0-arm64-darwin)

DEPENDENCIES
  rails (~> 8)
  private-gem!

BUNDLED WITH
   2.6.9
"""


class ParsingTests(unittest.TestCase):
    def test_workspaces_nested_and_direct_dependencies(self):
        rows = r.npm_packages("package-lock.json", npm())
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {v["name"]: v["scope"] for v in rows},
            {"direct": "direct", "nested": "transitive", "workspace-dev": "direct"},
        )
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_unsupported_lockfile_is_incomplete_not_clean(self):
        rows, _, errors = r.inventory({"package-lock.json": '{"lockfileVersion": 1}'})
        self.assertFalse(rows)
        self.assertIn("Only npm", errors[0])

    def test_malformed_lockfile_does_not_discard_other_inventory(self):
        rows, _, errors = r.inventory({"package-lock.json": "{", "Gemfile.lock": RUBY})
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(errors), 1)

    def test_ruby_platforms_git_source_and_directness(self):
        rows = r.ruby_packages("Gemfile.lock", RUBY)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({v["id"] for v in rows}), 5)
        self.assertFalse(rows[0]["public"])
        self.assertIn("#abc123", rows[0]["source"])
        self.assertTrue(rows[1]["public"])
        self.assertEqual(rows[1]["scope"], "direct")
        self.assertEqual(rows[2]["scope"], "transitive")
        self.assertEqual(rows[3]["version"], "2.0.0")

    def test_same_version_license_and_source_changes_are_reported(self):
        before = r.npm_packages("package-lock.json", npm())
        after = r.npm_packages("package-lock.json", npm(license="GPL-3.0-only"))
        after[1]["source"] = "https://other.test/nested.tgz"
        diff = r.changes(before, after)
        self.assertEqual(len(diff), 2)
        self.assertTrue(all(v["change"] == "changed" for v in diff))

    def test_add_remove_update_and_unchanged(self):
        before = r.npm_packages("package-lock.json", npm())
        after = r.npm_packages("package-lock.json", npm("1.2.0"))
        after.pop(1)
        new = dict(after[0], id="another:new", name="new")
        after.append(new)
        self.assertEqual(
            {v["change"] for v in r.changes(before, after)}, {"added", "removed", "changed"}
        )
        self.assertFalse(r.changes(before, before))

    def test_non_registry_dependencies_not_queried_as_public(self):
        doc = json.loads(npm())
        doc["packages"]["node_modules/direct"]["resolved"] = "https://private.test/direct.tgz"
        self.assertFalse(r.npm_packages("package-lock.json", json.dumps(doc))[0]["public"])

    def test_docker_and_action_references_are_data_only(self):
        _, refs, errors = r.inventory(
            {
                "Dockerfile": "FROM --platform=$BUILDPLATFORM node:24 AS build\nRUN evil",
                ".github/workflows/ci.yml": "steps:\n  - uses: actions/checkout@abc # comment",
            }
        )
        self.assertFalse(errors)
        self.assertEqual({v["value"] for v in refs}, {"node:24", "actions/checkout@abc"})


class RemoteTests(unittest.TestCase):
    def test_registry_failure_is_unknown_and_reported(self):
        rows = r.ruby_packages("Gemfile.lock", RUBY)
        queried = []

        def fetch(url):
            queried.append(url)
            if "rack/" in url:
                raise RuntimeError("unavailable")
            return {"licenses": ["MIT"]}

        errors = r.enrich_licenses(rows, fetch)
        self.assertEqual(len(errors), 1)
        self.assertFalse(any("private-gem" in url for url in queried))
        self.assertEqual(rows[1]["license"], "MIT")
        self.assertEqual(rows[2]["license"], "UNKNOWN")
        self.assertEqual(len(queried), 3)  # native variants share version metadata

    def test_analysis_only_fetches_license_metadata(self):
        class API:
            def snapshot(self, sha):
                return {"package-lock.json": npm(license="UNKNOWN")}, {}

        urls = []

        def fetch(url):
            self.assertTrue(url.startswith("https://registry.npmjs.org/"))
            urls.append(url)
            return {"license": "MIT"}

        report = r.analyze(API(), {"head": {"sha": "b" * 40}, "base": {"sha": "a" * 40}}, fetch)
        self.assertFalse(report["errors"])
        self.assertEqual(len(urls), 1)  # Same package/version in base and head.
        self.assertNotIn("advisories", json.dumps(report))
        self.assertNotIn("osv", json.dumps(report).lower())
        self.assertIn("✅ PASS", r.render(report))

    def test_token_cannot_be_sent_to_external_api(self):
        with self.assertRaises(ValueError):
            r.request("https://example.test/", token="secret")

    def test_truncated_tree_is_not_treated_as_complete(self):
        github = r.GitHub("org/repo", "token")
        github.api = lambda path: {"truncated": True}
        with self.assertRaisesRegex(ValueError, "truncated"):
            github.snapshot("a" * 40)


class ReportTests(unittest.TestCase):
    def make_report(self):
        rows = r.npm_packages("package-lock.json", npm())
        return dict(
            baseSha="a" * 40,
            headSha="b" * 40,
            basePackages=rows,
            headPackages=rows,
            changes=[],
            referenceChanges=[],
            errors=[],
            generatedAt="2026-10-13T00:00:00Z",
            runUrl="https://github.com/org/repo/actions/runs/1",
        )

    def test_render_explicit_incomplete_not_success(self):
        report = self.make_report()
        report["errors"] = ["License metadata unavailable"]
        body = r.render(report)
        self.assertIn("⚠️ INCOMPLETE", body)
        self.assertNotIn("✅ PASS", body)
        self.assertIn("License metadata unavailable", body)

    def test_clean_result_is_pass(self):
        self.assertIn("✅ PASS", r.render(self.make_report()))

    def test_existing_findings_are_warning_even_without_pr_changes(self):
        report = self.make_report()
        row = dict(report["headPackages"][0], license="UNKNOWN")
        report["basePackages"] = [row]
        report["headPackages"] = [row, dict(row, id="duplicate")]
        body = r.render(report)
        self.assertIn("⚠️ ATTENTION NEEDED", body)
        self.assertNotIn("✅ PASS", body)
        self.assertIn("| With unknown licenses | 1 | 0 | 1 |", body)
        self.assertIn("PR impact: no new unknown licenses", body)

    def test_new_findings_are_separate_from_existing(self):
        report = self.make_report()
        old = dict(report["headPackages"][0])
        new = dict(old, version="2.0.0", license="UNKNOWN")
        report["basePackages"] = [old]
        report["headPackages"] = [old, new]
        body = r.render(report)
        self.assertIn("| With unknown licenses | 1 | 1 | 0 |", body)
        self.assertIn("PR impact: new unknown licenses", body)

    def test_empty_inventory_and_errors_never_pass(self):
        for condition in ("empty", "error"):
            with self.subTest(condition=condition):
                report = self.make_report()
                if condition == "empty":
                    report["headPackages"] = []
                elif condition == "error":
                    report["errors"] = ["Registry unavailable"]
                body = r.render(report)
                self.assertIn("⚠️ INCOMPLETE", body)
                self.assertNotIn("✅ PASS", body)
                self.assertNotIn("PR impact: no new unknown licenses", body)
                self.assertIn("Not confirmed", body)

    def test_markdown_injection_and_mentions_escaped(self):
        value = r.cell("[click](https://evil.test) | <script> @everyone\n`code`")
        self.assertNotIn("<script>", value)
        self.assertNotIn("[click]", value)
        self.assertNotIn("@everyone", value)
        self.assertNotIn("|", value)
        self.assertNotIn("\n", value)

    def test_oversized_tables_remain_bounded(self):
        body = r.table(["Name", "Version"], [("x" * 10000, "y" * 10000)] * 1000)
        self.assertLess(len(body), 10000)
        self.assertIn("Showing 30 of 1000", body)

    def test_license_inventory_deduplicates_without_losing_declarations(self):
        row = r.npm_packages("package-lock.json", npm())[0]
        packages = r.package_licenses(
            [
                row,
                dict(row, id="duplicate"),
                dict(row, license="UNKNOWN"),
                dict(row, version="2.0.0"),
            ]
        )
        self.assertEqual(
            packages,
            [["npm", "direct", "1.0.0", "MIT; UNKNOWN"], ["npm", "direct", "2.0.0", "MIT"]],
        )
        self.assertEqual(sum(count for _, count in r.license_summary(packages)), 2)

    def test_comment_is_bounded_but_package_artifact_has_all_rows(self):
        report = self.make_report()
        row = report["headPackages"][0]
        report["headPackages"] = [dict(row, name=f"package-{i:03}") for i in range(75)]
        body = r.render(report)
        self.assertIn("MIT: **75**", body)
        self.assertIn("Showing 30 of 75", body)
        self.assertNotIn("package-074", body)
        full = r.render_package_licenses(report)
        self.assertIn("package-074", full)
        self.assertNotIn("Showing 30", full)
        self.assertIn("75 distinct package versions", full)
        report["errors"] = ["Unavailable registry"]
        self.assertIn("Incomplete analysis", r.render_package_licenses(report))

    def test_sticky_comment_updates_only_own_marker(self):
        report = self.make_report()
        writes = []

        class API:
            def api(self, path, data=None, method=None):
                if path.startswith("pulls/"):
                    return {"head": {"sha": report["headSha"]}, "base": {"sha": report["baseSha"]}}
                if "?per_page" in path:
                    return [
                        {"id": 1, "body": r.MARKER, "user": {"login": "someone"}},
                        {"id": 2, "body": r.MARKER, "user": {"login": "github-actions[bot]"}},
                    ]
                writes.append((path, method))
                return {"html_url": "https://github.com/comment/2"}

        r.publish(API(), 1, report, "updated", "github-actions[bot]")
        self.assertEqual(writes, [("issues/comments/2", "PATCH")])

    def test_stale_run_cannot_overwrite_new_head(self):
        report = self.make_report()

        class API:
            def api(self, path, data=None, method=None):
                if path != "pulls/1":
                    raise AssertionError("Stale report attempted to write")
                return {"head": {"sha": "c" * 40}, "base": {"sha": report["baseSha"]}}

        self.assertIsNone(r.publish(API(), 1, report, "old", "github-actions[bot]"))

    def test_manifest_change_without_lockfile_is_visible(self):
        class API:
            def snapshot(self, sha):
                return {"package-lock.json": npm()}, {"package.json": sha}

        report = r.analyze(
            API(),
            {"head": {"sha": "b" * 40}, "base": {"sha": "a" * 40}},
            lambda url: {"license": "MIT"},
        )
        self.assertIn("Manifest changed without", report["errors"][0])

    def test_privileged_workflow_uses_trusted_revision_and_is_optional(self):
        workflow = (ROOT.parent / "workflows/dependency-report.yml").read_text()
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("ref: ${{ github.workflow_sha }}", workflow)
        self.assertNotIn("ref: ${{ github.event.pull_request.head", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("vars.DEPENDENCY_REPORT_ENABLED != 'false'", workflow)


if __name__ == "__main__":
    unittest.main()
