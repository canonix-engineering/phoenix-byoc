import base64
import concurrent.futures
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

LIMIT = 8 * 1024 * 1024


def request(url, data=None, token=None, method=None):
    headers = {"Accept": "application/json", "User-Agent": "phoenix-dependency-report"}
    if token:
        if not url.startswith("https://api.github.com/"):
            raise ValueError("GitHub token must not leave api.github.com")
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )

    # Do not follow redirects with credentials or to endpoints supplied by PR data.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    for attempt in range(3):
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=25) as response:
                body = response.read(LIMIT + 1)
                if len(body) > LIMIT:
                    raise ValueError("API response exceeds size limit")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(
                    f"{urllib.parse.urlsplit(url).netloc}: HTTP {exc.code}"
                ) from None
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise RuntimeError(
                    f"{urllib.parse.urlsplit(url).netloc}: request timed out or failed"
                ) from None
        time.sleep(2**attempt)


class GitHub:
    def __init__(self, repo, token):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ValueError("Invalid repository")
        self.repo, self.token = repo, token

    def api(self, path, data=None, method=None):
        return request(
            "https://api.github.com/repos/" + self.repo + "/" + path,
            data=data,
            token=self.token,
            method=method,
        )

    def snapshot(self, sha):
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("Expected full commit SHA")
        tree = self.api(f"git/trees/{sha}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("Git tree truncated; cannot claim complete inventory")
        selected = []
        manifests = {}
        for entry in tree["tree"]:
            path = entry["path"]
            name = Path(path).name
            if name in ("package.json", "Gemfile", "pyproject.toml") or name.endswith(".gemspec"):
                manifests[path] = entry["sha"]
            if (
                name
                in (
                    "package-lock.json",
                    "Gemfile.lock",
                    "go.mod",
                    "go.work",
                    "uv.lock",
                    "pyproject.toml",
                    "requirements.txt",
                    "Chart.yaml",
                    "Chart.lock",
                )
                or name.startswith("requirements")
                and name.endswith(".txt")
                or "Dockerfile" in name
                or path in ("release.yaml", ".github/dependency-report.json")
                or (path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")))
            ):
                if entry.get("mode") not in ("100644", "100755"):
                    raise ValueError(f"Unsupported file type: {path}")
                if entry.get("size", 0) > 2 * 1024 * 1024:
                    raise ValueError(f"Input too large: {path}")
                selected.append(entry)
        if len(selected) > 100:
            raise ValueError("Too many input files; increase reviewed scan limit")

        def read(entry):
            blob = self.api("git/blobs/" + entry["sha"])
            if blob.get("encoding") != "base64":
                raise ValueError("Unsupported Git blob encoding")
            return entry["path"], base64.b64decode(blob["content"]).decode("utf-8")

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            files = dict(pool.map(read, selected))
        return files, manifests
