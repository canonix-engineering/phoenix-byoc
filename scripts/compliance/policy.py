"""Only known Phoenix entry packages are exempt from third-party attribution.

Do not exempt a whole namespace: private forks can contain upstream code.
"""
FIRST_PARTY = {
    'github.com/canonix-engineering/phoenix-workflow-engine',
    'github.com/canonix-engineering/phoenix-gateway',
    # Canonix-authored typed configuration loader (not an upstream fork).
    'github.com/canonix-engineering/appconfig-go',
    'phoenix-agents',
    # Canonix-authored Python services shipped in the agent runtime.
    'slurp',
    'phoenix-analyzer',
    # Local workspace packages authored in phoenix-web.
    '@phoenix/agent-e2e-runner',
    '@phoenix/shared',
    'phoenix-web-frontend',
    'phoenix-workflow-engine',
}


def first_party(package):
    return package['name'] in FIRST_PARTY


def dependency_group(package, fs):
    """APK virtual groups contain only dependencies, with no distributed files."""
    if package.get('type', package.get('ecosystem')) != 'apk' or not package['name'].startswith('.'):
        return False
    for paragraph in fs.read('/lib/apk/db/installed').split('\n\n'):
        fields = dict(line.split(':', 1) for line in paragraph.splitlines() if len(line) > 2 and line[1] == ':')
        if fields.get('P') == package['name'] and fields.get('V') == package['version']:
            return fields.get('T') == 'virtual meta package' and not any(
                line.startswith('R:') for line in paragraph.splitlines())
    return False
