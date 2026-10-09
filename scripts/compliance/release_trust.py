"""Keep candidate build identities separate from stable release trust."""
import argparse
import json
from pathlib import Path


def identity(policy, channel):
    if channel == 'development' and policy.get('developmentCertificateIdentityRegexp'):
        return policy['developmentCertificateIdentityRegexp']
    return policy['certificateIdentityRegexp']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('policy', type=Path)
    parser.add_argument('channel')
    args = parser.parse_args()
    print(identity(json.loads(args.policy.read_text()), args.channel))
