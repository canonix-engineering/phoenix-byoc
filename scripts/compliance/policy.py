"""Only known Phoenix entry packages are exempt from third-party attribution.

Do not exempt a whole namespace: private forks can contain upstream code.
"""
FIRST_PARTY = {
    'github.com/canonix-engineering/phoenix-workflow-engine',
    'github.com/canonix-engineering/phoenix-gateway',
    # Canonix-authored typed configuration loader (not an upstream fork).
    'github.com/canonix-engineering/appconfig-go',
    'phoenix-agents',
    'phoenix-workflow-engine',
}


def first_party(package):
    return package['name'] in FIRST_PARTY
