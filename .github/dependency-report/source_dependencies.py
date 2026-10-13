"""Explicit source dependency declarations and textual infrastructure references."""

import json
import re

CONFIG = ".github/dependency-report.json"


def declared_packages(files):
    config = json.loads(files.get(CONFIG, "{}"))
    rows = []
    for item in config.get("sourceDependencies", []):
        path, variable = item["versionFile"], item["versionArg"]
        matches = re.findall(r"^ARG\s+" + re.escape(variable) + r"=(\S+)", files[path], re.M)
        if not matches or len(set(matches)) != 1 or "$" in matches[0]:
            raise ValueError(f"Cannot resolve source dependency version: {path}:{variable}")
        version = matches[0].strip("'\"")
        rows.append(
            dict(
                id=f"{path}:{variable}",
                ecosystem="Source",
                name=item["name"],
                version=version,
                source=item["source"],
                public=False,
                path=path,
                scope="direct",
                license=item.get("license", "UNKNOWN"),
            )
        )
    return rows


def infrastructure_references(path, text):
    # Preserve hierarchy and values as text. No YAML tags/templates are evaluated.
    refs, parents = [], []
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^(\s*)([\w.-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        indent, key, value = match.groups()
        while parents and parents[-1][0] >= len(indent):
            parents.pop()
        if not value:
            parents.append((len(indent), key))
        elif (
            key in ("repository", "image", "tag", "digest", "version", "appVersion")
            or path == "release.yaml"
        ):
            label = ".".join([p[1] for p in parents] + [key])
            refs.append(
                dict(path=path, line=number, kind="Infrastructure", value=f"{label}: {value}")
            )
    return refs
