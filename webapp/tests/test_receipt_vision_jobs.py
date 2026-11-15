"""The receipt reading queue: one worker, no duplicate calls for one image, named failures.

Every image here is a synthetic placeholder; the recognizer is a local fake.
"""
import threading
import time
import unittest

from webapp import receipt_vision_jobs as jobs


class FakeVisionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def wait_for(job_id, statuses, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = jobs.lookup(job_id)
        if state and state['status'] in statuses:
            return state
        time.sleep(0.01)
    raise AssertionError('job did not reach %s' % (statuses,))


class ReceiptVisionJobTests(unittest.TestCase):
    def setUp(self):
        with jobs._LOCK:
            jobs._JOBS.clear()
            jobs._BY_IMAGE.clear()

    def test_a_submitted_image_is_recognized_once_and_the_result_is_kept(self):
        calls = []

        def recognize(path):
            calls.append(path)
            return {'receipts': [], 'confirmed': False}

        queued = jobs.submit('a' * 64, 'img-a', recognize)
        self.assertIn(queued['status'], ('queued', 'running', 'done'))
        done = wait_for(queued['job_id'], ('done',))
        self.assertEqual(done['result'], {'receipts': [], 'confirmed': False})
        again = jobs.submit('a' * 64, 'img-a', recognize)
        self.assertEqual(again['job_id'], queued['job_id'])
        self.assertEqual(calls, ['img-a'])

    def test_a_failure_is_recorded_with_its_code_and_is_not_retried_by_itself(self):
        calls = []

        def recognize(path):
            calls.append(path)
            raise FakeVisionError('VISION_RESPONSE_INVALID')

        first = jobs.submit('b' * 64, 'img-b', recognize)
        failed = wait_for(first['job_id'], ('failed',))
        self.assertEqual(failed['code'], 'VISION_RESPONSE_INVALID')
        self.assertIsNone(failed['result'])
        self.assertEqual(len(calls), 1)
        retry = jobs.submit('b' * 64, 'img-b', recognize)
        self.assertNotEqual(retry['job_id'], first['job_id'])

    def test_an_unexpected_error_still_becomes_a_named_failure(self):
        def recognize(path):
            raise RuntimeError('synthetic crash')

        queued = jobs.submit('c' * 64, 'img-c', recognize)
        self.assertEqual(wait_for(queued['job_id'], ('failed',))['code'], 'VISION_EXECUTION_FAILED')

    def test_waiting_work_is_capped_and_the_next_request_is_refused(self):
        gate = threading.Event()

        def hold(path):
            gate.wait(5)
            return {'receipts': []}

        try:
            for index in range(jobs.MAX_QUEUED):
                jobs.submit(format(index, 'x') * 64, 'img-%d' % index, hold)
            with self.assertRaises(jobs.JobBusy):
                jobs.submit('f' * 64, 'img-x', hold)
        finally:
            gate.set()

    def test_an_unknown_job_is_reported_as_missing_not_guessed(self):
        self.assertIsNone(jobs.lookup('0' * 32))

    def test_the_worker_does_not_hold_the_store_lock(self):
        """The job reads only the image file it is given; it takes no lock of its own."""
        seen = {}

        def recognize(path):
            seen['held'] = jobs._LOCK.locked()
            return {'receipts': []}

        queued = jobs.submit('d' * 64, 'img-d', recognize)
        wait_for(queued['job_id'], ('done',))
        self.assertFalse(seen['held'])


if __name__ == '__main__':
    unittest.main()
