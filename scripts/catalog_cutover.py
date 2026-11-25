"""One-time maintenance window for installing the engine-owned workflow catalog."""

import json
import subprocess
import time
import uuid
from contextlib import contextmanager

NAME = "phoenix-catalog-cutover"
WEB = "phoenix-web"
ENGINE = "phoenix-workflow-engine"
API = ENGINE + "-api"
WEB_WRITERS = [WEB, WEB + "-worker", WEB + "-conversation-stream-reader"]
ENGINE_WRITERS = [API, ENGINE + "-operator", ENGINE + "-orchestrator"]
OPEN = "select id from workflow_runs where status in ('pending','queued','running','waiting_hitl')"
MIGRATION = "20261124100000"


class Cluster:
    def __init__(self, context, namespace):
        self.cmd = ["kubectl", "--context", context, "-n", namespace]
        self.namespace = namespace

    def call(self, *args, data=None):
        lock = getattr(self, "lock_process", None)
        if lock is not None and lock.poll() is not None:
            raise RuntimeError("Lost the catalog maintenance lock")
        return subprocess.run(
            self.cmd + list(args),
            input=data,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()

    def get(self, kind, name):
        raw = self.call("get", kind, name, "--ignore-not-found", "-o", "json")
        return json.loads(raw) if raw else None

    def create(self, kind, name, spec):
        manifest = {
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": {"app.kubernetes.io/managed-by": NAME},
            },
            **spec,
        }
        self.call("create", "-f", "-", data=json.dumps(manifest))

    def owned(self, kind, name):
        obj = self.get(kind, name)
        if (
            obj
            and obj["metadata"].get("labels", {}).get("app.kubernetes.io/managed-by")
            != NAME
        ):
            raise RuntimeError(f"{kind}/{name} already exists with a different owner")
        return obj

    def phase(self, value):
        data = {"phase": value}
        if value == "web-schema":
            data["drained"] = None
        self.call(
            "patch", "configmap", NAME, "--type=merge", "-p", json.dumps({"data": data})
        )
        print("Workflow catalog upgrade:", value, flush=True)

    def exec(self, container, *args, data=None):
        return self.call("exec", "-i", NAME, "-c", container, "--", *args, data=data)

    def sql(self, db, sql):
        conn = {"web": "DATABASE_URL", "engine": "INTERNAL_DATABASE_URL"}[db]
        return self.exec(
            "postgres",
            "sh",
            "-ec",
            f'exec psql -XqAt -v ON_ERROR_STOP=1 "${conn}"',
            data=sql,
        )

    def scale_down(self, names):
        for name in names:
            deployment = self.get("deployment", name)
            if not deployment:
                continue
            selector = ",".join(
                f"{k}={v}"
                for k, v in deployment["spec"]["selector"]["matchLabels"].items()
            )
            self.call("scale", "deployment/" + name, "--replicas=0")
            deadline = time.monotonic() + 300
            while self.call(
                "get",
                "pods",
                "-l",
                selector,
                "--field-selector",
                "status.phase!=Succeeded,status.phase!=Failed",
                "-o",
                "name",
            ):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out stopping " + name)
                time.sleep(2)

    def assert_stopped(self):
        for name in WEB_WRITERS + ENGINE_WRITERS:
            deployment = self.get("deployment", name)
            if deployment and (
                deployment["spec"]["replicas"]
                or deployment.get("status", {}).get("replicas", 0)
            ):
                raise RuntimeError("Writer restarted during maintenance: " + name)
        if self.sql("web", OPEN):
            raise RuntimeError("Open runs appeared during maintenance")

    def preflight_writers(self):
        targets = set(WEB_WRITERS + ENGINE_WRITERS)
        hpas = json.loads(self.call("get", "horizontalpodautoscalers", "-o", "json"))
        for hpa in hpas["items"]:
            target = hpa["spec"]["scaleTargetRef"]
            if target["kind"] == "Deployment" and target["name"] in targets:
                raise RuntimeError(
                    "An autoscaler controls a catalog writer: " + target["name"]
                )

    def gate(self, service, closed):
        self.call(
            "patch",
            "service",
            service,
            "--type=merge",
            "-p",
            json.dumps(
                {
                    "spec": {
                        "selector": {
                            "phoenix-catalog-maintenance": "closed" if closed else None
                        }
                    }
                }
            ),
        )

    def incoming_catalog(self, template, image, service):
        # Neither legacy executable exposes a capability flag. Inspect the target
        # without attaching a service account, service credentials or volumes.
        if service == WEB:
            test = f"test -r /rails/bin/rails; if test -f /rails/db/migrate/{MIGRATION}_record_workflow_definition_on_triggers.rb; then echo catalog; else echo legacy; fi"
        elif service == ENGINE:
            test = """test -r /usr/local/bin/migrate
            if grep -aFq 'CREATE TABLE IF NOT EXISTS workflow_definition_identities' /usr/local/bin/migrate; then
              echo catalog
            else
              test "$?" = 1
              echo legacy
            fi"""
        else:
            raise ValueError("Unknown catalog participant")
        name = NAME + "-image-" + uuid.uuid4().hex[:10]
        self.create(
            "Pod",
            name,
            {
                "spec": {
                    **self.placement(template),
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "probe",
                            "image": image,
                            "command": ["sh", "-ec", test],
                        }
                    ],
                }
            },
        )
        try:
            self.call(
                "wait",
                "--for=jsonpath={.status.phase}=Succeeded",
                "pod/" + name,
                "--timeout=300s",
            )
            result = self.call("logs", name)
            if result not in ("catalog", "legacy"):
                raise RuntimeError("Unexpected result inspecting " + service + " image")
            return result == "catalog"
        finally:
            self.call("delete", "pod", name, "--wait=false")

    @staticmethod
    def placement(template):
        return {
            k: template[k]
            for k in ("nodeSelector", "affinity", "tolerations", "imagePullSecrets")
            if k in template
        }

    @staticmethod
    def pg_container(image):
        return {
            "name": "postgres",
            "image": image,
            "env": [
                {
                    "name": key,
                    "valueFrom": {"secretKeyRef": {"name": ENGINE, "key": key}},
                }
                for key in ("DATABASE_URL", "INTERNAL_DATABASE_URL")
            ],
        }

    def helper(self, web, pg_image):
        if not self.owned("pod", NAME):
            template = web["spec"]["template"]["spec"]
            app = next(c for c in template["containers"] if c["name"] == WEB)
            ruby = {key: app[key] for key in ("image", "imagePullPolicy") if key in app}
            ruby["env"] = [
                {
                    "name": "PHOENIX_WORKFLOW_ENGINE_TOKEN",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": ENGINE,
                            "key": "PHOENIX_WORKFLOW_ENGINE_TOKEN",
                        }
                    },
                }
            ]
            postgres = self.pg_container(pg_image)
            self.create(
                "Pod",
                NAME,
                {
                    "spec": {
                        **self.placement(template),
                        "automountServiceAccountToken": False,
                        "restartPolicy": "Always",
                        "containers": [
                            dict(ruby, name="rails", command=["sleep", "infinity"]),
                            dict(postgres, command=["sleep", "infinity"]),
                        ],
                    }
                },
            )
        self.call("wait", "--for=condition=Ready", "pod/" + NAME, "--timeout=300s")

    @contextmanager
    def lock(self):
        # The kernel releases flock on EOF/disconnect. A crashed installer need
        # not steal a durable lock from a potentially live second installer.
        with subprocess.Popen(
            self.cmd
            + [
                "exec",
                "-i",
                NAME,
                "-c",
                "postgres",
                "--",
                "flock",
                "-n",
                "/tmp/.catalog-upgrade.lock",
                "sh",
                "-ec",
                "echo locked; cat >/dev/null",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        ) as lock:
            if lock.stdout.readline().strip() != "locked":
                raise RuntimeError(
                    "Another catalog upgrade holds the maintenance pod lock"
                )
            self.lock_process = lock
            try:
                yield
            finally:
                self.lock_process = None
                lock.stdin.close()

    def check_external(self, runs):
        if not runs:
            return
        ids = ",".join("'" + str(uuid.UUID(run)) + "'" for run in runs)
        leases = self.sql("engine", "select to_regclass('dev_box_leases') is not null")
        if leases == "t" and self.sql(
            "engine",
            f"select 1 from dev_box_leases where workflow_run_id in ({ids}) limit 1",
        ):
            raise RuntimeError(
                "Cancelled runs still own external machines; waiting for provider cleanup"
            )
        sandboxes = self.sql(
            "web",
            f"""
            select distinct a.execution_context_json #>> '{{runtime_execution,opensandbox,sandbox_id}}'
            from workflow_step_attempts a join workflow_run_steps s on s.id=a.workflow_run_step_id
            where s.workflow_run_id in ({ids}) and a.execution_context_json #>>
              '{{runtime_execution,opensandbox,sandbox_id}}' is not null""",
        )
        for sandbox in sandboxes.splitlines():
            if self.get(
                "batchsandboxes.sandbox.opensandbox.io", str(uuid.UUID(sandbox))
            ):
                raise RuntimeError("Cancelled sandbox still exists: " + sandbox)

    def drain(self):
        self.gate(WEB, True)
        self.gate(API, True)
        self.scale_down(WEB_WRITERS)
        journal = self.owned("configmap", NAME)["data"]
        cancelled = set(journal.get("drained", "").splitlines())
        deadline = time.monotonic() + 300
        while True:
            runs = self.sql("web", OPEN).splitlines()
            if not runs:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Old Engine did not drain all open runs")
            cancelled.update(str(uuid.UUID(run)) for run in runs)
            # Persist the IDs before cancellation so a retry can still check
            # external executions after their runs have become terminal.
            self.call(
                "patch",
                "configmap",
                NAME,
                "--type=merge",
                "--patch-file=/dev/stdin",
                data=json.dumps({"data": {"drained": "\n".join(sorted(cancelled))}}),
            )
            api = self.get("deployment", API)
            if api["spec"]["replicas"] == 0:
                self.call("scale", "deployment/" + API, "--replicas=1")
                self.call("rollout", "status", "deployment/" + API, "--timeout=300s")
            selector = api["spec"]["selector"]["matchLabels"]
            pods = json.loads(
                self.call(
                    "get",
                    "pod",
                    "-l",
                    ",".join(k + "=" + v for k, v in selector.items()),
                    "-o",
                    "json",
                )
            )
            pod = next(
                p
                for p in pods["items"]
                if p["status"].get("podIP")
                and not p["metadata"].get("deletionTimestamp")
            )
            port = next(
                p["containerPort"]
                for c in pod["spec"]["containers"]
                for p in c.get("ports", [])
                if p["name"] == "http"
            )
            ip = pod["status"]["podIP"]
            url = f"http://[{ip}]:{port}" if ":" in ip else f"http://{ip}:{port}"
            self.exec(
                "rails",
                "ruby",
                "-rnet/http",
                "-e",
                """
endpoint = URI(ARGV.fetch(0))
http = Net::HTTP.new(endpoint.hostname, endpoint.port, nil)
http.open_timeout = 5
http.read_timeout = 30
http.start do |connection|
  STDIN.each_line do |line|
    id = line.chomp
    request = Net::HTTP::Post.new("/workflow-runs/#{id}/cancel")
    request["Authorization"] = "Bearer " + ENV.fetch("PHOENIX_WORKFLOW_ENGINE_TOKEN")
    response = connection.request(request)
    # A concurrent terminal transition is rechecked by the outer database query.
    unless response.is_a?(Net::HTTPSuccess) || response.code == "409"
      abort "Cancellation of #{id} returned HTTP #{response.code}"
    end
  end
end
""",
                url,
                data="\n".join(runs) + "\n",
            )
        while True:
            try:
                self.check_external(cancelled)
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(5)
        self.scale_down(ENGINE_WRITERS)
        if self.sql("web", OPEN):
            raise RuntimeError(
                "A run raced the drain; resume cancellation on the old Engine"
            )


def cutover(
    cluster, *, pg_image, identity, migrate_web, deploy_engine, deploy_web, verify
):
    """Resume the exact release pair. Callers serialize deployments in the namespace."""
    state = cluster.owned("configmap", NAME)
    if state and state["data"]["phase"] == "complete":
        return False
    web = cluster.get("deployment", WEB)
    if not web:
        if state:
            raise RuntimeError(
                "Missing Web deployment during an unfinished catalog upgrade"
            )
        return False
    if state and state["data"]["phase"] == "remove-helper":
        if cluster.owned("pod", NAME):
            cluster.call("delete", "pod", NAME)
        cluster.phase("complete")
        return True
    if not state:
        cluster.preflight_writers()
    cluster.helper(web, pg_image)
    with cluster.lock():
        result = run_phases(
            cluster, identity, migrate_web, deploy_engine, deploy_web, verify
        )
    cluster.call("delete", "pod", NAME, "--ignore-not-found")
    if result:
        cluster.phase("complete")
    return result


def run_phases(cluster, identity, migrate_web, deploy_engine, deploy_web, verify):
    state = cluster.owned("configmap", NAME)
    if state and state["data"]["phase"] == "complete":
        return False
    if not state:
        migrated = cluster.sql(
            "web",
            f"select exists(select 1 from schema_migrations where version='{MIGRATION}')",
        )
        engine = cluster.sql(
            "engine", "select to_regclass('workflow_definition_identities') is not null"
        )
        if (migrated, engine) == ("t", "t"):
            # A previously completed/manual cutover must never drain again.
            cluster.create("ConfigMap", NAME, {"data": {"phase": "complete"}})
            return False
        if (migrated, engine) != ("f", "f"):
            raise RuntimeError(
                "Partially migrated installation has no catalog upgrade checkpoint"
            )
        pins = cluster.sql(
            "engine", "select to_regclass('workflow_run_definition_refs') is not null"
        )
        history = (
            cluster.sql(
                "engine",
                "select workflow_run_id || ':' || btrim(content_hash) from workflow_run_definition_refs order by workflow_run_id desc limit 1",
            )
            if pins == "t"
            else ""
        )
        cluster.create(
            "ConfigMap",
            NAME,
            {"data": {"phase": "drain", "pair": identity, "history": history}},
        )
        state = cluster.owned("configmap", NAME)
    if state["data"]["pair"] != identity:
        raise RuntimeError(
            "Resume the in-progress catalog upgrade with its original image pair"
        )
    phase = state["data"]["phase"]

    def schema():
        cluster.assert_stopped()
        migrate_web()
        if (
            cluster.sql(
                "web",
                f"select exists(select 1 from schema_migrations where version='{MIGRATION}')",
            )
            != "t"
        ):
            raise RuntimeError(
                "Incoming Web release did not apply the catalog migration"
            )

    def engine():
        deploy_engine()
        if (
            cluster.sql(
                "engine",
                "select to_regclass('workflow_definition_identities') is not null",
            )
            != "t"
        ):
            raise RuntimeError(
                "Incoming Engine release did not initialize definition identities"
            )
        for workload in ENGINE_WRITERS:
            cluster.call(
                "rollout", "status", "deployment/" + workload, "--timeout=600s"
            )
        cluster.gate(API, False)

    def check():
        verify(state["data"]["history"])
        cluster.gate(WEB, False)

    phases = [
        ("drain", cluster.drain),
        ("web-schema", schema),
        ("engine", engine),
        ("web", deploy_web),
        ("verify", check),
    ]
    names = [name for name, task in phases] + ["remove-helper"]
    for i in range(names.index(phase), len(phases)):
        try:
            phases[i][1]()
        except Exception as error:
            raise RuntimeError(
                f"Catalog upgrade stopped at {names[i]}. Retry the same release in {cluster.namespace}."
            ) from error
        cluster.phase(names[i + 1])
    return True


def verify_catalog(cluster, history):
    for release in (WEB, ENGINE):
        cluster.call(
            "rollout",
            "status",
            "deployment",
            "-l",
            f"app.kubernetes.io/instance={release}",
            "--timeout=600s",
        )
    cluster.call(
        "exec",
        "deployment/" + WEB,
        "--",
        "env",
        "CUTOVER_HISTORY=" + history,
        "bin/rails",
        "runner",
        """
client = WorkflowEngine::Client.new
abort "SDLC missing in Engine" unless client.workflow_definitions.any? { |d| d["name"] == "sdlc" }
id, hash = ENV.fetch("CUTOVER_HISTORY").split(":", 2)
if id && client.workflow_run_definition(id).fetch("content_hash").delete_prefix("xxh3:") != hash
  abort "Historical workflow pin changed"
end
""",
    )
