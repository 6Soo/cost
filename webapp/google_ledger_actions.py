"""Owner refresh and access-checked source navigation; never write to Google."""
import datetime as dt
import os
import threading

from app import google_authority as ga, sync_schedule
from app.google_sheet_navigation import source_url
from . import google_ledger_page as page

ROUTES = ('/api/google-ledger/sync', '/api/google-ledger/source')
_guard = threading.Lock()
_state = {'status': 'idle'}


def _refresh():
    global _state
    now = dt.datetime.now(ga.KST)
    path, rows = page._snapshot_path(), page._rows_path()
    try:
        with sync_schedule.SyncLock(path.with_name('sync.lock'), now=now):
            state_path = path.with_name('sync-state.json')
            state = sync_schedule.read_state(state_path)
            if not sync_schedule.may_attempt(state, now):
                raise ValueError('BACKOFF_WAIT')
            fetcher = None
            auth = os.environ.get('WEBLEDGER_GOOGLE_AUTH', 'public')
            if auth == 'adc':
                from app.google_adc_export import authorized_export_fetcher
                fetcher = authorized_export_fetcher(timeout=15, max_bytes=ga.DEFAULT_MAX_BYTES)
            elif auth != 'public':
                raise ValueError('GOOGLE_AUTH_UNAVAILABLE')
            snapshot = ga.sync(path, rows, timeout=15, fetcher=fetcher)
            failed = any(s.get('status') != 'ok' for s in snapshot['sources'].values())
            sync_schedule.record_result(state_path, ok=not failed, now=now,
                                        error_code='SOURCE_REFRESH_FAILED' if failed else None)
            result = {'status': 'error' if failed else 'done',
                      'message': ('일부 장부를 읽지 못했습니다. 마지막 정상 자료를 유지합니다.' if failed
                                  else '동기화가 완료되었습니다.'),
                      'synced_at': snapshot['synced_at']}
    except sync_schedule.LockHeld:
        result = {'status': 'error', 'message': '다른 동기화가 진행 중입니다. 잠시 후 다시 눌러 주세요.'}
    except ValueError as error:
        result = {'status': 'error', 'message': ('재시도 대기 중입니다. 잠시 후 다시 눌러 주세요.'
                  if str(error) == 'BACKOFF_WAIT' else '동기화 설정을 확인해 주세요.')}
    except Exception:
        result = {'status': 'error', 'message': '동기화하지 못했습니다. 마지막 정상 자료를 유지합니다.'}
    with _guard:
        _state = result


def dispatch(handler, parsed, *, is_owner, viewer_user_id=None, viewer_tabs=None,
             query=None, raw=None, csrf=''):
    global _state
    if parsed.path not in ROUTES or not page.enabled():
        return False
    if not is_owner and not viewer_user_id:
        handler._send_json({'code': 'LOGIN_REQUIRED'}, 403)
        return True
    if parsed.path.endswith('/sync'):
        if not is_owner:
            handler._send_json({'code': 'OWNER_ONLY'}, 403)
            return True
        if raw is None:
            with _guard:
                result = dict(_state)
            handler._send_json(result)
            return True
        if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
            handler._send_json({'code': 'CSRF_REQUIRED'}, 403)
            return True
        with _guard:
            if _state['status'] != 'running':
                _state = {'status': 'running', 'message': 'Google 장부를 읽고 있습니다.'}
                try:
                    threading.Thread(target=_refresh, daemon=True).start()
                except Exception:
                    _state = {'status': 'error', 'message': '동기화를 시작하지 못했습니다.'}
            result = dict(_state)
        handler._send_json(result, 202)
        return True
    if raw is not None:
        handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
        return True
    try:
        tab = ((query or {}).get('trip') or [''])[0]
        mapping = page.load_mapping(page._snapshot_path())
        keys = [key for key, value in mapping.items() if value == tab]
        if len(keys) != 1:
            raise ValueError()
        if not is_owner:
            allowed = page.viewer_allowed_keys(page.load_grants(page._snapshot_path()),
                                                viewer_user_id, mapping, viewer_tabs)
            if keys[0] not in allowed:
                raise ValueError()
        snapshot, _ = page._load_consistent_measured(page._snapshot_path(), page._rows_path())
        trip = next(t for t in page.owner_payload(snapshot, page.load_choices(page._snapshot_path()))['trips']
                    if t['key'] == keys[0])
        source = trip.get('chosen_source')
        sheet = trip['copies'][source]['sheet']
    except Exception:
        handler._send_json({'code': 'NOT_FOUND'}, 404)
        return True
    try:
        url = source_url(source, sheet)
    except ga.SourceError:
        handler._send('해당 원본 탭을 찾지 못했습니다. 잠시 후 다시 열어 주세요.', code=503)
        return True
    handler.send_response(302)
    handler.send_header('Location', url)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', '0')
    handler.end_headers()
    return True
