"""REAL-REVIEW-001: the in-app screen for the actual-source comparison.

A separate module from `webapp.review_ui.py`, and that file is not touched: the
local `serve_review` contract it serves is unchanged. This one renders a screen
for the authenticated web app, so it fetches same-origin `/api/review/model`,
saves through `/api/review/decisions` and exports through `/api/review/export`.

Two rules shape everything here.

* No data is ever put into markup. Every source value, candidate value and
  stored choice reaches the page through `textContent`, never through an HTML
  string, so a value that happens to contain a tag is shown as text. The document
  this returns embeds no data and loads nothing external.
* A choice the user has not made yet is not a choice. Rows the user has not
  touched arrive blank, and a save sends the whole set including the blanks, so
  "I looked at this and left it" is a recorded answer and "I did not look" is
  not guessed at.

The saved revision is polled every two seconds so a second device's save is
visible, but a poll never overwrites a selection this device has not saved: it
reports that the saved set moved and leaves the pending choices alone, because
losing an unsaved decision to a background refresh is the one thing this screen
must not do.
"""

from __future__ import annotations

#: Rows per page. The dataset is 1,734 rows; fifty cards is what a reviewer can
#: actually read on a page, and search is how they reach the rest.
PAGE_SIZE = 50
#: The owner-only plan and apply routes, named here rather than written into the
#: page so the page and the server cannot end up on different paths.
APPLY_PLAN_URL = "/api/review/apply/plan"
APPLY_URL = "/api/review/apply"

#: How often the saved revision is re-read, in milliseconds. The board's own live
#: refresh uses the same interval, so the two agree on what "current" means.
POLL_MS = 2000

from .real_review_assets import _DOCUMENT



def render_real_review_ui(csrf_token: str = "") -> str:
    """The static review document.

    Only the CSRF token and the two numbers are substituted. No source value, no
    candidate value and no saved choice is placed in the document: the screen
    fetches them over the authenticated model route, so a copy of the HTML on
    its own carries no data.
    """
    from .review_guidance_ui import SCRIPT as guidance_script

    return (_DOCUMENT
            .replace("function buildCard(row, ordinal, total) {",
                     guidance_script + "\nfunction buildCard(row, ordinal, total) {")
            .replace("__PAGE_SIZE__", str(PAGE_SIZE))
            .replace("__POLL_MS__", str(POLL_MS))
            .replace("__APPLY_URL__", APPLY_URL)
            .replace("__PLAN_URL__", APPLY_PLAN_URL)
            .replace('<meta name="viewport"',
                     f'<meta name="csrf-token" content="{_escape_attr(csrf_token)}">'
                     '<meta name="viewport"'))


def _escape_attr(value: str) -> str:
    import html

    return html.escape("" if value is None else str(value), quote=True)
