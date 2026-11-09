"""Shared HTML error pages for browser requests.

The request handlers keep their JSON contracts for API and non-HTML clients.
When a browser asks for a page, they pass this complete document to the normal
board sender.  The sender then adds the application shell around the document.
"""

from __future__ import annotations

from html import escape
import inspect
from typing import Iterable


def wants_html(handler, path: str) -> bool:
    """Return whether *handler* explicitly requested an HTML page.

    An API path is never upgraded to HTML, even when a generic browser header
    happens to include ``text/html``.  ``*/*`` also stays on the existing JSON
    path so command line clients do not receive a shell document by accident.
    """

    if str(path or "").startswith("/api/"):
        return False
    headers = getattr(handler, "headers", None)
    try:
        accept = headers.get("Accept", "") if headers is not None else ""
    except AttributeError:
        accept = ""
    return "text/html" in str(accept or "").lower()


def send(handler, document: str, status: int) -> None:
    """Send an HTML error through either a production or test handler.

    ``Handler._send`` calls its status argument ``code``; lightweight route
    fakes in the existing tests call it ``status``.  Supporting both keeps the
    route contract focused on the response body and status code.
    """

    try:
        parameters = inspect.signature(handler._send).parameters
    except (AttributeError, TypeError, ValueError):
        parameters = {}
    if "code" in parameters:
        handler._send(document, code=status)
    else:
        handler._send(document, status=status)


def render(status: int, title: str, message: str,
           actions: Iterable[tuple[str, str]]) -> str:
    """Render a complete, shell-ready error document.

    ``actions`` contains user-visible link labels and local paths.  Escaping
    happens here so callers can pass the same trusted route constants used by
    JSON handlers without building markup themselves.
    """

    try:
        status_code = int(status)
    except (TypeError, ValueError):
        status_code = 500
    title_text = escape(str(title or ""), quote=False)
    message_text = escape(str(message or ""), quote=False)
    links = []
    for label, href in actions or ():
        links.append(
            "<a class='btn' href='{}'>{}</a>".format(
                escape(str(href or "/"), quote=True),
                escape(str(label or ""), quote=False),
            )
        )
    action_markup = "".join(links)
    return (
        "<!doctype html><html lang='ko'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title_text}</title>"
        "<style>"
        ".error-page{max-width:720px;margin:clamp(24px,8vh,72px) auto;"
        "padding:clamp(20px,4vw,40px);background:var(--shell-paper);"
        "border:1px solid var(--shell-line);border-radius:12px}"
        ".error-page h1{margin:0 0 12px;line-height:1.3}"
        ".error-page .error-message{margin:0;line-height:1.6}"
        ".error-page .error-actions{display:flex;flex-wrap:wrap;gap:10px;"
        "margin-top:24px}"
        "</style></head><body>"
        f"<main id='main' class='error-page' data-error-page=\"1\" data-status='{status_code}'>"
        f"<h1>{title_text}</h1>"
        f"<p class='error-message' role='alert'>{message_text}</p>"
        f"<nav class='error-actions' aria-label='다음 행동'>{action_markup}</nav>"
        "</main></body></html>"
    )
