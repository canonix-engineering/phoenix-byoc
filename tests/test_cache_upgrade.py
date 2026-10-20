"""Exercise cutover recovery and data-retention boundaries without a cluster."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "cache_upgrade", Path(__file__).resolve().parents[1] / "scripts/upgrade-poc-cache.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def obj(name, **spec):
    return {"metadata": {"name": name, "uid": name + "-uid", "annotations": {
        "meta.helm.sh/release-name": "redis", "meta.helm.sh/release-namespace": "poc"}},
        "spec": spec}


class FakeCutover(MOD.Cutover):
    def __init__(self, path):
        super().__init__("poc", "test-context", Path("rendered.yaml"))
        self.state_path = path / "journal.json"
        self.objects = {
            ("namespace", "poc"): obj("poc"),
            ("statefulset", "redis"): obj("redis"),
            ("pvc", "data-redis-0"): obj("data-redis-0", volumeName="original-volume"),
            ("service", "redis-client"): obj("redis-client", clusterIP="10.0.0.1"),
            ("deployment", "phoenix-web"): obj("phoenix-web", replicas=2),
            ("hpa", None): {"items": []},
            ("replicasets", None): {"items": []},
            ("pods", None): {"items": []},
        }
        self.scales = []
        self.clients = "id=1 addr=127.0.0.1:6379 cmd=client"
        self.helm_calls = 0
        self.fail_helm = False

    def get(self, kind, name=None):
        if kind == "deployments":
            return {"items": [copy.deepcopy(self.objects[("deployment", "phoenix-web")])]}
        return copy.deepcopy(self.objects.get((kind, name)))

    def kubectl(self, *args):
        if args[0] == "scale":
            replicas = int(args[2].split("=")[1])
            self.scales.append(replicas)
            self.objects[("deployment", "phoenix-web")]["spec"]["replicas"] = replicas
        elif args[0] == "exec":
            return self.clients
        return ""

    def verify_cache(self):
        if not self.objects.get(("statefulset", "valkey")):
            raise RuntimeError("Valkey not ready")

    def run(self, *args):
        if args[0] == "yq":
            return json.dumps([
                {"kind": "Deployment", "metadata": {"name": "phoenix-web"}},
                {"kind": "StatefulSet", "metadata": {"name": "valkey"}},
                {"kind": "StatefulSet", "metadata": {"name": "postgresql-postgresql"}}])
        if args[0] == "helmfile":
            self.helm_calls += 1
            if self.fail_helm:
                raise RuntimeError("injected Helm failure")
            self.objects.pop(("statefulset", "redis"), None)
            self.objects[("statefulset", "valkey")] = obj("valkey")
            return ""
        raise AssertionError(args)


class CacheUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cutover = FakeCutover(Path(self.temp.name))
        self.mock = patch.object(MOD, "run", side_effect=self.cutover.run)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_cutover_preserves_volume_and_service_and_restores_replicas(self):
        original = copy.deepcopy(self.cutover.objects)
        self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2])
        for key in [("pvc", "data-redis-0"), ("service", "redis-client")]:
            self.assertEqual(self.cutover.objects[key], original[key])
        self.assertFalse(self.cutover.state_path.exists())

    def test_retry_never_resets_existing_valkey(self):
        self.cutover.execute()
        self.cutover.execute()
        self.assertEqual(self.cutover.helm_calls, 1)
        self.assertEqual(self.cutover.scales, [0, 2])

    def test_helm_failure_restores_replicas_and_retry_keeps_original_baseline(self):
        self.cutover.fail_helm = True
        with self.assertRaisesRegex(RuntimeError, "Helm failure"):
            self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2])
        self.assertTrue(self.cutover.state_path.exists())
        self.cutover.objects[("deployment", "phoenix-web")]["spec"]["replicas"] = 0
        self.cutover.fail_helm = False
        self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2, 0, 2])

    def test_delete_retention_policy_refused_before_scale(self):
        self.cutover.objects[("statefulset", "redis")]["spec"] = {
            "persistentVolumeClaimRetentionPolicy": {"whenDeleted": "Delete"}}
        with self.assertRaisesRegex(RuntimeError, "retention"):
            self.cutover.execute()
        self.assertEqual(self.cutover.scales, [])

    def test_remaining_remote_writer_aborts_and_restores(self):
        self.cutover.clients = "id=2 addr=10.0.0.9:1234 cmd=xadd"
        with self.assertRaisesRegex(RuntimeError, "remote clients"):
            self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2])
        self.assertEqual(self.cutover.helm_calls, 0)

    def test_live_sandbox_aborts_and_restores(self):
        self.cutover.objects[("pods", None)] = {"items": [
            {"metadata": {"name": "active-sandbox"}, "status": {"phase": "Running"}}]}
        with self.assertRaisesRegex(RuntimeError, "active-sandbox"):
            self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2])
        self.assertEqual(self.cutover.helm_calls, 0)

    def test_retained_redis_volume_alone_requires_recovery(self):
        self.cutover.objects.pop(("statefulset", "redis"))
        with self.assertRaisesRegex(RuntimeError, "Retained Redis PVC"):
            self.cutover.execute()
        self.assertEqual(self.cutover.helm_calls, 0)

    def test_bundled_postgres_is_left_running(self):
        self.cutover.objects[("pods", None)] = {"items": [{"metadata": {
            "name": "postgresql-postgresql-0", "ownerReferences": [{
                "kind": "StatefulSet", "name": "postgresql-postgresql", "uid": "pg-uid"}]},
            "status": {"phase": "Running"}}]}
        self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2])
        self.assertEqual(self.cutover.helm_calls, 1)

    def test_hpa_refused_before_scale(self):
        self.cutover.objects[("hpa", None)] = {"items": [obj("autoscaler")]}
        with self.assertRaisesRegex(RuntimeError, "autoscaling"):
            self.cutover.execute()
        self.assertEqual(self.cutover.scales, [])

    def test_existing_valkey_volume_is_not_silently_reused(self):
        self.cutover.objects[("pvc", "data-valkey-0")] = obj("data-valkey-0")
        with self.assertRaisesRegex(RuntimeError, "Valkey volume already exists"):
            self.cutover.execute()
        self.assertEqual(self.cutover.helm_calls, 0)

    def test_replaced_namespace_refused_on_retry(self):
        self.cutover.fail_helm = True
        with self.assertRaises(RuntimeError):
            self.cutover.execute()
        self.cutover.objects[("namespace", "poc")]["metadata"]["uid"] = "other-namespace"
        with self.assertRaisesRegex(RuntimeError, "Namespace identity"):
            self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2])

    def test_retry_after_switch_does_not_require_legacy_statefulset(self):
        with patch.object(self.cutover, "verify_cache", side_effect=RuntimeError("probe failed")):
            with self.assertRaisesRegex(RuntimeError, "probe failed"):
                self.cutover.execute()
        self.assertIsNone(self.cutover.get("statefulset", "redis"))
        self.assertTrue(self.cutover.state_path.exists())
        self.cutover.execute()
        self.assertEqual(self.cutover.scales, [0, 2, 0, 2])
        self.assertFalse(self.cutover.state_path.exists())


if __name__ == "__main__":
    unittest.main()
