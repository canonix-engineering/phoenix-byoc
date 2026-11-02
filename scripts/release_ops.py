#!/usr/bin/env python3
"""Ordinary BYOC release tooling. Never builds images or deploys a cluster."""
import argparse
import base64
import copy
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

import yaml

ORG = 'canonix-engineering'
BYOC = f'{ORG}/phoenix-byoc'
GROUPS = {
    'web': ('phoenix-web', ['phoenixWeb', 'phoenixWebFrontend']),
    'engine': ('phoenix-workflow-engine', ['phoenixWorkflowEngine', 'phoenixOpensandbox']),
    'agents': ('phoenix-agents', ['phoenixAgent']),
    'gateway': ('phoenix-gateway', ['phoenixGateway']),
}
DEPLOYMENTS = {
    'phoenixWeb': ['phoenix-web', 'phoenix-web-worker'],
    'phoenixWebFrontend': ['phoenix-web-frontend'],
    'phoenixWorkflowEngine': ['phoenix-workflow-engine-api', 'phoenix-workflow-engine-artifact-api',
                              'phoenix-workflow-engine-operator', 'phoenix-workflow-engine-orchestrator'],
    'phoenixOpensandbox': ['phoenix-workflow-engine-opensandbox'],
    'phoenixGateway': ['phoenix-gateway'],
}
CHARTS = {
    'fuseDevicePlugin': 'fuse-device-plugin', 'cortexPostgresql': 'cortex-postgresql',
    'opensandboxController': 'opensandbox-controller', 'phoenixGateway': 'phoenix-gateway',
    'phoenixWeb': 'phoenix-web', 'phoenixWebFrontend': 'phoenix-web-frontend',
    'phoenixWorkflowEngine': 'phoenix-workflow-engine',
}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(*args, env=None, binary=False):
    result = subprocess.run(args, capture_output=True, text=not binary, env=env, timeout=300)
    # Command output may contain private registry credentials or Kubernetes data.
    require(result.returncode == 0, f'{args[0]} {args[1]} failed (exit {result.returncode}); inspect privately')
    return result.stdout if binary else result.stdout.strip()


def api(endpoint):
    return json.loads(run('gh', 'api', endpoint))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def load(path):
    return json.loads(Path(path).read_text())


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def version(value):
    require(re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value), 'Use a stable X.Y.Z version')
    return value


def groups(value):
    chosen = value.split(',') if value != 'all' else list(GROUPS)
    require(chosen and len(set(chosen)) == len(chosen) and set(chosen) <= GROUPS.keys(),
            'Services must be all or comma-separated web,engine,agents,gateway')
    return chosen


def ref(item):
    require(DIGEST.fullmatch(item['digest']), 'Image must have an immutable sha256 digest')
    return f"{item['repository']}:{item['tag']}@{item['digest']}"


def ecr_digest(item):
    match = re.fullmatch(r'(\d{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/(.+)', item['repository'])
    require(match, 'Application image is not in the configured ECR registry')
    account, region, repository = match.groups()
    data = json.loads(run('aws', 'ecr', 'describe-images', '--region', region, '--registry-id', account,
                          '--repository-name', repository, '--image-ids', f"imageTag={item['tag']}", '--output', 'json'))
    digest = data['imageDetails'][0]['imageDigest']
    require(DIGEST.fullmatch(digest), 'Invalid ECR image digest')
    return digest


def ecr_manifests(item, check_layers=False):
    match = re.fullmatch(r'(\d{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/(.+)', item['repository'])
    require(match, 'Expected ECR application image')
    account, region, repository = match.groups()
    prefix = ['aws', 'ecr']
    suffix = ['--region', region, '--registry-id', account, '--repository-name', repository, '--output', 'json']
    def manifest(digest):
        data = json.loads(run(*prefix, 'batch-get-image', *suffix, '--image-ids', f'imageDigest={digest}'))
        require(not data.get('failures') and len(data.get('images', [])) == 1, 'Image manifest unavailable')
        return json.loads(data['images'][0]['imageManifest'])
    top = manifest(item['digest'])
    allowed = {item['digest']}
    manifests = [top]
    if 'manifests' in top:
        children = [m['digest'] for m in top['manifests']
                    if m.get('platform', {}).get('os') == 'linux' and m['platform'].get('architecture') == 'amd64']
        require(children, 'Application index has no linux/amd64 image')
        allowed.update(children)
        manifests = [manifest(digest) for digest in children]
    if check_layers:
        for document in manifests:
            for layer in document.get('layers', []):
                # Obtain signed URL but never print or persist it.
                run(*prefix, 'get-download-url-for-layer', *suffix, '--layer-digest', layer['digest'])
    return allowed


def successful_ci(repo, commit):
    data = api(f'repos/{ORG}/{repo}/actions/workflows/ci.yml/runs?head_sha={commit}&per_page=100')
    runs = [r for r in data['workflow_runs'] if r['head_sha'] == commit
            and r['event'] in ('push', 'workflow_dispatch') and r['head_branch'] in ('preview', 'main')]
    require(runs, f'{repo}: no branch CI for frozen Preview SHA')
    latest = max(runs, key=lambda r: r['id'])
    require(latest['status'] == 'completed' and latest['conclusion'] == 'success',
            f'{repo}: latest same-SHA branch CI is not successful: {latest["html_url"]}')
    return {k: latest[k] for k in ('id', 'run_attempt', 'head_sha', 'head_branch', 'html_url', 'conclusion')}


def image_matches(actual, expected):
    # Preview may use tag-only; its live Pods must additionally verify the digest.
    return actual in (ref(expected), f"{expected['repository']}:{expected['tag']}",
                      f"{expected['repository']}@{expected['digest']}")


def deployment_check(deployment, expected, pods, allowed_digests=None):
    name = deployment['metadata']['name']
    spec, status = deployment['spec'], deployment.get('status', {})
    replicas = spec.get('replicas', 1)
    require(replicas > 0 and status.get('observedGeneration', 0) >= deployment['metadata']['generation'],
            f'{name}: rollout not observed or scaled to zero')
    require(all(status.get(k, 0) == replicas for k in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')),
            f'{name}: rollout incomplete')
    containers = spec['template']['spec']['containers']
    names = {c['name'] for c in containers if image_matches(c['image'], expected)}
    require(names, f'{name}: expected image not in deployment')
    labels = spec['selector'].get('matchLabels', {})
    require(labels and not spec['selector'].get('matchExpressions'), f'{name}: unsupported pod selector')
    live = [p for p in pods if all(p['metadata'].get('labels', {}).get(k) == v for k, v in labels.items())
            and not p['metadata'].get('deletionTimestamp')]
    require(len(live) == replicas, f'{name}: live pod count differs')
    for pod in live:
        statuses = {s['name']: s for s in pod.get('status', {}).get('containerStatuses', [])}
        for container_name in names:
            c = statuses.get(container_name, {})
            require(c.get('ready') and any(c.get('imageID', '').endswith('@' + digest) for digest in (allowed_digests or {expected['digest']})),
                    f'{name}: live image digest or readiness mismatch (platform digest may need explicit review)')
    return {'deployment': name, 'replicas': replicas, 'reference': ref(expected)}


def preview_check(release, selected, context):
    def kube(kind):
        return json.loads(run('kubectl', '--context', context, '-n', 'preview', 'get', kind, '-o', 'json'))
    deployments = {d['metadata']['name']: d for d in kube('deployments')['items']}
    pods = kube('pods')['items']
    checks = []
    for group in selected:
        for key in GROUPS[group][1]:
            for name in DEPLOYMENTS.get(key, []):
                require(name in deployments, f'Preview deployment absent: {name}')
                checks.append(deployment_check(deployments[name], release['images'][key], pods,
                                               ecr_manifests(release['images'][key])))
    if 'agents' in selected:
        cm = kube('configmap/phoenix-workflow-engine')
        actual = json.loads(cm['data']['WORKFLOW_RUNTIME_IMAGES'])['phoenix-agent']
        require(actual == ref(release['images']['phoenixAgent']), 'Preview Engine runtime Agent reference differs')
        # Confirm running Engine processes see the current ConfigMap; do not print env.
        engine = deployments['phoenix-workflow-engine-api']
        selector = engine['spec']['selector']['matchLabels']
        live = [p for p in pods if all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items())
                and not p['metadata'].get('deletionTimestamp')]
        require(live, 'No Engine API pod for runtime configuration verification')
        for pod in live:
            runtime = run('kubectl', '--context', context, '-n', 'preview', 'exec', pod['metadata']['name'],
                          '--', 'printenv', 'WORKFLOW_RUNTIME_IMAGES')
            require(json.loads(runtime)['phoenix-agent'] == actual, 'Running Engine Agent configuration is stale')
        checks.append({'runtime': 'phoenix-agent', 'reference': actual})
    return {'checkedAt': now(), 'namespace': 'preview', 'checks': checks}


def candidate_dir(release):
    return Path('.release') / version(release['release']['version'])


def prepare(args):
    version(args.version)
    selected = groups(args.services)
    directory = Path('.release') / args.version
    require(not directory.exists(), 'Candidate already frozen; review existing PR. Refresh explicitly, do not silently refreeze.')
    baseline = api(f'repos/{BYOC}/releases/latest')
    require(not baseline['draft'] and not baseline['prerelease'], 'Baseline must be a published stable release')
    base_tag = baseline['tag_name']
    base_sha = api(f'repos/{BYOC}/commits/{base_tag}')['sha']
    content = api(f'repos/{BYOC}/contents/release.yaml?ref={base_sha}')
    base = yaml.safe_load(base64.b64decode(content['content']))
    require(tuple(map(int, args.version.split('.'))) > tuple(map(int, version(base['release']['version']).split('.'))),
            'Candidate version must be newer than published baseline')
    current = yaml.safe_load(Path('release.yaml').read_text())
    require(current['images'] == base['images'], 'BYOC main already contains unpublished image changes; review them first')
    release = copy.deepcopy(current)
    release['release'].update(version=args.version, channel='stable', sourceEnvironment='preview', observedAt=now()[:10])
    plan = {'schemaVersion': 1, 'version': args.version, 'createdAt': now(), 'baseTag': base_tag,
            'baseCommit': base_sha, 'selectedServices': selected, 'services': {}, 'blockers': [],
            'devopsCommit': api(f'repos/{ORG}/phoenix-devops/commits/main')['sha']}
    for group, (repo, keys) in GROUPS.items():
        if group not in selected:
            plan['services'][group] = {'selected': False, 'images': {k: base['images'][k] for k in keys}}
            continue
        preview = api(f'repos/{ORG}/{repo}/commits/preview')
        main = api(f'repos/{ORG}/{repo}/commits/main')
        sha = preview['sha']
        old_sha = base['images'][keys[0]]['tag'].removeprefix('sha-')
        entry = {'selected': True, 'repository': repo, 'previewCommit': sha, 'mainCommit': main['sha'],
                 'treesEqual': preview['commit']['tree']['sha'] == main['commit']['tree']['sha'],
                 'compareUrl': f'https://github.com/{ORG}/{repo}/compare/{old_sha}...{sha}', 'images': {}}
        plan['services'][group] = entry
        try:
            entry['ci'] = successful_ci(repo, sha)
        except ValueError as error:
            plan['blockers'].append(str(error))
        for key in keys:
            item = copy.deepcopy(base['images'][key])
            item['tag'] = f'sha-{sha}'
            try:
                item['digest'] = ecr_digest(item)
                release['images'][key] = item
                entry['images'][key] = item
            except ValueError as error:
                plan['blockers'].append(f'{key}: {error}')
    if not plan['blockers']:
        try:
            plan['preview'] = preview_check(release, selected, args.context)
        except ValueError as error:
            plan['blockers'].append(str(error))
    Path('release.yaml').write_text(yaml.safe_dump(release, sort_keys=False))
    save(directory / 'plan.json', plan)
    review = {'inputSha256': '', 'planSha256': sha256((directory / 'plan.json').read_bytes()),
              'compatibility': '', 'chartsAndValues': '', 'upgradeInstructions': '',
              'customerRegistryAccess': '', 'customerChanges': '', 'validationEvidence': [],
              'criticalChanges': None, 'rehearsal': {'performed': False, 'reason': '', 'evidence': ''}}
    save(directory / 'review.json', review)
    report = [f'# BYOC {args.version} candidate', f'Baseline: {base_tag} ({base_sha})',
              f'Services: {", ".join(selected)}', f'DevOps source: {plan["devopsCommit"]}',
              '\n## Blockers', *(plan['blockers'] or ['None in automated source/Preview checks. Human review is still required.']),
              '\n## Source changes']
    for group, entry in plan['services'].items():
        report.append(f'- {group}: {entry.get("compareUrl", "retained from baseline")}')
        if entry.get('selected'):
            report.append(f'  main/Preview trees equal: {entry["treesEqual"]}; CI: {entry.get("ci", {}).get("html_url", "blocked")}')
    report += ['\nReview chart changes, required values/secrets, exact mixed-version compatibility and upgrade instructions.',
               'No images built; no cluster deployment or AWS upgrade rehearsal performed.',
               'Complete review.json after applicable tests; see docs/release-automation.md.']
    (directory / 'REPORT.md').write_text('\n'.join(report) + '\n')
    print(directory)


def refresh(args):
    """Explicitly refresh named groups, or recheck existing frozen refs."""
    release = yaml.safe_load(Path('release.yaml').read_text())
    directory = candidate_dir(release)
    plan = load(directory / 'plan.json')
    require(api(f'repos/{BYOC}/releases/latest')['tag_name'] == plan['baseTag'], 'Baseline changed; prepare a new candidate')
    selected = groups(args.services) if args.command == 'refresh' else []
    for group in selected:
        repo, keys = GROUPS[group]
        preview = api(f'repos/{ORG}/{repo}/commits/preview')
        main = api(f'repos/{ORG}/{repo}/commits/main')
        old = plan['services'][group]
        old_sha = old['images'].get(keys[0], release['images'][keys[0]])['tag'].removeprefix('sha-')
        # Preserve the comparison's original baseline when refreshing a group.
        old_sha = old.get('compareUrl', '').split('/compare/')[-1].split('...')[0] or old_sha
        entry = {'selected': True, 'repository': repo, 'previewCommit': preview['sha'], 'mainCommit': main['sha'],
                 'treesEqual': preview['commit']['tree']['sha'] == main['commit']['tree']['sha'],
                 'compareUrl': f'https://github.com/{ORG}/{repo}/compare/{old_sha}...{preview["sha"]}', 'images': {}}
        # Resolve every image before replacing this group's snapshot.
        for key in keys:
            item = copy.deepcopy(release['images'][key])
            item['tag'] = 'sha-' + preview['sha']
            item['digest'] = ecr_digest(item)
            entry['images'][key] = item
        release['images'].update(entry['images'])
        plan['services'][group] = entry
    plan['selectedServices'] = [g for g in GROUPS if plan['services'][g]['selected']]
    plan['blockers'] = []
    for group in plan['selectedServices']:
        entry = plan['services'][group]
        try:
            entry['ci'] = successful_ci(entry['repository'], entry['previewCommit'])
            for key in GROUPS[group][1]:
                require(ecr_digest(entry['images'][key]) == entry['images'][key]['digest'], f'{key}: frozen tag changed')
        except (ValueError, KeyError) as error:
            plan['blockers'].append(f'{group}: {error}')
    if not plan['blockers']:
        try:
            plan['preview'] = preview_check(release, plan['selectedServices'], args.context)
        except ValueError as error:
            plan['blockers'].append(str(error))
    plan['updatedAt'] = now()
    Path('release.yaml').write_text(yaml.safe_dump(release, sort_keys=False))
    save(directory / 'plan.json', plan)
    review = load(directory / 'review.json')
    # Preserve reviewer notes for editing, but require renewed review of new inputs.
    review['inputSha256'] = ''
    review['planSha256'] = sha256((directory / 'plan.json').read_bytes())
    review['validationEvidence'] = []
    review['criticalChanges'] = None
    review['rehearsal'] = {'performed': False, 'reason': '', 'evidence': ''}
    save(directory / 'review.json', review)
    report = [f'# BYOC {plan["version"]} candidate', f'Baseline: {plan["baseTag"]}',
              'Snapshot refreshed/rechecked explicitly; previous qualification invalidated.', '\n## Blockers',
              *(plan['blockers'] or ['No automated blockers; complete renewed human review.'])]
    report.extend(f'- {group}: {entry.get("compareUrl", "retained from baseline")}' for group, entry in plan['services'].items())
    (directory / 'REPORT.md').write_text('\n'.join(report) + '\n')
    print(directory)


def working_files():
    names = run('git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0')
    return {name: Path(name).read_bytes() for name in sorted(set(names)) if name and not name.startswith('.release/')
            and Path(name).is_file() and not Path(name).is_symlink()}


def input_hash(files):
    return sha256(b''.join(name.encode() + b'\0' + hashlib.sha256(data).digest()
                           for name, data in sorted(files.items()) if not name.startswith('.release/')))


def check_review(release, files, plan, review):
    require(not plan['blockers'], 'Candidate has unresolved blockers; refresh evidence before publication')
    require(plan['version'] == release['release']['version'], 'Plan/release version differs')
    require(review['inputSha256'] == input_hash(files), 'Review is stale: delivery contents changed')
    plan_bytes = files[f'.release/{plan["version"]}/plan.json']
    require(review['planSha256'] == sha256(plan_bytes), 'Frozen plan changed after review')
    for field in ('compatibility', 'chartsAndValues', 'upgradeInstructions', 'customerRegistryAccess', 'customerChanges'):
        require(isinstance(review.get(field), str) and len(review[field].strip()) >= 20, f'Review {field} needs a concrete assessment')
    require(review.get('validationEvidence') and all(isinstance(x, str) and len(x) >= 20 for x in review['validationEvidence']),
            'Provide concrete validation evidence links/records')
    require(type(review.get('criticalChanges')) is bool, 'Critical change assessment is missing')
    rehearsal = review['rehearsal']
    require(type(rehearsal.get('performed')) is bool, 'Rehearsal performed must be a boolean')
    if rehearsal['performed']:
        require(len(rehearsal.get('evidence', '')) >= 20, 'Rehearsal evidence required')
    else:
        require(review['criticalChanges'] is False and len(rehearsal.get('reason', '')) >= 20,
                'Critical changes require rehearsal; ordinary releases require a reason for omitting it')
    for group, entry in plan['services'].items():
        for key in GROUPS[group][1]:
            require(release['images'][key] == entry['images'][key], f'{key}: changed outside frozen snapshot')


def chart_inventory(release, destination):
    entries = []
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, HELM_REGISTRY_CONFIG=f'{tmp}/registry.json', DOCKER_CONFIG=f'{tmp}/docker',
                   HELM_REPOSITORY_CONFIG=f'{tmp}/repositories.yaml', HELM_REPOSITORY_CACHE=f'{tmp}/cache')
        chart_list = [(key, name, f'oci://ghcr.io/{ORG}/phoenix-byoc/{name}') for key, name in CHARTS.items()]
        chart_list += [(key, key, f'oci://ghcr.io/helmforgedev/helm/{key}') for key in ('postgresql', 'redis')]
        chart_list += [('ingressNginx', 'ingress-nginx', 'https://kubernetes.github.io/ingress-nginx')]
        for key, name, registry in chart_list:
            chart_version = str(release['versions'][key])
            command = ['helm', 'pull', registry, '--version', chart_version, '--destination', tmp]
            if registry.startswith('https:'):
                command = ['helm', 'pull', name, '--repo', registry, '--version', chart_version, '--destination', tmp]
            run(*command, env=env)
            archive = Path(tmp) / f'{name}-{chart_version}.tgz'
            entries.append({'name': name, 'version': chart_version, 'registry': registry,
                            'archiveSha256': sha256(archive.read_bytes()), 'anonymousDownloadVerified': True})
    included = []
    for chart in sorted(Path('charts').glob('*/Chart.yaml')):
        data = yaml.safe_load(chart.read_text())
        included.append({'name': data['name'], 'version': data['version'], 'path': str(chart.parent)})
    result = {'remoteCharts': entries, 'includedCharts': included}
    save(destination, result)
    return result


def verify(args):
    release = yaml.safe_load(Path('release.yaml').read_text())
    directory = candidate_dir(release)
    plan = load(directory / 'plan.json')
    files = working_files()
    files[str(directory / 'plan.json')] = (directory / 'plan.json').read_bytes()
    check_review(release, files, plan, load(directory / 'review.json'))
    for group, entry in plan['services'].items():
        if entry['selected']:
            successful_ci(entry['repository'], entry['previewCommit'])
        for key in GROUPS[group][1]:
            require(ecr_digest(release['images'][key]) == release['images'][key]['digest'], f'{key}: image tag drift')
            ecr_manifests(release['images'][key], check_layers=True)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    chart_inventory(release, out / 'chart-index.json')
    save(out / 'verification.json', {'inputSha256': input_hash(working_files()), 'checkedAt': now(),
                                    'checks': ['same-sha-ci', 'application-ecr-manifests-and-layer-urls', 'anonymous-chart-downloads'],
                                    'customerRegistryAccess': 'reviewed separately; runner credentials are not customer credentials'})


def archive_files(commit):
    raw = run('git', 'archive', commit, binary=True)
    files, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.isdir():
                continue
            require(member.isfile() and '..' not in Path(member.name).parts and not member.name.startswith('/'),
                    f'Unsafe archive member: {member.name}')
            require(not member.name.startswith(('.tmp/', '.rendered/')) and member.name not in ('values.yaml', 'values.secrets.yaml', 'customer-values.yaml', 'customer-secrets.yaml'),
                    'Private local configuration is tracked; refusing delivery')
            files[member.name] = archive.extractfile(member).read()
            modes[member.name] = member.mode
    return files, modes


def package(args):
    commit = run('git', 'rev-parse', 'HEAD')
    require(not run('git', 'status', '--porcelain', '--untracked-files=normal'), 'Package only a clean committed checkout')
    files, modes = archive_files(commit)
    release = yaml.safe_load(files['release.yaml'])
    v = version(release['release']['version'])
    directory = f'.release/{v}'
    plan, review = json.loads(files[directory + '/plan.json']), json.loads(files[directory + '/review.json'])
    check_review(release, files, plan, review)
    require(f'docs/releases/{v}.md' in files and 'UPGRADE.md' in files, 'Release notes and upgrade instructions required')
    for name in ('UPGRADE.md', f'docs/releases/{v}.md'):
        require(v.encode() in files[name], f'{name} must describe this release')
    require(files['UPGRADE.md'] != run('git', 'show', f'{plan["baseCommit"]}:UPGRADE.md', binary=True),
            'Upgrade instructions still describe the baseline release')
    evidence = load(Path(args.evidence) / 'verification.json')
    require(evidence['inputSha256'] == input_hash(files), 'Artifact verification is for different delivery content')
    chart_index = load(Path(args.evidence) / 'chart-index.json')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {'version': v, 'sourceCommit': commit, 'channel': release['release']['channel'],
                'distribution': 'online-installation', 'upgradeFrom': plan['baseTag'],
                'byocUpgradeRehearsalPerformed': review['rehearsal']['performed'],
                'qualification': review, 'gcpTestingInScope': False}
    images = {'release': v, 'images': [{'key': k, **item, 'reference': ref(item)} for k, item in release['images'].items()]}
    def image_refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'image' and isinstance(item, str):
                    yield item
                else:
                    yield from image_refs(item)
        elif isinstance(value, list):
            for item in value:
                yield from image_refs(item)
    rendered = list(yaml.safe_load_all(Path(args.rendered).read_text()))
    require(any(isinstance(item, dict) and item.get('kind') for item in rendered), 'Rendered manifests are empty')
    pinned = {item['reference'] for item in images['images']}
    images['additionalDeploymentImages'] = [{'reference': item} for item in sorted(set(image_refs(rendered)) - pinned)]
    for name, data in [('DELIVERY.json', metadata), ('image-index.json', images), ('chart-index.json', chart_index)]:
        files[name] = (json.dumps(data, indent=2, sort_keys=True) + '\n').encode()
    # Release review records are internal. Technical docs remain in the delivery.
    files = {name: data for name, data in files.items() if not name.startswith(('.release/', '.github/'))}
    files['SHA256SUMS'] = ''.join(f'{sha256(data)}  {name}\n' for name, data in sorted(files.items())).encode()
    path = output / f'phoenix-byoc-{v}.tar.gz'
    stamp = int(run('git', 'show', '-s', '--format=%ct', commit))
    with path.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(f'phoenix-byoc-{v}/{name}')
                info.size, info.mtime = len(data), stamp
                info.mode = 0o755 if modes.get(name, 0o644) & 0o111 else 0o644
                archive.addfile(info, io.BytesIO(data))
    path.with_suffix('.gz.sha256').write_text(f'{sha256(path.read_bytes())}  {path.name}\n')
    for name in ('DELIVERY.json', 'release.yaml', 'image-index.json', 'chart-index.json', 'UPGRADE.md'):
        (output / name).write_bytes(files[name])
    (output / 'RELEASE-NOTES.md').write_bytes(files[f'docs/releases/{v}.md'])
    save(output / 'candidate-verification.json', {k: val for k, val in evidence.items() if k != 'checkedAt'})
    print(path)


def chart_diff(args):
    release = yaml.safe_load(Path('release.yaml').read_text())
    plan = load(candidate_dir(release) / 'plan.json')
    devops = Path(args.devops_root).resolve()
    require(run('git', '-C', str(devops), 'rev-parse', 'HEAD') == plan['devopsCommit'], 'DevOps checkout must match frozen commit')
    require(not run('git', '-C', str(devops), 'status', '--porcelain', '--untracked-files=no'), 'DevOps chart source is dirty')
    def contents(path):
        with tarfile.open(path) as archive:
            return {'/'.join(m.name.split('/')[1:]): sha256(archive.extractfile(m).read())
                    for m in archive if m.isfile()}
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'published').mkdir()
        (root / 'source').mkdir()
        env = dict(os.environ, HELM_REGISTRY_CONFIG=str(root / 'registry.json'), DOCKER_CONFIG=str(root / 'docker'))
        for key, name in CHARTS.items():
            pinned = str(release['versions'][key])
            source = devops / 'charts' / name
            require((source / 'Chart.yaml').exists(), f'DevOps chart missing: {name}')
            source_version = str(yaml.safe_load((source / 'Chart.yaml').read_text())['version'])
            run('helm', 'pull', f'oci://ghcr.io/{ORG}/phoenix-byoc/{name}', '--version', pinned,
                '--destination', str(root / 'published'), env=env)
            run('helm', 'package', str(source), '--destination', str(root / 'source'))
            old = contents(root / 'published' / f'{name}-{pinned}.tgz')
            new = contents(root / 'source' / f'{name}-{source_version}.tgz')
            changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
            rows.append({'chart': name, 'pinnedVersion': pinned, 'sourceVersion': source_version,
                         'changedFiles': changed, 'sameVersionDifferentContent': bool(changed) and pinned == source_version})
    save(args.output, {'devopsCommit': plan['devopsCommit'], 'charts': rows,
                       'note': 'Review relevance to BYOC. Do not overwrite published versions or automatically bump every chart.'})


def verify_delivery(output, v, commit):
    """Verify the complete staged delivery before any release API mutation."""
    archive_path = output / f'phoenix-byoc-{v}.tar.gz'
    require(archive_path.with_suffix('.gz.sha256').read_text() == f'{sha256(archive_path.read_bytes())}  {archive_path.name}\n',
            'Archive checksum mismatch')
    files = {}
    prefix = f'phoenix-byoc-{v}/'
    with tarfile.open(archive_path) as archive:
        for member in archive:
            require(member.isfile() and member.name.startswith(prefix) and '..' not in Path(member.name).parts,
                    'Unexpected delivery archive member')
            name = member.name[len(prefix):]
            require(name not in files, 'Duplicate archive member')
            files[name] = archive.extractfile(member).read()
    sums = files.pop('SHA256SUMS').decode().splitlines()
    expected = {name: sha256(data) for name, data in files.items()}
    require(sums == [f'{digest}  {name}' for name, digest in sorted(expected.items())], 'Internal checksums mismatch')
    for name in ('DELIVERY.json', 'release.yaml', 'image-index.json', 'chart-index.json', 'UPGRADE.md'):
        require(files[name] == (output / name).read_bytes(), f'Archive/asset mismatch: {name}')
    require(files[f'docs/releases/{v}.md'] == (output / 'RELEASE-NOTES.md').read_bytes(), 'Release notes mismatch')
    source, _ = archive_files(commit)
    for name, data in source.items():
        if not name.startswith(('.release/', '.github/')):
            require(files.get(name) == data, f'Delivery differs from merged source: {name}')
    metadata = json.loads(files['DELIVERY.json'])
    require(metadata['sourceCommit'] == commit and metadata['version'] == v, 'Delivery source mismatch')


def publish(args):
    commit = run('git', 'rev-parse', 'HEAD')
    release = yaml.safe_load(Path('release.yaml').read_text())
    v = version(release['release']['version'])
    tag = f'v{v}'
    require(release['release']['channel'] == 'stable', 'Publication requires stable channel')
    plan = load(candidate_dir(release) / 'plan.json')
    prs = api(f'repos/{BYOC}/commits/{commit}/pulls')
    require(any(p.get('merged_at') and p['base']['ref'] == 'main' and p['merge_commit_sha'] == commit for p in prs),
            'Publish only the exact merged release PR commit')
    run('git', 'merge-base', '--is-ancestor', commit, 'origin/main')
    runs = api(f'repos/{BYOC}/actions/workflows/compliance-tests.yml/runs?head_sha={commit}&per_page=100')['workflow_runs']
    runs = [r for r in runs if r['head_sha'] == commit and r['event'] == 'push' and r['head_branch'] == 'main']
    require(runs and max(runs, key=lambda r: r['id'])['conclusion'] == 'success', 'Merged-commit BYOC tests must pass')
    existing = json.loads(run('gh', 'release', 'list', '--repo', BYOC, '--limit', '100', '--json', 'tagName,isDraft'))
    found = next((r for r in existing if r['tagName'] == tag), None)
    latest = api(f'repos/{BYOC}/releases/latest')['tag_name']
    require(latest in (plan['baseTag'], tag), 'Published baseline advanced; reconcile candidate before publishing')
    output = Path(args.output)
    expected_names = {f'phoenix-byoc-{v}.tar.gz', f'phoenix-byoc-{v}.tar.gz.sha256', 'DELIVERY.json',
                      'release.yaml', 'image-index.json', 'chart-index.json', 'UPGRADE.md',
                      'RELEASE-NOTES.md', 'candidate-verification.json'}
    require({p.name for p in output.iterdir()} == expected_names, 'Delivery output must contain exactly the expected nine assets')
    verify_delivery(output, v, commit)
    if not found:
        # A pre-existing tag might point at another commit; never move it.
        refs = api(f'repos/{BYOC}/git/matching-refs/tags/{tag}')
        if any(r['ref'] == f'refs/tags/{tag}' for r in refs):
            require(api(f'repos/{BYOC}/commits/{tag}')['sha'] == commit, 'Existing tag points to another commit')
        run('gh', 'release', 'create', tag, '--repo', BYOC, '--target', commit, '--draft', '--title', f'Phoenix BYOC {v}',
            '--notes-file', str(output / 'RELEASE-NOTES.md'))
    data = api(f'repos/{BYOC}/releases/tags/{tag}')
    require(data['target_commitish'] == commit or (not data['draft'] and api(f'repos/{BYOC}/commits/{tag}')['sha'] == commit),
            'Existing release target differs')
    require(set(a['name'] for a in data['assets']) <= expected_names, 'Release contains unexpected assets; inspect before continuing')
    with tempfile.TemporaryDirectory() as tmp:
        for asset in data['assets']:
            run('gh', 'release', 'download', tag, '--repo', BYOC, '--pattern', asset['name'], '--dir', tmp)
            require((Path(tmp) / asset['name']).read_bytes() == (output / asset['name']).read_bytes(),
                    f'Existing asset differs: {asset["name"]}; no overwrite')
        missing = expected_names - {a['name'] for a in data['assets']}
        require(data['draft'] or not missing, 'Published release is incomplete; do not mutate it automatically')
        if missing:
            run('gh', 'release', 'upload', tag, '--repo', BYOC, *(str(output / name) for name in sorted(missing)))
            for name in sorted(missing):
                run('gh', 'release', 'download', tag, '--repo', BYOC, '--pattern', name, '--dir', tmp)
                require((Path(tmp) / name).read_bytes() == (output / name).read_bytes(), f'Uploaded asset verification failed: {name}')
    if data['draft']:
        run('gh', 'release', 'edit', tag, '--repo', BYOC, '--draft=false', '--latest')
    require(api(f'repos/{BYOC}/commits/{tag}')['sha'] == commit, 'Published tag verification failed')
    final = api(f'repos/{BYOC}/releases/tags/{tag}')
    require(not final['draft'] and len(final['assets']) == len(expected_names), 'Publication not complete')
    print(final['html_url'])


def message(args):
    release = yaml.safe_load(Path('release.yaml').read_text())
    v = version(release['release']['version'])
    published = api(f'repos/{BYOC}/releases/tags/v{v}')
    require(not published['draft'], 'Do not prepare a ready-to-send handoff for an unpublished release')
    review = load(candidate_dir(release) / 'review.json')
    text = fr"""Hi Pushpendra, we have prepared a new platform release, `{v}`.

{review['customerChanges']}

The release and update instructions are here: {published['html_url']}
Please check the release-specific prerequisites in `UPGRADE.md`, and keep your existing `values.yaml` and `values.secrets.yaml`.

When convenient, select the release in your existing checkout:

```bash
git fetch origin --tags
git checkout v{v}
```

Then follow `UPGRADE.md` and apply the update using your existing namespace and configuration files:

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

Please wait for the installation to finish successfully before starting a new workflow. If you run into any issues, message me — I’ll be happy to help.
"""
    Path(args.output).write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare', help='Freeze Preview and baseline; no deploy/build; write draft candidate')
    p.add_argument('--version', required=True)
    p.add_argument('--services', default='all')
    p.add_argument('--context', required=True)
    for command in ('refresh', 'recheck'):
        p = commands.add_parser(command, help='Explicitly refresh named groups or recheck frozen sources; invalidate qualification')
        p.add_argument('--context', required=True)
        if command == 'refresh':
            p.add_argument('--services', required=True)
    commands.add_parser('input-hash', help='Hash current delivery contents for reviewed qualification')
    p = commands.add_parser('verify', help='Check reviewed candidate, existing image digests and public charts')
    p.add_argument('--output', required=True)
    p = commands.add_parser('package', help='Package clean committed candidate from verified evidence')
    p.add_argument('--evidence', required=True)
    p.add_argument('--rendered', required=True, help='Fixture-rendered manifests; only image references enter delivery')
    p.add_argument('--output', required=True)
    p = commands.add_parser('chart-diff', help='Compare published chart content with frozen DevOps sources')
    p.add_argument('--devops-root', required=True)
    p.add_argument('--output', required=True)
    p = commands.add_parser('publish', help='Publish verified assets from the merged PR; never overwrite differing assets')
    p.add_argument('--output', required=True)
    p = commands.add_parser('message', help='Generate a customer message draft outside tracked files after publication')
    p.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'input-hash':
        print(input_hash(working_files()))
    elif args.command in ('refresh', 'recheck'):
        refresh(args)
    else:
        globals()[args.command](args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, IndexError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
