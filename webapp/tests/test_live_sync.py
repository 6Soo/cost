"""Cross-screen live refresh: the change check, its scope, and its refusals.

The feature under test is a second browser noticing a save made in the first.
These tests drive the real `ledger_board.py` routes over real HTTP against a
real store, so a refusal is observed as a status and a change is observed as a
token that moved.

Synthetic accounts only. The owner is `syn-owner-O`, `syn-staff-V1` may read
trip A and `syn-staff-V2` may read trip B. There is no real Google login, no
customer data and no real database file from a deployment in this file.

The browser half, two real pages against the same server, is
`test_live_sync_browser.py`.
"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import ledger_design
from webapp import live_sync
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-O"
V1 = "syn-staff-V1"          # assigned to trip A
V2 = "syn-staff-V2"          # assigned to trip B
TRIP_A = "trip-demo-a"
TRIP_B = "trip-demo-b"
ROW_A = "expense-demo-c1"


def raw_get(port: int, path: str, user: str | None = None,
            headers: dict | None = None, timeout: float = 5.0) -> bytes:
    """One request over a raw socket, returning every byte the server sent.

    `urllib` is the wrong tool for this and cannot answer the question these tests
    ask. It reads exactly one response, honouring the first `Content-Length`, so a
    handler that writes a second document onto the same connection is invisible to
    it: the client sees a correct answer and the extra bytes are never looked at.
    A browser streaming the connection would see both, and a proxy in between could
    be handed the second one.

    The request is written by hand for the same reason. `HTTP/1.0` with
    `Connection: close` means the server closes when it is done, so the whole
    stream is exactly what it produced and nothing more.
    """
    request = f"GET {path} HTTP/1.0\r\n"
    if user:
        request += f"{access_control.SyntheticSessionAdapter.HEADER}: {user}\r\n"
    for name, value in (headers or {}).items():
        request += f"{name}: {value}\r\n"
    request += "Connection: close\r\n\r\n"
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(request.encode("utf-8"))
        sock.settimeout(timeout)
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()


def response_count(raw: bytes) -> int:
    """How many HTTP responses the server put on this connection."""
    return raw.count(b"HTTP/1.")


def normalise_requests(markup: str) -> str:
    """Blank out the per-render client request ids.

    The restore form in the archived drawer and the row forms carry a fresh
    `client_request_id` on every render, which is what stops a replayed request
    from being mistaken for a new one. Two renders of the same region therefore
    differ in exactly those values and nowhere else, so comparing them means
    ignoring them. Anything else that differs is a real disagreement and the
    comparison below will catch it.
    """
    import re

    return re.sub(r"value='[0-9a-f]{32}'", "value='<request-id>'", markup)


def live_blocks(bundle: str) -> list:
    """The top-level region elements of a fragment bundle, as (name, source).

    Extracted by tracking `div` depth rather than by matching `</div></div>`: the
    regions contain tables, lists and nested divs of their own, so a pattern that
    assumes a fixed closing sequence finds a prefix rather than the element. The
    browser swaps in exactly these elements, so a test built on this operates on
    what the browser would actually put on the page.
    """
    import re

    found: list = []
    index = 0
    depth = 0
    for match in re.finditer(r"<div\b[^>]*>|</div>", bundle):
        if match.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                block = bundle[index:match.end()]
                name = re.search(r"data-live='([^']+)'", block[:200])
                if name:
                    found.append((name.group(1), block))
        else:
            if depth == 0:
                index = match.start()
            depth += 1
    return found


def swap_regions(page: str, bundle: str) -> str:
    """The swap the browser performs, done to the markup as text.

    The client looks the region up by `id` and puts the fetched element in its
    place, so this reproduces that: the existing element's whole source text is
    replaced by the fetched block's. Reproducing the same lookup and the same
    replacement is the point — a bug in either is a bug the test has to see.
    """
    for name, block in live_blocks(bundle):
        page = _replace_by_id(page, name, block)
    return page


def _replace_by_id(page: str, element_id: str, block: str) -> str:
    """Replace the div carrying `id=element_id` with `block`, found by depth."""
    import re

    match = re.search(rf"<div id='{re.escape(element_id)}'\b[^>]*>", page)
    if match is None:
        return page
    depth = 0
    for tag in re.finditer(r"<div\b[^>]*>|</div>", page[match.start():]):
        depth += -1 if tag.group(0).startswith("</") else 1
        if depth == 0:
            end = match.start() + tag.end()
            return page[:match.start()] + block + page[end:]
    return page


class LiveSyncStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "live.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        self.seed()

    def tearDown(self):
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    # ------------------------------------------------------------- helpers
    def restart_server(self):
        """Stop this server and start another one on the same database.

        A real restart, not a store reopen: a new `serve()`, a new store and a
        new access store over the same file. Anything that only lived in the old
        process is gone, which is the point.
        """
        db_path = self.store.path
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.store.close()
        self.store = LedgerStore(db_path)
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False,
                                      db_path=db_path)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)

    def seed(self):
        self.access.ensure_owner(OWNER)
        for user in (V1, V2):
            self.access.create_account(user_id=user,
                                       role=access_control.ROLE_VIEWER)
        # A viewer needs an approved application and an active connection before
        # an assignment grants anything: `visible_tabs` requires all three. The
        # link is made here through the store's own methods rather than over
        # HTTP, so the fixture does not depend on the routes under test.
        for index, (user, tab, person) in enumerate((
                (V1, TRIP_A, "rp-live-1"), (V2, TRIP_B, "rp-live-2")), start=1):
            self.access.register_reservation_person(
                reservation_person_id=person, display_name=f"합성 담당자 {index}")
            application = self.access.create_application(
                user_id=user, requested_name=f"합성 담당자 {index}",
                nickname=f"담당 {index}", description="합성 링크",
                client_request_id=f"app-live-{index}")
            self.access.approve_application(
                application_id=application["application_id"], owner_id=OWNER,
                expected_revision=1, reservation_person_id=person,
                client_request_id=f"dec-live-{index}")
            self.access.apply_assignment_snapshot(
                user_id=user,
                items=[{"tab_id": tab, "snapshot_revision": 1,
                        "state": access_control.ASSIGN_ACTIVE}],
                source_version="src-live", complete=False)

    def api(self, path, user=None, headers=None, method="GET"):
        head = dict(headers or {})
        if user:
            head[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers=head, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def raw(self, path, user=None, headers=None):
        return raw_get(self.port, path, user, headers)

    def live_fragment_via_raw(self, tab=TRIP_A, user=OWNER):
        """The fragment answer, read off a raw socket and split on the status line.

        The split is what makes the count meaningful: a second document on the same
        connection shows up as a second status line, whatever its content.
        """
        raw = self.raw(f"/api/live/state?tab={tab}", user,
                       {"X-Part": "live-state"})
        parts = raw.split(b"HTTP/1.")
        bodies = [p.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in p else b""
                  for p in parts[1:]]
        return raw, bodies

    def api_json(self, path, user=None, headers=None):
        status, body, response_headers = self.api(path, user, headers)
        try:
            return status, json.loads(body.decode("utf-8")), response_headers
        except ValueError:
            return status, None, response_headers

    def poll(self, tab="", user=None, token=None, headers=None):
        query = []
        if tab:
            query.append(f"tab={tab}")
        if token:
            query.append(f"token={token}")
        path = "/api/live/state" + ("?" + "&".join(query) if query else "")
        return self.api_json(path, user, headers)

    def save(self, row_id=ROW_A, **changes):
        row = self.store.get_row(row_id)
        return self.store.save(
            row_id=row_id, expected_revision=row["revision"],
            client_request_id=f"live-{row['revision']}-{row_id}-"
                              f"{sorted(changes)[0]}",
            change_mode="exception", changes=changes)

    def fill_trip_b(self):
        """Give trip B a row of its own, so a save there is a real change there.

        The synthetic board seeds trip B empty. A test that needs "a save in
        another trip" has to make that trip hold something first, otherwise it
        would be testing a no-op.
        """
        self.save("expense-demo-c4", display_tab_id=TRIP_B,
                  description="B 여행으로 옮긴 행")
        return "expense-demo-c4"

    # ------------------------------------------- one response per request
    def test_the_json_poll_writes_exactly_one_response(self):
        """The blocking defect: a poll must put one document on the connection.

        `_phase7_get` answers the authenticated poll and then `do_GET` fell through
        to the no-session branch, which wrote a second, owner-scoped document
        behind it. A client that reads the first `Content-Length` sees the correct
        viewer answer; a client that reads the stream sees the owner's token as
        well. Counting status lines is the only way to see the second one.
        """
        raw = self.raw(f"/api/live/state?tab={TRIP_A}", V1)
        self.assertEqual(response_count(raw), 1,
                         f"expected one response, got {response_count(raw)}")
        self.assertIn(b'"role": "viewer"', raw)
        self.assertNotIn(b'"role": "owner"', raw)

    def test_the_fragment_poll_writes_exactly_one_response(self):
        raw, bodies = self.live_fragment_via_raw(TRIP_A, V1)
        self.assertEqual(response_count(raw), 1,
                         f"expected one response, got {response_count(raw)}")
        self.assertEqual(len(bodies), 1)
        # the single body is the viewer's own trips, not a second owner bundle
        self.assertIn(b"data-live='live-viewer'", bodies[0])
        self.assertNotIn(b"data-live='live-rows'", bodies[0],
                         "an owner fragment bundle followed a viewer fragment")
        self.assertNotIn(TRIP_B.encode("utf-8"), bodies[0])

    def test_a_denied_poll_writes_exactly_one_response(self):
        """A refusal is an answer, so it ends the request like any other.

        Each refusal is checked for its own status as well as for being the only
        one, so a test that passed on a single 404 could not hide a second document
        carrying a different status.
        """
        cases = (("viewer on a trip it may not read", V1, TRIP_B, b"404"),
                 ("no session at all", None, TRIP_A, b"401"),
                 ("a fragment request for a trip it may not read", V1, TRIP_B,
                  b"404"))
        for label, user, tab, status in cases:
            headers = {"X-Part": "live-state"} if "fragment" in label else None
            raw = self.raw(f"/api/live/state?tab={tab}", user, headers)
            self.assertEqual(response_count(raw), 1, label)
            self.assertIn(status, raw, label)

    def test_the_owner_poll_writes_exactly_one_response(self):
        raw = self.raw(f"/api/live/state?tab={TRIP_A}", OWNER)
        self.assertEqual(response_count(raw), 1)
        self.assertIn(b'"role": "owner"', raw)
        raw, bodies = self.live_fragment_via_raw(TRIP_A, OWNER)
        self.assertEqual(response_count(raw), 1)
        self.assertEqual(len(bodies), 1)

    def test_the_initial_board_writes_exactly_one_response(self):
        """Loading the board must not put a second document on the connection.

        This is the same defect as the poll, on the page. `_phase7_get` answers a
        viewer's `/board` with its own board, and then `do_GET` carried on to the
        owner's rendering, so the connection carried two responses, two `live-config`
        elements, and an owner token in the second one. A viewer client reads the
        first response and never sees it, which is why only a raw socket shows it.

        Each case is checked for the response count, the number of `live-config`
        elements, and the role inside that config, because a single response can
        still carry the wrong role and a fix that only counted status lines would
        not notice.
        """
        # An owner and a viewer each get one page. A caller with no session gets the
        # board's own JSON refusal, which is not a page at all, so it is checked for
        # the refusal and for carrying no config rather than for a document.
        for label, user, tab, role in (
                ("owner", OWNER, TRIP_A, b'"role": "owner"'),
                ("viewer", V1, TRIP_A, b'"role": "viewer"')):
            raw = self.raw(f"/board?tab={tab}", user)
            body = raw.split(b"\r\n\r\n", 1)[-1]
            self.assertEqual(response_count(raw), 1,
                             f"{label}: {raw[:400]!r}")
            self.assertIn(b"200", raw, label)
            self.assertEqual(body.count(b"<html"), 1,
                             f"{label} board carried more than one document")
            # exactly one, and it is this caller's: two is the defect, and one with
            # the wrong role in it is the same defect seen from inside.
            self.assertEqual(body.count(b"id='live-config'"), 1,
                             f"{label} board carried more than one config")
            self.assertIn(role, body, label)

        raw = self.raw(f"/board?tab={TRIP_A}", None)
        self.assertEqual(response_count(raw), 1, f"no session: {raw[:400]!r}")
        self.assertIn(b"401", raw)
        self.assertNotIn(b"live-config", raw,
                         "a refused board still shipped a live config")

    def test_the_viewer_initial_board_never_carries_an_owner_token(self):
        """The second response was an owner config, and the token in it was real.

        A viewer's own token covers only its own trips; the owner's covers
        everything. Shipping the owner's in a second body would let a viewer track
        trips it may not read, so this checks the byte is absent rather than only
        that the response count is one.
        """
        from webapp import live_sync as live_sync_module

        owner_token = live_sync_module.owner_token(self.store, TRIP_B)
        raw = self.raw(f"/board?tab={TRIP_A}", V1)
        self.assertEqual(response_count(raw), 1)
        self.assertNotIn(owner_token.encode("ascii"), raw)

    def test_a_stale_session_poll_writes_exactly_one_response(self):
        generation = self.access.session_generation(V1)
        self.access.bump_session_generation(V1)
        raw = self.raw(f"/api/live/state?tab={TRIP_A}", V1,
                       {access_control.SyntheticSessionAdapter.GENERATION_HEADER:
                        str(generation)})
        self.assertEqual(response_count(raw), 1)
        self.assertIn(b"SESSION_STALE", raw)

    # ------------------------------------------------- the fragment markup
    def test_a_region_is_written_by_one_renderer_on_both_paths(self):
        """The page and a fragment must not have two renderers for one region.

        The earlier version built the whole rail and sliced the region back out of
        the string, which took the footer and the mask element with it, and wrapped
        a region that already had a wrapper. Both are only preventable by there
        being one function each: `nav_region` for the element the page embeds and
        the inner one a fragment carries, and likewise for the rows. If a second
        renderer appears for either, this fails on the difference between what the
        two paths produce.
        """
        self.as_owner()
        page = ledger_design.page(TRIP_A)
        nav_region = ledger_design.nav_region(TRIP_A)
        rows_region = ledger_design.rows_region(TRIP_A)
        # each region's element appears exactly once on the page
        self.assertEqual(page.count("<div id='live-nav'>"), 1)
        self.assertEqual(page.count("<div id='live-rows'>"), 1)
        # and the fragment's inner markup is that same element's contents
        for region, part in ((nav_region, ledger_design.nav_part(TRIP_A)),
                             (rows_region, ledger_design.rows_part(TRIP_A))):
            self.assertTrue(region.endswith("</div>"))
            inner = region[len("<div id='live-nav'>") if "live-nav" in region
                           else len("<div id='live-rows'>"):-len("</div>")]
            self.assertEqual(part, inner)
        # the sidebar elements that sit outside the region are not inside it
        for chrome in ("nav-mask", "tripq"):
            self.assertNotIn(chrome, nav_region, chrome)
            self.assertNotIn(chrome, rows_region, chrome)
        # and they are on the page exactly once
        for chrome in ("id='nav-mask'", "id='tripq'"):
            self.assertEqual(page.count(chrome), 1, chrome)
        # the board-only record note is on the page once and never in a fragment
        self.assertNotIn("ledger-note", nav_region)
        self.assertNotIn("ledger-note", rows_region)
        self.assertEqual(page.count("id='ledger-note'"), 0)

    def test_a_fragment_bundle_carries_no_duplicate_ids(self):
        """A bundle is parsed as a document, so its ids must be unique.

        `getElementById` returns the first match, so a region that arrived with a
        second copy of itself would have its first copy replaced and its second
        left behind: the screen would keep showing a stale region and every later
        refresh would target the wrong element.
        """
        import re

        html = live_sync.owner_fragments(self.store, TRIP_A, "", "", "", "")
        ids = re.findall(r"\sid='([^']+)'", html)
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(duplicates, [], f"duplicate ids in the bundle: {duplicates}")
        for region in ("live-nav", "live-sum", "live-rows"):
            self.assertEqual(ids.count(region), 1, region)

    def test_a_fragment_bundle_carries_no_sidebar_chrome(self):
        """The nav region is the region, not the rail around it.

        The rail's footer and its mask element live outside the swappable region on
        screen. A fragment that carried them would append a second footer and a
        second `nav-mask` to the page on every refresh.
        """
        html = live_sync.owner_fragments(self.store, TRIP_A, "", "", "", "")
        self.assertNotIn("nav-mask", html)
        self.assertNotIn("ledger-note", html)
        self.assertNotIn("id='nav'", html)
        self.assertNotIn("id='tripq'", html,
                         "the search box is outside the region and must not be "
                         "swapped: it holds what the user typed")

    def test_a_fragment_region_is_the_same_markup_the_page_renders(self):
        """One renderer for a region, so a refresh cannot disagree with a load.

        The page and the fragment are compared as text rather than by eye: the page
        must contain the region markup a fragment carries, character for character.
        """
        page = ledger_design.page(TRIP_A)
        self.assertIn(normalise_requests(ledger_design.nav_part(TRIP_A)),
                      normalise_requests(page))
        self.assertIn(normalise_requests(ledger_design.rows_part(TRIP_A)),
                      normalise_requests(page))

    def test_a_refreshed_page_keeps_one_of_each_region_id(self):
        """Repeated refreshes must not accumulate regions.

        A bundle whose block nested its own wrapper inside the region it replaces
        leaves one extra element per refresh. `getElementById` then finds the stale
        copy and the screen quietly stops updating after the first swap, so the
        count is checked after every round rather than only at the end.
        """
        import re

        page = ledger_design.page(TRIP_A)
        for round_number in range(1, 4):
            bundle = live_sync.owner_fragments(
                self.store, TRIP_A, "", "", "", "")
            names = [name for name, _ in live_blocks(bundle)]
            self.assertEqual(sorted(names), ["live-nav", "live-rows", "live-sum"],
                             f"round {round_number}: bundle regions {names}")
            page = swap_regions(page, bundle)
            ids = re.findall(r"\sid='([^']+)'", page)
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            self.assertEqual(duplicates, [],
                             f"round {round_number}: {duplicates}")
            # the sidebar chrome is still exactly one of each
            self.assertEqual(page.count("id='nav-mask'"), 1,
                             f"round {round_number}")
            self.assertEqual(page.count("id='ledger-note'"), 0,
                             f"round {round_number}")
            # and the search box the region must not swallow is still there
            self.assertEqual(page.count("id='tripq'"), 1,
                             f"round {round_number}")

    # --------------------------------------- the view state a fragment needs
    def test_a_fragment_keeps_the_archived_drawer_and_the_selected_row(self):
        """The drawer state and the open row are part of the view, not extras.

        A refresh that dropped `arch` would close a drawer the user opened, and one
        that dropped `row` would come back with nothing selected. Both are checked
        on the rendered markup, because that is where a lost parameter shows up.
        """
        self.as_owner()
        self.fill_trip_b()
        self.store.conn.execute("UPDATE trip_tabs SET starts_on='2026-07-01', ends_on='2026-07-03' WHERE tab_id=?", (TRIP_B,))
        self.store.conn.commit()
        self.store.save_trip_meta(
            tab_id=TRIP_B, expected_revision=self.store.get_trip(TRIP_B)["revision"],
            archived=True, client_request_id="live-arch-1", actor=OWNER)
        html = ledger_design.page(TRIP_A, archived="1", selected=ROW_A)
        # the drawer is open on screen, and the row is the selected one
        self.assertIn("id='archived'", html)
        self.assertIn("aria-selected=\"true\"", html)
        # and a fragment asked with the same state agrees
        page = normalise_requests(html)
        self.assertIn(normalise_requests(
            ledger_design.nav_part(TRIP_A, archived="1")), page)
        self.assertIn(normalise_requests(
            ledger_design.rows_part(TRIP_A, selected=ROW_A, archived="1")), page)
        # a fragment asked WITHOUT the state would not agree, which is what makes
        # the two assertions above about the state and not about the renderer
        self.assertNotIn(
            normalise_requests(ledger_design.nav_part(TRIP_A)),
            page.replace("/board?tab=trip-demo-a&arch=1", "/board?tab=trip-demo-a"))

    def test_the_client_state_url_carries_the_view_state(self):
        """The poll URL has to carry what the screen is showing.

        `state_url` is what the browser asks, so a missing parameter here is a
        refresh that quietly forgets the drawer or the selected row.
        """
        url = live_sync.state_url(TRIP_A, "호텔", "ex", archived="1",
                                  selected=ROW_A)
        self.assertIn("tab=" + TRIP_A, url)
        self.assertIn("q=", url)
        self.assertIn("kind=ex", url)
        self.assertIn("arch=1", url)
        self.assertIn(f"row={ROW_A}", url)
        # and the page hands that same URL to the script
        config = live_sync.client_config("t" * live_sync.TOKEN_LENGTH, TRIP_A,
                                         archived="1", selected=ROW_A)
        self.assertIn("arch=1", config)
        self.assertIn(f"row={ROW_A}", config)

    # ----------------------------------------------- the unassigned bucket
    def test_the_unclassified_bucket_is_not_empty_just_because_it_is_not_a_trip(self):
        """분류대기 is not in `trip_tabs`, and its rows must still refresh.

        A guard that asked "is this a real trip" would return an empty fragment for
        the unassigned bucket, and rows added to it or moved into it would never
        appear however often the page was checked.
        """
        unassigned = [r for r in self.store.list_tab_rows(None)]
        self.assertTrue(unassigned, "the fixture needs an unassigned row")
        fragment = ledger_design.rows_part("unclassified")
        self.assertTrue(fragment, "the unassigned bucket rendered nothing")
        for row in unassigned:
            self.assertIn(row["row_id"], fragment, row["row_id"])

    def _unassigned_row_ids(self):
        return {row["row_id"] for row in self.store.list_tab_rows(None)}

    def as_owner(self):
        """Render as the owner, the way a request thread would.

        `current_role()` answers "viewer" when no role has been decided on this
        thread and enforcement is on, which is the right default for a request that
        has not been through `resolve_role`. A test calling a renderer directly has
        to say which role it is asking for, or the viewer's allowlist filter runs
        with no session and hides every trip.
        """
        board_mod._ROLE_LOCAL.role = "owner"
        board_mod._ROLE_LOCAL.session = None
        self.addCleanup(self._clear_role)

    def _clear_role(self):
        board_mod._ROLE_LOCAL.role = None
        board_mod._ROLE_LOCAL.session = None

    def test_a_row_moved_into_the_unassigned_bucket_shows_up(self):
        """A move into 분류대기 is a change the fragment has to carry, both ways.

        Checked from both sides: the row appears in the unassigned list and leaves
        the tab it came from, in the same pass. A renderer that only handled the
        destination would leave the user looking at a row in two places.
        """
        self.assertNotIn(ROW_A, self._unassigned_row_ids())
        self.assertIn(ROW_A, ledger_design.rows_part(TRIP_A))
        self.save(ROW_A, display_tab_id=None)
        self.assertIn(ROW_A, self._unassigned_row_ids())
        self.assertIn(ROW_A, ledger_design.rows_part("unclassified"))
        self.assertNotIn(ROW_A, ledger_design.rows_part(TRIP_A))

    def test_a_row_moved_out_of_the_unassigned_bucket_disappears(self):
        """And the same move in the other direction."""
        unassigned = sorted(self._unassigned_row_ids())
        self.assertTrue(unassigned, "the fixture needs an unassigned row")
        row_id = unassigned[0]
        self.assertIn(row_id, ledger_design.rows_part("unclassified"))
        self.save(row_id, display_tab_id=TRIP_A)
        self.assertNotIn(row_id, ledger_design.rows_part("unclassified"))
        self.assertIn(row_id, ledger_design.rows_part(TRIP_A))

    def test_a_new_unassigned_row_reaches_the_fragment(self):
        """A genuinely new row, not a move, so the insert path is covered too.

        A move between two existing rows and an insert are different code paths in
        the store and different ones in the renderer. Only the insert proves a row
        that was never on the screen can appear on it.

        The store's manual-expense entry point stores `display_tab_id` as given, and
        the unassigned bucket is the `NULL` one, so the row is created in a trip and
        then moved to unassigned. That is the two real steps a new unassigned row
        takes, and each is checked on the fragment it should have changed.
        """
        self.as_owner()
        before = self._unassigned_row_ids()
        created = self.store.create_manual_expense(
            fields={"display_tab_id": TRIP_A, "occurred_on": "2026-05-01",
                    "amount_krw": 12345, "item": "새 수기 지출",
                    "description": "분류대기 확인용", "pay_method": "현금"},
            client_request_id=f"live-new-{time.time_ns()}", actor=OWNER)
        row_id = created["row_id"]
        # it lands in the trip first
        self.assertIn(row_id, ledger_design.rows_part(TRIP_A))
        self.assertNotIn(row_id, before)
        # and moving it to unassigned puts it in the bucket's fragment
        self.save(row_id, display_tab_id=None)
        self.assertIn(row_id, self._unassigned_row_ids(),
                      "the row is not unassigned after the move")
        fragment = ledger_design.rows_part("unclassified")
        self.assertIn(row_id, fragment)
        self.assertIn("새 수기 지출", fragment)
        self.assertNotIn(row_id, ledger_design.rows_part(TRIP_A))

    # --------------------------------------------------------- the token
    def test_a_poll_reports_the_current_token_and_whether_it_moved(self):
        status, body, headers = self.poll(TRIP_A, OWNER)
        self.assertEqual(status, 200)
        # a page that presents nothing is told it is out of date, so it renders
        # once rather than sitting on a screen it cannot vouch for
        self.assertTrue(body["changed"], "no token presented yet")
        self.assertTrue(body["token"])
        self.assertEqual(body["role"], "owner")
        # the interval the client is told to use is the one this module sets
        self.assertEqual(body["poll_interval_ms"], live_sync.POLL_INTERVAL_MS)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        # a poll that presents the current token is told nothing moved
        status, body, _ = self.poll(TRIP_A, OWNER, token=body["token"])
        self.assertEqual(status, 200)
        self.assertFalse(body["changed"])
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_a_save_moves_the_token_and_the_next_poll_says_so(self):
        _status, first, _ = self.poll(TRIP_A, OWNER)
        self.save(ROW_A, description="다른 브라우저에서 저장")
        status, body, _ = self.poll(TRIP_A, OWNER, token=first["token"])
        self.assertEqual(status, 200)
        self.assertTrue(body["changed"], "a save in this tab must move the token")
        self.assertNotEqual(body["token"], first["token"])
        # and the new token is now the current one
        _status, again, _ = self.poll(TRIP_A, OWNER, token=body["token"])
        self.assertFalse(again["changed"])

    def test_a_save_in_another_trip_still_moves_the_owner_screen(self):
        # the rail shows a total for every trip, so a save the owner is not
        # looking at has to be noticed
        row_b = self.fill_trip_b()
        _status, first, _ = self.poll(TRIP_A, OWNER)
        self.save(row_b, description="B 여행 저장")
        _status, body, _ = self.poll(TRIP_A, OWNER, token=first["token"])
        self.assertTrue(body["changed"])

    def test_the_token_is_stable_for_unchanged_data(self):
        first = live_sync.owner_token(self.store, TRIP_A)
        for _ in range(3):
            self.assertEqual(live_sync.owner_token(self.store, TRIP_A), first)

    def test_a_restart_alone_is_not_an_edit(self):
        """A server restart must not move the token.

        The token is derived from the database, so the same rows give the same
        token from a different server process. If it were an in-memory counter, a
        restart would look like a change nobody made, and every open draft would
        be replaced by a screen the user never asked for.

        The restart is real: this server is shut down and another is started on
        the same database file, with its own store and its own access store.
        """
        # a real save first, so "the token did not move" cannot be mistaken for
        # "the token never moves"
        self.save(ROW_A, description="재시작 전에 저장한 값")
        _status, before, _ = self.poll(TRIP_A, OWNER)

        self.restart_server()

        # the new process computes the same token from the same rows
        self.assertEqual(live_sync.owner_token(self.store, TRIP_A),
                         before["token"])
        status, after, headers = self.poll(TRIP_A, OWNER,
                                           token=before["token"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertFalse(
            after["changed"],
            "a restart is not an edit: the open tab must not discard its draft")
        self.assertEqual(after["token"], before["token"])

    def test_a_save_before_a_restart_is_still_seen_after_it(self):
        """The other half: the restart hides nothing either.

        A token derived from the database keeps its meaning across a restart, so
        a change made before the restart is still a change afterwards. If a
        restart reset the token, an edit made in the seconds before the process
        went down would be lost with nothing to say so.
        """
        _status, before, _ = self.poll(TRIP_A, OWNER)
        self.save(ROW_A, description="재시작 전에 저장한 값")
        self.restart_server()
        _status, after, _ = self.poll(TRIP_A, OWNER, token=before["token"])
        self.assertTrue(after["changed"])

    def test_a_missing_or_malformed_token_counts_as_changed(self):
        _status, body, _ = self.poll(TRIP_A, OWNER)
        self.assertTrue(live_sync.tokens_differ("", body["token"]))
        self.assertTrue(live_sync.tokens_differ(None, body["token"]))
        self.assertTrue(live_sync.tokens_differ(body["token"] + "x", body["token"]))
        self.assertFalse(live_sync.tokens_differ(body["token"], body["token"]))

    # --------------------------------------------------------- the scope
    def test_a_viewer_token_covers_only_its_own_trips(self):
        row_b = self.fill_trip_b()
        _status, first, _ = self.poll(TRIP_A, V1)
        # a save in the trip the viewer may not read
        self.save(row_b, description="B 여행 저장")
        _status, body, _ = self.poll(TRIP_A, V1, token=first["token"])
        self.assertFalse(
            body["changed"],
            "another trip's save must not move a viewer's token")
        # a save in its own trip does
        self.save(ROW_A, description="내 여행 저장")
        _status, body, _ = self.poll(TRIP_A, V1, token=first["token"])
        self.assertTrue(body["changed"])

    def test_a_viewer_poll_for_a_trip_it_may_not_read_is_404(self):
        # 404 rather than 403, and the existing refusal body, so a poll cannot be
        # used to map which trips exist
        status, body, headers = self.api(f"/api/live/state?tab={TRIP_B}", V1)
        self.assertEqual(status, 404)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertNotIn(TRIP_A, body.decode("utf-8"))
        self.assertNotIn(TRIP_B, body.decode("utf-8"))

    def test_a_poll_with_no_session_is_401(self):
        status, body, _headers = self.api(f"/api/live/state?tab={TRIP_A}")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body.decode("utf-8"))["code"],
                         access_control.AUTH_REQUIRED)

    def test_a_stale_session_generation_still_answers_401(self):
        """A permission change invalidates the old session, polls included.

        A poll is a read of ledger data, so it is refused by the same generation
        check as a page load. Without this a revoked viewer's open tab would keep
        being told the current token.
        """
        _status, body, _ = self.api_json(f"/api/live/state?tab={TRIP_A}", V1)
        self.assertEqual(body["token"],
                         live_sync.viewer_token(self.store, {TRIP_A}))
        # an owner logs the viewer out, so the generation moves
        generation = self.access.session_generation(V1)
        self.access.bump_session_generation(V1)
        # the open tab still presents the old generation, exactly as a cookie
        # signed before the logout would
        headers = {access_control.SyntheticSessionAdapter.GENERATION_HEADER:
                   str(generation)}
        status, raw, _ = self.api(f"/api/live/state?tab={TRIP_A}", V1,
                                  headers=headers)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw.decode("utf-8"))["code"],
                         "SESSION_STALE")

    def test_a_revoked_assignment_shrinks_the_viewer_scope(self):
        _status, first, _ = self.poll(TRIP_A, V1)
        # before the revoke the trip is readable
        self.assertTrue(self.access.can_view_tab(V1, TRIP_A))
        self.access.apply_assignment_snapshot(
            user_id=V1, items=[{"tab_id": TRIP_A, "snapshot_revision": 2,
                                "state": access_control.ASSIGN_REVOKED}],
            source_version="src-live-2", complete=False)
        # the trip itself is now refused, on the poll exactly as on a page load
        status, _body, _ = self.poll(TRIP_A, V1)
        self.assertEqual(status, 404)
        # and the viewer's own scope no longer contains it, so the token the
        # still-open tab holds is not the token the server would give it now
        status, after, _ = self.poll(user=V1, token=first["token"])
        self.assertEqual(status, 200)
        self.assertTrue(after["changed"])
        self.assertNotEqual(after["token"], first["token"])
        self.assertNotIn(TRIP_A,
                         live_sync.scope_token(self.store, [TRIP_A]),
                         "sanity: the scope is computed from the tabs given")

    def test_the_poll_body_carries_no_ledger_content(self):
        _status, body, _ = self.poll(TRIP_A, V1)
        blob = json.dumps(body, ensure_ascii=False)
        for marker in ("operator_note", "memo_internal", "card_last4",
                       "expense-demo", "amount_krw", TRIP_B, "change_count"):
            self.assertNotIn(marker, blob, marker)
        # the token is a fixed-width hex digest: it carries no row id, no amount
        # and no length, so nothing can be read back out of it
        self.assertEqual(len(body["token"]), live_sync.TOKEN_LENGTH)
        int(body["token"], 16)

    # --------------------------------------------------------- fragments
    def test_the_owner_fragment_bundle_has_the_swappable_regions(self):
        status, body, headers = self.api(
            f"/api/live/state?tab={TRIP_A}", OWNER,
            {"X-Part": "live-state"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        html = body.decode("utf-8")
        for region in ("live-nav", "live-sum", "live-rows"):
            self.assertIn(f"data-live='{region}'", html, region)
        # the edit panel is not one of them: replacing a panel is what would
        # destroy a draft
        self.assertNotIn("id='panel'", html)

    def test_the_owner_fragment_bundle_follows_a_save(self):
        _status, body, _headers = self.api(
            f"/api/live/state?tab={TRIP_A}", OWNER, {"X-Part": "live-state"})
        before = body.decode("utf-8")
        self.save(ROW_A, description="프래그먼트에 보여야 하는 값")
        _status, body, _headers = self.api(
            f"/api/live/state?tab={TRIP_A}", OWNER, {"X-Part": "live-state"})
        after = body.decode("utf-8")
        self.assertIn("프래그먼트에 보여야 하는 값", after)
        self.assertNotIn("프래그먼트에 보여야 하는 값", before)

    def test_a_viewer_fragment_names_only_its_own_trips(self):
        status, body, headers = self.api(
            f"/api/live/state?tab={TRIP_A}", V1, {"X-Part": "live-state"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        html = body.decode("utf-8")
        self.assertIn("data-live='live-viewer'", html)
        self.assertIn(TRIP_A, html)
        self.assertNotIn(TRIP_B, html)
        for denied in access_control.VIEWER_DENIED_FIELDS:
            self.assertNotIn(denied, html, denied)

    def test_a_viewer_fragment_for_a_trip_it_may_not_read_is_404(self):
        status, _body, _headers = self.api(
            f"/api/live/state?tab={TRIP_B}", V1, {"X-Part": "live-state"})
        self.assertEqual(status, 404)

    # ------------------------------------------------------- the screen
    def test_the_board_page_carries_the_config_and_the_script(self):
        status, body, headers = self.api(f"/board?tab={TRIP_A}", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        html = body.decode("utf-8")
        self.assertIn("id='live-config'", html)
        self.assertIn("id='live-nav'", html)
        self.assertIn("id='live-sum'", html)
        self.assertIn("id='live-rows'", html)
        self.assertIn("id='live-status'", html)
        self.assertIn("__ledgerLiveSync", html)
        # the token on the page is the one the endpoint reports
        _status, state, _ = self.poll(TRIP_A, OWNER)
        self.assertIn(state["token"], html)

    def test_the_viewer_board_carries_a_config_scoped_to_its_trips(self):
        status, body, _ = self.api("/board", V1)
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("id='live-viewer'", html)
        self.assertIn("id='live-config'", html)
        self.assertNotIn(TRIP_B, html)
        _status, state, _ = self.poll(TRIP_A, V1)
        self.assertIn(state["token"], html)

    def test_the_config_token_escapes_markup(self):
        # a token is a hex digest today, but the config is JSON in a script
        # element, so a value carrying markup must not close the element
        body = live_sync.client_config("</script><img src=x onerror=1>",
                                       TRIP_A)
        self.assertNotIn("</script><img", body)
        self.assertIn("\\u003c/script", body)

    # ------------------------------------------------ the draft guard
    def test_a_draft_is_not_covered_by_a_fragment(self):
        """The panel is outside every swappable region, by construction.

        This is the property the guard relies on, so it is asserted on the
        rendered page rather than on the script: the open form's fields live in
        `panel-slot`, and no fragment bundle contains them.
        """
        status, body, _ = self.api(f"/board?tab={TRIP_A}&row={ROW_A}", OWNER)
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("id='panel-slot'", html)
        self.assertIn("id='panel'", html)
        _status, fragments, _ = self.api(
            f"/api/live/state?tab={TRIP_A}", OWNER, {"X-Part": "live-state"})
        text = fragments.decode("utf-8")
        self.assertNotIn("f-description", text)
        self.assertNotIn("name='csrf'", text)
        self.assertNotIn("expected_revision", text)


class LiveSyncTokenScopeTests(unittest.TestCase):
    """`scope_token` on its own, with no server and no HTTP."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = LedgerStore(Path(self.tmp) / "scope.sqlite")
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, starts_on, ends_on)"
            " VALUES ('t-a','A','2026-01-01','2026-01-02')")
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, starts_on, ends_on)"
            " VALUES ('t-b','B','2026-02-01','2026-02-02')")
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES ('r-a','expense','t-a',1,'{\"item\":\"x\"}')")
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES ('r-b','expense','t-b',1,'{\"item\":\"y\"}')")
        self.store.conn.commit()

    def tearDown(self):
        self.store.close()

    def test_the_scope_is_exactly_the_tabs_asked_for(self):
        a_only = live_sync.scope_token(self.store, ["t-a"])
        self.assertNotEqual(a_only, live_sync.scope_token(self.store, ["t-b"]))
        self.assertNotEqual(a_only, live_sync.scope_token(self.store, ["t-a", "t-b"]))
        # and asking twice gives the same answer
        self.assertEqual(a_only, live_sync.scope_token(self.store, ["t-a"]))

    def test_a_row_revision_moves_the_token_of_its_tab_only(self):
        before_a = live_sync.scope_token(self.store, ["t-a"])
        before_b = live_sync.scope_token(self.store, ["t-b"])
        self.store.conn.execute(
            "UPDATE board_rows SET revision=2 WHERE row_id='r-a'")
        self.store.conn.commit()
        self.assertNotEqual(before_a, live_sync.scope_token(self.store, ["t-a"]))
        self.assertEqual(before_b, live_sync.scope_token(self.store, ["t-b"]))

    def test_a_trip_revision_moves_the_token(self):
        before = live_sync.scope_token(self.store, ["t-a"])
        self.store.conn.execute(
            "UPDATE trip_tabs SET revision=2 WHERE tab_id='t-a'")
        self.store.conn.commit()
        self.assertNotEqual(before, live_sync.scope_token(self.store, ["t-a"]))

    def test_an_allocation_moves_the_token_of_its_tab_only(self):
        before_a = live_sync.scope_token(self.store, ["t-a"])
        before_b = live_sync.scope_token(self.store, ["t-b"])
        self.store.conn.execute(
            "INSERT INTO income_allocations(allocation_id, source_row_id,"
            " display_tab_id, amount_krw, active, source_revision, created_at,"
            " client_request_id) VALUES"
            " ('al-1','r-a','t-a',1000,1,1,'2026-01-01T00:00:00Z','req-1')")
        self.store.conn.commit()
        self.assertNotEqual(before_a, live_sync.scope_token(self.store, ["t-a"]))
        self.assertEqual(before_b, live_sync.scope_token(self.store, ["t-b"]))

    def test_the_unclassified_bucket_is_owner_only(self):
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES ('r-u','expense',NULL,1,'{\"item\":\"u\"}')")
        self.store.conn.commit()
        with_bucket = live_sync.scope_token(self.store, ["t-a"],
                                            include_unclassified=True)
        without = live_sync.scope_token(self.store, ["t-a"])
        self.assertNotEqual(with_bucket, without)
        self.store.conn.execute(
            "UPDATE board_rows SET revision=2 WHERE row_id='r-u'")
        self.store.conn.commit()
        self.assertNotEqual(
            with_bucket,
            live_sync.scope_token(self.store, ["t-a"], include_unclassified=True))
        self.assertEqual(without,
                         live_sync.scope_token(self.store, ["t-a"]),
                         "a viewer scope must not see the unclassified bucket")

    def test_the_digest_does_not_carry_row_content(self):
        token = live_sync.scope_token(self.store, ["t-a"])
        self.assertEqual(len(token), live_sync.TOKEN_LENGTH)
        self.assertNotIn("x", token.replace(live_sync._digest(["x"]), ""))
        int(token, 16)  # it is a hex digest, not an encoded value

    def test_a_missing_store_is_still_a_token(self):
        token = live_sync.scope_token(None, ["t-a"])
        self.assertTrue(token)
        self.assertEqual(token, live_sync.scope_token(None, ["t-a"]))


if __name__ == "__main__":
    unittest.main()
