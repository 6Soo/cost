"""Real HTTP boundaries with synthetic bytes, including persistent connections."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

from app.http_request_counts import RequestCounts
from webapp.ledger_board import Handler


class SyntheticHandler(Handler):
    protocol_version = 'HTTP/1.1'

    def end_headers(self):
        # Keep the real counting transition while bypassing unrelated session
        # renewal in this isolated protocol fixture.
        super(Handler, self).end_headers()
        self._http_body_started = True

    def do_GET(self):
        self.send_response(404 if self.path.startswith('/missing') else 200)
        self.send_header('Content-Length', '3')
        self.end_headers()
        self.wfile.write(b'abc')

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(201)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_real_http_counts_once_per_keepalive_request_and_excludes_headers(tmp_path):
    path = tmp_path / 'counts.json'
    counter = RequestCounts(path, start_flusher=False)
    server = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticHandler)
    server.http_request_counts = counter
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        conn.request('GET', '/board?token=synthetic-secret', headers={'X-Private': 'synthetic-header'})
        response = conn.getresponse()
        assert (response.status, response.read()) == (200, b'abc')
        conn.request('POST', '/api/synthetic-id', body=b'confidential-payload')
        response = conn.getresponse()
        assert response.status == 201
        assert response.read() == b'confidential-payload'
        conn.request('GET', '/missing/private-id')
        response = conn.getresponse()
        assert (response.status, response.read()) == (404, b'abc')
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        counter.close()
    raw = path.read_text(encoding='utf-8')
    assert all(value not in raw for value in (
        'synthetic-secret', 'synthetic-header', 'synthetic-id', 'private-id', 'confidential-payload'))
    values = [value for routes in json.loads(raw)['buckets'].values()
              for methods in routes.values() for value in methods.values()]
    assert sum(value['started'] for value in values) == 3
    assert sum(sum(value['completed'].values()) for value in values) == 3
    assert sum(value['aborted'] for value in values) == 0
    assert sum(value['request_body_bytes'] for value in values) == len(b'confidential-payload')
    assert sum(value['response_body_bytes'] for value in values) == 6 + len(b'confidential-payload')
