"""Loopback preview with disposable synthetic data; no operational configuration."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import zipfile
from xml.etree import ElementTree


CARD = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
        'Date,Post Date,Authorization Code,Cancel,Status\n'
        '국민,0000,domestic,purchase,합성상점,37000,,,37000,2026-10-01,2026-10-02,PREVIEW1,,매입\n').encode('utf-8')


def _seed(server, root):
    from app import google_authority as ga
    from ledger.domain.direct_trip_schedule_authority import SCHEMA_VERSION, END_SEMANTICS
    from openpyxl import Workbook
    from webapp.card_flow import CardFlow

    schedule = dict(trip_code='0803_합성여행', event_year=2027, starts_on='2027-08-03',
                    ends_on='2027-08-05', region='합성여행', authority_kind='user_confirmed_schedule',
                    authority_status='authoritative', end_semantics=END_SEMANTICS)
    source = root / 'owner-schedule-preview.json'
    source.write_text(json.dumps(dict(schema_version='owner-trip-schedule-v1', schedule=schedule)), encoding='utf-8')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    record = dict(schedule, source_locator=str(source) + '#schedule', source_sha256=digest)
    (root / 'authority.json').write_text(json.dumps(dict(schema_version=SCHEMA_VERSION, records=[record])), encoding='utf-8')
    trip = server.card_store.create_trip(starts_on=schedule['starts_on'], ends_on=schedule['ends_on'],
        destination=schedule['region'], display_key=schedule['trip_code'], source_sha256=digest,
        client_request_id='preview-trip')
    CardFlow(server.card_store).pipeline.receive(CARD, 'synthetic-preview.csv')

    book = Workbook()
    sheet = book.active
    sheet.title = schedule['trip_code']
    for column, label in zip('BCDEFGH', ga.INCOME_HEADER):
        sheet[f'{column}5'] = label
    sheet['B6'], sheet['C6'], sheet['D6'], sheet['H6'] = '2027-08-03', '합성 고객', '예시', 900000
    sheet['C8'] = '=SUM(H6:H6)'
    for column, label in zip('BCDEFGH', ga.EXPENSE_HEADER):
        sheet[f'{column}11'] = label
    sheet['B12'], sheet['C12'], sheet['D12'], sheet['H12'] = '2027-08-03', '합성 지급처', '식비', 120000
    sheet['C13'] = '=SUM(H12:H12)'
    output = io.BytesIO()
    book.save(output)
    book.close()
    # openpyxl does not calculate formulas. Supply the known cached results
    # of this synthetic workbook so the real validator can check both totals.
    cached = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as original, zipfile.ZipFile(cached, 'w') as target:
        namespace = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        for name in original.namelist():
            contents = original.read(name)
            if name == 'xl/worksheets/sheet1.xml':
                tree = ElementTree.fromstring(contents)
                for cell in tree.iter(namespace + 'c'):
                    if cell.get('r') in ('C8', 'C13'):
                        cell.find(namespace + 'v').text = '900000' if cell.get('r') == 'C8' else '120000'
                contents = ElementTree.tostring(tree, encoding='utf-8')
            target.writestr(name, contents)
    ga.sync(root / 'google-snapshot.json', root / 'google-rows.json', fetcher=lambda url: cached.getvalue())
    from webapp import google_ledger_page
    google_ledger_page.set_mapping(root / 'google-snapshot.json', key=schedule['trip_code'],
        tab_id=trip['tab_id'], known_keys={schedule['trip_code']}, known_tab_ids={trip['tab_id']})


# Production gateway and board ports on the operations host.
RESERVED_PORTS = frozenset({8751, 8752, 8790})


def _refuse_busy_port(port):
    # Windows lets a reuse-address socket share a listening port, which would
    # take traffic meant for the production gateway, so refuse before binding.
    if not port:
        return
    if port in RESERVED_PORTS:
        raise SystemExit(f'포트 {port}는 운영 서비스용이라 미리보기에 쓸 수 없습니다.')
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise SystemExit(f'포트 {port}가 이미 사용 중입니다. 다른 포트를 지정하세요.')


@contextmanager
def preview_server(port=0):
    _refuse_busy_port(port)
    # Ignore inherited production paths and credentials. The tool accepts no data path or host.
    original ={key: value for key, value in os.environ.items() if key.startswith('WEBLEDGER_')}
    for key in original:
        os.environ.pop(key)
    from webapp import access_control, ledger_board as board
    previous = (board._STORE, board._ACCESS, board._OIDC, board._IMPORTER, access_control.session_adapter())
    server = None
    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix='cost-synthetic-preview-')
        directory = temporary.name
        root = Path(directory)
        os.environ.update(WEBLEDGER_UNIFIED_DB='1', WEBLEDGER_CARD_FLOW='1',
            WEBLEDGER_CARD_SCHEMA_POLICY='create', WEBLEDGER_EVIDENCE_ROOT=str(root),
            WEBLEDGER_TRIP_AUTHORITY=str(root / 'authority.json'),
            WEBLEDGER_EXPORT_DIR=str(root / 'exports'),
            WEBLEDGER_RECEIPTS_STORE=str(root / 'receipts.json'),
            WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT=str(root / 'google-snapshot.json'),
            WEBLEDGER_GOOGLE_LEDGER_ROWS=str(root / 'google-rows.json'))
        board.bind_access(None)
        board.bind_oidc(None)
        server = board.serve(port=port, host='127.0.0.1', db_path=root / 'preview.sqlite',
                             with_worker=False, seed_demo=False)
        access = access_control.attach_to_ledger_store(server.card_store)
        access.ensure_schema()
        access.create_account(user_id='preview-owner', role='owner', is_synthetic=True)
        token = secrets.token_urlsafe(32)

        class PreviewSessions(access_control.SyntheticSessionAdapter):
            def session_for(self, headers, cookies=None):
                jar = SimpleCookie()
                try:
                    jar.load(headers.get('Cookie', ''))
                except CookieError:
                    return None
                value = jar.get('cost_preview')
                if value is None or not hmac.compare_digest(value.value, token):
                    return None
                return super().session_for({'X-Synthetic-User': 'preview-owner'})

        access_control.bind_sessions(PreviewSessions(allow_synthetic=True, access_store=access))
        board.bind_access(access)

        class PreviewHandler(board.Handler):
            def do_GET(self):
                if self.path == '/preview':
                    self.send_response(303)
                    self.send_header('Set-Cookie', f'cost_preview={token}; Path=/; HttpOnly; SameSite=Strict')
                    self.send_header('Location', '/')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                super().do_GET()

            def _send(self, text, code=200):
                text = text.replace('<body>', "<body><p style='margin:0;padding:8px;background:#fff4cc'>"
                    "로컬 합성 미리보기 · 실제 고객·회계·Google 자료가 아닙니다. "
                    "OCR은 연결되지 않았으며 영수증은 수동으로 입력합니다.</p>", 1)
                super()._send(text, code)

        server.RequestHandlerClass = PreviewHandler
        _seed(server, root)
        yield server
        # The caller stops serve_forever before leaving this context.
    finally:
        if server is not None:
            server.server_close()
            server.card_store.close()
        if temporary is not None:
            temporary.cleanup()
        old_store, old_access, old_oidc, old_importer, adapter = previous
        access_control.bind_sessions(adapter)
        board.bind_store(old_store)
        board.bind_access(old_access)
        board.bind_oidc(old_oidc)
        board.bind_importer(old_importer)
        for key in list(os.environ):
            if key.startswith('WEBLEDGER_'):
                os.environ.pop(key)
        os.environ.update(original)


def main():
    parser = argparse.ArgumentParser(description='COST 로컬 합성 미리보기. 종료하면 입력한 예시 자료도 삭제됩니다.')
    parser.add_argument('--port', type=int, default=8795)
    args = parser.parse_args()
    with preview_server(args.port) as server:
        print(f'합성 미리보기: http://127.0.0.1:{server.server_address[1]}/preview', flush=True)
        print('운영 자료와 외부 서비스를 사용하지 않습니다. 종료: Ctrl+C', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
