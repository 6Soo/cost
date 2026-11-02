"""Synthetic signed-service harness for the autonomous workflow audit.

Run ``python .local-archive/autonomous-qa-20261102/synthetic-journeys.py --serve``
then give the printed loopback URL and owner cookie to the assigned browser tester.
The service uses only temporary SQLite/files and synthetic signed identities.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.tests.test_signed_session_http import SignedSessionHttpTests
from webapp.google_oidc import COOKIE_NAME
from tests.card_pipeline.fixtures import domestic_row, make_xlsx


@contextmanager
def synthetic_service():
    """Reuse the repo's signed owner/viewer and read-only Google fixture."""
    service = SignedSessionHttpTests()
    service.setUp()
    try:
        yield service
    finally:
        service.tearDown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help='keep the isolated service alive for browser work')
    args = parser.parse_args()
    if not args.serve:
        parser.error('use --serve to start the temporary browser harness')
    with synthetic_service() as service:
        upload_file = Path(os.environ.get('TEMP', service.root)) / 'cost-autonomous-synthetic-upload.xlsx'
        upload_file.write_bytes(make_xlsx([domestic_row(
            merchant='SYNTHETIC BROWSER CAFE', amount=14600,
            approval='SYN-BROWSER-001', issuer='SYNTHETIC ISSUER')]))
        server_info = {
            'base_url': f'http://127.0.0.1:{service.port}',
            'owner_cookie_name': COOKIE_NAME,
            'owner_cookie': service.cookie('synthetic-owner-sub'),
            'viewer_cookie': service.cookie('synthetic-viewer-sub'),
            'entry': '/import',
            'upload_file': str(upload_file.resolve()),
            'note': 'synthetic-only; temporary database; stop with Ctrl+C',
        }
        info_path = ROOT / '.local-archive/autonomous-qa-20261102/journey-server.json'
        info_path.write_text(json.dumps(server_info, indent=2), encoding='utf-8')
        print(json.dumps(server_info), flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0


if __name__ == '__main__':
    raise SystemExit(main())
