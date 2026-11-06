"""Owner-only insurance comparison API; the standalone page has been removed."""
from __future__ import annotations

ROUTES = ("/participants/insurance-match", "/api/participants/insurance-match")
PAGE_PATH = ROUTES[0]


def owns_route(path: str) -> bool:
    return path in ROUTES


def dispatch(handler, parsed, *, is_owner: bool, query=None, raw=None, csrf: str = "",
             state_loader=None) -> bool:
    if not owns_route(parsed.path):
        return False
    if not is_owner:
        handler._send_json({"code": "ACTION_FORBIDDEN", "message": "소유자만 볼 수 있습니다"}, 403)
        return True
    if raw is not None or str(getattr(handler, "command", "GET")).upper() != "GET":
        handler._send_json({"code": "METHOD_NOT_ALLOWED", "message": "조회만 할 수 있습니다"}, 405)
        return True
    if parsed.path == PAGE_PATH:
        handler._send_json({"code": "PAGE_REMOVED", "message": "삭제된 페이지입니다"}, 410)
        return True
    query = query or {}
    if state_loader is None:
        from . import insurance_income_match_service
        state_loader = insurance_income_match_service.build_state
    try:
        state = state_loader(query=query)
    except Exception:
        state = {"available": False, "code": "SOURCE_UNAVAILABLE",
                 "message": "보험 명단 또는 수입 자료를 불러올 수 없습니다", "counts": {}, "contracts": []}
    handler._send_json(state, 200 if state.get("available") else
                       400 if state.get('code') == 'INVALID_FILTER' else 503)
    return True
