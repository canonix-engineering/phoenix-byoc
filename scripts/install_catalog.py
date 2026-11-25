#!/usr/bin/env python3
"""Wrap the standard BYOC sync/verify in the one-time catalog maintenance window."""

import json
import os
import subprocess
import sys
from pathlib import Path

from catalog_cutover import API, ENGINE, NAME, WEB, Cluster, cutover, verify_catalog

ROOT = Path(__file__).resolve().parents[1]


def manifest(kind, name):
    expr = f'select(.kind == "{kind}" and .metadata.name == "{name}")'
    output = subprocess.check_output(
        ["yq", "eval", "-N", "-o=json", "-I=0", expr, str(ROOT / ".rendered/all.yaml")],
        text=True,
    )
    return json.loads(output) if output.strip() else None


def install(context, namespace, finish):
    cluster = Cluster(context, namespace)

    def sync_all():
        subprocess.run(finish, check=True)

    def verify_install():
        subprocess.run(
            [
                str(ROOT / "scripts/verify.sh"),
                "--namespace",
                namespace,
                "--values",
                os.environ["PHOENIX_BYOC_VALUES_FILE"],
                "--secrets",
                os.environ["PHOENIX_BYOC_SECRETS_FILE"],
            ],
            check=True,
        )

    def normal():
        sync_all()
        verify_install()

    state = cluster.owned("configmap", NAME)
    if state and not cluster.get("deployment", WEB):
        raise RuntimeError("Missing Web deployment during recorded catalog upgrade")
    if not cluster.get("deployment", WEB) or (
        state and state["data"]["phase"] == "complete"
    ):
        normal()
        return
    web = manifest("Deployment", WEB)["spec"]["template"]
    engine_spec = manifest("Deployment", API)["spec"]["template"]["spec"]
    engine = engine_spec["containers"][0]["image"]
    image = next(c["image"] for c in web["spec"]["containers"] if c["name"] == WEB)
    if not state:
        web_new = cluster.incoming_catalog(web["spec"], image, WEB)
        engine_new = cluster.incoming_catalog(engine_spec, engine, ENGINE)
        if web_new != engine_new:
            raise RuntimeError(
                "Release contains only one side of the catalog migration"
            )
        if not web_new:
            normal()
            return
    bootstrap = manifest("Job", "postgresql-bootstrap-schema")
    if not bootstrap:
        if state:
            raise RuntimeError(
                "Restore the original hook settings to resume the catalog upgrade"
            )
        # Respect customer ownership. Never cancel a run on a customer-managed schema.
        present = cluster.call(
            "exec",
            "deployment/" + WEB,
            "--",
            "bin/rails",
            "runner",
            "puts ActiveRecord::Base.connection.column_exists?(:workflow_triggers,:definition_name)",
        )
        if present.splitlines()[-1] != "true":
            raise RuntimeError(
                "Database hooks are disabled; complete the customer-managed catalog migration first"
            )
        verify_catalog(cluster, "")
        normal()
        return

    def sync(release):
        subprocess.run(
            ["helmfile", "--kube-context", context, "-l", "name=" + release, "sync"],
            cwd=ROOT,
            check=True,
        )

    pg_image = manifest("Job", "postgresql-bootstrap")["spec"]["template"]["spec"][
        "containers"
    ][0]["image"]

    def verify(history):
        verify_install()
        verify_catalog(cluster, history)

    if not cutover(
        cluster,
        pg_image=pg_image,
        identity=image + "/" + engine,
        migrate_web=lambda: sync("postgresql-bootstrap"),
        deploy_engine=lambda: sync(ENGINE),
        deploy_web=sync_all,
        verify=verify,
    ):
        normal()


if __name__ == "__main__":
    install(sys.argv[1], sys.argv[2], sys.argv[3:])
