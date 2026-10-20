#!/usr/bin/env python3
"""Explicit PoC cutover to a separate Valkey volume; never copy or flush Redis."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                            timeout=900)
    if result.returncode:
        # Helm output can include rendered secrets. Do not echo captured output.
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}); "
                           "check workload events and Helm status before retrying")
    return result.stdout.strip()


class Cutover:
    def __init__(self, namespace, context, rendered):
        self.namespace, self.context = namespace, context
        self.rendered = rendered
        key = hashlib.sha256(f"{context}/{namespace}".encode()).hexdigest()[:16]
        self.state_path = ROOT / ".tmp" / f"cache-upgrade-{key}.json"

    def kubectl(self, *args):
        return run("kubectl", "--context", self.context, "-n", self.namespace,
                   *args)

    def get(self, kind, name=None):
        args = ["get", kind]
        if name:
            args += [name, "--ignore-not-found"]
        result = self.kubectl(*args, "-o", "json")
        return json.loads(result) if result else None

    def owned(self, obj, release):
        annotations = obj["metadata"].get("annotations", {})
        return (annotations.get("meta.helm.sh/release-name") == release and
                annotations.get("meta.helm.sh/release-namespace") == self.namespace)

    def restore(self, state):
        failures = []
        for name, saved in state["deployments"].items():
            try:
                live = self.get("deployment", name)
                if not live or live["metadata"]["uid"] != saved["uid"]:
                    raise RuntimeError("deployment identity changed")
                self.kubectl("scale", f"deployment/{name}",
                             f"--replicas={saved['replicas']}")
            except (RuntimeError, subprocess.TimeoutExpired):
                failures.append(name)
        if failures:
            raise RuntimeError("Could not restore replicas for " + ", ".join(failures)
                               + f"; saved replica counts: {self.state_path}")

    def validate_pvc(self, state):
        pvc = self.get("pvc", "data-redis-0")
        if not pvc or pvc["metadata"]["uid"] != state["pvc_uid"]:
            raise RuntimeError("Original Redis PVC identity changed; stop the upgrade")
        if pvc["spec"].get("volumeName") != state["volume"]:
            raise RuntimeError("Original Redis volume binding changed; stop the upgrade")

    def verify_cache(self):
        self.kubectl("rollout", "status", "statefulset/valkey", "--timeout=300s")
        pong = self.kubectl("exec", "valkey-0", "--", "redis-cli", "-h",
                            "redis-client", "PING")
        info = self.kubectl("exec", "valkey-0", "--", "redis-cli", "-h",
                            "redis-client", "INFO", "server")
        if pong != "PONG" or "valkey_version:" not in info:
            raise RuntimeError("redis-client does not reach a healthy Valkey server")

    def execute(self):
        # Extract only workload descriptions; never load Secrets into the journal.
        documents = json.loads(run("yq", "eval-all", "-o=json", "[select("
            '.kind == "Deployment" or .kind == "StatefulSet"'
            ")]", str(self.rendered)))
        documents = [d for d in documents
                     if d["metadata"].get("namespace", self.namespace) == self.namespace]
        if not any(d["kind"] == "StatefulSet" and d["metadata"]["name"] == "valkey"
                   for d in documents):
            raise RuntimeError("--discard-redis-state requires bundled Valkey")
        namespace = self.get("namespace", self.namespace)
        if not namespace:
            print("Namespace does not exist yet; continuing normal installation.")
            return
        namespace_uid = namespace["metadata"]["uid"]
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else None
        if state and state["namespace_uid"] != namespace_uid:
            raise RuntimeError("Namespace identity differs from the saved cutover")
        legacy = self.get("statefulset", "redis")
        valkey = self.get("statefulset", "valkey")
        if not legacy and not state:
            if valkey:
                print("Valkey already installed; no data reset performed.")
                return
            if self.get("pvc", "data-redis-0"):
                raise RuntimeError("Retained Redis PVC without a running Redis server; "
                                   "follow docs/redis.md for recovery")
            print("No legacy Redis installation; continuing normal installation.")
            return
        if legacy:
            if not self.owned(legacy, "redis"):
                raise RuntimeError("Legacy Redis does not belong to this BYOC Helm release")
            policy = legacy["spec"].get("persistentVolumeClaimRetentionPolicy", {})
            if "Delete" in policy.values():
                raise RuntimeError("Redis PVC retention must be Retain before cutover")
        if valkey and not state:
            raise RuntimeError("Both Redis and Valkey exist; reconcile the partial migration first")
        if not state and self.get("pvc", "data-valkey-0"):
            raise RuntimeError("A Valkey volume already exists; reconcile it before starting a fresh cutover")
        pvc = self.get("pvc", "data-redis-0")
        if not pvc or pvc["metadata"].get("ownerReferences"):
            raise RuntimeError("Expected a retained Redis PVC without deletion owner references")
        service = self.get("service", "redis-client")
        if not service or not self.owned(service, "redis"):
            raise RuntimeError("redis-client does not belong to this BYOC Helm release")
        deployments = self.get("deployments")["items"]
        expected_names = {d["metadata"]["name"] for d in documents if d["kind"] == "Deployment"}
        dependency_names = {d["metadata"]["name"] for d in documents
                            if d["kind"] == "StatefulSet"} | {"redis"}
        if any(d["metadata"]["name"] not in expected_names for d in deployments):
            raise RuntimeError("PoC shortcut requires a namespace with only the rendered "
                               "Phoenix Deployments; use the coordinated migration otherwise")
        if self.get("hpa")["items"]:
            raise RuntimeError("Suspend autoscaling before using the PoC shortcut")
        if not state:
            state = {"namespace_uid": namespace_uid,
                     "context": self.context, "namespace": self.namespace,
                     "pvc_uid": pvc["metadata"]["uid"], "volume": pvc["spec"].get("volumeName"),
                     "service_uid": service["metadata"]["uid"],
                     "service_ip": service["spec"]["clusterIP"],
                     "deployments": {d["metadata"]["name"]: {
                         "uid": d["metadata"]["uid"], "replicas": d["spec"].get("replicas", 1)
                     } for d in deployments}}
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2) + "\n")
            temporary.replace(self.state_path)
        self.validate_pvc(state)
        print(f"PoC Redis cutover: context={self.context}, namespace={self.namespace}")
        print("Redis state will NOT be copied. The original PVC will be retained.")
        try:
            for name in state["deployments"]:
                self.kubectl("scale", f"deployment/{name}", "--replicas=0")
            # Wait for every application Pod, including terminating Pods, to exit.
            replica_sets = self.get("replicasets")["items"]
            deployment_uids = {d["uid"] for d in state["deployments"].values()}
            rs_uids = {r["metadata"]["uid"] for r in replica_sets if any(
                o["uid"] in deployment_uids for o in r["metadata"].get("ownerReferences", []))}
            deadline = time.monotonic() + 300
            while True:
                pods = self.get("pods")["items"]
                pending = [p for p in pods if any(o["uid"] in rs_uids for o in
                           p["metadata"].get("ownerReferences", []))]
                if not pending:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("Application Pods did not stop within 300 seconds")
                time.sleep(2)
            # Catch live sandboxes, jobs and other event producers outside Deployments.
            for pod in pods:
                if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
                    continue
                owners = pod["metadata"].get("ownerReferences", [])
                if not any(o["kind"] == "StatefulSet" and o["name"] in dependency_names
                           for o in owners):
                    raise RuntimeError("Active non-Deployment workload remains: " +
                                       pod["metadata"]["name"] + "; finish workflows/jobs first")
            if legacy:
                clients = self.kubectl("exec", "redis-0", "--", "redis-cli", "CLIENT", "LIST")
                for client in clients.splitlines():
                    fields = dict(x.split("=", 1) for x in client.split() if "=" in x)
                    if not fields.get("addr", "").startswith(("127.0.0.1:", "[::1]:")):
                        raise RuntimeError("Redis still has remote clients; stop them before cutover")
            self.validate_pvc(state)
            run("helmfile", "--kube-context", self.context, "--quiet", "-l", "name=redis", "sync")
            self.verify_cache()
            self.validate_pvc(state)
            current_service = self.get("service", "redis-client")
            if (current_service["metadata"]["uid"] != state["service_uid"] or
                    current_service["spec"]["clusterIP"] != state["service_ip"]):
                raise RuntimeError("redis-client identity changed unexpectedly")
        finally:
            # Also restore after Helm failure or Ctrl-C. A failed cache may leave
            # applications unready, but retry never records zero as their baseline.
            self.restore(state)
        self.state_path.unlink()
        print("Valkey is healthy; old Redis volume retained; application replicas restored.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--rendered", type=Path, required=True)
    parser.add_argument("--discard-redis-state", action="store_true", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ["KUBECTL_REMOTE_COMMAND_WEBSOCKETS"] = "false"
    os.environ["PHOENIX_BYOC_NAMESPACE"] = args.namespace
    os.environ.setdefault("HELMFILE_CACHE_HOME", str(ROOT / ".tmp" / "helmfile-cache"))
    cutover = Cutover(args.namespace, args.context, args.rendered)
    cutover.state_path.parent.mkdir(parents=True, exist_ok=True)
    def interrupted(_signum, _frame):
        raise RuntimeError("Cutover interrupted; retry the same installation command")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with open(str(cutover.state_path) + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            cutover.execute()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Keep this directory and retry the same command after fixing the cause. "
              "Do not delete PVCs or roll back Redis over new Valkey writes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
