"""Read Python manifests as data, without resolving or installing packages."""

import json
import re
import tomllib


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def python_row(path, name, version, source, scope, public, identity=""):
    return dict(
        id=f"{path}:{name}:{identity}",
        ecosystem="PyPI",
        name=normalize(name),
        version=version,
        source=source,
        public=public,
        path=path,
        scope=scope,
        license="UNKNOWN",
    )


def uv_packages(path, text):
    lock = tomllib.loads(text)
    if lock.get("version") != 1:
        raise ValueError("Unsupported uv.lock format")
    direct = set()
    for package in lock.get("package", []):
        source = package.get("source", {})
        if source.get("editable") == "." or source.get("virtual") == ".":
            for dep in package.get("dependencies", []):
                direct.add(normalize(dep["name"]))
            for field in ("dev-dependencies", "optional-dependencies"):
                for deps in package.get(field, {}).values():
                    direct.update(normalize(d["name"]) for d in deps)
    rows = []
    for package in lock.get("package", []):
        source = package.get("source", {})
        if source.get("editable") == "." or source.get("virtual") == ".":
            continue
        name, version = package["name"], package.get("version", "unresolved")
        registry = source.get("registry", "").rstrip("/")
        identity = json.dumps(source, sort_keys=True) + ":" + version
        rows.append(
            python_row(
                path,
                name,
                version,
                json.dumps(source, sort_keys=True),
                "direct" if normalize(name) in direct else "transitive",
                registry == "https://pypi.org/simple" and version != "unresolved",
                identity,
            )
        )
    return rows


def requirement_rows(path, text):
    rows, errors = [], []
    logical = text.replace("\\\n", " ")
    private_index = bool(
        re.search(r"--(?:extra-)?index-url|--no-index|--find-links|(?:^|\s)-[if]\s", logical)
    )
    for number, raw in enumerate(logical.splitlines(), 1):
        line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            errors.append(f"{path}:{number}: requirement option/include needs manual review")
            continue
        line = re.sub(r"\s+--hash=\S+", "", line)
        requirement = line.split(";", 1)[0].strip()
        match = re.fullmatch(r"([\w.-]+)(?:\[[\w, .-]+\])?\s*==\s*([\w.+!-]+)", requirement)
        if not match:
            errors.append(
                f"{path}:{number}: dependency is not an exact registry version: {requirement}"
            )
            rows.append(
                python_row(path, requirement, "unresolved", line, "declared", False, str(number))
            )
            continue
        name, version = match.groups()
        rows.append(
            python_row(
                path,
                name,
                version,
                "custom index" if private_index else "https://pypi.org",
                "declared",
                not private_index,
                str(number),
            )
        )
    return rows, errors


def pyproject_packages(path, text):
    project = tomllib.loads(text)
    specs = list(project.get("project", {}).get("dependencies", []))
    for dependencies in project.get("project", {}).get("optional-dependencies", {}).values():
        specs.extend(dependencies)
    rows, errors = requirement_rows(path, "\n".join(specs))
    if project.get("tool", {}).get("poetry"):
        errors.append(f"{path}: Poetry dependencies need a supported lockfile")
    if "dependencies" in project.get("project", {}).get("dynamic", []):
        errors.append(f"{path}: dynamic dependencies cannot be evaluated statically")
    return rows, errors
