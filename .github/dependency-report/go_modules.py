"""Static go.mod inventory; no Go commands or module code are executed."""

import re
import shlex


def go_packages(path, text):
    required, replacements = [], {}
    section = ""
    for raw in text.splitlines():
        line, _, comment = raw.partition("//")
        words = shlex.split(line)
        if not words:
            continue
        if words == [")"]:
            section = ""
            continue
        directive = section or words.pop(0)
        if words == ["("]:
            section = directive
            continue
        if directive == "require":
            if len(words) != 2:
                raise ValueError("Unsupported Go require declaration")
            required.append(
                (words[0], words[1], "transitive" if "indirect" in comment.split() else "direct")
            )
        elif directive == "replace":
            if "=>" not in words:
                raise ValueError("Unsupported Go replace declaration")
            pivot = words.index("=>")
            old, new = words[:pivot], words[pivot + 1 :]
            if len(old) not in (1, 2) or len(new) not in (1, 2):
                raise ValueError("Unsupported Go replace declaration")
            replacements[tuple(old)] = new
    rows = []
    for name, requested, scope in required:
        replacement = replacements.get((name, requested), replacements.get((name,)))
        lookup, version = name, requested
        if replacement:
            lookup = replacement[0]
            version = replacement[1] if len(replacement) == 2 else "local"
        public = (
            bool(re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]+/", lookup))
            and not lookup.startswith("github.com/canonix-engineering/")
            and version.startswith("v")
        )
        rows.append(
            dict(
                id=f"{path}:{name}",
                ecosystem="Go",
                name=name,
                version=version,
                requestedVersion=requested,
                lookupName=lookup,
                lookupVersion=version,
                source=f"{lookup}@{version}",
                public=public,
                path=path,
                scope=scope,
                license="UNKNOWN",
            )
        )
    return rows
