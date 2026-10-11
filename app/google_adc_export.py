"""Optional authenticated, read-only XLSX export for the two known Google ledgers.

No credentials are stored here. Application Default Credentials (ADC) must be
configured by the operator and authorized to read the workbooks. There is no
anonymous retry or redirect that could send an access token to another host.
"""

from __future__ import annotations

import re

from app.google_authority import SPREADSHEET_IDS, SourceError

_EXPORT = re.compile(r'https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)/export\?format=xlsx\Z')
_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def authorized_export_fetcher(*, timeout: float, max_bytes: int, session=None):
    """Return a fetcher compatible with google_authority.sync(fetcher=...)."""
    from google.auth.exceptions import RefreshError

    if session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
        session = AuthorizedSession(credentials)

    def fetch(url: str) -> bytes:
        match = _EXPORT.fullmatch(url)
        if match is None or match.group(1) not in SPREADSHEET_IDS.values():
            raise SourceError('SOURCE_NOT_ALLOWED')
        # Only Google's Drive export API is requested. Disable redirects so the
        # AuthorizedSession never forwards credentials to an unverified host.
        endpoint = f'https://www.googleapis.com/drive/v3/files/{match.group(1)}/export'
        try:
            response = session.get(endpoint, params={'mimeType': _MIME},
                                   timeout=timeout, stream=True, allow_redirects=False)
        except RefreshError as error:
            code = 'SOURCE_UNREACHABLE' if error.retryable else 'GOOGLE_AUTH_REFRESH_REQUIRED'
            raise SourceError(code) from None
        except Exception:
            raise SourceError('SOURCE_UNREACHABLE') from None
        try:
            if response.status_code in (401, 403):
                raise SourceError('SOURCE_ACCESS_DENIED')
            if response.status_code == 404:
                raise SourceError('SOURCE_NOT_FOUND')
            if response.status_code != 200:
                raise SourceError('SOURCE_UNREACHABLE')
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if content_type not in (_MIME, 'application/octet-stream'):
                raise SourceError('SOURCE_WRONG_TYPE')
            content = bytearray()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise SourceError('SOURCE_TOO_LARGE')
            if not content:
                raise SourceError('SOURCE_UNREACHABLE')
            return bytes(content)
        except SourceError:
            raise
        except Exception:
            raise SourceError('SOURCE_UNREACHABLE') from None
        finally:
            try:
                response.close()
            except Exception:
                # Cleanup must never replace a safe status with transport details.
                pass

    return fetch
