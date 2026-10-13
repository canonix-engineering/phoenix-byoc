import html
import re
from licenses import unknown_license

MARKER = "<!-- phoenix-dependency-report:v1 -->"


def cell(value):
    # PR-controlled names are plain text: no mentions, links or table injection.
    value = re.sub(r"[\r\n\t]+", " ", str(value))
    if len(value) > 120:
        value = value[:117] + "…"
    return (
        html.escape(value)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("@", "@\u200b")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("*", "&#42;")
        .replace("_", "&#95;")
    )


def table(headers, rows, limit=30):
    rows = list(rows)
    if not rows:
        return "_None._\n"
    text = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    text += "\n".join("| " + " | ".join(cell(v) for v in row) + " |" for row in rows[:limit]) + "\n"
    if len(rows) > limit:
        text += f"\nShowing {limit} of {len(rows)} rows; see the full JSON report.\n"
    return text


def package_licenses(rows):
    # Keep every distinct declaration when duplicate entries disagree.
    grouped = {}
    for row in rows:
        key = (row["ecosystem"], row["name"], row["version"])
        grouped.setdefault(key, set()).add(
            "UNKNOWN" if unknown_license(row["license"]) else row["license"]
        )
    return [[*key, "; ".join(sorted(licenses))] for key, licenses in sorted(grouped.items())]


def license_summary(packages):
    counts = {}
    for _, _, _, license in packages:
        counts[license] = counts.get(license, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def render_package_licenses(report):
    packages = package_licenses(report["headPackages"])
    body = "# Packages & licenses\n\n"
    body += f"Base: `{report['baseSha']}` → head: `{report['headSha']}`\n\n"
    if report.get("referencesOnly") and not packages:
        body += "Image/chart references only; no package licenses were evaluated.\n\n"
    elif report["errors"] or not packages:
        body += "**Incomplete analysis: this inventory may be partial.**\n\n"
    body += f"{len(packages)} distinct package versions.\n\n"
    body += table(
        ["License declaration", "Package versions"], license_summary(packages), len(packages)
    )
    body += "\n## Packages\n\n"
    body += table(["Ecosystem", "Package", "Version", "License"], packages, len(packages))
    return body


def render(report):
    diff, head = report["changes"], report["headPackages"]
    unknown = [r for r in head if unknown_license(r["license"])]
    key = lambda row: (row["ecosystem"], row["name"], row["version"])
    unique_unknown = {key(r): r for r in unknown}
    old_unknown = {key(r) for r in report["basePackages"] if unknown_license(r["license"])}
    new_unknown = len(unique_unknown.keys() - old_unknown)
    references_only = report.get("referencesOnly") and not head
    incomplete = bool(report["errors"]) or not head and not references_only
    if incomplete:
        state = "⚠️ INCOMPLETE — a clean result cannot be confirmed"
    elif references_only:
        state = "ℹ️ REFERENCES ONLY — package licenses are not evaluated"
    elif unknown:
        state = "⚠️ ATTENTION NEEDED — unknown licenses"
    else:
        state = "✅ PASS — license metadata available for all dependencies"
    body = f"{MARKER}\n## Dependencies & licenses\n\n**{state}**\n\n"
    counts = lambda total, new: [
        total,
        "Not confirmed" if incomplete else new,
        "Not confirmed" if incomplete else total - new,
    ]
    body += table(
        ["Package versions", "Total", "New", "Existing"],
        [
            ["With unknown licenses", *counts(len(unique_unknown), new_unknown)],
        ],
    )
    if not incomplete and not references_only:
        body += (
            "\n**PR impact: new unknown licenses.**\n\n"
            if new_unknown
            else "\n**PR impact: no new unknown licenses.**\n\n"
        )
    if incomplete:
        body += "\nNew/existing license findings could not be confirmed.\n\n"
        if not head:
            body += "No dependencies were available to check.\n\n"
    body += f"Dependency changes: **{len(diff)}**.\n\n"
    packages = package_licenses(head)
    summary = license_summary(packages)
    body += (
        "**Licenses:** "
        + " · ".join(f"{cell(license)}: **{count}**" for license, count in summary[:6])
        if summary
        else ""
    )
    if len(summary) > 6:
        body += f" · +{len(summary) - 6} more"
    if summary:
        body += f" ({len(packages)} distinct package versions).\n\n"
    body += "<details><summary>Details</summary>\n\n"
    body += "### Dependency changes\n\n" if diff else ""
    body += (
        table(
            ["Change", "Package / lockfile", "Scope", "Before → after", "License before → after"],
            (
                [
                    d["change"],
                    f"{(d['after'] or d['before'])['name']} ({(d['after'] or d['before'])['path']})",
                    (d["after"] or d["before"])["scope"],
                    f"{(d['before'] or {}).get('version', '—')} → {(d['after'] or {}).get('version', '—')}",
                    f"{(d['before'] or {}).get('license', '—')} → {(d['after'] or {}).get('license', '—')}",
                ]
                for d in diff
            ),
        )
        if diff
        else ""
    )
    body += "\n### Unknown licenses\n\n" if unknown else ""
    body += (
        table(
            ["Package", "Version", "Compared with base"],
            (
                [
                    r["name"],
                    r["version"],
                    "comparison incomplete"
                    if incomplete
                    else "new unknown license"
                    if key(r) not in old_unknown
                    else "also present in base",
                ]
                for r in unique_unknown.values()
            ),
            15,
        )
        if unknown
        else ""
    )
    body += "\n### Docker / workflow reference changes\n\n" if report["referenceChanges"] else ""
    body += (
        table(["Change", "File", "Reference"], report["referenceChanges"], 15)
        if report["referenceChanges"]
        else ""
    )
    if report["errors"]:
        body += (
            "\n### Incomplete checks\n\n"
            + "\n".join("- " + cell(e) for e in report["errors"][:15])
            + "\n"
        )
        if len(report["errors"]) > 15:
            body += "\nAdditional errors are recorded in the full JSON report.\n"
    body += "\n</details>\n\n"
    if packages:
        body += f"<details><summary>Packages & licenses ({len(packages)})</summary>\n\n"
        body += table(["Ecosystem", "Package", "Version", "License"], packages)
        body += (
            "\nComplete list: `packages-licenses.md` in the full report artifact.\n\n</details>\n\n"
        )
    if report.get("runUrl"):
        body += f"[Full report]({report['runUrl']}) · "
    body += f"`{report['baseSha'][:7]}` → `{report['headSha'][:7]}` · {report['generatedAt'][:16].replace('T', ' ')} UTC\n"
    if len(body) > 60000:
        body = (
            body[:57000]
            + "\n\n</details>\nComment shortened to fit GitHub limits; see the full JSON report.\n"
        )
    return body
