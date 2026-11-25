"""Regression tests for the destructive and retryable phases of an upgrade."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import catalog_cutover as catalog


class CatalogRetryTests(unittest.TestCase):
    def setUp(self):
        self.cluster = Mock(namespace="test")
        self.state = {
            "data": {"pair": "web/engine", "phase": "verify", "history": "run:pin"}
        }
        self.cluster.owned.return_value = self.state
        self.cluster.phase.side_effect = lambda phase: self.state["data"].update(
            phase=phase
        )
        self.callbacks = [Mock() for _ in range(4)]

    def run_phases(self):
        return catalog.run_phases(self.cluster, "web/engine", *self.callbacks)

    def test_verification_failure_retries_only_verification(self):
        verify = self.callbacks[-1]
        verify.side_effect = RuntimeError("run pin differs")
        with self.assertRaisesRegex(RuntimeError, "stopped at verify"):
            self.run_phases()
        self.assertEqual(self.state["data"]["phase"], "verify")
        self.cluster.gate.assert_not_called()
        verify.side_effect = None
        self.run_phases()
        verify.assert_called_with("run:pin")
        for callback in self.callbacks[:-1]:
            callback.assert_not_called()
        self.assertEqual(self.state["data"]["phase"], "remove-helper")

    def test_schema_migration_requires_stopped_writers(self):
        self.state["data"]["phase"] = "web-schema"
        self.cluster.assert_stopped = Mock(side_effect=RuntimeError("writer restarted"))
        with self.assertRaisesRegex(RuntimeError, "stopped at web-schema"):
            self.run_phases()
        self.callbacks[0].assert_not_called()

    def test_mismatched_image_pair_does_not_change_state(self):
        self.state["data"]["pair"] = "different"
        with self.assertRaisesRegex(RuntimeError, "original image pair"):
            self.run_phases()
        self.cluster.phase.assert_not_called()

    def test_partial_manual_migration_stops_before_draining(self):
        self.cluster.owned.return_value = None
        self.cluster.sql.side_effect = ["t", "f"]
        with self.assertRaisesRegex(RuntimeError, "Partially migrated"):
            self.run_phases()
        self.cluster.drain.assert_not_called()

    def test_completed_upgrade_preserves_open_runs(self):
        self.state["data"]["phase"] = "complete"
        self.assertFalse(self.run_phases())
        self.cluster.drain.assert_not_called()


class InstallerTests(unittest.TestCase):
    def test_mixed_pair_is_rejected_before_cancellation(self):
        from unittest.mock import patch

        import install_catalog

        cluster = Mock()
        cluster.owned.return_value = None
        cluster.incoming_catalog.side_effect = [True, False]
        obj = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": catalog.WEB, "image": "fixture:web"}]
                    }
                }
            }
        }
        with (
            patch.object(install_catalog, "Cluster", return_value=cluster),
            patch.object(install_catalog, "manifest", return_value=obj),
            patch.object(install_catalog, "cutover") as begin,
        ):
            with self.assertRaisesRegex(RuntimeError, "only one side"):
                install_catalog.install("context", "test", ["unused"])
            begin.assert_not_called()

    def test_customer_managed_schema_is_checked_before_cancellation(self):
        from unittest.mock import patch

        import install_catalog

        cluster = Mock()
        cluster.owned.return_value = None
        cluster.incoming_catalog.return_value = True
        cluster.call.return_value = "false"
        obj = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": catalog.WEB, "image": "fixture:web"}]
                    }
                }
            }
        }
        with (
            patch.object(install_catalog, "Cluster", return_value=cluster),
            patch.object(install_catalog, "manifest", side_effect=[obj, obj, None]),
            patch.object(install_catalog, "cutover") as begin,
        ):
            with self.assertRaisesRegex(RuntimeError, "hooks are disabled"):
                install_catalog.install("context", "test", ["unused"])
            begin.assert_not_called()
