"""reserve 내부 API에서 가이드와 여행 담당 기준을 읽는다. 문제가 있으면 항상 예외로 멈춘다."""
import datetime as dt
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA = 'reservation-authority-v1'
DEFAULT_BASE_URL = 'https://reserve.foresttour.kr'
BASE_URL_ENV = 'RESERVATION_INTERNAL_BASE_URL'
TOKEN_ENV = 'RESERVATION_INTERNAL_API_TOKEN'
TOKEN_FILE_ENV = 'RESERVATION_INTERNAL_API_TOKEN_FILE'
MAX_BYTES = 2_000_000
LOCAL_HOSTS = ('127.0.0.1', 'localhost')
GUIDE_STATUSES = ('active', 'inactive')
DATE_RE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
GUIDE_KEYS = ('id', 'nickname', 'real_name', 'flight_name_en', 'status')
TOUR_KEYS = ('fldid', 'code', 'title', 'leader', 'leader_guide_id', 'depart_date', 'return_date', 'status')


class AuthorityUnavailable(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _send(request, timeout):
    return _OPENER.open(request, timeout=timeout)


def configured_token(default_token_file=None):
    token = os.environ.get(TOKEN_ENV, '').strip()
    if token:
        return token
    for path in (os.environ.get(TOKEN_FILE_ENV), default_token_file):
        token = _first_line(path)
        if token:
            return token
    return ''


def _first_line(path):
    if not path:
        return ''
    try:
        lines = Path(path).read_text(encoding='utf-8-sig').splitlines()
    except OSError:
        return ''
    return lines[0].strip() if lines else ''


def _base_url(base_url):
    base = (base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip('/')
    try:
        parts = urllib.parse.urlsplit(base)
        host = parts.hostname
    except ValueError:
        raise AuthorityUnavailable('not_configured') from None
    local = parts.scheme == 'http' and host in LOCAL_HOSTS
    if not host or not (parts.scheme == 'https' or local):
        raise AuthorityUnavailable('not_configured')
    return base


def _status_code(status):
    if status in (401, 403):
        return 'unauthorized'
    if 300 <= status < 400:
        return 'redirected'
    if status != 200:
        return 'unavailable'
    return None


def _body(response):
    status = response.status
    try:
        data = response.read(MAX_BYTES + 1) if status == 200 else b''
    finally:
        close = getattr(response, 'close', None)
        if close:
            close()
    return status, data


def _get(url, token, timeout, opener):
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + token, 'User-Agent': 'ForesttourLedger/1', 'Accept': 'application/json'})
    try:
        status, data = _body((opener or _send)(request, timeout))
    except urllib.error.HTTPError as exc:
        status, data = exc.code, b''
    except urllib.error.URLError as exc:
        code = 'timeout' if isinstance(exc.reason, TimeoutError) else 'unavailable'
        raise AuthorityUnavailable(code) from None
    except TimeoutError:
        raise AuthorityUnavailable('timeout') from None
    except OSError:
        raise AuthorityUnavailable('unavailable') from None
    code = _status_code(status)
    if code:
        raise AuthorityUnavailable(code)
    if len(data) > MAX_BYTES:
        raise AuthorityUnavailable('malformed')
    try:
        payload = json.loads(data)
    except ValueError:
        raise AuthorityUnavailable('malformed') from None
    if not isinstance(payload, dict):
        raise AuthorityUnavailable('malformed')
    return payload


def _pick(row, keys):
    if not isinstance(row, dict) or any(k not in row for k in keys):
        raise AuthorityUnavailable('malformed')
    return {k: row[k] for k in keys}


def _text(value):
    return isinstance(value, str) and value.strip() != ''


def _optional_text(value):
    return value is None or isinstance(value, str)


def _optional_date(value):
    if value is None:
        return True
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _guides(payload):
    rows = payload.get('guides')
    if not isinstance(rows, list):
        raise AuthorityUnavailable('malformed')
    guides = []
    for row in rows:
        guide = _pick(row, GUIDE_KEYS)
        if (type(guide['id']) is not int or not _text(guide['nickname']) or guide['status'] not in GUIDE_STATUSES
                or not _optional_text(guide['real_name']) or not _optional_text(guide['flight_name_en'])):
            raise AuthorityUnavailable('malformed')
        guides.append(guide)
    if len({g['id'] for g in guides}) != len(guides) or len({g['nickname'] for g in guides}) != len(guides):
        raise AuthorityUnavailable('malformed')
    return guides


def _tours(payload, guide_ids):
    rows = payload.get('tours')
    if not isinstance(rows, list):
        raise AuthorityUnavailable('malformed')
    tours = []
    for row in rows:
        tour = _pick(row, TOUR_KEYS)
        leader_id = tour['leader_guide_id']
        if (not _text(tour['fldid']) or not _optional_text(tour['code']) or not isinstance(tour['title'], str)
                or not _optional_text(tour['leader']) or not isinstance(tour['status'], str)
                or (leader_id is not None and (type(leader_id) is not int or leader_id not in guide_ids))
                or not _optional_date(tour['depart_date']) or not _optional_date(tour['return_date'])):
            raise AuthorityUnavailable('malformed')
        tours.append(tour)
    if len({t['fldid'] for t in tours}) != len(tours):
        raise AuthorityUnavailable('malformed')
    return tours


def fetch_authority(base_url=None, token=None, *, timeout=15, opener=None):
    base = _base_url(base_url)
    token = (configured_token() if token is None else token).strip()
    if not token:
        raise AuthorityUnavailable('not_configured')
    guides = _guides(_get(base + '/api/internal/guides', token, timeout, opener))
    if not guides:
        raise AuthorityUnavailable('empty')
    tours = _tours(_get(base + '/api/internal/tours?include_past=1', token, timeout, opener),
                   {g['id'] for g in guides})
    if not tours:
        raise AuthorityUnavailable('empty')
    authority = {'schema': SCHEMA,
                 'guides': sorted(guides, key=lambda g: g['id']),
                 'tours': sorted(tours, key=lambda t: t['fldid'])}
    authority['digest'] = authority_digest(authority)
    return authority


def fetch_passenger_candidates(tour_fldid, base_url=None, token=None, *, timeout=15, opener=None):
    """Read the minimum candidate fields for one tour; this endpoint never writes reservations."""
    tour_id = str(tour_fldid or '').strip()
    if not tour_id:
        raise AuthorityUnavailable('malformed')
    base = _base_url(base_url)
    token = (configured_token() if token is None else token).strip()
    if not token:
        raise AuthorityUnavailable('not_configured')
    query = urllib.parse.urlencode({'tourFldid': tour_id})
    payload = _get(base + '/api/internal/passenger-candidates?' + query, token, timeout, opener)
    if (payload.get('tour_id') != tour_id or not _text(payload.get('source_revision')) or
            not isinstance(payload.get('candidates'), list)):
        raise AuthorityUnavailable('malformed')
    candidates = []
    seen = set()
    for row in payload['candidates']:
        candidate = _pick(row, ('kind', 'reference_id', 'name_kr', 'status'))
        candidate['name_en'] = row.get('name_en')
        if (candidate['kind'] not in ('lead', 'companion', 'guide') or
                not _text(candidate['reference_id']) or not _text(candidate['name_kr']) or
                not _optional_text(candidate['name_en']) or not _text(candidate['status'])):
            raise AuthorityUnavailable('malformed')
        identity = (candidate['kind'], candidate['reference_id'])
        if identity in seen:
            raise AuthorityUnavailable('malformed')
        seen.add(identity)
        candidates.append(candidate)
    return {'tour_id': tour_id, 'source_revision': payload['source_revision'],
            'candidates': candidates}


def authority_digest(authority):
    body = {'schema': SCHEMA, 'guides': authority['guides'], 'tours': authority['tours']}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
