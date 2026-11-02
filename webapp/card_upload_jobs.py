"""Short upload acknowledgement and lock-free status; financial writes stay serialized."""
import re
import threading
import time
import uuid

PREFIX = '/api/imports/upload-status/'
_guard = threading.RLock()


def owns_route(path):
    return bool(re.fullmatch(re.escape(PREFIX) + r'[a-f0-9]{32}', path))


def running(board):
    with _guard:
        return any(job['public']['status'] == 'running'
                   for job in getattr(board, '_upload_jobs', {}).values())


def status(board, identity):
    with _guard:
        job = getattr(board, '_upload_jobs', {}).get(identity)
        if job is None:
            return {'code': 'UPLOAD_STATUS_EXPIRED'}, 404
        return dict(job['public']), 200


def start(board, handler, flow, received, source_file, inspection):
    # receive + queue_batch have committed before this acknowledgement. Repeating
    # bytes cannot create duplicate transactions; active and completed jobs are
    # coalesced too. Failed jobs deliberately get a fresh worker for retry.
    completed = None
    with _guard:
        jobs = getattr(board, '_upload_jobs', None)
        if jobs is None:
            jobs = board._upload_jobs = {}
        for identity, job in list(jobs.items()):
            public = job['public']
            if (public['status'] in ('running', 'done') and
                    job['batch_id'] == received['batch_id']):
                if public['status'] == 'done':
                    completed = (identity, job)
                else:
                    return dict(status_url=PREFIX+identity,
                                batch_id=received['batch_id'],
                                status=public['status'],
                                source_rows_persisted=True)
                break
            if job['public']['status'] != 'running' and (time.monotonic()-job['created'] > 3600 or len(jobs) >= 16):
                del jobs[identity]
        if completed is None:
            identity = uuid.uuid4().hex
            job = {'batch_id': received['batch_id'], 'created': time.monotonic(),
                   'public': {'status': 'running', 'message': '파일 접수 완료 · 처리 대기 중'}}
            jobs[identity] = job
            def progress(message):
                with _guard:
                    job['public'] = {'status': 'running', 'message': message}
            def run():
                try:
                    # Same lock order as HTTP and the durable completion worker.
                    with handler.server.store_lock:
                        if getattr(handler.server, 'runtime_closing', False):
                            raise RuntimeError('SERVER_STOPPING')
                        result, code = process(board, handler, flow, received, source_file, inspection, progress)
                    public = ({'status': 'done', 'result': result} if code == 200 else
                              {'status': 'error', 'message': result['message']})
                except Exception:
                    public = {'status': 'error', 'message': '원천 파일은 저장되었습니다. 저장된 파일 상세 결과를 확인해 주세요.'}
                with _guard:
                    job['public'] = public
            try:
                threading.Thread(target=run, name='card-upload', daemon=True).start()
            except Exception:
                job['public'] = {'status': 'error', 'message': '원천 파일은 저장되었습니다. 저장된 파일 상세 결과를 확인해 주세요.'}
            return dict(status_url=PREFIX+identity, batch_id=received['batch_id'],
                        status='running', source_rows_persisted=True)
    if completed:
        identity, job = completed
        # Read the latest committed projection after a manual correction. Never
        # hold _guard while acquiring store_lock: the worker takes them in the
        # opposite order when it publishes completion.
        try:
            with handler.server.store_lock:
                fresh = flow.saved_state(received['batch_id'])
            if (not isinstance(fresh, dict) or fresh.get('refresh_required') or
                    not isinstance(fresh.get('rows'), list)):
                raise RuntimeError('LATEST_BATCH_STATE_UNAVAILABLE')
            with _guard:
                if getattr(board, '_upload_jobs', {}).get(identity) is job and job['public']['status'] == 'done':
                    result = dict(job['public']['result'])
                    result.update(fresh)
                    result.pop('refresh_required', None)
                    job['public'] = {'status': 'done', 'result': result}
        except Exception:
            with _guard:
                if getattr(board, '_upload_jobs', {}).get(identity) is job and job['public']['status'] == 'done':
                    result = dict(job['public'].get('result') or {})
                    result.pop('rows', None)
                    result.pop('preview', None)
                    result.pop('summary', None)
                    result['refresh_required'] = True
                    result['upload_summary'] = dict(result.get('upload_summary') or {},
                                                    status='refresh_required')
                    job['public'] = {'status': 'done', 'result': result}
        with _guard:
            public = job['public']
            acknowledgement = dict(status_url=PREFIX+identity,
                                    batch_id=received['batch_id'],
                                    status=public['status'],
                                    source_rows_persisted=True)
            if public['status'] == 'done':
                acknowledgement['result'] = public['result']
            return acknowledgement


def process(board, handler, flow, received, source_file, inspection, progress=lambda message: None):
    from . import ota_payment_review
    from .card_completion_worker import finish_jobs
    recovery = getattr(board, '_card_completion_worker', None)
    try:
        progress('카드 분류 중')
        flow.classify(received['batch_id'])
        result = {}
        progress('예약 대사 갱신 중')
        if ota_payment_review.enabled():
            backend = None
            try:
                backend = ota_payment_review.backend_for_request(board, handler, read_only=False)
                refresh = getattr(backend, 'refresh_after_import', None)
                if refresh:
                    transaction_ids = [str(row.get('transaction_id') or '')
                                       for row in flow.pipeline.get_batch(received['batch_id'])['rows'] if row.get('transaction_id')]
                    refresh(transaction_ids)
                result['ota_refresh_status'] = 'refreshed'
            except Exception:
                result['ota_refresh_status'] = 'unavailable'
            finally:
                closer = getattr(backend, 'close', None)
                if closer:
                    closer()
        # OTA refresh can make a row recordable after classify's first pass.
        progress('내부 기록 및 전수 검증 중')
        recorded = flow.auto_record(received['batch_id'])
        if 'ota_refresh_status' in result:
            recorded['ota_refresh_status'] = result['ota_refresh_status']
        if source_file.channel != 'approval':
            from app.upload_reconciliation import summarize
            from .card_classification_completion import context
            with board._lock:
                trips, nets = context(flow)
                recorded['upload_summary'] = summarize(flow.pipeline, received, source_file,
                    trips, nets=nets, inspection=inspection)
        from . import card_upload_coverage
        with board._lock:
            coverage = card_upload_coverage.batch_inspection(board, received['batch_id'])
            recorded['coverage_evidence'] = coverage['evidence']
            recorded['coverage_available'] = coverage['available']
        finish_jobs(board)
    except Exception:
        # receive() commits the validated source batch before classification and
        # recording. The activated worker resumes from this durable batch;
        # without one, an idempotent same-file retry remains available.
        scheduled = recovery is not None and recovery.running
        if scheduled:
            recovery.wake()
        return {'code':'UPLOAD_PROCESSING_INCOMPLETE',
            'message':('원천 파일은 저장했고 후속 처리를 자동으로 재시도합니다. 다시 업로드할 필요가 없습니다.' if scheduled else
                       '원천 파일은 저장했지만 후속 처리가 완료되지 않았습니다. 같은 파일을 다시 올려 재시도해 주세요.'),
            'batch_id':received['batch_id'], 'source_rows_persisted':True,
            'verification_status':'unavailable', 'retry_same_file':not scheduled,
            'automatic_recovery_scheduled':scheduled}, 503
    else:
        return recorded, 200
