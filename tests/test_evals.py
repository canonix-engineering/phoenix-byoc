import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAPS = ("maxConcurrentSandboxTasksEval", "maxConcurrentInProcessTasksEval")
SCOPES = ["workflow:evals:read", "workflow:evals:write"]


def config():
    return {
        "services": {"workflowEngine": {"operator": dict.fromkeys(CAPS, 5)}},
        "secrets": {"application": {
            "workflowEngineToken": "test-only-token",
            "internalServiceTokens": json.dumps([{
                "identity": "phoenix-gateway", "token": "test-only-token",
                "scopes": ["workflow:context:read", *SCOPES],
                "tenant_ids": ["customer"], "app_slugs": ["app"],
            }]),
        }},
    }


@unittest.skipUnless(shutil.which("yq"), "requires Mike Farah yq")
class EvalDefaultsTests(unittest.TestCase):
    def test_fresh_install_defaults_and_example_enable_both_queues(self):
        for path in ("defaults/values.yaml", "examples/values.yaml"):
            with self.subTest(path=path):
                doc = json.loads(subprocess.check_output(
                    ["yq", "-o=json", ".", str(ROOT / path)], text=True))
                operator = doc["services"]["workflowEngine"]["operator"]
                for key in CAPS:
                    self.assertGreater(operator[key], 0, f"{path}: {key} disables eval execution")


class EvalConfigTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("eval_config", ROOT / "scripts/eval-config.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_enabled_requires_permissions_on_actual_gateway_credential(self):
        doc = config()
        self.mod.validate(doc)
        entries = json.loads(doc["secrets"]["application"]["internalServiceTokens"])
        entries[0]["scopes"] = ["workflow:context:read"]
        entries.append({"identity": "other", "token": "other-token", "scopes": SCOPES})
        doc["secrets"]["application"]["internalServiceTokens"] = json.dumps(entries)
        with self.assertRaisesRegex(ValueError, "workflow:evals:read"):
            self.mod.validate(doc)

    def test_disabled_is_explicit_and_partial_or_invalid_capacity_is_rejected(self):
        for capacities, valid in [((0, 0), True), ((2, 8), True), ((0, 5), False),
                                  ((5, 0), False), ((-1, 5), False), ((True, 5), False),
                                  (("5", 5), False)]:
            with self.subTest(capacities=capacities):
                doc = config()
                doc["services"]["workflowEngine"]["operator"] = dict(zip(CAPS, capacities))
                if valid:
                    self.mod.validate(doc)
                else:
                    with self.assertRaises(ValueError):
                        self.mod.validate(doc)

    def test_empty_override_uses_template_but_malformed_or_missing_credential_fails(self):
        doc = config()
        doc["secrets"]["application"]["internalServiceTokens"] = ""
        self.mod.validate(doc)
        for invalid in ("secret-invalid-json", "{}", "[]", "[null]",
                        json.dumps([{"identity": "gateway", "token": "wrong", "scopes": SCOPES}])):
            with self.subTest(invalid=invalid):
                doc["secrets"]["application"]["internalServiceTokens"] = invalid
                with self.assertRaises(ValueError) as error:
                    self.mod.validate(doc)
                self.assertNotIn("secret-invalid-json", str(error.exception))

    def test_duplicate_credential_is_rejected_instead_of_changing_wrong_identity(self):
        doc = config()
        entries = json.loads(doc["secrets"]["application"]["internalServiceTokens"])
        entries.append(copy.deepcopy(entries[0]))
        doc["secrets"]["application"]["internalServiceTokens"] = json.dumps(entries)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.mod.validate(doc)

    def test_whitespace_identity_cannot_authenticate(self):
        doc = config()
        entries = json.loads(doc["secrets"]["application"]["internalServiceTokens"])
        entries[0]["identity"] = " \t"
        doc["secrets"]["application"]["internalServiceTokens"] = json.dumps(entries)
        with self.assertRaises(ValueError):
            self.mod.validate(doc)

    def test_blank_gateway_credential_is_rejected_even_with_template_fallback(self):
        doc = config()
        doc["secrets"]["application"]["workflowEngineToken"] = " \t"
        doc["secrets"]["application"]["internalServiceTokens"] = ""
        with self.assertRaises(ValueError):
            self.mod.validate(doc)


@unittest.skipUnless(shutil.which("yq"), "requires Mike Farah yq")
class EvalUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.values = self.directory / "values.yaml"
        self.secrets = self.directory / "values.secrets.yaml"
        doc = config()
        doc["services"]["workflowEngine"]["operator"] = dict(zip(CAPS, (0, 9)))
        self.values.write_text(json.dumps({"services": doc["services"], "customer": "preserve"}))
        entries = json.loads(doc["secrets"]["application"]["internalServiceTokens"])
        entries[0]["scopes"] = ["workflow:context:read"]
        entries.append({"identity": "other", "token": "other-token", "scopes": ["workflow:context:read"]})
        doc["secrets"]["application"]["internalServiceTokens"] = json.dumps(entries)
        self.secrets.write_text(json.dumps({"secrets": doc["secrets"]}))
        self.before = doc

    def run_upgrade(self):
        return subprocess.run(["python3", str(ROOT / "scripts/eval-config.py"), "enable",
                               "--values", str(self.values), "--secrets", str(self.secrets)],
                              text=True, capture_output=True)

    def read_yaml(self, path):
        return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)], text=True))

    def test_upgrade_preserves_custom_limits_secrets_and_restrictions_and_is_repeatable(self):
        result = self.run_upgrade()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("test-only-token", result.stdout + result.stderr)
        values = self.read_yaml(self.values)
        self.assertEqual(values["services"]["workflowEngine"]["operator"], dict(zip(CAPS, (5, 9))))
        self.assertEqual(values["customer"], "preserve")
        actual = self.read_yaml(self.secrets)
        expected = copy.deepcopy(self.before["secrets"])
        entries = json.loads(expected["application"]["internalServiceTokens"])
        entries[0]["scopes"].extend(SCOPES)
        expected["application"]["internalServiceTokens"] = json.dumps(entries)
        self.assertEqual(actual["secrets"], expected)
        self.assertEqual(self.secrets.stat().st_mode & 0o777, 0o600)
        before_retry = (self.values.read_bytes(), self.secrets.read_bytes())
        self.assertEqual(self.run_upgrade().returncode, 0)
        self.assertEqual((self.values.read_bytes(), self.secrets.read_bytes()), before_retry)

    def test_bad_mapping_does_not_partially_modify_files_or_print_secrets(self):
        doc = self.read_yaml(self.secrets)
        doc["secrets"]["application"]["internalServiceTokens"] = "test-only-invalid-secret"
        self.secrets.write_text(json.dumps(doc))
        before = (self.values.read_bytes(), self.secrets.read_bytes())
        result = self.run_upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("test-only-invalid-secret", result.stdout + result.stderr)
        self.assertEqual((self.values.read_bytes(), self.secrets.read_bytes()), before)

    def test_tracked_secrets_are_refused(self):
        subprocess.run(["git", "init", "-q", str(self.directory)], check=True)
        subprocess.run(["git", "-C", str(self.directory), "add", "values.secrets.yaml"], check=True)
        result = self.run_upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked", result.stderr)

    def test_capacity_override_in_secrets_is_refused_before_any_file_changes(self):
        doc = self.read_yaml(self.secrets)
        doc["services"] = {"workflowEngine": {"operator": dict.fromkeys(CAPS, 0)}}
        self.secrets.write_text(json.dumps(doc))
        before = (self.values.read_bytes(), self.secrets.read_bytes())
        result = self.run_upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("capacity overrides", result.stderr)
        self.assertEqual((self.values.read_bytes(), self.secrets.read_bytes()), before)

    def test_blank_token_is_refused(self):
        doc = self.read_yaml(self.secrets)
        doc["secrets"]["application"]["workflowEngineToken"] = " \t"
        doc["secrets"]["application"]["internalServiceTokens"] = ""
        self.secrets.write_text(json.dumps(doc))
        self.assertNotEqual(self.run_upgrade().returncode, 0)


if __name__ == "__main__":
    unittest.main()
