#!/usr/bin/env python3
"""Read PR files as data; never install dependencies or execute PR code."""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from network import GitHub, request
from licenses import enrich_licenses, unknown_license
from npm_ruby import npm_packages, ruby_packages
from inventory import inventory, changes
from presentation import (
    MARKER,
    cell,
    table,
    package_licenses,
    license_summary,
    render_package_licenses,
    render,
)


def analyze(github, pr, fetch=request):
    report = dict(
        baseSha=pr["base"]["sha"],
        headSha=pr["head"]["sha"],
        changes=[],
        basePackages=[],
        headPackages=[],
        referenceChanges=[],
        errors=[],
        generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        runUrl=os.environ.get("REPORT_RUN_URL", ""),
        referencesOnly=False,
    )
    try:
        before, old_manifests = github.snapshot(report["baseSha"])
        after, new_manifests = github.snapshot(report["headSha"])
        if (
            ".github/dependency-report.json" not in before
            and ".github/dependency-report.json" in after
        ):
            before[".github/dependency-report.json"] = after[".github/dependency-report.json"]
        report["referencesOnly"] = bool(
            json.loads(after.get(".github/dependency-report.json", "{}")).get("referencesOnly")
        )
        base, old_refs, errors = inventory(before)
        head, new_refs, head_errors = inventory(after)
        report["errors"].extend(errors + head_errors)
        report["errors"].extend(enrich_licenses(base + head, fetch))
        report.update(basePackages=base, headPackages=head, changes=changes(base, head))
        old = {(r["path"], r["value"]) for r in old_refs}
        new = {(r["path"], r["value"]) for r in new_refs}
        report["referenceChanges"] = [["removed", *r] for r in sorted(old - new)] + [
            ["added", *r] for r in sorted(new - old)
        ]
        for path in old_manifests.keys() | new_manifests.keys():
            if old_manifests.get(path) != new_manifests.get(path):
                parent = str(Path(path).parent)
                locks = (
                    ["uv.lock"]
                    if Path(path).name == "pyproject.toml"
                    else ["package-lock.json"]
                    if Path(path).name == "package.json"
                    else ["Gemfile.lock"]
                )
                candidates = [str(Path(parent) / name) for name in locks]
                if "package-lock.json" in after and locks == ["package-lock.json"]:
                    candidates.append("package-lock.json")
                if not any(before.get(p) != after.get(p) for p in candidates):
                    report["errors"].append(
                        f"Manifest changed without a corresponding lockfile change: {path}"
                    )
    except Exception as exc:
        report["errors"].append(f"Analysis could not finish: {exc}")
    return report


def publish(github, number, report, body, author):
    # An old run must not overwrite the report for a newer PR head/base.
    current = github.api(f"pulls/{number}")
    if any(current[side]["sha"] != report[side + "Sha"] for side in ("base", "head")):
        print("PR changed during analysis; not publishing stale results.")
        return None
    comment = None
    for page in range(1, 101):
        batch = github.api(f"issues/{number}/comments?per_page=100&page={page}")
        for item in batch:
            if item["user"]["login"] == author and item.get("body", "").startswith(MARKER):
                comment = item
                break
        if comment or len(batch) < 100:
            break
    else:
        raise ValueError("Comment pagination limit reached")
    result = (
        github.api(f"issues/comments/{comment['id']}", {"body": body}, "PATCH")
        if comment
        else github.api(f"issues/{number}/comments", {"body": body}, "POST")
    )
    print("Report comment:", result["html_url"])
    return result["html_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--output", default="dependency-report")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    token = (
        os.environ.get("GH_TOKEN")
        or subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    )
    github = GitHub(args.repo, token)
    pr = github.api(f"pulls/{args.pr}")
    report = analyze(github, pr)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    body = render(report)
    (output / "report.md").write_text(body)
    (output / "packages-licenses.md").write_text(render_package_licenses(report))
    print(
        f"Analyzed {len(report['headPackages'])} entries, {len(report['changes'])} changes, {len(report['errors'])} incomplete checks"
    )
    if args.publish:
        author = (
            "github-actions[bot]"
            if os.environ.get("GITHUB_ACTIONS") == "true"
            else request("https://api.github.com/user", token=token)["login"]
        )
        publish(github, args.pr, report, body, author)


if __name__ == "__main__":
    main()
