"""Muse recognition runs in a worker thread, never inside a request or under the store lock.

A request only queues a job and reads its state. The worker touches no database: it
reads one already-verified image file and returns data for a person to review. Jobs
live in memory, so a restart makes an unfinished job expire rather than resume it.
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

MAX_QUEUED = 3
RESULT_TTL_SECONDS = 3600
MAX_JOBS = 200

_LOCK = threading.Lock()
_JOBS = {}
_BY_IMAGE = {}
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='receipt-vision')


class JobBusy(Exception):
    """Too many recognitions are already waiting; the user retries later."""


def _snapshot(job):
    return {'job_id': job['job_id'], 'image': job['image'], 'status': job['status'],
            'code': job.get('code'), 'result': job.get('result') if job['status'] == 'done' else None,
            'created_at': job['created_at'], 'finished_at': job.get('finished_at')}


def _prune(now):
    for job_id in [j for j, job in _JOBS.items() if job['status'] in ('done', 'failed')
                   and now - (job.get('finished_at') or now) > RESULT_TTL_SECONDS]:
        job = _JOBS.pop(job_id)
        if _BY_IMAGE.get(job['image']) == job_id:
            del _BY_IMAGE[job['image']]
    while len(_JOBS) > MAX_JOBS:
        oldest = min(_JOBS, key=lambda j: _JOBS[j]['created_at'])
        if _JOBS[oldest]['status'] in ('queued', 'running'):
            break
        job = _JOBS.pop(oldest)
        if _BY_IMAGE.get(job['image']) == oldest:
            del _BY_IMAGE[job['image']]


def submit(image, image_path, recognize):
    """Queue one recognition for an image, or return the job that already covers it."""
    now = time.time()
    with _LOCK:
        _prune(now)
        current = _BY_IMAGE.get(image)
        if current in _JOBS and _JOBS[current]['status'] in ('queued', 'running', 'done'):
            return _snapshot(_JOBS[current])
        waiting = sum(1 for job in _JOBS.values() if job['status'] in ('queued', 'running'))
        if waiting >= MAX_QUEUED:
            raise JobBusy('VISION_BUSY')
        job_id = uuid.uuid4().hex
        job = {'job_id': job_id, 'image': image, 'status': 'queued', 'created_at': now}
        _JOBS[job_id] = job
        _BY_IMAGE[image] = job_id
        snapshot = _snapshot(job)
    _POOL.submit(_run, job_id, image_path, recognize)
    return snapshot


def _run(job_id, image_path, recognize):
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job['status'] = 'running'
    try:
        result = recognize(image_path)
        outcome = {'status': 'done', 'result': result}
    except Exception as error:  # noqa: BLE001 - every failure becomes a named code for the screen
        outcome = {'status': 'failed', 'code': getattr(error, 'code', 'VISION_EXECUTION_FAILED')}
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(outcome, finished_at=time.time())


def lookup(job_id):
    """The current state of a job, or None when it is unknown (for example after a restart)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        return None if job is None else _snapshot(job)
