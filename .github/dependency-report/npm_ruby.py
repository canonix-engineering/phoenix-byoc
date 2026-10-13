import json
import re
from licenses import license_text


def npm_packages(path, text):
    lock = json.loads(text)
    if lock.get("lockfileVersion") not in (2, 3) or not isinstance(lock.get("packages"), dict):
        raise ValueError("Only npm lockfile v2/v3 is supported")
    declared = set()
    for location, item in lock["packages"].items():
        if "node_modules/" not in location:
            for field in (
                "dependencies",
                "devDependencies",
                "optionalDependencies",
                "peerDependencies",
            ):
                declared.update(item.get(field, {}))
    rows = []
    for location, item in lock["packages"].items():
        if "node_modules/" not in location or item.get("link"):
            continue
        name = item.get("name") or location.rsplit("node_modules/", 1)[1]
        version = item.get("version", "")
        resolved = item.get("resolved", "")
        public = bool(re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version)) and (
            resolved.startswith("https://registry.npmjs.org/")
        )
        rows.append(
            dict(
                id=path + ":" + location,
                ecosystem="npm",
                name=name,
                version=version,
                source=resolved,
                public=public,
                path=path,
                scope="direct" if name in declared else "transitive",
                license=license_text(item.get("license")),
            )
        )
    return rows


def ruby_packages(path, text):
    rows, section, remote = [], "", ""
    direct = set()
    dependency_section = False
    for line in text.splitlines():
        if line and not line.startswith(" "):
            dependency_section = line == "DEPENDENCIES"
        elif dependency_section:
            match = re.match(r"^  ([\w.-]+)", line)
            if match:
                direct.add(match[1])
    revision = ""
    for line in text.splitlines():
        if line and not line.startswith(" "):
            section, remote, revision = line, "", ""
        if line.startswith("  remote: "):
            remote = line.split(": ", 1)[1]
        if line.startswith("  revision: "):
            revision = line.split(": ", 1)[1]
        match = re.fullmatch(r"    ([\w.-]+) \(([^ )]+)\)", line)
        if match and section in ("GEM", "GIT", "PATH"):
            name, raw = match.groups()
            version, _, platform = raw.partition("-")
            rows.append(
                dict(
                    id=f"{path}:{name}:{platform or 'ruby'}",
                    ecosystem="RubyGems",
                    name=name,
                    version=version,
                    platform=platform or "ruby",
                    path=path,
                    source=remote + ("#" + revision if revision else ""),
                    public=section == "GEM" and remote.rstrip("/") == "https://rubygems.org",
                    scope="direct" if name in direct else "transitive",
                    license="UNKNOWN",
                )
            )
    if not rows:
        raise ValueError("No supported Ruby dependencies found")
    return rows
