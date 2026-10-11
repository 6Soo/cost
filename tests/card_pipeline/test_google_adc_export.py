"""Synthetic, offline tests: no Google account, token, or live workbook."""

import pytest

from app.google_authority import SourceError
from app.google_adc_export import authorized_export_fetcher


class FakeResponse:
    def __init__(self, status=200, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', payload=b'xlsx'):
        self.status_code = status
        self.headers = {'Content-Type': content_type}
        self.payload = payload
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.payload

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def sample_url():
    from app.google_authority import SPREADSHEET_IDS
    return 'https://docs.google.com/spreadsheets/d/' + SPREADSHEET_IDS['main'] + '/export?format=xlsx'


def test_authenticated_export_accepts_known_workbook_and_no_redirect():
    response = FakeResponse()
    session = FakeSession(response)
    fetcher = authorized_export_fetcher(timeout=5, max_bytes=1024, session=session)
    assert fetcher(sample_url()) == b'xlsx'
    assert len(session.calls) == 1
    url, options = session.calls[0]
    assert url.startswith('https://www.googleapis.com/drive/v3/files/')
    assert options['allow_redirects'] is False
    assert options['params']['mimeType'].endswith('spreadsheetml.sheet')
    assert response.closed


def test_authenticated_export_never_fetches_unrecognized_host_or_id():
    session = FakeSession(FakeResponse())
    fetcher = authorized_export_fetcher(timeout=5, max_bytes=1024, session=session)
    for url in ['https://evil.example/export?format=xlsx',
                'https://docs.google.com/spreadsheets/d/unknown/export?format=xlsx']:
        with pytest.raises(SourceError) as exc:
            fetcher(url)
        assert exc.value.code == 'SOURCE_NOT_ALLOWED'
    assert not session.calls


@pytest.mark.parametrize('status,expected', [(401, 'SOURCE_ACCESS_DENIED'),
                                              (403, 'SOURCE_ACCESS_DENIED'),
                                              (404, 'SOURCE_NOT_FOUND'),
                                              (302, 'SOURCE_UNREACHABLE')])
def test_authenticated_export_fails_closed_on_status(status, expected):
    response = FakeResponse(status=status)
    fetcher = authorized_export_fetcher(timeout=5, max_bytes=1024, session=FakeSession(response))
    with pytest.raises(SourceError) as exc:
        fetcher(sample_url())
    assert exc.value.code == expected
    assert response.closed


def test_authenticated_export_rejects_html_and_oversize():
    for response, code in [(FakeResponse(content_type='text/html'), 'SOURCE_WRONG_TYPE'),
                           (FakeResponse(payload=b'12345'), 'SOURCE_TOO_LARGE')]:
        fetcher = authorized_export_fetcher(timeout=5, max_bytes=4, session=FakeSession(response))
        with pytest.raises(SourceError) as exc:
            fetcher(sample_url())
        assert exc.value.code == code
        assert response.closed


@pytest.mark.parametrize('retryable,expected', [(False, 'GOOGLE_AUTH_REFRESH_REQUIRED'),
                                               (True, 'SOURCE_UNREACHABLE')])
def test_refresh_failure_is_classified_without_exposing_credentials(retryable, expected):
    from google.auth.exceptions import RefreshError

    class BrokenSession:
        def get(self, *args, **kwargs):
            raise RefreshError('synthetic-secret-token', retryable=retryable)

    fetcher = authorized_export_fetcher(timeout=5, max_bytes=1024, session=BrokenSession())
    with pytest.raises(SourceError) as error:
        fetcher(sample_url())
    assert error.value.code == expected
    assert 'synthetic-secret-token' not in str(error.value)


def test_response_cleanup_failure_never_replaces_safe_error():
    class BrokenClose(FakeResponse):
        def close(self):
            raise RuntimeError('synthetic-secret-token')

    fetcher = authorized_export_fetcher(timeout=5, max_bytes=1024,
                                        session=FakeSession(BrokenClose(status=401)))
    with pytest.raises(SourceError) as error:
        fetcher(sample_url())
    assert error.value.code == 'SOURCE_ACCESS_DENIED'
    assert 'synthetic-secret-token' not in str(error.value)
