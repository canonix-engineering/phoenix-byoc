from pathlib import Path
import re
import json
from go_modules import go_packages
from python_packages import uv_packages, requirement_rows, pyproject_packages
from source_dependencies import CONFIG, declared_packages, infrastructure_references
from npm_ruby import npm_packages, ruby_packages


def inventory(files):
    rows, references, errors = [], [], []
    config = json.loads(files.get(CONFIG, "{}"))
    for path, text in sorted(files.items()):
        if path == CONFIG or any(
            path.startswith(prefix) for prefix in config.get("excludePaths", [])
        ):
            continue
        try:
            if Path(path).name == "package-lock.json":
                rows.extend(npm_packages(path, text))
            elif Path(path).name == "Gemfile.lock":
                rows.extend(ruby_packages(path, text))
            elif Path(path).name == "go.mod":
                rows.extend(go_packages(path, text))
            elif Path(path).name == "go.work":
                errors.append(f"{path}: Go workspace replacements require manual review")
            elif Path(path).name == "uv.lock":
                rows.extend(uv_packages(path, text))
            elif Path(path).name.startswith("requirements") and path.endswith(".txt"):
                packages, problems = requirement_rows(path, text)
                rows.extend(packages)
                errors.extend(problems)
            elif Path(path).name == "pyproject.toml":
                if str(Path(path).with_name("uv.lock")) not in files:
                    packages, problems = pyproject_packages(path, text)
                    rows.extend(packages)
                    errors.extend(problems)
            elif path == "release.yaml" or Path(path).name in ("Chart.yaml", "Chart.lock"):
                references.extend(infrastructure_references(path, text))
            else:
                for number, line in enumerate(text.splitlines(), 1):
                    if "Dockerfile" in Path(path).name:
                        match = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line, re.I)
                        kind = "Docker FROM"
                    else:
                        match = re.match(r'^\s*(?:-\s*)?uses:\s*[\'"]?([^\s\'"#]+)', line)
                        kind = "GitHub Actions"
                    if match:
                        references.append(dict(path=path, line=number, kind=kind, value=match[1]))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path}: {exc}")
    try:
        rows.extend(declared_packages(files))
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(f"Source dependency declaration: {exc}")
    return rows, references, errors


def changes(base, head):
    old, new = {r["id"]: r for r in base}, {r["id"]: r for r in head}
    result = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        if (
            before
            and after
            and all(
                before.get(f) == after.get(f)
                for f in ("name", "version", "source", "license", "scope")
            )
        ):
            continue
        result.append(
            {
                "change": "added" if not before else "removed" if not after else "changed",
                "before": before,
                "after": after,
            }
        )
    return result
