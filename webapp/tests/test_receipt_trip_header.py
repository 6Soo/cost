"""RCPT-030: a receipt photo needs no trip chosen; the trip name at its top decides, then the receipt date."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from app import local_receipt_ocr, receipt_vision
from app import receipt_trip_match as match
from webapp.tests import test_receipt_review as base
from webapp.tests.test_receipt_review import PNG, make_png

TRIPS = [
    {'id': 't-akita', 'name': '0625_아키타', 'destination': '아키타', 'starts_on': '2027-06-25', 'ends_on': '2027-06-28'},
    {'id': 't-tokyo1', 'name': '1201_도쿄', 'destination': '도쿄', 'starts_on': '2026-12-01', 'ends_on': '2026-12-05'},
    {'id': 't-tokyo2', 'name': '1205_도쿄', 'destination': '도쿄', 'starts_on': '2026-12-05', 'ends_on': '2026-12-09'},
    {'id': 't-shin', 'name': '0301_신도쿄', 'destination': '신도쿄', 'starts_on': '2027-03-01', 'ends_on': '2027-03-03'},
    {'id': 't-open', 'name': 'andre::2026::1111_철원', 'destination': '철원', 'starts_on': '2026-11-11', 'ends_on': ''},
    {'id': 't-next', 'name': '1115_호남', 'destination': '호남', 'starts_on': '2026-11-15', 'ends_on': '2026-11-17'},
]


PLACES = [
    {'id': 't-osaka', 'name': '0310_오사카', 'destination': '오사카', 'starts_on': '2026-03-10', 'ends_on': '2026-03-14'},
    {'id': 't-busan', 'name': '0910_부산', 'destination': '부산', 'starts_on': '2026-09-10', 'ends_on': '2026-09-13'},
]


class PlaceOnlyHeaderTests(unittest.TestCase):
    """A header that names only a place does not override the receipt date (review of #957, R1)."""

    def decide(self, header, date, **options):
        return match.decide(match.match_header(header, PLACES, **options), date, PLACES)

    def test_a_place_only_header_with_a_date_in_another_trip_stays_unassigned(self):
        self.assertEqual(self.decide('오사카', '2026-09-12')['trip_id'], '')
        self.assertEqual(self.decide('오사카', '2026-05-01')['trip_id'], '')  # outside every trip
        found = self.decide('오사카', '2026-03-12')
        self.assertEqual((found['trip_id'], found['source']), ('t-osaka', 'header_text'))
        self.assertEqual(self.decide('오사카', None)['trip_id'], 't-osaka')

    def test_the_mmdd_still_beats_the_date(self):
        found = self.decide('0310_오사카', '2026-09-12')
        self.assertEqual((found['trip_id'], found['source']), ('t-osaka', 'header_text'))

    def test_ocr_top_lines_need_the_mmdd_too(self):
        # Without a written trip name, the OCR top lines are the store's own address.
        found = self.decide('부산광역시 해운대구 TEL 0625', '2026-03-11', require_date=True)
        self.assertEqual((found['trip_id'], found['source']), ('t-osaka', 'date'))
        self.assertNotEqual(found['trip_id'], 't-busan')
        found = self.decide('0910 부산 출장', '2026-03-11', require_date=True)
        self.assertEqual((found['trip_id'], found['source']), ('t-busan', 'header_text'))

    def test_a_place_inside_a_longer_name_is_not_that_place(self):
        self.assertEqual(match.match_header('히가시오사카 시청', PLACES)['ids'], [])
        found = self.decide('히가시오사카 시청', '2026-09-12')
        self.assertEqual((found['trip_id'], found['source']), ('t-busan', 'date'))  # never Osaka from the header
        self.assertEqual(match.match_header('오사카시 중앙구', PLACES)['ids'], ['t-osaka'])
        self.assertEqual(match.match_header('0310오사카', PLACES)['ids'], ['t-osaka'])


class MatchUnitTests(unittest.TestCase):
    def ids(self, text):
        return match.match_header(text, TRIPS)['ids']

    def test_spelling_variants_find_one_trip(self):
        for text in ('0625_아키타', '0625 아키타', '０６２５＿아키타', '0625-아키타 여행', '6/25 아키타', '아키타', '  아키타  '):
            with self.subTest(text=text):
                self.assertEqual(self.ids(text), ['t-akita'])

    def test_same_place_two_trips_is_ambiguous_until_the_prefix_names_one(self):
        self.assertEqual(sorted(self.ids('도쿄')), ['t-tokyo1', 't-tokyo2'])
        self.assertEqual(self.ids('1205_도쿄'), ['t-tokyo2'])
        self.assertEqual(self.ids('12/01 도쿄'), ['t-tokyo1'])

    def test_a_longer_place_name_wins_over_the_name_inside_it(self):
        self.assertEqual(self.ids('0301_신도쿄'), ['t-shin'])

    def test_qualified_owner_key_matches_by_its_sheet_name(self):
        self.assertEqual(self.ids('1111_철원'), ['t-open'])

    def test_no_header_or_unknown_name_matches_nothing(self):
        for text in (None, '', '영수증', '0625_없는곳', 12):
            self.assertEqual(self.ids(text), [])

    def test_date_decides_when_the_header_does_not(self):
        header = match.match_header('도쿄', TRIPS)
        self.assertEqual(match.decide(header, '2026-12-03', TRIPS)['trip_id'], 't-tokyo1')
        self.assertEqual(match.decide(header, '2026-12-03', TRIPS)['source'], 'date')
        self.assertEqual(match.decide(header, '2026-12-05', TRIPS)['trip_id'], '')  # both trips contain the 5th
        empty = match.match_header('', TRIPS)
        self.assertEqual(match.decide(empty, '2027-06-26', TRIPS)['trip_id'], 't-akita')
        self.assertEqual(match.decide(empty, '2027-01-01', TRIPS)['trip_id'], '')
        self.assertEqual(match.decide(empty, '', TRIPS)['trip_id'], '')

    def test_header_beats_a_date_inside_another_trip(self):
        found = match.decide(match.match_header('0625_아키타', TRIPS), '2026-12-03', TRIPS)
        self.assertEqual((found['trip_id'], found['source'], found['raw']), ('t-akita', 'header_text', '0625_아키타'))

    def test_open_ended_trip_runs_until_the_day_before_the_next_trip(self):
        empty = match.match_header('', TRIPS)
        self.assertEqual(match.decide(empty, '2026-11-14', TRIPS)['trip_id'], 't-open')
        self.assertEqual(match.decide(empty, '2026-11-15', TRIPS)['trip_id'], 't-next')

    def test_trip_title_is_not_a_merchant(self):
        self.assertTrue(match.is_header_text('0625_아키타', '0625_아키타', TRIPS))
        self.assertTrue(match.is_header_text('０６２５ 아키타', '', TRIPS))
        self.assertFalse(match.is_header_text('아키타 라멘', '0625_아키타', TRIPS))
        self.assertFalse(match.is_header_text(None, '0625_아키타', TRIPS))

    def test_only_lines_in_the_top_fifth_are_the_header(self):
        lines = [{'text': '0625_아키타', 'top': 0.03}, {'text': '라멘집', 'top': 0.25}, {'text': 'x', 'top': 'bad'}, 'junk']
        self.assertEqual(match.top_lines(lines), ['0625_아키타'])
        self.assertEqual(match.top_lines(None), [])


class AdapterTests(unittest.TestCase):
    def test_vision_result_carries_the_header_but_never_a_trip(self):
        body = {'header_text': ' 0625_아키타 ', 'receipts': [{'merchant': '라멘집', 'date': '2027-06-26', 'amount': 900,
                                                           'currency': 'JPY', 'payment': 'cash'}]}
        result = receipt_vision.validate_response(body, image_hash='a' * 64)
        self.assertEqual(result['header_text'], '0625_아키타')
        self.assertFalse(result['trip_inferred'])
        self.assertIsNone(receipt_vision.validate_response({'receipts': []}, image_hash='a' * 64)['header_text'])
        self.assertIn('header_text', receipt_vision.SCHEMA_PATH.read_text(encoding='utf-8'))

    def test_windows_ocr_reports_line_positions(self):
        out = json.dumps({'text': 'a\nb', 'width': 10, 'height': 10,
                          'lines': [{'text': '0625_아키타', 'top': 0.02}, {'text': 'bad', 'top': 'x'}]}).encode()

        class Done:
            returncode, stdout = 0, out

        with patch.dict(os.environ, {'WEBLEDGER_RECEIPT_OCR': 'windows'}), \
                patch.object(local_receipt_ocr, 'enabled', return_value=True), \
                patch('subprocess.run', return_value=Done), patch('subprocess.CREATE_NO_WINDOW', 0, create=True):
            result = local_receipt_ocr.recognize(Path('x.png'), 'ja')
        self.assertEqual(result['lines'], [{'text': '0625_아키타', 'top': 0.02}])


class ReceiptTripHeaderTests(unittest.TestCase):
    setUp = base.ReceiptReviewTests.setUp
    tearDown = base.ReceiptReviewTests.tearDown
    request = base.ReceiptReviewTests.request
    csrf = base.ReceiptReviewTests.csrf

    def trips(self):
        store = self.server.card_store
        self.akita = store.create_trip(starts_on='2027-06-25', ends_on='2027-06-28', destination='아키타',
                                       client_request_id='hdr-akita')['tab_id']
        self.tokyo1 = store.create_trip(starts_on='2026-12-01', ends_on='2026-12-05', destination='도쿄',
                                        client_request_id='hdr-tokyo1')['tab_id']
        self.tokyo2 = store.create_trip(starts_on='2026-12-05', ends_on='2026-12-09', destination='도쿄',
                                        client_request_id='hdr-tokyo2')['tab_id']

    def photo(self, color=b'\xff\x00\x00'):
        status, body = self.request('/api/receipts/image', token=self.csrf(), raw=make_png(color))
        self.assertEqual(status, 200)
        return body['sha256']

    def scan(self, sha, region, **extra):
        return self.request('/api/receipts/scan', {'image': sha, 'regions': [region], **extra}, token=self.csrf())

    def region(self, merchant='라멘집', date='2027-06-26', total=900):
        return {'box': None, 'merchant': merchant, 'date': date, 'currency': 'JPY', 'total': total,
                'payment': 'cash', 'confidence': 1}

    def candidates(self):
        return self.request('/api/receipts')[1]['candidates']

    def test_upload_and_scan_work_without_naming_a_trip(self):
        self.trips()
        sha = self.photo()
        status, body = self.scan(sha, self.region(date='2027-01-01'))
        self.assertEqual((status, body['added']), (200, 1))
        saved = self.candidates()[0]
        self.assertFalse(saved.get('trip_id'))
        self.assertNotIn('trip_source', saved)

    def test_header_text_assigns_the_trip_and_records_where_it_came_from(self):
        self.trips()
        status, body = self.scan(self.photo(), self.region(date='2026-12-03'), header_text='０６２５＿아키타')
        self.assertEqual((status, body['added']), (200, 1))
        saved = self.candidates()[0]
        self.assertEqual((saved['trip_id'], saved['trip_source'], saved['trip_header_text']),
                         (self.akita, 'header_text', '０６２５＿아키타'))

    def test_a_trip_the_owner_names_wins_over_the_header(self):
        self.trips()
        self.scan(self.photo(), self.region(), header_text='0625_아키타', trip_id=self.tokyo1)
        saved = self.candidates()[0]
        self.assertEqual((saved['trip_id'], saved['trip_source']), (self.tokyo1, 'manual'))

    def test_ambiguous_header_falls_back_to_the_receipt_date(self):
        self.trips()
        self.scan(self.photo(), self.region(date='2026-12-03'), header_text='도쿄', header_source='model')
        self.scan(self.photo(b'\x00\xff\x00'), self.region(date='2026-12-05', total=500), header_text='도쿄',
                  header_source='model')
        by_total = {c['total_jpy']: c for c in self.candidates()}
        self.assertEqual((by_total[900]['trip_id'], by_total[900]['trip_source']), (self.tokyo1, 'date'))
        self.assertFalse(by_total[500].get('trip_id'))
        self.assertEqual(by_total[500]['trip_header_text'], '도쿄')

    def test_date_alone_assigns_when_exactly_one_trip_holds_it(self):
        self.trips()
        self.scan(self.photo(), self.region(date='2027-06-27'))
        saved = self.candidates()[0]
        self.assertEqual((saved['trip_id'], saved['trip_source']), (self.akita, 'date'))

    def test_the_trip_title_line_never_becomes_the_merchant(self):
        self.trips()
        status, body = self.scan(self.photo(), self.region(merchant='0625_아키타'), header_text='0625_아키타')
        self.assertEqual(status, 200)
        saved = self.candidates()[0]
        self.assertEqual((saved['merchant'], saved['hold']), ('', 'FIELD_MISSING'))
        self.scan(self.photo(b'\x00\x00\xff'), self.region(merchant='아키타 라멘', total=700), header_text='0625_아키타')
        self.assertIn('아키타 라멘', [c['merchant'] for c in self.candidates()])
        status, body = self.scan(self.photo(b'\x01\x01\x01'), {'merchant': '0625_아키타', 'currency': 'JPY'},
                                 header_text='0625_아키타')
        self.assertEqual(status, 400)  # a region holding only the title has nothing to register

    def test_the_same_receipt_is_still_one_cost(self):
        self.trips()
        sha = self.photo()
        self.scan(sha, self.region(), header_text='0625_아키타')
        status, body = self.scan(sha, self.region(), header_text='0625_아키타')
        self.assertEqual((status, body['added']), (200, 0))
        status, body = self.scan(self.photo(b'\x09\x09\x09'), self.region(), trip_id=self.tokyo1)
        self.assertEqual(body['added'], 0)
        self.assertEqual(len(self.candidates()), 1)

    def test_correcting_the_trip_by_hand_marks_it_manual(self):
        self.trips()
        self.scan(self.photo(), self.region(), header_text='0625_아키타')
        saved = self.candidates()[0]
        status, body = self.request('/api/receipts/edit', {'identity': saved['identity'], 'trip_id': self.tokyo2,
                                                           'expected_version': None}, token=self.csrf())
        self.assertEqual((status, body['trip_id'], body['trip_source']), (200, self.tokyo2, 'manual'))

    def test_an_ocr_header_counts_only_with_the_trip_mmdd(self):
        self.trips()
        self.scan(self.photo(), self.region(date='2026-12-03'), header_text='아키타 라멘 본점', header_source='ocr')
        saved = self.candidates()[0]
        self.assertEqual((saved['trip_id'], saved['trip_source']), (self.tokyo1, 'date'))
        self.assertNotIn('trip_header_text', saved)
        self.scan(self.photo(b'\x00\xff\x00'), self.region(date='2026-12-03', total=500), header_text='0625 아키타',
                  header_source='ocr')
        found = {c['total_jpy']: c for c in self.candidates()}[500]
        self.assertEqual((found['trip_id'], found['trip_source']), (self.akita, 'header_text'))
        status, body = self.scan(self.photo(b'\x01\x02\x03'), self.region(), header_text='0625 아키타',
                                 header_source='camera')
        self.assertEqual(status, 400)

    def test_unknown_named_trip_is_still_refused(self):
        self.trips()
        status, body = self.scan(self.photo(), self.region(), trip_id='trip-made-up')
        self.assertEqual((status, body['code']), (400, 'TRIP_UNKNOWN'))

    def test_a_draft_can_be_kept_before_any_trip_is_known(self):
        self.trips()
        sha = self.photo()
        draft = {'draft_id': 'a' * 32, 'expected_revision': 0, 'trip_id': '',
                 'groups': [{'kind': 'analysis', 'sha': sha, 'receipts': [], 'empty': True, 'headerText': '0625_아키타'}]}
        status, body = self.request('/api/receipts/drafts', draft, token=self.csrf())
        self.assertEqual((status, body['trip_id']), (200, ''))
        status, body = self.request('/api/receipts/drafts', {**draft, 'expected_revision': 1, 'trip_id': self.akita},
                                    token=self.csrf())
        self.assertEqual((status, body['trip_id']), (200, self.akita))

    def test_browser_uploads_on_mobile_and_desktop_without_choosing_a_trip(self):
        self.trips()
        photo = Path(tempfile.mkdtemp()) / 'synthetic.png'
        photo.write_bytes(PNG)
        self.addCleanup(lambda: photo.unlink(missing_ok=True))
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                for width in (375, 1440):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={'width': width, 'height': 900})
                        page.goto(self.base + '/receipts')
                        self.assertEqual(page.locator('#selected-trip').input_value(), '')
                        page.locator('#img-file').set_input_files(str(photo))
                        page.locator('#img-go').click()
                        page.wait_for_function("document.getElementById('upload-results').textContent.includes('원본 저장됨')")
                        self.assertIn('원본 저장됨', page.locator('#upload-results').inner_text())
                        self.assertEqual(page.locator('#trip-error').inner_text(), '')
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                        page.close()
            finally:
                browser.close()
        self.assertEqual(len(self.request('/api/receipts')[1]['images']), 1)


if __name__ == '__main__':
    unittest.main()
