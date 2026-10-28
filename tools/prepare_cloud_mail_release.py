"""Create an isolated Apps Script package; never modify a live script project."""
import argparse
import hashlib
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='A new local directory; existing paths are refused')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    destination = Path(args.output).resolve()
    if destination.exists() or destination == root or destination in root.parents:
        parser.error('CLOUD_MAIL_NEW_OUTPUT_REQUIRED')
    files = {'CloudMail.gs': root / 'cloud-mail/CloudMail.gs',
             'appsscript.json': root / 'cloud-mail/appsscript.json'}
    contents = {name: source.read_bytes() for name, source in files.items()}
    json.loads(contents['appsscript.json'])
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in contents.items():
        with (destination / name).open('xb') as stream:
            stream.write(content)
    print(json.dumps({'status': 'PREPARED', 'files': {
        name: hashlib.sha256(content).hexdigest() for name, content in contents.items()},
        'remote_written': False, 'credentials_included': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
