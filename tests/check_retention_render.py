"""Check rendered retention policy and preservation of explicit service identities."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys


def read_documents(path):
    result = subprocess.run(['yq', '-o=json', '-I=0', '.', str(path)],
                            check=True, capture_output=True, text=True)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def check(rendered, original_secrets):
    objects = {(o['kind'], o['metadata']['name']): o for o in read_documents(rendered)
               if isinstance(o, dict) and o.get('kind')}
    config = objects['ConfigMap', 'phoenix-workflow-engine']['data']
    assert config['WORKFLOW_RUN_RETENTION_ENABLED'] == 'false', 'BYOC cleanup must remain disabled'
    assert config['WORKFLOW_RUN_RETENTION_TTL_SECONDS'] == '1209600'
    assert config['WORKFLOW_RUN_RETENTION_ATTEMPT_PREVIOUS_SNAPSHOTS_TO_KEEP'] == '0'
    assert config['WORKFLOW_RUN_RETENTION_BATCH_SIZE'] == '100'
    app = read_documents(original_secrets)[0]['secrets']['application']
    web = objects['Secret', 'phoenix-web']['data']
    identities = json.loads(base64.b64decode(web['PHOENIX_INTERNAL_SERVICE_TOKENS']))
    matching = [i for i in identities if i['token'] == app['workflowEngineToken']]
    assert len(matching) == 1
    assert matching[0]['scopes'].count('workflow:retention:write') == 1
    if app.get('internalServiceTokens'):
        expected = copy.deepcopy(json.loads(app['internalServiceTokens']))
        for identity in expected:
            if identity['token'] == app['workflowEngineToken']:
                if 'workflow:retention:write' not in identity['scopes']:
                    identity['scopes'].append('workflow:retention:write')
        assert identities == expected, 'Credentials, identities or restrictions changed unexpectedly'


if __name__ == '__main__':
    check(Path(sys.argv[1]), Path(sys.argv[2]))
    print('Retention is disabled; internal credentials and restrictions are preserved.')
