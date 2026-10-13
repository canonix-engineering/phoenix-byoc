import concurrent.futures
import urllib.parse
from network import request


def license_text(value):
    if isinstance(value, dict):
        value = value.get("type")
    if isinstance(value, list):
        value = "; ".join(filter(None, (license_text(v) for v in value)))
    return value.strip() if isinstance(value, str) and value.strip() else "UNKNOWN"


def unknown_license(value):
    return value.upper() in (
        "UNKNOWN",
        "NOASSERTION",
        "NON-STANDARD",
        "UNLICENSED",
    ) or value.upper().startswith("SEE LICENSE IN")


def enrich_licenses(rows, fetch=request):
    targets = {}
    for row in rows:
        if unknown_license(row["license"]) and row["public"]:
            targets.setdefault(
                (
                    row["ecosystem"],
                    row.get("lookupName", row["name"]),
                    row.get("lookupVersion", row["version"]),
                ),
                [],
            ).append(row)

    def lookup(key):
        eco, name, version = key
        name, version = urllib.parse.quote(name, safe=""), urllib.parse.quote(version, safe="")
        urls = {
            "npm": f"https://registry.npmjs.org/{name}/{version}",
            "RubyGems": f"https://rubygems.org/api/v2/rubygems/{name}/versions/{version}.json",
            "Go": f"https://api.deps.dev/v3/systems/go/packages/{name}/versions/{version}",
            "PyPI": f"https://pypi.org/pypi/{name}/{version}/json",
        }
        try:
            data = fetch(urls[eco])
            if eco == "PyPI":
                info = data.get("info", {})
                value = info.get("license_expression") or info.get("license")
                # Older packages sometimes put the entire license in this field.
                if not value or len(value) > 200:
                    value = [
                        c.rsplit(" :: ", 1)[-1]
                        for c in info.get("classifiers", [])
                        if c.startswith("License :: ") and c.count(" :: ") >= 2
                    ]
            else:
                value = data.get("license") if eco == "npm" else data.get("licenses")
            return key, license_text(value), None
        except Exception as exc:
            if "HTTP 404" in str(exc):
                return key, "UNKNOWN", None
            return key, "UNKNOWN", str(exc)

    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for key, value, error in pool.map(lookup, targets):
            for row in targets[key]:
                row["license"] = value
            if error:
                errors.append(
                    f"License metadata unavailable for {key[0]} {key[1]}@{key[2]}: {error}"
                )
    return errors
