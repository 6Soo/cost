"""카드 파일부터 장부까지 이어지는 단일 사용자 흐름."""
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlencode

from app.db import decided_sql
from app.reconciliation import (GUIDE_AIRFARE_ORIGIN, OTA_MAIL_ORIGIN, OTA_PORTAL_ORIGIN, OWNER_COUNTRY_EXCEPTION_ORIGIN,
                                   handover_days, overlaps_stay, stay_trip)

from . import card_cleanup_ui
from . import card_trip_authority
from . import card_evidence_ui
from . import card_ota_projection
from . import card_refund_query
from . import read_scope
from app.partial_refund import read_only_scope as refund_read_only_scope


_OTA_REPORT_LOCK = threading.Lock()
_AUTHORITY_CACHE = {}
_GOOGLE_PERIOD_CACHE = {}
# 시트에 종료일이 적히지 않은 탭. 다음 여행 직전일로 정한 종료일(사용자 확정 규칙, reconciliation.open_trip_end)은
# 여행 기간으로 검증에 그대로 쓴다. 다만 옮긴 시트의 해시 확인된 원본 제목에 종료일이 적혀 있으면 그쪽이 앞선다.
_GUESSED_PERIOD_FLAGS = frozenset({'PERIOD_END_FROM_NEXT_TRIP', 'PERIOD_END_MISSING'})


def _redirect_legacy_import(handler, parsed, query):
    """Keep legacy GET parameters while routing the old page into card history."""
    from . import card_cleanup_queries

    query = query or {}
    reasons = query.get('cleanup_reason') or []
    if len(reasons) > 1:
        handler._send('잘못된 카드 확인 링크입니다.', 400)
        return True
    if reasons:
        reason = card_cleanup_queries.LEGACY_REASONS.get(reasons[0], reasons[0])
        if reason not in card_cleanup_queries.REASONS:
            handler._send('잘못된 카드 확인 링크입니다.', 400)
            return True

    params = [
        (key, reason if key == 'cleanup_reason' and reasons else value)
        for key, values in query.items() for value in values
    ]
    has_cleanup = bool(reasons or query.get('cleanup_page'))
    has_target = bool(query.get('batch') or query.get('transaction'))
    if has_cleanup:
        params.append(('legacy_cleanup', '1'))
    elif has_target:
        if not query.get('panel'):
            params.append(('panel', 'upload'))
    elif query.get('scope') != ['all']:
        if not query.get('panel'):
            params.append(('panel', 'upload'))
        if query:
            params.append(('legacy_import', '1'))

    location = '/cards/all' + (('?' + urlencode(params)) if params else '')
    handler.send_response(302)
    handler.send_header('Location', location)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', '0')
    handler.end_headers()
    return True


def _google_periods():
    """구글 여행 탭의 기간을 연결된 COST 탭 ID별 (시작일, 종료일, 추정 여부)로 돌려준다. 설정이 없거나 읽을 수 없으면 비어 있다."""
    return _google_trips()[0]


def _google_nets():
    """구글 여행 탭의 수입-비용 차액을 연결된 COST 탭 ID별로 돌려준다."""
    return _google_trips()[1]


def _google_trips():
    raw = os.environ.get('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', '').strip()
    if not raw:
        return {}, {}
    from app import google_authority
    from . import google_ledger_page
    path = Path(raw)
    try:
        stamp = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in (path, google_ledger_page.mapping_path(path)))
    except OSError:
        return {}, {}
    cached = _GOOGLE_PERIOD_CACHE.get(raw)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        snapshot = google_authority.load_snapshot(path)
        mapping = google_ledger_page.load_mapping(path)
    except (google_authority.SnapshotError, OSError, ValueError):
        return {}, {}
    by_key = {trip.get('key'): trip for trip in snapshot.get('trips', [])}
    periods, nets = {}, {}
    for key, tab_id in mapping.items():
        trip = by_key.get(key) or {}
        if isinstance(trip.get('net'), (int, float)):
            nets[tab_id] = trip['net']
        period = trip.get('period') or {}
        if period.get('starts_on'):
            guessed = not period.get('ends_on') or bool(_GUESSED_PERIOD_FLAGS & set(period.get('flags') or ()))
            periods.setdefault(tab_id, set()).add((period['starts_on'], period.get('ends_on') or '', guessed))
    _GOOGLE_PERIOD_CACHE[raw] = (stamp, (periods, nets))
    return periods, nets


def _trip_authority(path):
    """The trip authority records, parsed again only when the file's bytes change."""
    from ledger.domain.direct_trip_schedule_authority import load_document, sha256_bytes
    digest = sha256_bytes(path.read_bytes())
    cached = _AUTHORITY_CACHE.get(str(path))
    if cached is not None and cached[0] == digest:
        return cached[1], digest
    records, parsed_digest = load_document(path)
    _AUTHORITY_CACHE[str(path)] = (parsed_digest, records)
    return records, parsed_digest


def _is_ota_row(row):
    merchant = str(row.get('merchant') or row.get('merchant_normalized') or '').upper()
    from app.ota_matching_defaults import provider_for_merchant
    return bool(provider_for_merchant(merchant))


def _unchanged_workbook_schedule(record, current_bytes, cache):
    """원본 증거와 최신 명시 제목을 함께 검증하며 비용 셀 변경만 분리한다. current_bytes가 None이면 원본 증거의 제목만 검증한다."""
    import io
    import re
    import zipfile
    from datetime import date
    from openpyxl import load_workbook
    from xml.etree.ElementTree import ParseError

    path, _, locator = record.source_locator.partition('#')
    sheet, separator, cell = locator.rpartition('!')
    if not separator or sheet != record.trip_code or cell not in ('C2', 'D2'):
        return False
    books = []
    try:
        original_bytes = Path(path).read_bytes()
        if hashlib.sha256(original_bytes).hexdigest() != record.source_sha256:
            return False
        key = (record.source_sha256, '' if current_bytes is None else hashlib.sha256(current_bytes).hexdigest())
        if key not in cache:
            for contents in (original_bytes,) if current_bytes is None else (original_bytes, current_bytes):
                books.append(load_workbook(io.BytesIO(contents), read_only=True, data_only=False))
            original, current = books[0], books[-1]
            originals = {page.title:{address:page[address].value for address in ('C2', 'D2')}
                         for page in original}
            current_titles = {page.title:{value.value for row in page.iter_rows(min_row=2, max_row=2)
                              for value in row if isinstance(value.value, str) and '매출 확인자료' in value.value}
                              for page in current}
            current_cells = {page.title:{address:page[address].value for address in ('C2', 'D2')}
                             for page in current}
            cache[key] = (originals, current_titles, current_cells)
        originals, current_titles, current_cells = cache[key]
        if sheet not in originals or (current_bytes is not None and sheet not in current_titles):
            return False
        title = originals[sheet][cell]
        if not isinstance(title, str) or title.startswith('=') or '매출 확인자료' not in title:
            return False
        years = re.findall(r'(?<!\d)(\d{4})\s*년', title)
        periods = re.findall(r'(?<!\d)(\d{4})_(\d{4})(?!\d)', title)
        if len(years) != 1 or len(periods) != 1:
            return False
        year = int(years[0])
        start, end = periods[0]
        if (year != record.event_year
                or date(year, int(start[:2]), int(start[2:])) != record.starts_on
                or date(year, int(end[:2]), int(end[2:])) != record.ends_on):
            return False
        return current_bytes is None or (current_cells[sheet][cell] == title and current_titles[sheet] == {title})
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ParseError):
        return False
    finally:
        for book in books:
            book.close()


def _mail_evidence_from_report(report, source_hashes):
    """이미 계산된 OTA 대조 결과를 화면 표시용 사실로만 줄인다."""
    from app.ota_mail import reference_diagnosis
    wanted = set(source_hashes)
    evidence = {}
    for fact in report.get('matches', []):
        source = fact.get('source_hash')
        if source not in wanted:
            continue
        current = evidence.setdefault(source, {})
        if fact.get('booking_link_conflict'):
            current['booking_link_conflict'] = True
        elif fact.get('reservation_status') == 'cancelled':
            current['cancellation_mail'] = True
        else:
            current['booking_match'] = True
    exact = set(evidence)
    for fact in report.get('type_only_candidates', []):
        source = fact.get('source_hash')
        if source in wanted and source not in exact:
            evidence.setdefault(source, {})['mail_link_uncertain'] = True
    linked = exact | {f.get('source_hash') for f in report.get('type_only_candidates', [])}
    diagnoses = {d.get('source_hash'): d.get('reason') for d in report.get('portal_diagnoses', [])}
    # 이미 대조된 예약 번호도 참고 자료 조회에 쓴다.
    matched_refs = {f.get('source_hash'): f.get('booking_ref')
                    for f in report.get('matches', []) if f.get('booking_ref')}
    references = report.get('reference_sources')
    for fact in report.get('unmatched_transactions', []):
        source = fact.get('source_hash')
        if source in wanted and source not in linked:
            current = evidence.setdefault(source, {})
            # 자료가 있는데 연결이 안 됐다는 사실과 그 원인을 함께 남긴다.
            # 근거 부재와 자료 부재를 같은 표시로 두지 않는다.
            current['mail_link_absent'] = True
            # 구체 원인이 일반 사유보다 먼저다. 무엇이 막혔는지 알 수 있어야 한다.
            reason = diagnoses.get(source) or fact.get('reason')
            if reason:
                current['link_diagnosis'] = reason
    if references:
        for source in wanted:
            current = evidence.setdefault(source, {})
            row = {'source_hash': source}
            found = reference_diagnosis(references, row=row,
                                        booking_ref=matched_refs.get(source, ''))
            if found:
                current['reference_only'] = found['reason']
    inventory = report.get('ota_source_inventory') or {}
    diagnostics = inventory.get('diagnostics') or []
    source_errors = report.get('ota_source_errors') or []
    if diagnostics or source_errors:
        for source in wanted:
            current = evidence.setdefault(source, {})
            if diagnostics:
                current['source_diagnostic'] = 'registered_source_missing'
            elif source_errors:
                current['source_diagnostic'] = 'source_read_failed'
    return evidence


def _link_diagnosis_label(reason):
    """미연결 원인을 사람이 읽을 한 줄로 바꾼다. 원문과 경로는 쓰지 않는다."""
    labels = {
        'no_exact_payment_evidence': '결제 근거 미확인 · 연결 필요',
        'payment_amount_unavailable': '결제 금액 없음 · 연결 필요',
        'foreign_receipt_or_krw_acquisition_required': '외화 영수증 확인 필요',
        'future_payment': '결제 예정 · 실제 결제 확인 필요',
        'amount_mismatch': '같은 카드 예약 후보와 금액 불일치',
        'missing_period': '이용 기간 미확인 · 확인 필요',
        'booking_conflict': '예약 내용 충돌 · 확인 필요',
        'ambiguous_booking': '예약이 여러 건 · 구분 필요',
        'ambiguous_transaction': '같은 예약의 거래가 여러 건 · 구분 필요',
        'unverified_payment': '결제 근거 미검증 · 확인 필요',
        'multiple_real_transactions_same_amount': '동액 거래 여러 건 · 구분 필요',
        'reference_only': '참고 자료만 있음 · 검증 필요',
        'reference_content_conflict': '참고 자료 내용 불일치 · 확인 필요',
        'registered_source_missing': '등록된 근거 자료 없음 · 확인 필요',
        'source_read_failed': '근거 자료 읽기 실패 · 확인 필요',
        'snapshot_managed': '예약 근거는 이 거래의 상세 근거에서 바로 확인할 수 있습니다',
        'payment_date_unknown': '결제일 근거 없음 · 날짜 확인 필요',
        'card_identity': '카드 끝자리나 카드사가 맞지 않음 · 확인 필요',
        'provider': '예약 제공자와 카드 가맹점이 맞지 않음 · 연결 불가',
        'corroboration': '업체 근거(승인된 가맹점 별칭) 없음 · 확인 필요',
        'date': '카드 날짜와 결제일이 맞지 않음 · 확인 필요',
        'amount': '카드 금액과 결제 금액이 맞지 않음 · 확인 필요',
        'direction': '거래 방향이 맞지 않음 · 확인 필요',
        'row_flagged': '중복이나 오류가 있는 카드 거래 · 확인 필요',
        'row_missing': '카드 거래 원본 없음 · 확인 필요',
        'no_core_event': 'OTA 결제 자료와 연결되지 않음 · 확인 필요',
        'evidence_unavailable': 'OTA 근거 자료를 읽지 못함 · 확인 필요',
    }
    return labels.get(reason, '예약 근거 확인 필요')


def _review_evidence_labels(row, mail_evidence=None):
    """영구 상태를 만들지 않고 기존 사실을 사람이 읽을 문구로 번역한다."""
    evidence = mail_evidence or {}
    labels = []
    if evidence.get('booking_link_conflict'):
        labels.append('예약 근거 충돌 · 연결 확인 필요')
    elif evidence.get('cancellation_mail'):
        labels.append('취소 메일 있음')
    elif evidence.get('booking_match'):
        labels.append('예약 근거 있음')
    elif evidence.get('mail_link_uncertain'):
        labels.append('메일 있음 · 연결 확인 필요')
    elif _is_ota_row(row):
        # OTA 거래에만 예약 연결 안내를 붙인다. 다른 가맹점 거래에는 붙이지 않는다.
        reason = evidence.get('source_diagnostic') or evidence.get('link_diagnosis')
        labels.append(_link_diagnosis_label(reason))
        if evidence.get('reference_only'):
            labels.append('참고 자료만 있음 · 검증 필요')

    if evidence.get('source_diagnostic'):
        labels.append(_link_diagnosis_label(evidence['source_diagnostic']))
    hold = row.get('review_hold') or {}
    if hold.get('kind') == 'refund_pending':
        labels.append('환불 확인 필요')

    if row.get('classification_state') == 'needs_review' and hold.get('kind') != 'refund_pending':
        labels.append('분류 근거 필요')

    return list(dict.fromkeys(labels))[:3]


def enabled():
    return os.environ.get('WEBLEDGER_CARD_FLOW') == '1'


def reclassify_pending(board):
    """장부 규칙을 미래 적용으로 켠 직후, 아직 기록하지 않은 카드 거래를 다시 분류한다.

    사용자가 직접 정한 거래는 분류가 건드리지 않는다."""
    if not enabled():
        return 0
    flow = CardFlow(board)
    batches = [row[0] for row in board.conn.execute('SELECT batch_id FROM import_batches')]
    for batch_id in batches:
        flow.classify(batch_id)
    return len(batches)


def configure_ota_review_backend(*, read_factory=None, write_factory=None):
    """Override the default core adapter with separate read and write adapters."""
    from . import ota_payment_review
    ota_payment_review.configure_backend_factory(read_factory=read_factory, write_factory=write_factory)


def batch_display_info(issuers, first='', last=''):
    names = sorted({str(name).strip() for name in issuers if str(name).strip()})
    known = {'국민':'국민카드', '하나':'하나카드', '기업':'기업카드'}
    label = ' · '.join(known.get(name, name if name.endswith('카드') else name + ' 카드') for name in names)
    return {'display_name':(label or '카드') + ' 사용내역', 'period_start':first or '', 'period_end':last or ''}


def batch_catalog(board):
    """현재 검토 범위만 집계하며 원본 파일명과 저장된 거래를 변경하지 않는다."""
    review_from = os.environ.get('WEBLEDGER_REVIEW_FROM', '')
    from .card_cleanup_queries import completed_period_sql
    active_period = completed_period_sql(board)
    with board._lock:
        hold_filter = ("AND NOT EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
                       if board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else '')
        rows = board.conn.execute(
            "SELECT b.batch_id,b.filename,COUNT(DISTINCT t.transaction_id),b.status,GROUP_CONCAT(DISTINCT t.issuer),"
            "MIN(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
            "MAX(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
            "COALESCE(SUM(CASE WHEN (t.classification_state='needs_review' OR "
            "(t.classification_source='inference' AND t.classification_basis LIKE ?)) "
            "AND NOT " + decided_sql('t') + " AND COALESCE(t.duplicate_of,'')='' "
            "AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id) " + hold_filter +
            "AND " + active_period + " THEN 1 ELSE 0 END),0) AS questions "
            "FROM import_batches b LEFT JOIN import_batch_rows x ON x.batch_id=b.batch_id "
            "LEFT JOIN transactions t ON t.transaction_id=x.transaction_id "
            "WHERE (?='' OR t.transaction_id IS NULL OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)='' "
            "OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)>=?) "
            "GROUP BY b.batch_id ORDER BY questions DESC,b.received_at DESC,b.batch_id",
            ('추론 배정 · 낮음 ·%', review_from, review_from)).fetchall()
    catalog = [dict(batch_id=r[0], filename=r[1], rows=r[2], status=r[3], questions=r[7],
                    **batch_display_info((r[4] or '').split(','), r[5], r[6])) for r in rows]
    # Keep mixed or unknown issuers together after the three individual issuers.
    order = {'국민카드 사용내역': 0, '하나카드 사용내역': 1, '기업카드 사용내역': 2}
    catalog.sort(key=lambda b: (b['period_end'] or b['period_start'], b['period_start']), reverse=True)
    catalog.sort(key=lambda b: order.get(b['display_name'], 3))
    return catalog


@read_scope.scoped
def home_page(board):
    from . import ledger_board, ledger_design, receipt_review, ui_icons
    from . import card_upload_coverage, collection_status
    from app.reserve_trips import registrations, sync_status, today, KST
    import datetime as dt
    esc = ledger_board.esc
    review_from = os.environ.get('WEBLEDGER_REVIEW_FROM', '')
    from .card_cleanup_queries import completed_period_sql
    active_period = completed_period_sql(board)
    # 여러 파일이 같은 거래를 포함해도 메인 건수는 거래 정본에서 한 번만 센다.
    with board._lock:
        hold_filter = ("AND NOT EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
                       if board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else '')
        saved, questions = board.conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(CASE WHEN (t.classification_state='needs_review' OR "
            "(t.classification_source='inference' AND t.classification_basis LIKE ?)) "
            "AND NOT " + decided_sql('t') + " AND COALESCE(t.duplicate_of,'')='' "
            "AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id) " + hold_filter +
            "AND " + active_period + " THEN 1 ELSE 0 END),0) "
            "FROM transactions t WHERE (?='' OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)='' "
            "OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)>=?)",
            ('추론 배정 · 낮음 ·%', review_from, review_from)).fetchone()
        last_transaction_row = board.conn.execute(
            "SELECT MAX(COALESCE(NULLIF(approval_date,''),NULLIF(posting_date,''))) FROM transactions").fetchone()
    last_transaction = (last_transaction_row[0] if last_transaction_row else '') or ''
    trips = [t for t in board.list_trips()
             if not t.get('deleted') and not t.get('archived')
             and not ledger_board.is_previous_trip(t)]
    listed_trips = sorted(trips, key=lambda t:(t['starts_on'], t['display_key']))
    trip_heading = '진행 중 여행'
    posted = board.visible_row_count()
    try:
        trip_summaries = board.trip_management_summaries()
    except (AttributeError, sqlite3.Error, ValueError, KeyError, TypeError):
        trip_summaries = {}
    def short_date(value):
        parts = str(value).split('-')
        return f"{parts[1]}.{parts[2]}" if len(parts) == 3 else str(value)

    def trip_expense_count(trip):
        summary = trip_summaries.get(trip['tab_id'], {}) if isinstance(trip_summaries, dict) else {}
        return int(summary.get('expense_count', 0) or 0)
    items = ''.join(
        f"<tr><th scope='row'><a href='/board?tab={esc(t['tab_id'])}'>{esc(t['display_key'])}</a></th>"
        f"<td>{esc(short_date(t['starts_on']))}–{esc(short_date(t['ends_on']))}</td>"
        f"<td>{trip_expense_count(t)}건</td>"
        f"<td>{'마감' if t.get('visual_closed') else '미마감'}</td></tr>"
        for t in listed_trips[:8])
    state = sync_status(board)
    next_run = state.get('next_run_at')
    next_note = (dt.datetime.fromisoformat(next_run).astimezone(KST).strftime('%Y-%m-%d %H:%M')
                 if next_run else '')
    if next_run and dt.datetime.fromisoformat(next_run).astimezone(KST) <= dt.datetime.now(KST):
        next_note = ''
    coverage = {}
    try:
        coverage = card_upload_coverage.get_coverage_summary(board)
    except Exception:
        coverage = {}
    gap_count = int((coverage.get('overview') or {}).get('gap_count') or 0)
    receipt_count = 0
    if receipt_review.enabled():
        try:
            receipt_count = len(receipt_review.load(receipt_review._store_path()).get('candidates', []))
        except Exception:
            receipt_count = 0
    try:
        collection_html = collection_status.render(board)
    except Exception:
        collection_html = ''
    body = ("<style>"
             ".home-overview{padding:20px 24px 16px;border-bottom:1px solid var(--line)}"
             ".home-status{font-size:var(--t-meta);color:var(--mut);margin:0 0 12px}"
             ".home-status-list{list-style:none;padding:0;margin:0;display:grid;gap:10px}"
             ".home-status-list li{display:flex;gap:12px;flex-wrap:wrap;align-items:baseline}"
             ".home-status-list span{color:var(--mut);min-width:104px}"
             ".home-status b{color:var(--ink);font-weight:700}"
             ".page-body a.btn.primary{background:var(--grn);border-color:var(--grn);color:var(--c-on-accent)}"
             ".page-body a.btn.primary:hover{background:var(--grn-hover,var(--grn-dk));border-color:var(--grn-hover,var(--grn-dk));color:var(--c-on-accent)}"
             ".page-body a.home-review{margin:0!important;background:var(--grn);border-color:var(--grn);color:var(--c-on-accent)}"
            ".page-body a.home-review:hover{background:var(--grn-dk);border-color:var(--grn-dk);color:var(--c-on-accent)}"
            ".home-primary{display:inline-flex;align-items:center;justify-content:center;min-height:44px;margin:0 0 10px!important}"
            ".home-travel-section{padding:18px 24px 22px}"
            ".home-travel-heading{font-size:var(--t-h3)!important;margin:0 0 8px!important}"
            ".home-trips{margin:0 0 8px!important}"
            ".home-trips tbody th,.home-trips tbody td{background:var(--c-surface)}"
            ".home-all{font-size:var(--t-meta);margin:8px 0 0!important}"
            "@media(width < 760px){"
            ".home-main .page-hd{padding:20px 16px 6px;border-bottom:0;display:block}"
            ".home-main .page-hd h1{font-size:var(--t-h1);line-height:1.2}"
            ".home-main .page-hd .synth,.home-main .page-hd .meta,.home-main .page-hd .act{display:none}"
            ".home-overview{padding:0 16px 10px;border-bottom:0}"
            ".home-status-list li{display:grid;grid-template-columns:88px minmax(0,1fr);gap:6px}"
            ".home-status-list li a{grid-column:2}"
            ".home-status{font-size:var(--t-meta);line-height:1.35;margin:0 0 12px;white-space:normal}"
            ".home-primary{display:flex;width:100%;min-height:46px;margin:0 0 8px!important;justify-content:center;font-size:var(--t-body-sm)}"
            ".home-main .work-action{min-height:44px;padding:8px}"
            ".home-main .work-action small{display:none}"
            ".home-travel-section{padding:12px 16px 18px}"
            ".home-travel-heading{font-size:var(--t-h3)!important;line-height:1.25;margin:0 0 6px!important}"
            ".home-all{margin:7px 0 0!important;font-size:var(--t-meta)}"
            ".home-next-note{display:none}"
            "}"
            "</style>"
            "<section class='home-overview' aria-label='자료 상태'>"
                "<h2 class='home-travel-heading'>자료 상태</h2><ul class='home-status-list'>"
            + f"<li><span>카드 자료</span><strong>{'저장된 카드 거래 전체' if not review_from else '조회 기간 내 카드 거래'} <b>{saved}</b> · 장부 <b>{posted}</b></strong>"
            + (f" · 마지막 거래 {esc(last_transaction)}" if last_transaction else "")
            + (f" <a href='/cards/all?panel=coverage'>빈 기간 {gap_count}곳 보기</a>" if gap_count else "") + "</li>"
            + (f"<li><span>영수증</span><strong>이번 달 등록 {receipt_count}건</strong> <a href='/receipts'>영수증 열기</a></li>" if receipt_review.enabled() else "")
            + (f"<li><span>여행 일정 조회</span><strong>다음 조회 {esc(next_note)}</strong></li>" if next_note else "")
            + "</ul>"
            f"<a class='btn primary home-primary' href='/cards/all?panel=upload'>{ui_icons.icon('upload')}카드 업로드</a>"
            "</section>"
            + f"<section class='home-travel-section'><h2 class='home-travel-heading'>{trip_heading} {len(listed_trips[:8])}</h2>"
            + ("<div class='data-table-wrap'><table class='data-table home-trips'><thead><tr><th>여행</th><th>기간</th><th>지출</th><th>마감</th></tr></thead><tbody>" + items + "</tbody></table></div>"
               if items else "<p>진행 중인 여행이 없습니다. 여행은 Google 시트 탭으로 만듭니다.</p>")
            + "<p class='home-all'><a href='/trips'>전체 여행 보기</a></p>"
            + (f"<p class='muted home-next-note'>여행글은 한국 시간 매일 0시에 조회합니다. 다음 조회: {next_note}</p>" if next_note else '')
            + "</section>"
            + ("<section class='home-travel-section'>" + collection_html + "</section>" if collection_html else ""))
    return ledger_design.render(ledger_design.shell(
        '정산 현황', tab_id='', heading='정산 현황', body=body, home=True))


class CardFlow:
    def __init__(self, board):
        from app import Pipeline
        self.board = board
        self._ota_group_holds_cache = None
        self._ota_request_depth = 0
        self._request_ota_snapshot = None
        with board._lock:
            pipeline=getattr(board,'_card_pipeline',None)
            if pipeline is None or pipeline.store.conn is not board.conn:
                pipeline=Pipeline(board.conn)
                pipeline.store.lock=board._lock
                board._card_pipeline=pipeline
            self.pipeline=pipeline

    def trip_valid(self, trip_id):
        return card_trip_authority.trip_valid(
            self, trip_id, google_periods=_google_periods, trip_authority=_trip_authority,
            unchanged_workbook_schedule=_unchanged_workbook_schedule)

    def tab_valid(self, tab):
        from app import quarter_tab
        from app.ledger import REFUND_TAB
        return tab in ('', 'unclassified', REFUND_TAB) or bool(quarter_tab.parse_tab(tab)) or self.trip_valid(tab)

    def retail_trip(self, transaction, country):
        return card_trip_authority.retail_trip(self, transaction, country, google_nets=_google_nets)

    def booking_trip(self, transaction, period):
        return card_trip_authority.booking_trip(self, transaction, period, google_nets=_google_nets,
            handover_days=handover_days, overlaps_stay=overlaps_stay, stay_trip=stay_trip)

    def classify(self, batch_id, *, transaction_ids=None):
        from app import core_writer
        return core_writer.prepared(self.board, lambda: self._classify_request(batch_id, transaction_ids))

    def _classify_request(self, batch_id, transaction_ids):
        with self._ota_request_scope():
            with self.board._lock:
                result = self._classify(batch_id, transaction_ids=transaction_ids)
                self._auto_record_locked(batch_id, include_state=False)
                self.sync_ledger_rows()
                return result

    def sync_ledger_rows(self):
        """규칙 결과를 장부 행에 반영한다. 사용자가 고친 필드(`board_manual_overrides`)는 건드리지 않고, 배정이 있던 자리를 비우지 않는다."""
        conn = self.board.conn
        overridden = {(row_id, field) for row_id, field in conn.execute('SELECT row_id, field FROM board_manual_overrides')}
        rows = conn.execute(
            "SELECT b.row_id, b.revision, b.display_tab_id, b.payload_json, t.display_tab_id, t.item, t.description"
            " FROM board_rows b JOIN transactions t ON b.row_id = 'card-' || t.transaction_id"
            " WHERE b.row_kind='expense' AND t.classification_state='classified'").fetchall()
        synced = 0
        from app.ledger import REFUND_TAB
        for row_id, revision, board_tab, payload, tab, item, description in rows:
            if board_tab == REFUND_TAB:
                continue  # 상쇄되어 환불 탭에 둔 행은 여행 분류가 되돌리지 않는다.
            record = json.loads(payload)
            tab = '' if tab in (None, 'unclassified') else tab
            target = {}
            if tab and tab != board_tab and (row_id, 'display_tab_id') not in overridden:
                target['display_tab_id'] = tab
            if item and item != record.get('item') and (row_id, 'item') not in overridden:
                target['item'] = item
            if description and description != record.get('description') and (row_id, 'description') not in overridden:
                target['description'] = description
            if not target:
                continue
            key = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()[:12]
            self.board.save(row_id=row_id, expected_revision=revision, client_request_id=f'sync-{row_id}-{revision}-{key}',
                            change_mode='rule_change', changes=target, actor='automatic')
            synced += 1
        return synced

    def _classify(self, batch_id, *, transaction_ids=None, snapshot_only=False):
        from app import StoreError
        from .card_classification_completion import complete
        from app.automatic_classification import FIELDS
        initial = {row['transaction_id']: row for row in self._batch_rows(batch_id, transaction_ids)}
        try:
            result = (self._classify_evidence(batch_id, transaction_ids=transaction_ids, snapshot_only=True)
                      if snapshot_only else self._classify_evidence(batch_id, transaction_ids=transaction_ids))
        except StoreError as exc:
            if exc.code != 'OTA_EVIDENCE_UNAVAILABLE':
                raise
            # Missing booking evidence does not prevent an expense classification.
            result = self.pipeline.classify_batch(batch_id, trip_resolver=self.retail_trip,
                review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'), transaction_ids=transaction_ids)
            result['booking_evidence_unavailable'] = True
        result['completion'] = complete(self, batch_id, transaction_ids)
        if not snapshot_only:
            from .card_classification_completion import correct_recorded_booking_periods
            result['booking_trip_corrections'] = correct_recorded_booking_periods(self, batch_id, transaction_ids)
        from collections import Counter
        current = self._batch_rows(batch_id, transaction_ids)
        for row in current:
            before = initial.get(row['transaction_id'])
            if (before and row['revision'] == before['revision'] + 1
                    and all((row.get(key) or '') == (before.get(key) or '') for key in FIELDS)):
                # Repeating the same inference must not invalidate a user's open form.
                self.board.conn.execute('UPDATE transactions SET revision=? WHERE transaction_id=? AND revision=?',
                    (before['revision'], row['transaction_id'], row['revision']))
        if transaction_ids is not None:
            current = [row for row in current if row['transaction_id'] in transaction_ids]
        result['counts'] = dict(Counter(row['classification_state'] for row in current))
        result['needs_review'] = result['counts'].get('needs_review', 0)
        result['classified'] = result['counts'].get('classified', 0)
        return result

    def _batch_rows(self, batch_id, transaction_ids=None):
        """Rows of a batch, or only the named ones; a few-row write never reads the whole batch."""
        if transaction_ids is None:
            return self.pipeline.get_batch(batch_id)['rows']
        return self.pipeline.get_batch(batch_id, transaction_ids=transaction_ids)['rows']

    def _refund_scope(self, batch_id, selected):
        """`selected` plus every batch row its refund pairs and refund-tab groups are judged with.

        A pair or group is held or released as a whole, so the rows narrowed to for a preview must include
        every member that can change the verdict of a selected row.
        """
        from app.partial_refund import refund_links, refund_group
        from .refund_tab import groups
        in_batch = {row[0] for row in self.board.conn.execute(
            'SELECT transaction_id FROM import_batch_rows WHERE batch_id=?', (batch_id,))}
        scope = set(selected) & in_batch
        refund_ids = [r[0] for r in self.board.conn.execute(
            "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
        links = refund_links(self.board.conn, refund_ids)
        all_groups = groups(self.board)
        members = [{r['transaction_id'] for r in group} for group in all_groups]
        while True:
            grown = set(scope)
            for refund, link in links.items():
                if refund in grown or link['original_id'] in grown:
                    grown.update(refund_group(self.board.conn, link['original_id']))
            for group in members:
                if group & grown:
                    grown |= group
            grown &= in_batch
            if grown == scope:
                return scope, in_batch, all_groups
            scope = grown

    def _classify_evidence(self, batch_id, *, transaction_ids=None, snapshot_only=False):
        ota_rules=[]
        blocked_inference_sources=set()
        from app.classify import OWNER_BOOKING_ORIGIN
        selected=None if transaction_ids is None else set(transaction_ids)
        sources={source for source,identity,merchant in self.board.conn.execute(
            'SELECT t.source_hash,t.transaction_id,t.merchant FROM transactions t '
            'JOIN import_batch_rows b ON b.transaction_id=t.transaction_id '
            'WHERE b.batch_id=? AND NOT ' + decided_sql('t') + ' '
            'AND t.conflict_reason=? AND t.parse_error=?'
            + ('' if selected is None else ' AND t.transaction_id IN (SELECT value FROM json_each(?))'),
            (batch_id,'','') if selected is None else (batch_id,'','',json.dumps(sorted(selected))))
            if (selected is None or identity in selected) and _is_ota_row({'merchant':merchant})}
        from app import StoreError, ota_sources
        import sqlite3
        try:
            if snapshot_only:
                current, fresh = self._held_ota_snapshot()
                report = self._canonical_snapshot_report(current) if sources and current and fresh else None
            else:
                report=self._ota_report() if sources else None
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,ota_sources.OtaSourcesError):
            raise StoreError('OTA_EVIDENCE_UNAVAILABLE','등록된 예약 근거 자료를 읽지 못했습니다') from None
        if report is not None and (report.get('ota_source_errors')
                or report.get('ota_source_inventory',{}).get('missing')):
            raise StoreError('OTA_EVIDENCE_UNAVAILABLE','등록된 예약 근거 자료를 모두 확인해 주세요')
        if report is not None:
            blocked_inference_sources={f['source_hash'] for f in report['matches']
                if f.get('reservation_status')=='cancelled' or f.get('period_conflict')}
            blocked_inference_sources.update(f['source_hash'] for f in report.get('type_only_candidates',[])
                                             if not f.get('shared_period'))
            blocked_inference_sources.update(report.get('evidence_gate',{}).get('blocked_inference_sources',()))
            evidence={f['source_hash']:f for f in report['matches']}
            evidence.update({f['source_hash']:dict(f,period=f.get('shared_period'))
                             for f in report.get('type_only_candidates',[])})
            verified_trips=None
            for template in report['rules']:
                source=template['optional']['source_hash']
                if source not in sources:
                    continue
                draft=dict(template,optional=dict(template['optional']),effects=dict(template['effects']))
                fact=evidence.get(source,{})
                period=fact.get('period')
                # 취소되지 않은 예약의 이용기간이 있으면 그 기간의 여행으로 보낸다. 확정 메일 여부는 묻지 않는다.
                if (period and fact.get('reservation_status')!='cancelled'
                        and not fact.get('period_conflict')):
                    if verified_trips is None:
                        verified_trips=[trip for trip in self.board.list_trips() if self.trip_valid(trip['tab_id'])]
                    service=fact.get('item')=='항공료'
                    chosen=stay_trip(verified_trips,period['starts_on'],period['ends_on'],service=service,nets=_google_nets())
                    digests=fact.get('source_digests') or fact.get('evidence_digests') or [fact.get('source_sha256')]
                    if chosen and digests and digests[0]:
                        draft['optional']['booking_period']=dict(period,target_code=chosen['display_key'],
                                                                 source_sha256=digests[0],service=service)
                    else:
                        # 명시 이용기간과 맞지 않는 과거 추론 여행을 다시 붙이지 않는다.
                        blocked_inference_sources.add(source)
                draft['origin']=OTA_PORTAL_ORIGIN if fact.get('evidence_kind')=='portal_payment_claim' else OTA_MAIL_ORIGIN
                draft['rule_id']=('ota-portal-' if draft['origin']==OTA_PORTAL_ORIGIN else 'ota-mail-')+source
                ota_rules.append(draft)
            owned = self._booking_trip_assignments(report, sources)
            if owned:
                # 사용자가 고른 예약 배정이 같은 원본의 자동 제안을 대체한다.
                owned_sources = {rule['optional']['source_hash'] for rule in owned}
                ota_rules = [rule for rule in ota_rules if rule['optional'].get('source_hash') not in owned_sources]
                blocked_inference_sources.update(owned_sources)
                ota_rules += owned
            # 확정 전이라도 예약 이용기간과 하루도 겹치지 않는 여행으로는 저장된 추론을 배정하지 않는다. 사용자 예외는 그대로 둔다.
            trips_by_id = {trip['tab_id']: trip for trip in self.board.list_trips()}
            handover = handover_days(list(trips_by_id.values()))
            for rule in self.pipeline.list_rules():
                source = rule.get('optional', {}).get('source_hash')
                inference = rule.get('optional', {}).get('inferred_assignment') or {}
                fact = evidence.get(source) or {}
                period, trip = fact.get('period'), trips_by_id.get(inference.get('trip_id'))
                if (source in sources and period and trip and trip['starts_on'] and trip['ends_on']
                        and rule.get('origin') != OWNER_COUNTRY_EXCEPTION_ORIGIN
                        and not overlaps_stay(trip['starts_on'], trip['ends_on'], period['starts_on'], period['ends_on'],
                                              service=fact.get('item') == '항공료', handover=handover)):
                    blocked_inference_sources.add(source)
            # 이용기간으로 정해진 예약 배정은 같은 원본에 다른 제안이 없을 때만 적용한다.
            taken = {rule['optional'].get('source_hash') for rule in ota_rules}
            # 저장된 추론은 검증된 예약 이용기간보다 약하므로 기간 근거가 이를 대체할 수 있다.
            taken |= {rule['optional'].get('source_hash') for rule in self.pipeline.list_rules()
                      if rule.get('optional', {}).get('inferred_assignment')
                      and rule.get('origin') != OWNER_BOOKING_ORIGIN
                      and not str(rule.get('origin') or '').startswith('history-recovery')
                      and rule.get('optional', {}).get('source_hash') not in blocked_inference_sources}
            ota_rules += self._booking_period_assignments(report, sources, taken)
        taken = {rule['optional'].get('source_hash') for rule in ota_rules}
        candidate_sources = {source for source, in self.board.conn.execute(
            'SELECT t.source_hash FROM transactions t JOIN import_batch_rows r ON r.transaction_id=t.transaction_id '
            'WHERE r.batch_id=?', (batch_id,))}
        ota_rules += self._canonical_candidate_period_assignments(
            candidate_sources, taken, selected, blocked_inference_sources)
        taken = {rule['optional'].get('source_hash') for rule in ota_rules}
        if not snapshot_only:
            ota_rules += self._evidence_period_assignments(batch_id, sources, taken, selected)
        ota_rules += self._guide_airfare_rules(batch_id, selected)
        board_rules = self._board_future_rules()
        active_owner_sources = {rule['optional'].get('source_hash') for rule in ota_rules
                                if rule.get('origin') == OWNER_BOOKING_ORIGIN}
        stale_owner_sources = {rule.get('optional', {}).get('source_hash')
                               for rule in self.pipeline.list_rules()
                               if rule.get('origin') == OWNER_BOOKING_ORIGIN
                               and rule.get('optional', {}).get('source_hash') not in active_owner_sources}
        taken = set()
        for rule in ota_rules + board_rules + self.pipeline.list_rules():
            optional = rule.get('optional', {})
            if not (optional.get('inferred_assignment') or optional.get('booking_period')):
                continue
            if (rule.get('origin') == OWNER_BOOKING_ORIGIN
                    and optional.get('source_hash') not in active_owner_sources):
                continue
            taken.add(optional.get('source_hash'))
        ota_rules += self._fallback_trip_assignments(batch_id, taken, selected, blocked_inference_sources)
        from app.closed_period import formal_facts
        period_trips = [dict(t,trip_id=t['tab_id']) for t in self.board.list_trips() if self.trip_valid(t['tab_id'])]
        period_evidence = formal_facts((report or {}).get('matches', []),period_trips)
        if ota_rules or blocked_inference_sources or board_rules:
            from app.classify import classify_batch
            active=[rule for rule in self.pipeline.list_rules() if not
                    ((rule.get('optional',{}).get('inferred_assignment')
                      and rule['optional'].get('source_hash') in blocked_inference_sources)
                     or (rule.get('origin') == OWNER_BOOKING_ORIGIN
                         and rule.get('optional', {}).get('source_hash') in stale_owner_sources))]
            active, board_rules = self._board_rules_supersede(active, board_rules)
            return classify_batch(self.pipeline.store,batch_id,
                rules=active+board_rules+ota_rules,trip_resolver=self.retail_trip,
                review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),transaction_ids=selected,residual_policy=True,
                completed_trips=period_trips,completed_evidence=period_evidence)
        from app.classify import classify_batch
        return classify_batch(self.pipeline.store, batch_id, trip_resolver=self.retail_trip,
                              review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),transaction_ids=selected,
                              residual_policy=True,completed_trips=period_trips,completed_evidence=period_evidence)

    def _fallback_trip_assignments(self, batch_id, taken, selected, blocked_sources):
        """정확 근거가 없는 정상 카드에도 실제 여행의 우선 후보를 제안한다."""
        from datetime import date
        from app.classify import _pattern_for
        from app.normalize import normalize_merchant
        trips = [trip for trip in self.board.list_trips() if self.trip_valid(trip['tab_id'])
                 and trip.get('starts_on') and trip.get('ends_on')]
        if not trips:
            return []
        rows = self.board.conn.execute(
            "SELECT t.transaction_id,t.source_hash,t.merchant,t.item,t.approval_date,t.card_tail FROM transactions t"
            " JOIN import_batch_rows r ON r.transaction_id=t.transaction_id WHERE r.batch_id=?"
            " AND t.classification_state IN ('needs_review','classified') AND NOT " + decided_sql('t') +
            " AND t.transaction_direction='purchase' AND t.amount_krw>0"
            " AND COALESCE(t.card_tail,'')!='3820' AND COALESCE(t.item,'')!='분기 기타비용'"
            " AND ((COALESCE(t.display_tab_id,'') IN ('','unclassified') AND COALESCE(t.trip_id,'')='')"
            " OR (t.classification_source='inference' AND t.classification_basis LIKE '%AUTO_INFERRED:%'))"
            " AND COALESCE(t.duplicate_of,'')='' AND COALESCE(t.conflict_reason,'')='' AND COALESCE(t.parse_error,'')=''"
            " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
            " AND NOT EXISTS(SELECT 1 FROM board_rows b WHERE b.row_id='card-'||t.transaction_id)"
            " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
            " AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)"
            " AND NOT EXISTS(SELECT 1 FROM transactions f WHERE f.card_tail=t.card_tail"
            " AND f.transaction_direction='cancellation' AND f.original_approval_number=t.approval_number"
            " AND COALESCE(t.approval_number,'')!='')", (batch_id,)).fetchall()
        rules = []
        nets = _google_nets()
        held = self.ota_group_holds() if rows else {}
        current, fresh = self._held_ota_snapshot() if rows else (None, False)
        period_cards = set()
        if current and fresh:
            data = current.get('data') or {}
            dated = {str(event.get('ota_event_id')) for event in data.get('events', [])
                     if (event.get('service_period') or {}).get('starts_on')}
            for result in data.get('results', []):
                if str(result.get('ota_event_id')) in dated:
                    period_cards.update(str(candidate.get('transaction_id')) for candidate in
                                        (result.get('candidate_search') or {}).get('candidates', []))
                    if result.get('transaction_id'):
                        period_cards.add(str(result['transaction_id']))
        for tid, source, merchant, item, day, card_tail in rows:
            if tid in held or tid in period_cards or source in taken or source in blocked_sources or (selected is not None and tid not in selected):
                continue
            pattern = _pattern_for(normalize_merchant(merchant or ''))
            item = item or (pattern[0] if pattern else '')
            if not item:
                continue  # 항목 자체를 창작하지 않는다.
            try:
                occurred = date.fromisoformat(day)
            except (ValueError, TypeError):
                continue
            from app.provisional_assignment import card_trip_candidates, rank_trip_candidates
            canonical = [dict(trip, trip_id=trip['tab_id']) for trip in trips]
            decision = rank_trip_candidates(card_trip_candidates(
                {'merchant': merchant, 'approval_date': day, 'card_tail': card_tail}, canonical, nets=nets), trips=canonical)
            if decision['status'] != 'CLASSIFIED':
                continue
            trip = next(trip for trip in trips if trip['tab_id'] == decision['trip_id'])
            basis = ('AUTO_INFERRED: 실제 여행 후보 중 가맹점 지역명과 카드 이용일의 기간 근접도로 우선 배정. '
                     '확신 정도: 낮음. 카드 이용일을 예약 이용일로 확정하지 않았으며 예약번호와 결제 연결은 미확정입니다.')
            rules.append({'conditions': {'merchant_normalized': normalize_merchant(merchant),
                                        'transaction_direction': 'purchase'},
                          'optional': {'source_hash': source, 'inferred_assignment': {
                              'trip_id': trip['tab_id'], 'confidence': '낮음', 'basis': basis}},
                          'effects': {'item': item}, 'origin': 'automatic-trip-priority',
                          'rule_id': 'auto-trip-priority-' + source[:16], 'note': ''})
        return rules

    def _evidence_period_assignments(self, batch_id, sources, taken, selected):
        """예약 확정 메일의 서비스 기간으로 OTA 및 직접 결제 호텔의 미배정 거래를 연결한다.

        호텔 직접 결제는 호텔명·지점·금액·단일 카드 거래까지 확인한 경우에만 추론한다.
        결제일은 숙박일로 간주하지 않는다.
        """
        from app import booking_evidence
        from app.classify import PERIOD_OTA_ORIGIN, _pattern_for
        from app.normalize import normalize_merchant
        from . import ota_catalog
        rows = self.board.conn.execute(
            "SELECT t.transaction_id, t.source_hash, t.amount_krw, COALESCE(NULLIF(t.approval_date,''),t.posting_date), t.merchant"
            " FROM transactions t JOIN import_batch_rows b ON b.transaction_id=t.transaction_id"
            " WHERE b.batch_id=? AND t.classification_state IN ('needs_review','classified')"
            " AND t.transaction_direction='purchase' AND t.amount_krw > 0"
            " AND COALESCE(t.display_tab_id,'') IN ('','unclassified')"
            " AND NOT " + decided_sql('t') +
            " AND COALESCE(t.conflict_reason,'')='' AND COALESCE(t.parse_error,'')=''"
            " AND COALESCE(t.duplicate_of,'')=''"
            " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
            " AND NOT EXISTS(SELECT 1 FROM board_rows b2 WHERE b2.row_id='card-'||t.transaction_id)"
            " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)",
            (batch_id,)).fetchall()
        def eligible(row):
            if row[1] in taken or (selected is not None and row[0] not in selected):
                return False
            if _is_ota_row({'merchant': row[4] or ''}):
                # 기존 OTA 확정 경로만 유지한다. 일반적인 미배정 OTA 결제까지
                # 금액이 같은 메일만으로 추론 연결하는 범위를 넓히지 않는다.
                state, classification_source = self.board.conn.execute(
                    "SELECT classification_state,classification_source FROM transactions WHERE transaction_id=?",
                    (row[0],),
                ).fetchone()
                return (row[1] in sources and state == 'needs_review'
                        and classification_source == 'booking_evidence_needed')
            pattern = _pattern_for(normalize_merchant(row[4] or ''))
            return bool(pattern and pattern[0] == '숙박비')
        rows = [row for row in rows if eligible(row)]
        if not rows:
            return []
        index = booking_evidence.build_index(ota_catalog.configured_sources(self.board)['mail_directories'])
        rules = []
        for tid, source, amount, day, merchant in rows:
            direct = not _is_ota_row({'merchant': merchant or ''})
            found, _ = booking_evidence.find(index, amount, day, limit=None)
            if direct:
                # 띄어쓰기 등 카드 가맹점 표기가 다른 복수 결제도 중복 후보로 본다.
                if not day:
                    continue
                same_amount_cards = self.board.conn.execute(
                    "SELECT merchant FROM transactions WHERE amount_krw=?"
                    " AND transaction_direction='purchase'"
                    " AND COALESCE(NULLIF(approval_date,''),posting_date) BETWEEN date(?,'-120 days') AND date(?,'+120 days')",
                    (amount, day, day),
                ).fetchall()
                if sum(booking_evidence.same_direct_hotel_branch(other[0], merchant)
                       for other in same_amount_cards) != 1:
                    continue
                same_branch = [entry for entry in found
                               if booking_evidence.direct_hotel_branch_matches(entry, merchant)]
                # 동일 예약에 취소 또는 보증금 안내가 있으면 이전 확정 메일로 연결하지 않는다.
                if any('취소' in entry.get('subject', '') or any(
                        word in ' '.join(entry.get('notes') or ())
                        for word in ('환불', '돌려드립니다', '객실 확보', '보증금', '결제 실패', '결제 거부'))
                       for entry in same_branch):
                    continue
                # 같은 호텔·금액의 다른 예약번호가 있으면 결제 대상 예약을 결정할 수 없다.
                refs_in_branch = {tuple(entry.get('refs') or ()) for entry in same_branch}
                if len(refs_in_branch) != 1 or not all(refs_in_branch):
                    continue
                refs = next(iter(refs_in_branch))
                # 취소 및 환불 메일에는 카드 결제 금액이 생략되는 경우가 있다.
                # 이전 예약 확정 메일의 금액만으로 연결하지 않도록 예약번호 전체 이력을 확인한다.
                if any('취소' in entry.get('subject', '') or any(
                        word in ' '.join(entry.get('notes') or ())
                        for word in ('환불', '돌려드립니다', '객실 확보', '보증금', '결제 실패', '결제 거부'))
                       for entry in booking_evidence.find_refs(index, refs)):
                    continue
                found = [entry for entry in same_branch
                         if booking_evidence.matches_direct_hotel(entry, merchant, amount=amount)]
            bookings = {}
            for entry in found:
                subject = entry['subject']
                if '확정' not in subject or '취소' in subject or not entry['starts_on'] or not entry['ends_on'] or not entry['refs']:
                    continue
                bookings.setdefault(tuple(entry['refs']), set()).add((entry['starts_on'], entry['ends_on']))
            if len(bookings) != 1:
                continue
            (refs, periods), = bookings.items()
            if len(periods) != 1:
                continue
            starts_on, ends_on = next(iter(periods))
            trip = self.booking_trip({}, {'starts_on': starts_on, 'ends_on': ends_on})
            if not trip:
                continue
            rules.append({
                'conditions': {'merchant_normalized': normalize_merchant(merchant or ''), 'transaction_direction': 'purchase'},
                'optional': {'source_hash': source, 'inferred_assignment': {
                    'trip_id': trip, 'confidence': '중간' if direct else '높음',
                    'basis': (f"호텔 지점·예약번호·결제 완료 금액이 일치하는 메일의 이용기간 {starts_on}~{ends_on}이 검증된 여행에 속함"
                              if direct else f"같은 금액의 예약 확정 메일이 있고 이용기간 {starts_on}~{ends_on}이 여행 기간 안에 있음")}},
                'effects': {'item': '숙박비'}, 'origin': PERIOD_OTA_ORIGIN, 'note': '',
                'rule_id': f"auto-evidence-period-{refs[0]}-{source[:12]}",
            })
        return rules

    def _review_rules(self):
        """검토 저장소에 사용자가 승인한 좁은 규칙. 경로가 없거나 읽을 수 없으면 비어 있다."""
        from app import ota_review
        from . import ota_payment_review
        path = ota_payment_review.review_db_path()
        if not path or not Path(path).is_file():
            return []
        try:
            store = ota_review.OtaReviewStore(path)
        except ValueError:
            return []
        try:
            return store.active_rules()
        finally:
            store.close()

    def _booking_trip_rules(self):
        """사용자가 예약마다 고른 여행 배정. 검토 자료가 설정되지 않았거나 읽을 수 없으면 비어 있다."""
        from app import ota_review
        from . import ota_payment_review
        path = ota_payment_review.review_db_path()
        if not ota_payment_review.enabled() or not path or not Path(path).is_file():
            return {}
        try:
            store = ota_review.OtaReviewStore(path)
        except ValueError:
            return {}
        try:
            return store.booking_trip_rules()
        finally:
            store.close()

    def _booking_trip_assignments(self, report, sources):
        """예약 배정을 그 예약의 살아 있는 카드 결제 원본에만 적용하는 규칙을 만든다.

        취소된 예약과 기간이 충돌하는 대사는 제외한다. 원본 거래마다 따로 묶어 다른 거래로 번지지 않게 한다."""
        from app.classify import OWNER_BOOKING_ORIGIN
        from app.normalize import normalize_merchant
        assignments = self._booking_trip_rules()
        if not assignments:
            return []
        owned = {}
        for fact in report.get('matches', []):
            source = fact.get('source_hash')
            if source not in sources or fact.get('reservation_status') == 'cancelled' or fact.get('period_conflict'):
                continue
            if fact.get('direction', 'purchase') != 'purchase':
                continue
            assignment = assignments.get((str(fact.get('provider')), str(fact.get('booking_ref'))))
            item = str(fact.get('item') or '').strip()
            merchant = str(fact.get('merchant') or '').strip()
            if not assignment or not item or not merchant:
                continue
            owned[source] = {
                'conditions': {'merchant_normalized': normalize_merchant(merchant), 'transaction_direction': 'purchase'},
                'optional': {'source_hash': source, 'inferred_assignment': {
                    'trip_id': assignment['trip_tab_id'], 'confidence': '높음',
                    'basis': f"예약 {fact.get('booking_ref')} 배정 r{assignment['revision']}: {assignment['basis']}"}},
                'effects': {'item': item}, 'origin': OWNER_BOOKING_ORIGIN, 'note': '',
                'rule_id': f"owner-ota-booking-{fact.get('provider')}-{fact.get('booking_ref')}-{source[:12]}",
            }
        return list(owned.values())

    def _booking_period_assignments(self, report, sources, taken):
        """예약이 확정되어 이용기간을 덮는 검증된 여행이 하나뿐인 카드 결제에 그 여행을 추론 배정으로 적용한다."""
        candidates = [fact for fact in report.get('matches', [])
                      if fact.get('source_hash') in sources and fact.get('source_hash') not in taken]
        if not candidates:
            return []
        import sqlite3
        from app import ota_sources
        from app.classify import PERIOD_OTA_ORIGIN
        from app.normalize import normalize_merchant
        from . import ota_catalog
        try:
            index = ota_catalog._index(self.board, ota_catalog.configured_sources(self.board))
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, ota_sources.OtaSourcesError):
            return []
        periods = {(entry['provider'], entry['booking_ref']): entry['period_trip']
                   for entry in index['entries'] if entry.get('period_trip')}
        if not periods:
            return []
        rules = {}
        for fact in candidates:
            source = fact.get('source_hash')
            if source not in sources or source in taken or fact.get('reservation_status') == 'cancelled' \
                    or fact.get('period_conflict') or fact.get('direction', 'purchase') != 'purchase':
                continue
            trip = periods.get((str(fact.get('provider') or '').lower(), str(fact.get('booking_ref') or '')))
            item = str(fact.get('item') or '').strip()
            merchant = str(fact.get('merchant') or '').strip()
            if not trip or not item or not merchant:
                continue
            rules[source] = {
                'conditions': {'merchant_normalized': normalize_merchant(merchant), 'transaction_direction': 'purchase'},
                'optional': {'source_hash': source, 'inferred_assignment': {
                    'trip_id': trip['id'], 'confidence': '높음',
                    'basis': f"예약 이용기간이 여행 「{trip['name']}」 기간 안에 있고 예약이 확정됨"}},
                'effects': {'item': item}, 'origin': PERIOD_OTA_ORIGIN, 'note': '',
                'rule_id': f"auto-ota-period-{fact.get('booking_ref')}-{source[:12]}",
            }
        return list(rules.values())

    def _canonical_candidate_period_assignments(self, sources, taken, selected, blocked_sources):
        """Infer a trip from verified OTA service dates without confirming its payment link."""
        from app import ota_payments
        from app.classify import PERIOD_OTA_ORIGIN
        from app.ota_core_projection import project_canonical_candidate_period_assignments
        from collections import defaultdict

        current, fresh = self._held_ota_snapshot()
        if not current or not fresh:
            return []
        data = current.get('data') or {}
        events = {str(event.get('ota_event_id') or ''): event for event in data.get('events', [])}
        cards = {str(card.get('transaction_id') or ''): card for card in data.get('transactions', [])}
        results = data.get('results', [])
        reserved = {str(identity) for result in results
                    for identity in result.get('reserved_card_ids') or ()}
        reserved.update(str(link.get('transaction_id')) for link in (data.get('links') or {}).values()
                        if isinstance(link, dict) and link.get('transaction_id'))
        reserved.update(str(result.get('transaction_id')) for result in results
                        if result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER') and
                        result.get('transaction_id'))
        verified_trips = [trip for trip in self.board.list_trips() if self.trip_valid(trip['tab_id'])]
        choices = defaultdict(set)
        for result in results:
            reservation_only = result.get('status') == 'RESERVATION_ONLY'
            if result.get('status') not in ('HOLD_DATE_UNKNOWN', 'RESERVATION_ONLY'):
                continue
            event = events.get(str(result.get('ota_event_id') or ''), {})
            period = event.get('service_period') or {}
            reservation = (reservation_only and event.get('provider') == 'toyoko'
                           and event.get('event_type') == 'reservation'
                           and event.get('evidence_status') == 'reservation_only')
            if ((not reservation and (event.get('event_type') != 'charge' or not ota_payments._event_is_paid(event))) or
                    event.get('reservation_status') in ('cancelled', 'refunded') or
                    event.get('service_period_conflict') or event.get('period_conflict') or
                    not period.get('starts_on') or not period.get('ends_on') or
                    result.get('evidence_missing') or result.get('evidence_changed') or
                    result.get('group_count') or event.get('group_count')):
                continue
            search = result.get('candidate_search') or {}
            if search.get('status') != 'CANDIDATES_FOUND':
                continue
            item = str(event.get('item') or '').strip()
            if not item:
                continue
            trip = stay_trip(verified_trips, period['starts_on'], period['ends_on'],
                             service=item not in ('숙박비', '숙박료'), nets=_google_nets())
            if not trip:
                continue
            for candidate in search.get('candidates') or ():
                transaction_id = str(candidate.get('transaction_id') or '')
                card = cards.get(transaction_id)
                source = str((card or {}).get('source_hash') or '')
                if (not card or not source or source not in sources or source in taken or
                        source in blocked_sources or transaction_id in reserved or
                        (selected is not None and transaction_id not in selected) or
                        card.get('ota_inference_eligible') is not True or
                        card.get('transaction_direction') != 'purchase' or card.get('duplicate_of') or
                        card.get('parse_error') or card.get('conflict_reason') or
                        candidate.get('resolution_allowed')):
                    continue
                choices[source].add((str(trip['tab_id']), item,
                                     str(period['starts_on']), str(period['ends_on'])))

        flattened = [(source, *option) for source, options in choices.items() for option in options]
        rules = project_canonical_candidate_period_assignments(
            cards=cards, choices=flattened)
        return [rule for rule in rules if self.trip_valid(rule['optional']['inferred_assignment']['trip_id'])]

    def _board_future_rules(self):
        """장부에서 '미래 적용'으로 켠 규칙을 카드 분류 규칙으로 옮긴다.

        가맹점 조건만 가진 규칙만 옮기고(카드 구분·방향 조건이나 제외 조건이 있으면 건너뛴다),
        여행 배정은 규칙의 연도 범위로 제한한다. 사용자가 직접 정한 답변은 분류가 덮지 않는다."""
        lister = getattr(self.board, 'active_future_rules', None)
        if not callable(lister):
            return []
        converted = []
        for stored in lister():
            rule = stored.get('rule') or {}
            conditions = rule.get('conditions') or {}
            if list(conditions) != ['merchant_normalized'] or rule.get('exceptions'):
                continue
            entry = conditions['merchant_normalized']
            merchants = entry['value'] if entry.get('op') == 'in' else [entry.get('value')] if entry.get('op') == 'eq' else []
            effects = {k: v for k, v in (rule.get('effects') or {}).items() if k in ('item', 'display_tab_id')}
            if not merchants or not effects:
                continue
            optional = {}
            amount = (rule.get('optional_conditions') or {}).get('amount_range')
            if amount:
                optional['amount_range'] = dict(amount)
            period = dict((rule.get('optional_conditions') or {}).get('date_or_service_period') or {})
            scope = rule.get('scope') or {}
            if 'display_tab_id' in effects and scope.get('event_year'):
                year = str(scope['event_year'])
                period.setdefault('from', year + '-01-01')
                period.setdefault('to', year + '-12-31')
            if period:
                optional['date_or_service_period'] = {k: v for k, v in
                                                      (('start', period.get('from')), ('end', period.get('to'))) if v}
            for index, merchant in enumerate(merchants):
                converted.append({'rule_id': f"board-{stored['rule_id']}-{index}", 'version': stored.get('version', 1),
                                  'status': 'active', 'conditions': {'merchant_normalized': merchant},
                                  'effects': dict(effects), 'optional': optional,
                                  'note': '장부 규칙(미래 적용)', 'origin': 'board-rule'})
        return converted

    @staticmethod
    def _board_rules_supersede(card_rules, board_rules):
        """사용자가 미리보기를 보고 명시 적용한 가맹점 규칙이 같은 가맹점의 일반 카드 규칙을 대체한다.

        일반 규칙 = 가맹점 조건만 있고 선택 조건이 없는 규칙. 대체하지 않으면 두 규칙이 서로 다른
        항목을 제안해 이후 거래가 전부 충돌 검토로 빠진다. 설명 등 새 규칙이 바꾸지 않는 항목은
        기존 규칙 값을 이어받는다. 원천 거래·예약에 묶인 규칙은 건드리지 않는다."""
        kept = list(card_rules)
        merged_rules = []
        for rule in board_rules:
            merchant = rule['conditions']['merchant_normalized']
            if rule.get('optional') or 'item' not in rule['effects']:
                merged_rules.append(rule)
                continue
            generic = [r for r in kept
                       if (r.get('conditions') or {}).get('merchant_normalized') == merchant
                       and set(r.get('conditions') or {}) <= {'merchant_normalized', 'card_kind', 'transaction_direction'}
                       and not r.get('optional')]
            if not generic:
                merged_rules.append(rule)
                continue
            # 새 규칙이 바꾸지 않는 항목(설명 등)은 기존 규칙들이 모두 같은 값일 때만 이어받는다.
            inherited = {}
            for key in {k for old in generic for k in (old.get('effects') or {})}:
                values = {str((old.get('effects') or {}).get(key)) for old in generic}
                if len(values) == 1:
                    inherited[key] = next(iter(generic)).get('effects', {}).get(key)
            for old in generic:
                kept.remove(old)
            merged_rules.append(dict(rule, effects={**inherited, **rule['effects']}))
        return kept, merged_rules

    _GUIDE_KIND_LABELS = {
        'pre_departure': '여행 시작 전 출국', 'post_trip_return': '여행 종료 뒤 귀국',
        'inter_trip': '여행 사이 이동', 'mid_trip_join': '여행 중 합류',
        'early_leave': '여행 중 조기 이탈', 'round_trip': '왕복 업무 이동'}

    def _guide_airfare_rules(self, batch_id, selected):
        """대장·가이드 항공권 귀속 판정을 스냅샷에서만 읽어 규칙으로 만든다. 여기서 대사나 파싱을 하지 않는다."""
        from . import ota_payment_review
        if not ota_payment_review.enabled():
            return []
        from . import guide_airfare_review
        if not guide_airfare_review.write_authorization(self.board)[0]:
            return []
        current, fresh = self._held_ota_snapshot()
        if current is None or not fresh:
            return []
        attributed = {}
        for result in current.get('results') or []:
            guide = result.get('guide_airfare') or {}
            if (guide.get('status') == 'ATTRIBUTED' and guide.get('trip_id') and result.get('transaction_id')
                    and result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER')):
                attributed[str(result['transaction_id'])] = guide
        if not attributed:
            return []
        rows = self.board.conn.execute(
            'SELECT t.transaction_id,t.source_hash,t.merchant,t.merchant_normalized,t.card_kind '
            'FROM transactions t JOIN import_batch_rows b ON b.transaction_id=t.transaction_id '
            'WHERE b.batch_id=? AND NOT ' + decided_sql('t') + ' '
            'AND t.conflict_reason=? AND t.parse_error=? AND t.transaction_direction=?',
            (batch_id, '', '', 'purchase')).fetchall()
        rules = []
        for identity, source_hash, merchant, merchant_normalized, card_kind in rows:
            guide = attributed.get(str(identity))
            if guide is None or (selected is not None and identity not in selected) or not _is_ota_row({'merchant': merchant}):
                continue
            kind = str(guide.get('code') or '').removeprefix('guide_airfare_')
            basis = '{} · 탑승자 대장 확인 · 여행 {} · 근거 {}'.format(
                self._GUIDE_KIND_LABELS.get(kind, kind), guide.get('trip_name') or '', str(guide.get('evidence_digest') or '')[:12])
            rules.append(dict(
                conditions={'merchant_normalized': merchant_normalized, 'card_kind': card_kind,
                            'transaction_direction': 'purchase'},
                optional={'source_hash': source_hash,
                          'inferred_assignment': {'trip_id': guide['trip_id'], 'confidence': '높음', 'basis': basis}},
                effects={'item': '항공료', 'description': '예약 ' + str(guide.get('booking_ref') or '')},
                origin=GUIDE_AIRFARE_ORIGIN, rule_id='guide-airfare-' + source_hash))
        return rules

    def preview_metadata(self, *, display_only=False):
        """한 미리보기 요청에서는 같은 OTA 대조 결과를 재사용한다."""
        from app.ota_mail import ledger_metadata
        from app import ota_sources
        import sqlite3
        report = None
        loaded = False

        def metadata(entry):
            nonlocal report, loaded
            if not _is_ota_row(entry):
                return {}
            if not loaded:
                try:
                    from . import ota_payment_review
                    if display_only and ota_payment_review.enabled():
                        current, fresh = self._held_ota_snapshot()
                        report = self._canonical_snapshot_report(current) if current is not None and fresh else None
                    else:
                        report = self._ota_report()
                except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,ota_sources.OtaSourcesError):
                    report = {'ota_source_errors':[{'error':'source_read_failed'}]}
                loaded = True
            return ledger_metadata(report, entry)

        return metadata

    def project(self, entry):
        """새 전기와 기존 장부 화면의 행을 같은 트랜잭션에서 저장한다."""
        from app import quarter_tab
        from app.db import StoreError
        trip = entry.get('trip_id') or ''
        tab = entry.get('display_tab_id') or ''
        # 분기 기타비용 탭은 여행이 아니므로 여행 일정 근거 검증 대상이 아니다.
        if not (self.tab_valid(tab) or quarter_tab.parse_tab(tab)) or (trip and not self.trip_valid(trip)):
            raise StoreError('TRIP_AUTHORITY_CHANGED', '여행 일정 근거를 다시 확인해 주세요')
        if trip and tab != trip:
            raise StoreError('TRIP_TARGET_CONFLICT', '여행과 장부 탭이 다릅니다')
        row_id = 'card-' + entry['transaction_id']
        board_tab = None if tab in ('','unclassified') else tab
        conn = self.board.conn
        if conn.execute('SELECT 1 FROM board_rows WHERE row_id=?', (row_id,)).fetchone():
            raise StoreError('BOARD_ROW_CONFLICT', '이미 존재하는 장부 행입니다')
        source = conn.execute('SELECT issuer,card_tail,approval_number,posting_date,'
                              'foreign_amount,foreign_currency,transaction_kind,approval_date,classification_source,classification_basis FROM transactions '
                              'WHERE transaction_id=?', (entry['transaction_id'],)).fetchone()
        if self._already_projected(source, entry):
            raise StoreError('EXISTING_LEDGER_TRANSACTION', '기존 장부에 같은 승인 거래가 있습니다. 다시 기록하지 않습니다')
        record = dict(row_id=row_id, row_kind='expense', revision=1,
                      display_tab_id=board_tab, occurred_on=entry['occurred_on'],
                      item=entry['item'], description=entry['description'],
                      service_period=entry.get('service_period',''), reservation_no=entry.get('booking_ref',''), evidence_type='카드',
                      amount_krw=entry['amount_krw'], source_kind='카드',
                      source_event_id=entry['transaction_id'], source_fact_digest=entry['source_hash'],
                      source_merchant=entry['merchant'], source_issuer=source[0],
                      source_card_last4=source[1], source_approval_number=source[2],
                      source_approval_date=source[7], source_posting_date=source[3],
                      source_local_amount=source[4], source_currency=source[5],
                      event_kind=source[6], classification_state=entry['classification_state'],
                      confirmed_by=('automatic' if entry.get('automatic_record') else 'owner'), memo='')
        if entry.get('ota_evidence'):
            record['classification_basis'] = 'OTA 예약 메타데이터 근거 · ' + json.dumps(
                entry['ota_evidence'], ensure_ascii=False, sort_keys=True)
        if entry.get('automatic_record'):
            record['classification_source'] = source[8]
            if source[9]:
                record['classification_basis'] = source[9]
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                     (row_id, 'expense', board_tab, 1, payload))
        conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,'
                     'change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                     (row_id,1,'{}',payload,'','exception','automatic' if entry.get('automatic_record') else 'owner',entry['now'],row_id))

    def projected_ids(self, rows):
        """(거래 ID, 금액, 일자) 목록 가운데 이미 장부에 있는 거래 ID. 장부 색인은 한 번만 만든다."""
        index = self._projection_index()
        found = set()
        for transaction_id, amount_krw, occurred_on in rows:
            source = self.board.conn.execute(
                'SELECT issuer,card_tail,approval_number,posting_date,foreign_amount,foreign_currency,transaction_kind,approval_date'
                ' FROM transactions WHERE transaction_id=?', (transaction_id,)).fetchone()
            if self._already_projected(source, {'transaction_id': transaction_id, 'amount_krw': amount_krw,
                                                'occurred_on': occurred_on}, index):
                found.add(transaction_id)
        return found

    def _already_projected(self, source, entry, index=None):
        """같은 거래를 두 번 기록하지 않으면서 실제 여러 건은 함께 남긴다.

        카드 행이 스스로 가진 거래 ID를 정본으로 삼는다. 같은 승인번호라도 거래 ID가 다른
        결제와 취소는 서로 다른 거래이므로 합치지 않는다. 거래 ID가 없는 과거 장부 행에만
        발급사·카드·승인번호·일자·부호 있는 금액·거래 종류가 모두 같은 좁은 조건을 적용한다.
        원문 해시만으로는 구분하지 않는다. 해시에 행 위치가 들어가지 않아 정당한 여러 건이
        같은 해시를 공유하기 때문이다.
        """
        by_event, legacy = index or self._projection_index()
        if entry['transaction_id'] in by_event:
            return True
        if not source[2]:
            # 승인번호가 없으면 거래 ID가 유일한 정본이다. 좁은 조건을 쓸 근거가 없다.
            return False
        return (source[0], source[1], source[2], entry['occurred_on'],
                entry['amount_krw'], source[6] or '') in legacy

    def _projection_index(self):
        """장부 행의 거래 ID와 옛 행의 승인 키를 한 번에 모은다. 장부 행이 바뀔 때만 다시 만든다."""
        conn = self.board.conn
        version = tuple(conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid),0), COALESCE(SUM(revision),0) FROM board_rows").fetchone())
        cached = getattr(self, '_projection_cache', None)
        if cached and cached[0] == version:
            return cached[1]
        by_event = {row[0] for row in conn.execute(
            "SELECT json_extract(payload_json,'$.source_event_id') FROM board_rows "
            "WHERE COALESCE(json_extract(payload_json,'$.source_event_id'),'')!=''")}
        legacy = {row for row in conn.execute(
            "SELECT json_extract(payload_json,'$.source_issuer'), json_extract(payload_json,'$.source_card_last4'), "
            "json_extract(payload_json,'$.source_approval_number'), json_extract(payload_json,'$.occurred_on'), "
            "json_extract(payload_json,'$.amount_krw'), COALESCE(json_extract(payload_json,'$.event_kind'),'') "
            "FROM board_rows WHERE COALESCE(json_extract(payload_json,'$.source_event_id'),'')=''")
            if None not in row[:5]}
        index = (by_event, legacy)
        self._projection_cache = (version, index)
        return index

    def _ota_sources(self):
        """등록된 OTA 근거 자료를 모두 모은다. 임의로 훑지 않는다."""
        from app import ota_sources
        from app.ota_portal import evidence_path
        data_directory = self.board.path.parent
        mail_default = os.environ.get('WEBLEDGER_OTA_MAIL_DIR') or (data_directory/'ota-mail')
        sources = ota_sources.resolve_sources(
            data_directory, mail_default=mail_default, portal_default=evidence_path(data_directory))
        return sources

    def _ota_report(self):
        """한 조회 안에서는 미리보기와 근거 조회가 같은 대사 결과를 쓴다."""
        from . import ota_payment_review
        if ota_payment_review.enabled():
            current, fresh = self._held_ota_snapshot()
            if current is not None and fresh:
                return self._canonical_snapshot_report(current)

        memo = getattr(self, '_request_report', None)
        if memo is None:
            report = self._compute_ota_report()
        else:
            if not memo:
                memo.append(self._compute_ota_report())
            report = memo[0]
        if report is not None and ota_payment_review.enabled():
            current, fresh = self._held_ota_snapshot()
            if current is not None and fresh:
                # A snapshot can become fresh while the legacy recovery report is
                # being calculated. Discard that report so it cannot reserve a
                # card or outrank the newly available canonical decision.
                return self._canonical_snapshot_report(current)
        if report is not None:
            report = dict(report)
            report['_reconciliation_authority'] = (
                'legacy_fallback_stale_snapshot' if ota_payment_review.enabled()
                else 'legacy_fallback_feature_disabled')
        return report

    def _canonical_snapshot_report(self, current):
        """Project only a fresh central snapshot; never merge stale legacy decisions into it."""
        from app.ota_core_projection import extend_report
        data = current.get('data') or {}
        events = {str(event.get('ota_event_id')): event for event in data.get('events', [])}
        cards = {str(card.get('transaction_id')): card for card in data.get('transactions', [])}
        blocked = set()
        for result in data.get('results', []):
            event = events.get(str(result.get('ota_event_id')))
            if not event or not (event.get('service_period_conflict') or event.get('period_conflict')
                                 or result.get('service_period_conflict') or result.get('period_conflict')):
                continue
            identities = [result.get('transaction_id'), *(result.get('reserved_card_ids') or [])]
            blocked.update(str(cards[str(identity)].get('source_hash')) for identity in identities
                           if identity and str(identity) in cards and cards[str(identity)].get('source_hash'))
        canonical = {
            'matches': [], 'type_only_candidates': [], 'rules': [],
            'ota_source_errors': [], 'ota_source_inventory': {'missing': []},
            'evidence_gate': {'blocked_inference_sources': sorted(blocked)},
        }
        report = dict(extend_report(canonical, data))
        report['_reconciliation_authority'] = 'canonical_snapshot'
        return report

    def _compute_ota_report(self):
        """분류와 화면이 같은 읽기 전용 대사를 쓰며 실제 입력 변경 시 다시 계산한다."""
        from app import ota_sources
        from app.ota_mail import load_reference_documents, match_mail
        from app.ota_portal import extend_report
        sources = self._ota_sources()
        mail_dirs = sources['mail_directories']
        portal_dbs = sources['portal_databases']
        if not sources['missing'] \
                and not any(Path(directory).is_dir() for directory in mail_dirs) \
                and not any(Path(database).is_file() for database in portal_dbs) \
                and not sources['reference_documents']:
            return None
        # 등록된 자료가 없으면 그 사실 자체를 진단으로 남긴다. 조용히 넘어가지 않는다.
        watched = [sources.get('manifest_path')]
        for directory in mail_dirs:
            watched += list(Path(directory).glob('gmail*.json'))+[Path(directory)/'collection.json']
        for database in portal_dbs:
            watched += [database, Path(str(database)+'-wal')]
        watched += list(sources['reference_documents'])
        # 크기와 시각이 같아도 내용이 다르면 다르다. 그래서 내용 해시를 쓴다.
        stamps = tuple(sorted(
            (stamp for stamp in (ota_sources.content_stamp(path) for path in
                                 {Path(item) for item in watched if Path(item).is_file()})),
            key=lambda stamp: stamp['path']))
        columns=('transaction_id','source_hash','merchant','merchant_normalized','card_kind','card_tail',
                 'transaction_direction','approval_date','amount_krw','foreign_currency','foreign_amount',
                 'duplicate_of','parse_error','conflict_reason','issuer','approval_number')
        from app import ota_exact
        with self.board._lock:
            report_columns = ','.join('t.' + column for column in columns)
            protected_sources = ','.join("'" + source.replace("'", "''") + "'"
                                         for source in ota_exact.PROTECTED_SOURCES)
            rows=[tuple(row) for row in self.board.conn.execute(
                'SELECT '+report_columns+',t.classification_source,'
                'CASE WHEN t.classification_source IN ('+protected_sources+') OR EXISTS('
                "SELECT 1 FROM board_rows b WHERE b.row_kind='expense' "
                "AND b.row_id='card-' || t.transaction_id) THEN 0 ELSE 1 END AS _ota_open "
                'FROM transactions t ORDER BY t.transaction_id').fetchall()]
            open_ids=sorted(str(row[0]) for row in rows if row[len(columns)+1])
            rows=[row[:len(columns)] for row in rows]
            inference_excluded_ids = ({row[0] for row in self.board.conn.execute('SELECT transaction_id FROM transaction_review_holds')}
                if self.board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else set())
        fingerprint=hashlib.sha256(json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        # 장부 기록 여부가 게이트 결과를 바꾸므로 열린 거래 집합도 지문에 넣는다.
        gate_enabled = ota_exact.enabled()
        open_digest=(hashlib.sha256(json.dumps([open_ids, sorted(inference_excluded_ids)],separators=(',',':')).encode()).hexdigest()
                     if gate_enabled else None)
        # manifest 자체와 추가 소스의 추가·삭제·변경이 모두 지문에 들어간다.
        key = (str([str(path) for path in mail_dirs]),
               str([str(path) for path in portal_dbs]),
               str([str(path) for path in sources['reference_documents']]),
               sources['manifest_stamp'], stamps, fingerprint, gate_enabled, open_digest)
        cache=getattr(self.board,'_card_review_mail_cache',None)
        if cache and cache.get('key')==key:
            return cache['report']
        # 같은 지문의 계산은 한 번만 한다. 계산 중에는 DB 잠금을 잡지 않는다.
        with _OTA_REPORT_LOCK:
            cache=getattr(self.board,'_card_review_mail_cache',None)
            if cache and cache.get('key')==key:
                return cache['report']
            transactions=[dict(zip(columns,row)) for row in rows]
            report=extend_report(match_mail(mail_dirs,transactions,source_key=repr(stamps)),portal_dbs,transactions)
            import sqlite3
            from app import ota_payments
            try:
                events=ota_payments.build_ota_payment_events(sources)
            except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
                events=None
            report=ota_exact.apply_gate(report,transactions,events=events,rules=self._review_rules(),
                                        open_ids=set(open_ids), inference_excluded_ids=inference_excluded_ids)
            references = load_reference_documents(sources['reference_documents'])
            report['reference_sources']=references
            report['ota_source_inventory']={
                'manifest_path':sources['manifest_path'],
                'manifest_present':sources['manifest_present'],
                'mail_directories':[str(path) for path in mail_dirs],
                'portal_databases':[str(path) for path in portal_dbs],
                'reference_documents':[str(path) for path in sources['reference_documents']],
                'registered':{key:[str(path) for path in value]
                              for key,value in sources['registered'].items()},
                'missing':sources['missing'],
                'diagnostics':sources['diagnostics'],
            }
            # 명시 등록한 자료의 읽기 실패만 오류다. 기본 위치는 있으면 쓰는 자리다.
            registered={str(Path(item).resolve())
                        for values in sources['registered'].values() for item in values}
            report['ota_source_errors']=(
                [entry for entry in report.get('mail_source_errors',[])
                 if str(Path(entry['path']).resolve()) in registered]
                + [entry for entry in report.get('portal_sources',{}).get('errors',[])
                   if str(Path(entry['path']).resolve()) in registered]
                + list(references.get('errors',[])))
            self.board._card_review_mail_cache={'key':key,'report':report}
            return report

    def review_mail_evidence(self, rows):
        """같은 대사 결과에서 화면에 필요한 근거만 꺼내며 DB에는 쓰지 않는다."""
        from app import ota_sources
        import sqlite3
        sources={row['source_hash'] for row in rows if _is_ota_row(row) and row.get('source_hash')}
        if not sources:
            return {}
        from . import ota_payment_review
        if ota_payment_review.enabled():
            # The OTA panel already reads the worker's reconciled snapshot.
            # Re-parsing all messages here holds the server's shared DB request
            # lock and can block every page (including health probes).
            # This is a display hint only; preview/commit keep the snapshot guards.
            return {source: {'source_diagnostic': 'snapshot_managed'} for source in sources}
        try:
            report=self._ota_report()
        except ota_sources.OtaSourcesError:
            # 목록 파일이 없거나 형식이 틀리면 자료가 없는 것이 아니라 읽지 못한 것이다.
            return {source:{'mail_link_absent':True,'source_diagnostic':'source_read_failed'}
                    for source in sources}
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            return {source:{'mail_link_absent':True,'source_diagnostic':'source_read_failed'}
                    for source in sources}
        if report is None:
            return {}
        return _mail_evidence_from_report(report, sources)

    def record_decision(self, batch_id, transaction_id):
        """사용자가 정한 거래 한 건만 장부에 기록한다. 같은 배치의 다른 거래는 기록 제외로 두어 소급 반영하지 않는다."""
        from app.ledger import recordable_rows
        options = dict(trip_validator=self.trip_valid, tab_validator=self.tab_valid,
                       review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'), entry_metadata=self.preview_metadata())
        from app.db import StoreError
        with self.board._lock:
            holds = dict(self.automatic_holds(batch_id))
            probe = self.pipeline.preview(batch_id, **options, additional_holds=holds)
            for row in probe['rows']:
                if row['transaction_id'] != transaction_id:
                    holds.setdefault(row['transaction_id'], {'kind': 'batch_scope', 'reason': '이번에 정한 거래만 기록합니다'})
            preview = self.pipeline.preview(batch_id, **options, additional_holds=holds)
            if not any(row['transaction_id'] == transaction_id for row in recordable_rows(preview['rows'])):
                if any(row['transaction_id'] == transaction_id and row.get('already_booked') for row in preview['rows']):
                    return 0
                reason =(holds.get(transaction_id) or {}).get('reason') or '지금은 장부에 기록할 수 없습니다'
                raise StoreError('NOT_RECORDED', reason)
            result = self.pipeline.commit(batch_id, preview['digest'],
                'decision-record:' + transaction_id + ':' + preview['digest'],
                projection=lambda entry: self.project(entry), additional_holds=holds, **options)
            return result['applied']

    def _trip_move_origin_revision(self, transaction_id, request_id, originating_revision=None):
        row = self.board.conn.execute(
            "SELECT response_json FROM requests WHERE request_id=? AND scope='save_decision'",
            (str(request_id),)).fetchone()
        if row is None:
            return None
        try:
            saved = json.loads(row[0])
            revision = int(saved['revision'])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return None
        try:
            supplied_revision = (None if originating_revision is None
                                 else int(originating_revision))
        except (TypeError, ValueError):
            return None
        if (saved.get('transaction_id') != str(transaction_id)
                or (supplied_revision is not None and supplied_revision != revision)):
            return None
        return revision

    def _trip_move_is_current(self, transaction_id, to_trip_id, request_id, originating_revision=None):
        revision = self._trip_move_origin_revision(
            transaction_id, request_id, originating_revision)
        if revision is None:
            return False
        row = self.board.conn.execute(
            "SELECT revision, classification_source, display_tab_id, trip_id"
            " FROM transactions WHERE transaction_id=?", (str(transaction_id),)).fetchone()
        return bool(row and int(row[0]) == revision and row[1] == 'user_decision'
                    and str(row[2] or '') == str(to_trip_id or '')
                    and str(row[3] or '') == str(to_trip_id or ''))

    def persist_card_trip_move(self, transaction_id, from_trip_id, to_trip_id, *, request_id,
                               originating_revision=None):
        """Save the owner's trip move to the COST row before any optional AI work."""
        source_trip, target_trip = str(from_trip_id or ''), str(to_trip_id or '')
        if not source_trip or not target_trip or source_trip == target_trip:
            return {"status": "not_needed"}
        with self.board._lock:
            row_id = 'card-' + str(transaction_id)
            row = self.board.get_row(row_id)
            if row is None:
                return {"status": "not_recorded"}
            if not self._trip_move_is_current(
                    transaction_id, target_trip, request_id, originating_revision):
                return {"status": "superseded"}
            case_request_id = 'card-trip-move-' + hashlib.sha256(
                f"{transaction_id}\0{request_id}".encode('utf-8')).hexdigest()[:32]
            case_id = 'case-' + case_request_id
            if row.get('display_tab_id') != target_trip:
                saved = self.board.save(row_id=row_id, expected_revision=int(row['revision']),
                                        client_request_id=case_request_id, change_mode='rule_change',
                                        changes={'display_tab_id': target_trip}, actor='owner')
                case_id = saved.get('learning_case_id') or case_id
            self.board.ensure_learning_case(case_id=case_id, row_id=row_id)
            return {"status": "saved", "case_id": case_id, "row_id": row_id,
                    "request_id": case_request_id}

    def open_trip_move_learning(self, transaction_id, from_trip_id, to_trip_id, *, request_id,
                                originating_revision=None):
        """Open the existing rule dialogue after the owner move has been persisted."""
        source_trip, target_trip = str(from_trip_id or ''), str(to_trip_id or '')
        with self.board._lock:
            persisted = self.persist_card_trip_move(
                transaction_id, source_trip, target_trip, request_id=request_id,
                originating_revision=originating_revision)
            if persisted['status'] != 'saved':
                return persisted
            case_id = persisted['case_id']
            case_request_id = persisted['request_id']
            row_id = persisted['row_id']
            current = self.board.get_row(row_id)
            draft = {
                'learning_case_id': case_id,
                'rule_kind': '', 'evidence_basis': '',
                'conditions': {},
                'scope': {'trip_id': target_trip},
                'effects': {'item': current.get('item') or '',
                            'display_tab_id': target_trip},
            }
            self.board.open_rule_dialog(learning_case_id=case_id, draft=draft,
                                        client_request_id=case_request_id + ':dialog')
            self.board.open_conversation(learning_case_id=case_id,
                                         client_request_id=case_request_id + ':conversation')
            self.board.ensure_trip_move_reason_question(case_id)
            return {"status": "opened", "case_id": case_id,
                    "conversation_id": 'conv-' + case_id,
                    "url": '/rules?case=' + case_id}

    def saved_state(self, batch_id, *, classify=False):
        """Only call after the write committed; refresh failure cannot undo that write."""
        with self._ota_request_scope():
            try:
                if classify:
                    self.classify(batch_id)
                    return self.auto_record(batch_id)
                return self.state(batch_id)
            except Exception:
                return {'saved': True, 'refresh_required': True}

    def automatic_holds(self, batch_id, *, include_verified_full_refunds=False, scope=None):
        """Holds for a batch. `scope` is `_refund_scope`'s result: judge only the rows a few selected rows depend on."""
        from app import quarter_costs
        holds = dict(self.ota_group_holds())
        rows = (self.pipeline.get_batch(batch_id)['rows'] if scope is None
                else self._batch_rows(batch_id, scope[0]))
        projection_index = self._projection_index()
        for row in rows:
            tid = row['transaction_id']
            if row.get('classification_state') != 'classified':
                holds.setdefault(tid, {'kind': 'classification_needed', 'reason': '비용 항목과 배정 내용을 확인해 주세요.'})
            elif not row.get('display_tab_id') or row['display_tab_id'] == 'unclassified':
                if not quarter_costs.destination(row) and not local_expense_without_trip(row):
                    holds.setdefault(tid, {'kind': 'trip_needed', 'reason': '예약 이용일과 숙소를 확인하고 여행을 선택해 주세요.'})
            # get_batch already read these raw fields for every row. Reuse the
            # same read instead of a SQL round trip for each transaction.
            source = tuple(row.get(field) for field in (
                'issuer', 'card_tail', 'approval_number', 'posting_date',
                'foreign_amount', 'foreign_currency', 'transaction_kind', 'approval_date'))
            if self._already_projected(source, dict(row, occurred_on=row.get('approval_date') or row.get('posting_date')),
                                       projection_index):
                holds[tid] = {'kind': 'existing_ledger', 'reason': '장부에 이미 기록되어 추가로 기록하지 않습니다.'}
        from app.partial_refund import refund_links, is_numbered_partial, partial_group_exclusion
        booked_now = {r[0] for r in self.board.conn.execute('SELECT transaction_id FROM ledger_entries')}
        refund_ids = [r[0] for r in self.board.conn.execute(
            "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
        verified_links = refund_links(self.board.conn, refund_ids)
        batch_ids = {r['transaction_id'] for r in rows} if scope is None else scope[1]
        for refund, link in verified_links.items():
            if not {refund, link['original_id']} & batch_ids:
                continue
            if link.get('inferred'):
                for member in (refund, link['original_id']):
                    holds.setdefault(member, {'kind': 'refund_inferred',
                        'reason': '원결제 자동 연결 · 별도 근거 검증 전 기록을 준비합니다 (환급 완료 아님)'})
                continue
            # A classified full offset belongs in refunds, so an automatic trip
            # request cannot block it. Persisted/manual/financial holds remain.
            if (link['status'] == 'full' and link['original_id'] not in booked_now
                    and holds.get(link['original_id'], {}).get('kind') == 'trip_needed'):
                holds.pop(link['original_id'])
            if link['original_id'] not in holds and holds.get(refund, {}).get('kind') in ('trip_needed', 'classification_needed'):
                holds.pop(refund)
            # 전액 상쇄 쌍은 환불이 여행이나 항목을 기다릴 필요가 없다. 원거래가 기록돼 있으면 환불도 환불 탭으로 간다.
            if (link['status'] == 'full' and refund not in booked_now
                    and holds.get(refund, {}).get('kind') in ('trip_needed', 'classification_needed')
                    and holds.get(link['original_id'], {}).get('kind') == 'existing_ledger'):
                holds.pop(refund)
            # 환불이 이미 기록돼 있으면 원거래는 그 배속을 이어받으므로 원거래의 여행 확인 보류를 풀어준다.
            if refund in booked_now and holds.get(link['original_id'], {}).get('kind') in ('trip_needed', 'classification_needed'):
                holds.pop(link['original_id'])
        from .refund_tab import groups
        from app.review_holds import active_holds
        active = active_holds(self.board.conn)
        ids = {r['transaction_id'] for r in rows} if scope is None else scope[1]
        booked = {r[0] for r in self.board.conn.execute('SELECT transaction_id FROM ledger_entries')}
        # 이미 기록된 쪽의 "기록됨" 표시는 보류가 아니다. 빠진 쪽에 실제 보류가 있을 때만 묶음을 함께 보류한다.
        blocking = {tid for tid, hold in holds.items() if hold.get('kind') != 'existing_ledger'}
        for group in (groups(self.board) if scope is None else scope[2]):
            members = {r['transaction_id'] for r in group}
            if not members & ids:
                continue
            if include_verified_full_refunds:
                # A verified, exactly zero-net group may span several source
                # files. The ledger preview pulls EVERY member and commits
                # them atomically. Never treat inferred or held groups as safe.
                refunds_in_group = members & set(refund_ids)
                trusted_full = bool(refunds_in_group) and all(
                    (rid in verified_links
                     and not verified_links[rid].get('inferred')
                     and verified_links[rid].get('status') == 'full'
                     and verified_links[rid].get('net_krw') == 0)
                    for rid in refunds_in_group)
                allowed_holds = {'trip_needed', 'classification_needed', 'existing_ledger'}
                # A numbered partial refund inherits its original's trip or quarter cost
                # through the ledger's pair rules; it never goes to the refund tab.
                trusted_partial = bool(refunds_in_group) and all(
                    rid in verified_links and is_numbered_partial(verified_links[rid])
                    for rid in refunds_in_group)
                # Only a group that spans files; PROC-072 completed periods and unclean cancels come first.
                if trusted_partial and not members <= ids:
                    trusted_partial = not partial_group_exclusion(
                        self.board.conn, verified_links[next(iter(refunds_in_group))]['original_id'])
                else:
                    trusted_partial = False
                if trusted_partial and not trusted_full:
                    if (not members & set(active)
                            and all(holds.get(tid, {}).get('kind') in (None, *allowed_holds)
                                    for tid in members)):
                        for tid in members & ids & set(refund_ids):
                            if holds.get(tid, {}).get('kind') in ('trip_needed', 'classification_needed'):
                                holds.pop(tid)
                        continue
                if (trusted_full and not members & set(active)
                        and all(holds.get(tid, {}).get('kind') in (None, *allowed_holds)
                                for tid in members)):
                    # Verified full offsets are always booked to the refund
                    # tab; trip/classification placeholders should not prevent
                    # the ledger's own source and authority checks.
                    for tid in members & ids:
                        if holds.get(tid, {}).get('kind') in ('trip_needed', 'classification_needed'):
                            holds.pop(tid)
                    continue
            if not members <= ids or members & (blocking | set(active)):
                for tid in members & ids:
                    holds.setdefault(tid, {'kind': 'refund_group_incomplete', 'reason': '원결제와 모든 환불을 함께 확인해야 합니다.'})
        from app.partial_refund import count_held_cancellations
        for tid in count_held_cancellations(self.board.conn):
            if tid in ids and tid not in holds:
                holds[tid] = {'kind': 'refund_count_group', 'reason': '같은 조건의 구매가 있지만 짝을 정하지 못한 취소라 개수를 명세와 맞춘 뒤 기록합니다.'}
        return holds

    @contextmanager
    def _automatic_write(self):
        """Keep inference, ledger entries and their projections atomic."""
        conn = self.board.conn
        nested = conn.in_transaction
        conn.execute('SAVEPOINT card_automatic_write' if nested else 'BEGIN IMMEDIATE')
        try:
            yield
            conn.execute('RELEASE SAVEPOINT card_automatic_write' if nested else 'COMMIT')
        except BaseException:
            if nested:
                conn.execute('ROLLBACK TO SAVEPOINT card_automatic_write')
                conn.execute('RELEASE SAVEPOINT card_automatic_write')
            else:
                conn.execute('ROLLBACK')
            raise

    def auto_record(self, batch_id):
        """소유자의 변경 요청에서만 실행한다. 조회는 쓰지 않는다."""
        from app import core_writer
        return core_writer.prepared(self.board, lambda: self._auto_record(batch_id))

    def _pending_reclassification(self, batch_id):
        from .card_classification_completion import missing_assignment_sql
        return {row[0] for row in self.board.conn.execute(
                "SELECT t.transaction_id FROM transactions t JOIN import_batch_rows b USING(transaction_id)"
                " WHERE b.batch_id=? AND (((t.classification_state NOT IN ('classified','booked')"
                " OR COALESCE(t.item,'')='')"
                " AND t.classification_source IN ('booking_evidence_needed','travel_location_hold',"
                " 'authority_review','rule_conflict','inference_conflict'))"
                " OR (" + missing_assignment_sql() +
                " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
                " AND NOT EXISTS(SELECT 1 FROM board_rows r WHERE r.row_id='card-'||t.transaction_id)"
                " AND NOT EXISTS(SELECT 1 FROM transactions f WHERE f.issuer=t.issuer"
                " AND f.card_tail=t.card_tail AND f.original_approval_number=t.approval_number"
                " AND COALESCE(f.original_approval_number,'')!=''"
                " AND (f.transaction_direction IN ('cancellation','refund') OR f.amount_krw<0))))"
                " AND t.transaction_direction='purchase' AND t.amount_krw>0"
                " AND COALESCE(t.classification_source,'') NOT IN ('owner_booking','manual','manual_hold')"
                " AND COALESCE(t.parse_error,'')='' AND COALESCE(t.conflict_reason,'')=''"
                " AND COALESCE(t.duplicate_of,'')=''"
                " AND NOT " + decided_sql('t') +
                " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
                " AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e"
                " WHERE e.transaction_id=t.transaction_id AND e.excluded=1)"
                " AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id)"
                " AND NOT EXISTS(SELECT 1 FROM board_manual_overrides o WHERE o.row_id='card-'||t.transaction_id)", (batch_id,))}

    def _auto_record(self, batch_id):
        from app import core_writer
        # The Rust writer commits in its own transaction and cannot run inside ours: classify first, outside it.
        # Python keeps inference, ledger entries and projections in one transaction (PR #846).
        rust = core_writer.selected() == 'rust'
        with self.board._lock:
            # Older imports and interrupted uploads may have finished only the
            # basic classifier. Re-run evidence + final inference before asking
            # the ledger to record them; a read must never repair these rows.
            pending = self._pending_reclassification(batch_id) if rust else None
            if pending:
                self._classify(batch_id, transaction_ids=pending)
            with self._automatic_write():
                if not rust:
                    pending = self._pending_reclassification(batch_id)
                    if pending:
                        self._classify(batch_id, transaction_ids=pending)
                return self._auto_record_locked(batch_id)

    def _auto_record_locked(self, batch_id, *, include_state=True, transaction_ids=None):
        from app import auto_record_policy, quarter_tab
        # The policy accepts every real imported batch, including historical ones.
        # The existence guard still blocks invalid batch IDs.
        if not auto_record_policy.batch_is_new(self.pipeline.store.conn, batch_id):
            if not include_state:
                return {'auto_recorded': 0}
            state = self.state(batch_id)
            state['auto_recorded'] = 0
            return state
        include_refund_groups = transaction_ids is None
        # A selected chunk is previewed and committed with only the rows it is judged with (itself and its
        # refund pairs/groups); the rest of the batch used to be read, held and previewed again for nothing.
        scope = None if transaction_ids is None else self._refund_scope(batch_id, transaction_ids)
        options = dict(trip_validator=self.trip_valid, tab_validator=self.tab_valid,
                       review_from=None, entry_metadata=self.preview_metadata(),
                       additional_holds=self.automatic_holds(batch_id, include_verified_full_refunds=include_refund_groups,
                                                             scope=scope),
                       include_verified_full_refunds=include_refund_groups)
        if transaction_ids is not None:
            selected = frozenset(transaction_ids)
            options['additional_holds'].update({tid: {'kind': 'completion_scope', 'reason': '다음 자동 처리 범위'}
                for tid in scope[0] if tid not in selected})
            options['transaction_ids'] = frozenset(scope[0])
        # PROC-072: completed periods and completed trips are never recorded automatically.
        from app.closed_period import excluded_ids
        from .card_classification_completion import completed_period_evidence
        closed = excluded_ids(self.board.conn, self.board.list_trips(),
                              evidence=completed_period_evidence(self.board, flow=self))
        for tid in closed:
            options['additional_holds'][tid] = {'kind': 'completed_period', 'reason': 'PROC-072 완료 기간·완료 여행'}
        in_batch = {row[0] for row in self.board.conn.execute(
            'SELECT transaction_id FROM import_batch_rows WHERE batch_id=?', (batch_id,))}
        booked_ids = {row[0] for row in self.board.conn.execute('SELECT transaction_id FROM ledger_entries')}
        skipped = len((in_batch & closed) - booked_ids)
        preview = self.pipeline.preview(batch_id, **options)
        from app.ledger import recordable_rows
        applied = 0
        if recordable_rows(preview['rows']):
            result = self.pipeline.commit(batch_id, preview['digest'],
                'auto-record:' + batch_id + ':' + preview['digest'],
                projection=lambda entry: self.project(dict(entry, automatic_record=True)), automatic_record=True, **options)
            applied = result['applied']
        allowed = (in_batch if transaction_ids is None else set(transaction_ids)) - closed
        if transaction_ids is None:
            applied += quarter_tab.book_batch(self.pipeline.store, batch_id, projection=self.project,
                                              transaction_ids=allowed)
        else:
            applied += quarter_tab.book_batch(self.pipeline.store, batch_id,
                projection=lambda entry: self.project(dict(entry, automatic_record=True)),
                transaction_ids=allowed)
        excluded = {'completed_period_excluded': skipped, 'exclusion_reason': 'PROC-072_COMPLETED_PERIOD'} if skipped else {}
        if not include_state:
            return {'auto_recorded': applied, **excluded}
        state = self.state(batch_id)
        state['auto_recorded'] = applied
        state.update(excluded)
        return state

    def state(self, batch_id):
        with self._ota_request_scope():
            return self._state(batch_id)

    @contextmanager
    def _ota_request_scope(self):
        """Reuse one published OTA generation across nested work for a card request."""
        outermost = self._ota_request_depth == 0
        if outermost:
            self._request_report = []
            self._request_ota_snapshot = False
            self._ota_group_holds_cache = None
        self._ota_request_depth += 1
        try:
            yield
        finally:
            self._ota_request_depth -= 1
            if outermost:
                self._request_report = None
                self._request_ota_snapshot = None
                self._ota_group_holds_cache = None

    def _held_ota_snapshot(self):
        """Share one published matcher generation across a single card request."""
        memo = getattr(self, "_request_ota_snapshot", None)
        if memo is False:
            from . import ota_payment_review
            memo = ota_payment_review.snapshot_service(self.board).held()
            self._request_ota_snapshot = memo
        elif memo is None:
            from . import ota_payment_review
            return ota_payment_review.snapshot_service(self.board).held()
        return memo

    def _state(self, batch_id):
        result = self.pipeline.get_batch(batch_id)
        approval_batch = result['summary'].get('status') == 'approval_evidence'
        review_from = os.environ.get('WEBLEDGER_REVIEW_FROM','')
        result['rows'] = [r for r in result['rows'] if (not review_from or not (r['approval_date'] or r['posting_date'])
                               or (r['approval_date'] or r['posting_date']) >= review_from)]
        result['summary']['row_count'] = len(result['rows'])
        from collections import Counter
        result['summary']['counts'] = dict(Counter(r['classification_state'] for r in result['rows']))
        dates = sorted(r['approval_date'] or r['posting_date'] for r in result['rows'] if r['approval_date'] or r['posting_date'])
        result['summary'].update(batch_display_info((r['issuer'] for r in result['rows']),
                                                     dates[0] if dates else '', dates[-1] if dates else ''))
        if approval_batch:
            from collections import Counter
            evidence_rows = self.board.conn.execute(
                "SELECT e.link_state,e.conflict_reason,e.approval_date"
                " FROM approval_batch_rows b JOIN approval_evidence e USING(approval_key)"
                " WHERE b.batch_id=? ORDER BY b.row_index", (batch_id,)).fetchall()
            states = Counter(row[0] for row in evidence_rows)
            period = [row[2] for row in evidence_rows if row[2]]
            result['summary'].update({
                'channel': 'approval',
                'display_name': '승인 증거 자료',
                'row_count': len(evidence_rows),
                'period_start': min(period) if period else '',
                'period_end': max(period) if period else '',
            })
            result['approval_summary'] = {
                'source_rows': len(evidence_rows),
                'distinct_evidence': len({row[0] for row in self.board.conn.execute(
                    "SELECT approval_key FROM approval_batch_rows WHERE batch_id=?", (batch_id,))}),
                'conflict_rows': sum(bool(row[1]) for row in evidence_rows),
                'states': dict(states),
            }
        # 한 조회의 미리보기와 선택지는 같은 검증 결과를 쓴다. 다음 조회와 기록 시에는 다시 검증한다.
        trips=self.board.list_trips()
        available={t['tab_id']:self.trip_valid(t['tab_id']) for t in trips}
        result['preview'] = self.pipeline.preview(batch_id, trip_validator=lambda target:available.get(target,False),
                                                  tab_validator=lambda target:target in ('','unclassified') or available.get(target,False),
                                                  review_from=review_from or None,
                                                  entry_metadata=self.preview_metadata(display_only=True),
                                                  additional_holds=self.ota_group_holds())
        ota_statuses, ota_generation, ota_reconciliation = self._ota_card_statuses(result['rows'])
        result['ota_reconciliation'] = ota_reconciliation
        ota_candidate_notes = self._ota_candidate_notes(result['rows'])
        for row in result['rows']:
            status = ota_statuses.get(row['transaction_id'], 'UNLINKED')
            row['ota_link_status'] = status if ota_generation else 'UNKNOWN'
            row['ota_snapshot_generation'] = ota_generation
            row['ota_candidate_notes'] = ota_candidate_notes.get(row['transaction_id'], [])
        for row in result['preview']['rows']:
            row['ota_link_status'] = ota_statuses.get(row['transaction_id'], 'UNLINKED') if ota_generation else 'UNKNOWN'
            row['ota_snapshot_generation'] = ota_generation
            row['ota_candidate_notes'] = ota_candidate_notes.get(row['transaction_id'], [])
            row['internal_expense_status'] = (
                'SAVED' if row.get('already_booked') else
                'READY_FOR_INTERNAL_SAVE' if not row.get('blocked') else 'HELD')
        result['trips'] = [dict(id=t['tab_id'],name=t['display_key'],available=available[t['tab_id']]) for t in trips]
        result['refund_groups'] = self.refund_group_views(result['preview'], result['trips'])
        from .card_actions import next_action
        originals = {r['transaction_id']: r for r in result['rows']}
        guards = self.automatic_holds(batch_id)
        for row in result['preview']['rows']:
            source = dict(originals[row['transaction_id']], batch_id=batch_id)
            row['next_action'] = next_action(source, row, guards.get(row['transaction_id']),
)
        from . import quarter_ledger
        result['quarter_targets'] = quarter_ledger.targets(result['rows'])
        # 원본 전체 셀은 요청했을 때만 제공한다. 검토 화면에는 필요한 필드만 있다.
        for row in result['rows']:
            row.pop('raw_row', None)
        from app.review_holds import active_holds
        holds=active_holds(self.board.conn)
        for row in result['rows']:
            if row['transaction_id'] in holds:
                row['review_hold']=holds[row['transaction_id']]
        mail_evidence = self.review_mail_evidence(result['rows'])
        for row in result['rows']:
            row['review_evidence_labels'] = _review_evidence_labels(
                row, mail_evidence.get(row.get('source_hash')))
        return result

    def _ota_card_statuses(self, rows):
        """Read OTA resolution labels from the published matcher generation; never run a matcher here."""
        from . import ota_payment_review
        from app.ota_core_projection import project_card_ota_statuses
        if not ota_payment_review.enabled():
            return {}, None, {'enabled': False, 'fresh': False, 'status': 'disabled',
                              'generation': None}
        current, fresh = self._held_ota_snapshot()
        if current is None or not fresh:
            reconciliation = {
                'enabled': True,
                'fresh': bool(current is not None and fresh),
                'status': ('ready' if current is not None and fresh else
                           'stale' if current is not None else 'loading'),
                'generation': current.get('generation') if current else None,
            }
            return {}, None, reconciliation
        return project_card_ota_statuses(current)

    def _ota_candidate_notes(self, rows):
        """Attach unresolved canonical OTA candidates as review-only screen notes."""
        import re
        from . import ota_payment_review
        from app.ota_core_projection import project_card_ota_candidate_notes
        if not ota_payment_review.enabled():
            return {}
        current, fresh = self._held_ota_snapshot()
        if current is None or not fresh:
            return {}
        wanted = {str(row.get('transaction_id')) for row in rows}
        return project_card_ota_candidate_notes(current, wanted, rows)

    def refund_group_views(self, preview, trips):
        """Each linked refund pair as its own group, with the digest its own commit button uses."""
        from app import ledger
        from app.db import StoreError
        names = {t['id']: t['name'] for t in trips}
        views = []
        for row in preview['rows']:
            link = row.get('refund_link')
            if not link or link['role'] != 'original':
                continue
            try:
                scoped = ledger.scope_group(self.pipeline.store, preview, row['transaction_id'])
            except StoreError as exc:
                views.append({'original_id': row['transaction_id'], 'error': exc.code, 'message': str(exc)})
                continue
            views.append({
                'original_id': row['transaction_id'], 'digest': scoped['digest'],
                'recordable': scoped['recordable'], 'reason': scoped['reason'],
                'gross_krw': link['gross_krw'], 'refund_krw': link['refund_krw'],
                'net_krw': link['net_krw'], 'status': link['status'],
                'item': row.get('item') or '', 'trip_name': names.get(row.get('display_tab_id') or '', ''),
                'rows': [{'transaction_id': r['transaction_id'], 'amount_krw': r['amount_krw'],
                          'merchant': r.get('merchant') or '', 'blocked': r.get('blocked') or '',
                          'already_booked': bool(r.get('already_booked'))} for r in scoped['rows']]})
        return views

    def ota_group_holds(self):
        """Project partial/contested OTA card reservations into ledger preview guards."""
        cached = getattr(self, "_ota_group_holds_cache", None)
        if cached is not None:
            return cached
        guide_holds = self._guide_write_holds()
        holds = self._ota_group_holds_base()
        for transaction_id, hold in guide_holds.items():
            holds.setdefault(transaction_id, hold)
        self._ota_group_holds_cache = holds
        return holds

    def _guide_write_holds(self):
        """대장 항공권 귀속 행은 현재 신선한 reservation authority와 최신 스냅샷이 받쳐 줄 때만 기록한다.

        화면 표시용 유예 캐시는 근거가 아니다. 네트워크를 호출하지 않고 워커가 관리하는 상태만 읽는다."""
        conn = getattr(self.board, "conn", None)
        if conn is None:
            return {}
        rows = conn.execute(
            "SELECT transaction_id, trip_id FROM transactions "
            "WHERE classification_source='guide_airfare_evidence' AND NOT " + decided_sql() + "").fetchall()
        if not rows:
            return {}
        from . import guide_airfare_review, ota_payment_review
        allowed, code = guide_airfare_review.write_authorization(self.board)
        supported = {}
        if allowed:
            current, fresh = (self._held_ota_snapshot()
                              if ota_payment_review.enabled() else (None, False))
            if current is None or not fresh:
                allowed, code = False, "GUIDE_SNAPSHOT_STALE"
            else:
                digest = guide_airfare_review.authority_summary(self.board)["digest"]
                for result in current.get("results") or []:
                    guide = result.get("guide_airfare") or {}
                    if (guide.get("status") == "ATTRIBUTED" and guide.get("authority_state") == "fresh"
                            and guide.get("authority_digest") == digest and result.get("transaction_id")):
                        supported[str(result["transaction_id"])] = str(guide.get("trip_id") or "")
        holds = {}
        for transaction_id, trip_id in rows:
            transaction_id = str(transaction_id)
            if not allowed:
                reason, hold_code = "대장 항공권 근거가 현재 확인된 reservation 자료로 뒷받침되지 않아 기록하지 않아요", code
            elif supported.get(transaction_id) != str(trip_id or ""):
                reason, hold_code = "대장 항공권 귀속이 최신 확인과 달라 기록하지 않아요", "GUIDE_ATTRIBUTION_CHANGED"
            else:
                continue
            holds[transaction_id] = {"kind": "guide_authority_hold", "code": hold_code, "reason": reason,
                                     "ota_event_ids": []}
        return holds

    def _ota_group_holds_base(self):
        from . import ota_payment_review
        if not ota_payment_review.enabled():
            return {}
        backend = ota_payment_review.CoreOtaPaymentBackend.from_host(self.board, read_only=True)
        try:
            # Read the reconciled snapshot only; a full reconciliation never runs on a preview.
            current, fresh = self._held_ota_snapshot()
            results = current["results"] if current is not None else []
            holds = {}
            for result in results:
                # A quantity-mismatched OTA group is unresolved reservation evidence,
                # not a financial hold on each independently imported card row.
                # The card pipeline still enforces duplicate, refund, source-conflict,
                # and already-booked guards before an expense can be prepared.
                if result.get("status") == "HOLD_PARTIAL_GROUP":
                    continue
                for transaction_id in result.get("reserved_card_ids") or ():
                    hold = holds.setdefault(str(transaction_id), {
                        "kind":"ota_group_review",
                        "reason":"OTA repeated payment group is partial or contested",
                        "ota_event_ids":[]})
                    hold["ota_event_ids"].append(str(result.get("ota_event_id") or ""))
            for pin in backend.store.group_pins():
                event_ids = [str(identity) for identity in pin.get("event_ids", ())]
                for transaction_id in pin.get("card_ids", ()):
                    hold = holds.setdefault(str(transaction_id), {
                        "kind":"ota_group_review",
                        "reason":"OTA frozen group remains reserved until explicit reallocation",
                        "ota_event_ids":[]})
                    hold["ota_event_ids"].extend(event_ids)
            # OTA links describe reservation evidence; they do not decide whether a
            # financially valid card purchase can be prepared as an expense. Keep
            # contested N:M reservations above, while ordinary unlinked cards use
            # the existing duplicate/refund/source/trip guards in the ledger path.
            for hold in holds.values():
                hold["ota_event_ids"] = sorted(set(hold["ota_event_ids"]))
            return holds
        finally:
            backend.close()


def dispatch(handler, parsed, query=None, raw=None, csrf=''):
    """기존 로그인·소유자 검사 이후에만 호출한다."""
    from . import ota_payment_review
    ota_route = ota_payment_review.owns_route(parsed.path)
    ota_enabled = enabled() and ota_payment_review.enabled()
    if ota_route:
        if not ota_enabled:
            return False
        if raw is not None and (not csrf or not handler.headers.get('X-CSRF-Token')
                                or handler.headers.get('X-CSRF-Token') != csrf):
            handler._send_json({'code':'CSRF_REQUIRED','message':'화면을 새로 연 뒤 다시 시도해 주세요'}, 403)
            return True
        from .ledger_board import _active_store
        board = _active_store()
        if board is None:
            handler._send_json({'code':'STORE_UNBOUND','message':'검토 저장소를 연결하지 못했습니다'}, 503)
            return True
        try:
            backend = ota_payment_review.backend_for_request(
                board, handler, read_only=(raw is None or parsed.path.endswith('/preview')))
        except Exception:
            handler._send_json({'code':'OTA_REVIEW_UNAVAILABLE','message':'격리 검토 연결을 사용할 수 없습니다'}, 503)
            return True
        try:
            return ota_payment_review.dispatch(handler, parsed, raw=raw, csrf=csrf, backend=backend)
        finally:
            closer = getattr(backend, 'close', None)
            if closer:
                closer()
    maintenance_paths = ('/maintenance/expense-bulk',
                         '/api/maintenance/expense-bulk/preview',
                         '/api/maintenance/expense-bulk/apply')
    refund_pair_route = parsed.path.startswith('/api/maintenance/refund-pair/')
    if not enabled() or not ((parsed.path == '/' and raw is None) or parsed.path in ('/cards', '/import', '/api/imports')
                            or parsed.path.startswith('/api/imports/') or parsed.path in maintenance_paths
                            or parsed.path == '/api/cards/coverage/summary' or refund_pair_route):
        return False
    from .ledger_board import _active_store
    from app import StoreError, ParseError
    from app import ota_sources
    board = _active_store()
    if board is None:
        handler._send_json({'code':'STORE_UNBOUND','message':'장부를 열 수 없습니다'}, 503)
        return True
    from . import card_upload_jobs
    if raw is None and parsed.path == '/import':
        legacy_detail = bool((query or {}).get('batch') and (query or {}).get('transaction'))
        if not legacy_detail:
            return _redirect_legacy_import(handler, parsed, query)
    if raw is None and card_upload_jobs.owns_route(parsed.path):
        from .ledger_board import current_role
        if current_role() != 'owner':
            handler._send_json({'code': 'FORBIDDEN'}, 403)
        else:
            saved_batch = ((query or {}).get('batch') or [None])[0]
            result, code = card_upload_jobs.status(board, parsed.path.rsplit('/', 1)[-1], saved_batch=saved_batch)
            handler._send_json(result, code)
        return True
    try:
        from . import expense_bulk_maintenance, refund_cleanup_action
        if expense_bulk_maintenance.dispatch(handler, parsed, board=board, raw=raw, csrf=csrf):
            return True
        if refund_cleanup_action.dispatch(handler, parsed, board=board, raw=raw, csrf=csrf):
            return True
        if parsed.path == '/cards':
            # 오래된 카드 링크는 정식 카드 내역으로 보낸다.
            if raw is not None:
                handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
            else:
                location = '/cards/all' + (('?' + parsed.query) if parsed.query else '')
                handler.send_response(302)
                handler.send_header('Location', location)
                handler.send_header('Cache-Control', 'no-store')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
            return True
        if parsed.path == '/api/imports/reclassify-pending':
            from .ledger_board import current_role
            if current_role() != 'owner':
                handler._send_json({'code': 'FORBIDDEN'}, 403)
            elif raw is None:
                handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
            elif not csrf or handler.headers.get('X-CSRF-Token') != csrf:
                handler._send_json({'code': 'CSRF_REQUIRED'}, 403)
            else:
                # Keep the legacy route closed until a read-only preview,
                # freshness check, and audited maintenance apply flow exist.
                handler._send_json({'code': 'MAINTENANCE_FLOW_REQUIRED',
                                    'message': '일괄 정리는 안전한 유지관리 미리보기 경로가 준비될 때까지 사용할 수 없습니다.'}, 410)
            return True
        from . import provisional_trip_review
        if provisional_trip_review.dispatch(handler, parsed, query=query or {}, raw=raw, csrf=csrf, board=board):
            return True
        from . import card_upload_coverage
        if card_upload_coverage.dispatch(handler, parsed, board, query=query, raw=raw, csrf=csrf):
            return True
        flow = CardFlow(board)
        parts = parsed.path.strip('/').split('/')
        if raw is None:
            if parsed.path == '/':
                handler._send(home_page(board))
            elif parsed.path == '/import':
                body = page(csrf)
                if ota_payment_review.enabled():
                    body = body.replace('</body>', ota_payment_review.render_import_section(csrf) + '</body>')
                handler._send(body)
            elif parsed.path == '/api/imports/rules':
                handler._send_json({'rules':flow.pipeline.list_rules()})
            elif len(parts) == 4 and parts[3] == 'google-tsv':
                from app import google_tsv_adapter
                tab = ((query or {}).get('tab') or [''])[0]
                try:
                    state = flow.state(parts[2])
                    if tab.startswith('quarter:'):
                        from . import quarter_ledger
                        handler._send_json(quarter_ledger.export(state, tab))
                    else:
                        # Quarterly rows need their verified destination, never generic unclassified paste.
                        from app import quarter_costs
                        ids = {r['transaction_id'] for r in state['rows'] if quarter_costs.destination(r)}
                        ordinary = [r for r in state['preview']['rows'] if r['transaction_id'] not in ids]
                        from .sheet_expense_reconciliation import export_for_trip
                        handler._send_json(export_for_trip(board, ordinary, tab))
                except ValueError as error:
                    handler._send_json({'code': str(error)}, 400)
            elif len(parts) == 3:
                handler._send_json(flow.state(parts[2]))
            else:
                handler._send_json({'batches':batch_catalog(board)})
            return True
        if handler.headers.get('X-CSRF-Token') != csrf:
            handler._send_json({'code':'CSRF_REQUIRED','message':'화면을 다시 열어 주세요'}, 403)
            return True
        if parsed.path in ('/api/imports', '/api/imports/upload-batch'):
            from .ledger_board import current_role
            if current_role() != 'owner':
                handler._send_json({'code':'FORBIDDEN','message':'소유자만 카드 파일을 등록할 수 있습니다.'}, 403)
                return True
            if parsed.path == '/api/imports/upload-batch':
                result = card_upload_jobs.receive_batch(board, handler, flow, raw)
                handler._send_json(result, 202)
                return True
            from app.card_preflight import validate_upload
            filename = unquote(handler.headers.get('X-Filename') or 'card.xlsx')
            source_file, inspection = validate_upload(raw, filename)
            received = flow.pipeline.receive(raw, filename)
            from .card_completion_worker import queue_batch, finish_jobs
            queue_batch(board, received['batch_id'])
            recovery = getattr(board, '_card_completion_worker', None)
            if recovery is not None and handler.headers.get('X-Upload-Async') != '1':
                recovery.wake()
            autonomous = getattr(board, '_autonomous_cleanup_worker', None)
            if autonomous is not None:
                autonomous.wake()
            from . import card_upload_jobs
            if handler.headers.get('X-Upload-Async') == '1':
                job = card_upload_jobs.start(board, handler, flow, received, source_file, inspection)
                handler._send_json(job, 202)
            else:
                result, code = card_upload_jobs.process(board, handler, flow, received, source_file, inspection)
                handler._send_json(result, code)
            return True
        payload = json.loads(raw.decode('utf-8'))
        if parsed.path == '/api/imports/rules':
            from app.db import canonical
            request_id = str(payload['request_id'])
            digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
            previous = flow.pipeline.store.replay_request(request_id,'save_rule',digest)
            if previous is None:
                board.conn.execute('BEGIN IMMEDIATE')
                try:
                    draft = payload['draft']
                    if draft.get('rule_id'):
                        current = board.conn.execute('SELECT version FROM cost_classification_rules WHERE rule_id=?',
                                                     (draft['rule_id'],)).fetchone()
                        if current is None or current[0] != payload['expected_revision']:
                            raise StoreError('REVISION_CONFLICT','규칙이 바뀌었습니다. 다시 불러와 주세요')
                    previous=flow.pipeline.save_rule(draft)
                    flow.pipeline.store.remember_request(request_id,'save_rule',digest,previous)
                    board.conn.commit()
                except Exception:
                    board.conn.rollback()
                    raise
            try:
                if payload.get('batch_id'):
                    flow.classify(payload['batch_id'])
                rules = flow.pipeline.list_rules()
            except Exception:
                handler._send_json({'result': previous, 'rules': None, 'refresh_required': True})
            else:
                handler._send_json({'result': previous, 'rules': rules})
            return True
        batch_id = parts[2]
        if len(parts) == 4 and parts[3] == 'auto-record':
            from .ledger_board import _receipts_owner_request
            if not _receipts_owner_request():
                handler._send_json({'code': 'OWNER_ONLY', 'message': '소유자만 자동 반영할 수 있습니다.'}, 403)
                return True
            handler._send_json(flow.auto_record(batch_id))
        elif len(parts) == 4 and parts[3] == 'decision':
            row = board.conn.execute('SELECT 1 FROM import_batch_rows WHERE transaction_id=? AND batch_id=?',
                                     (payload['transaction_id'], batch_id)).fetchone()
            if not row:
                raise StoreError('NOT_FOUND', '이 파일에 없는 거래입니다')
            previous = board.conn.execute('SELECT display_tab_id FROM transactions WHERE transaction_id=?',
                                          (payload['transaction_id'],)).fetchone()
            previous_trip = str(previous[0] or '') if previous else ''
            tab = str(payload.get('display_tab_id') or '')
            if not flow.tab_valid(tab):
                raise StoreError('TRIP_AUTHORITY_REQUIRED', '원본 일정이 확인된 여행을 선택해 주세요')
            from app.quarter_tab import parse_tab
            saved_decision = flow.pipeline.save_decision(payload['transaction_id'], payload['revision'],
                item=payload['item'], description=payload.get('description',''), display_tab_id=tab,
                trip_id=tab if tab not in ('','unclassified') and not parse_tab(tab) else '', trip_validator=flow.trip_valid,
                tab_validator=flow.tab_valid,
                note=payload.get('note',''), reuse_rule=bool(payload.get('reuse_rule')),
                request_id=payload['request_id'])
            try:
                applied = flow.record_decision(batch_id, payload['transaction_id'])
                recording = {'status': 'recorded', 'applied': applied}
            except StoreError as exc:
                if exc.code != 'NOT_RECORDED':
                    raise
                # Classification already committed. A ledger prerequisite is not
                # an unconfirmed classification and must not make its save fail.
                recording = {'status': 'held', 'code': exc.code, 'reason': str(exc)}
            response = flow.saved_state(batch_id, classify=recording['status'] != 'held')
            response.update(saved=True, classification_state='classified', ledger_recording=recording)
            if previous_trip and tab and previous_trip != tab:
                try:
                    response['trip_move_persisted'] = flow.persist_card_trip_move(
                        payload['transaction_id'], previous_trip, tab,
                        request_id=str(payload['request_id']),
                        originating_revision=saved_decision['revision'])
                except Exception:
                    # The card decision is already saved; do not let optional learning undo it.
                    response['trip_move_persisted'] = {'status': 'unavailable'}
                try:
                    response['trip_move_learning'] = flow.open_trip_move_learning(
                        payload['transaction_id'], previous_trip, tab,
                        request_id=str(payload['request_id']),
                        originating_revision=saved_decision['revision'])
                except Exception:
                    # The owner decision and row move already committed; learning is optional.
                    response['trip_move_learning'] = {'status': 'unavailable'}
            handler._send_json(response)
        elif len(parts) == 6 and parts[3] == 'refund-groups' and parts[5] == 'commit':
            result = flow.pipeline.commit(batch_id,payload['digest'],payload['request_id'],projection=flow.project,
                                           trip_validator=flow.trip_valid,tab_validator=flow.tab_valid,
                                           review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),
                                           entry_metadata=flow.preview_metadata(),
                                           additional_holds=flow.ota_group_holds(),
                                           group_original=parts[4])
            handler._send_json({'result':result, **flow.saved_state(batch_id)})
        elif len(parts) == 4 and parts[3] == 'commit':
            result = flow.pipeline.commit(batch_id,payload['digest'],payload['request_id'],projection=flow.project,
                                           trip_validator=flow.trip_valid,tab_validator=flow.tab_valid,
                                           review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),
                                           entry_metadata=flow.preview_metadata(),
                                           additional_holds=flow.ota_group_holds())
            handler._send_json({'result':result, **flow.saved_state(batch_id)})
        else:
            handler._send_json({'code':'NOT_FOUND'},404)
    except (StoreError, ParseError) as exc:
        handler._send_json({'code':exc.code,'message':str(exc)},409)
    except (ValueError,KeyError,TypeError):
        handler._send_json({'code':'INVALID_INPUT','message':'입력 내용을 확인해 주세요'},422)
    except OSError:
        handler._send_json({'code':'SOURCE_UNAVAILABLE','message':'원본 자료를 열 수 없습니다. 잠시 후 다시 불러와 주세요'},503)
    return True


CLEANUP_SCRIPT = """(()=>{const csrf=__CSRF__;
const tripOptions=document.getElementById('cleanup-trip-options');
if(tripOptions)document.querySelectorAll('#expense-cleanup select[name=display_tab_id]').forEach(select=>{
  select.replaceChildren(tripOptions.content.cloneNode(true));
  const current=select.closest('.cleanup-row')?.dataset.currentTab||'';
  if(current&&Array.from(select.options).some(option=>option.value===current))select.value=current;
});
document.querySelectorAll('.cleanup-form').forEach(form=>form.addEventListener('submit',async e=>{
  e.preventDefault();const item=form.closest('.cleanup-row'),select=form.querySelector('select[name=display_tab_id]'),error=form.querySelector('.cleanup-error'),button=form.querySelector('button');
  if(!select.value){error.textContent='여행을 골라 주세요';return}
  error.textContent='';button.disabled=true;
  const isCard=item.dataset.kind==='card';
  const request=isCard?fetch('/api/imports/'+encodeURIComponent(item.dataset.batch)+'/decision',{method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:JSON.stringify({transaction_id:item.dataset.transaction,revision:Number(item.dataset.revision),item:form.querySelector('input[name=item]').value.trim(),
        description:'',display_tab_id:select.value,note:'지출 정리',reuse_rule:false,request_id:crypto.randomUUID().replace(/-/g,'')})})
    :fetch('/api/rows/'+encodeURIComponent(item.dataset.rowId)+'/save',{method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:JSON.stringify({csrf:csrf,expected_revision:Number(item.dataset.revision),client_request_id:crypto.randomUUID().replace(/-/g,''),change_mode:'exception',display_tab_id:select.value})});
  try{const response=await request;const result=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(result.message||'저장하지 못했습니다.');
    location.reload();
  }catch(err){button.disabled=false;error.textContent=err.message}
}));
})();"""

CARD_REASON = {'booking_evidence_needed': '예약 상품과 이용일을 연결할 원문 근거가 필요합니다',
               'travel_location_hold': '국내·해외 구분과 여행 기간에 맞는 여행이 없습니다'}


_CLEANUP_PAGE_SIZE = 20


def _cleanup_card_where(board):
    from app.card_export_profiles import redundant_purchase_conflicts
    from . import read_scope
    from .card_cleanup_queries import completed_assignment_sql, completed_period_sql
    completed = completed_assignment_sql(board)
    redundant = read_scope.remember(('cleanup-redundant-sources', id(board)),
                                   lambda: redundant_purchase_conflicts(board.conn))
    redundant_sql = ','.join("'" + tid.replace("'", "''") + "'" for tid in redundant) or 'SELECT NULL WHERE 0'
    return (
        " FROM transactions t JOIN import_batch_rows r ON r.transaction_id=t.transaction_id"
        " WHERE t.classification_state IN ('needs_review','classified','booked') AND COALESCE(t.duplicate_of,'')=''"
        " AND " + completed_period_sql(board) +
        f" AND t.transaction_id NOT IN ({redundant_sql})"
        " AND NOT (t.classification_state='classified'"
        " AND COALESCE(t.item,'')!=''"
        " AND COALESCE(t.parse_error,'')='' AND COALESCE(t.conflict_reason,'')=''"
        " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
        " AND (COALESCE(t.classification_basis,'') LIKE '%complete-card-inference-v1%'"
        " OR t.classification_source='refund_original' OR " + completed + "))"
        " AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)"
        " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM board_rows b WHERE b.row_id='card-'||t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id"
        " AND d.revision=(SELECT MAX(d2.revision) FROM review_decisions d2 WHERE d2.transaction_id=t.transaction_id)"
        " AND COALESCE(d.display_tab_id,'')!='')"
    )


def _cleanup_card_items(board, *, limit=_CLEANUP_PAGE_SIZE, offset=0, reason='all', owner='all'):
    """장부에 아직 없는 카드 거래를 한 페이지씩 읽는다. 충돌 거래도 숨기지 않고 검토 대상으로 보여 준다."""
    from . import card_cleanup_queries
    return board.conn.execute(
        "SELECT t.transaction_id, MIN(r.batch_id), COALESCE(NULLIF(t.approval_date,''),t.posting_date), t.merchant,"
        " t.amount_krw, t.item, t.classification_source, t.display_tab_id, t.revision,"
        " EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id),"
        " t.conflict_reason, t.parse_error" + _cleanup_card_where(board) +
        card_cleanup_queries.card_reason_filter(reason) +
        card_cleanup_queries.card_owner_filter(owner) +
        " GROUP BY t.transaction_id ORDER BY 3 DESC,t.transaction_id LIMIT ? OFFSET ?",
        card_cleanup_queries.card_reason_params(reason) + card_cleanup_queries.card_owner_params(owner) + (limit, offset)).fetchall()


def _cleanup_card_count(board):
    return board.conn.execute("SELECT COUNT(DISTINCT t.transaction_id)" + _cleanup_card_where(board)).fetchone()[0]


def reclassify_cleanup(board, **options):
    """미정리 카드를 분류하고 보호 검사를 통과한 거래는 같은 동작에서 기록한다."""
    from app import core_writer
    if options.get('_preview'):  # a preview runs on a clone and writes nothing
        return _reclassify_cleanup(board, **options)
    return core_writer.prepared(board, lambda: _reclassify_cleanup(board, **options))


def _reclassify_cleanup(board, *, _preview=False, expected_fingerprint=None, flow=None,
                        request_snapshot=True):
    from app import StoreError
    from app.core_writer import PeriodsStale
    from app.classify import _pattern_for
    from app.normalize import normalize_merchant
    from collections import defaultdict
    import sqlite3

    flow = flow or CardFlow(board)
    result = {'processed': 0, 'recorded': 0, 'assigned_existing': 0, 'failures': []}
    result['authority_inferred'] = 0
    result['authority_conflicts'] = 0
    # 오래 걸리는 예약 원문 해석 중에도 워커가 입력을 확인할 수 있어야 한다.
    # 전체 정리 잠금 안에서 처음 해석하면 최신 연결의 유효 시간이 지나고,
    # 워커는 같은 잠금을 기다려 그 연결을 분류에 전달하지 못한다.
    with board._lock:
        merchants = board.conn.execute("SELECT DISTINCT t.merchant" + _cleanup_card_where(board)).fetchall()
    if not _preview and any(_is_ota_row({'merchant': merchant}) for (merchant,) in merchants):
        try:
            # Use the same central snapshot/freshness contract as card review.
            # This call is a warm-up only; the worker check below can publish a
            # newer canonical generation while a stale fallback is prepared.
            flow._ota_report()
        except (StoreError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            pass  # 해당 OTA 묶음에서 기존 오류 처리로 보고하고 현지 지출은 계속한다.
        from . import ota_payment_review
        if request_snapshot and ota_payment_review.enabled():
            ota_payment_review.snapshot_service(board).request_check(wait_seconds=3)
    with board._lock:
        if expected_fingerprint:
            from .expense_bulk_maintenance import PreviewError, fingerprint
            service = getattr(board, '_ota_snapshot_service', None)
            if service is not None:
                current_snapshot, snapshot_state = service.display_context()
                pinned_snapshot = (current_snapshot, bool(snapshot_state.get('fresh')))
                # A worker may publish a newer generation immediately after
                # preview verification. Use the generation verified here for
                # every classification decision in this operation.
                flow._held_ota_snapshot = lambda: pinned_snapshot
            if fingerprint(board) != expected_fingerprint:
                raise PreviewError('PREVIEW_STALE',
                                   '미리보기 뒤 자료가 바뀌었습니다. 다시 미리보기를 실행해 주세요.')
        batches = [row[0] for row in board.conn.execute(
            "SELECT DISTINCT r.batch_id" + _cleanup_card_where(board))]
        rows = board.conn.execute(
            "SELECT t.transaction_id, MIN(r.batch_id), t.merchant" + _cleanup_card_where(board) +
            " AND NOT " + decided_sql('t') +
            " AND t.transaction_direction='purchase'"
            " AND t.amount_krw>0"
            " AND COALESCE(t.display_tab_id,'') IN ('','unclassified')"
            " AND COALESCE(t.trip_id,'')=''"
            " AND COALESCE(t.conflict_reason,'')='' AND COALESCE(t.parse_error,'')=''"
            " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
            " GROUP BY t.transaction_id"
        ).fetchall()
        groups = defaultdict(list)
        for tid, batch, merchant in rows:
            pattern = _pattern_for(normalize_merchant(merchant or ''))
            kind = ('ota' if _is_ota_row({'merchant': merchant or ''}) else
                    'hotel' if pattern and pattern[0] == '숙박비' else 'local')
            groups[batch, kind].append(tid)
        # 예약 자료 장애가 있어도 식당 등 일반 가맹점의 분류는 끝낸다.
        for (batch, kind), ids in sorted(groups.items(), key=lambda group: (
                {'local': 0, 'hotel': 1, 'ota': 2}[group[0][1]], group[0][0])):
            try:
                flow._classify(batch, transaction_ids=ids)
            except PeriodsStale:
                raise  # let core_writer.prepared rebuild the evidence instead of recording a failure
            except (StoreError, OSError, ValueError, sqlite3.Error) as exc:
                result['failures'].append({'kind': kind, 'count': len(ids),
                                           'code': getattr(exc, 'code', 'CLASSIFICATION_UNAVAILABLE')})
            else:
                result['processed'] += len(ids)
        for batch in batches:
            try:
                result['recorded'] += flow._auto_record_locked(batch, include_state=False)['auto_recorded']
            except (StoreError, OSError, ValueError, sqlite3.Error) as exc:
                result['failures'].append({'kind': 'validation', 'count': 1,
                                           'code': getattr(exc, 'code', 'RECORDING_UNAVAILABLE')})
        result['assigned_existing'] = assign_existing_local_expenses(flow, failures=result['failures'])
        inferred, conflicts = _sync_booked_authority_inferences(flow)
        result['authority_inferred'] = inferred
        result['authority_conflicts'] = conflicts
        result['breakdown'] = _cleanup_card_breakdown(board)
    return result


def _sync_booked_authority_inferences(flow):
    """Finish legacy source states while preserving valid recorded/manual assignments."""
    from .card_classification_completion import complete_scope
    result = complete_scope(flow)
    return result['to_classify'], 0


def assign_existing_local_expenses(flow, *, failures=None):
    """기존 미배정 장부의 현지 사용만 원문과 검증된 일정으로 연결한다."""
    from app.classify import _verified_local_trip
    from .ledger_store import SaveError
    conn = flow.board.conn
    rows = conn.execute(
        "SELECT b.row_id,b.revision,b.payload_json,t.transaction_id,t.merchant,t.card_kind,"
        "t.approval_date,t.posting_date,t.issuer,t.raw_row_json,"
        "t.trip_id,t.classification_source,t.classification_basis"
        " FROM board_rows b JOIN transactions t ON t.transaction_id=json_extract(b.payload_json,'$.source_event_id')"
        " WHERE b.row_kind='expense' AND b.display_tab_id IS NULL"
        " AND t.transaction_direction='purchase' AND COALESCE(t.duplicate_of,'')=''"
        " AND COALESCE(t.conflict_reason,'')='' AND COALESCE(t.parse_error,'')=''"
        " AND NOT EXISTS(SELECT 1 FROM board_manual_overrides m WHERE m.row_id=b.row_id AND m.field='display_tab_id')"
        " AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)"
        " AND NOT EXISTS(SELECT 1 FROM transactions refund WHERE refund.card_tail=t.card_tail"
        " AND refund.transaction_direction='cancellation' AND refund.original_approval_number=t.approval_number"
        " AND COALESCE(t.approval_number,'')!='')"
    ).fetchall()
    local_items = {'식비','주유비','통행료','입장료','교통비','대중교통','택시비','주차비','현지경비','편의점'}
    assigned = 0
    for row_id, revision, payload, tid, merchant, kind, day, posted, issuer, raw, source_trip, source_kind, source_basis in rows:
        item = json.loads(payload).get('item')
        high_inference = (source_kind == 'inference'
                          and str(source_basis or '').startswith('추론 배정 · 높음')
                          and bool(source_trip))
        if high_inference:
            # Transfer only an already-classified, validated card assignment.
            # Never infer a trip from free-text basis or create an authority.
            trip = source_trip if flow.trip_valid(source_trip) else ''
            basis = '자동 배정: 카드 원본의 검증된 높은 신뢰도 여행 귀속을 기존 장부에 반영'
        elif item in local_items:
            transaction = dict(transaction_id=tid, merchant=merchant, card_kind=kind,
                               approval_date=day, posting_date=posted, issuer=issuer,
                               transaction_direction='purchase', raw_row=json.loads(raw))
            trip = _verified_local_trip(transaction, item, flow.retail_trip)
            basis = f'자동 추론: 원문 국가와 이용일 {day}이 검증된 여행 기간에 속함. 확신 정도: 중간.'
        else:
            continue
        if not trip:
            continue
        try:
            previous_note = json.loads(payload).get('operator_note') or ''
            flow.board.save(row_id=row_id, expected_revision=revision,
                            client_request_id=f'cleanup-trip-{row_id}-{revision}-{trip}',
                            change_mode='rule_change', changes={'display_tab_id': trip,
                                'operator_note': (previous_note + '\n' + basis).strip()}, actor='automatic')
        except SaveError as exc:
            if failures is None:
                raise
            failures.append({'kind': 'assignment', 'count': 1, 'code': exc.code})
            continue
        assigned += 1
    return assigned


def _cleanup_card_breakdown(board):
    """Return mutually exclusive counts from the canonical cleanup reason classifier."""
    from .card_cleanup_queries import card_reason_sql
    categories = card_reason_sql()
    rows = board.conn.execute(
        "SELECT status, COUNT(*) FROM (SELECT DISTINCT t.transaction_id, " + categories +
        " AS status" + _cleanup_card_where(board) + ") GROUP BY status"
    ).fetchall()
    return dict(rows)


def _cleanup_owner_breakdown(board):
    """Count user-required vs auto-resolvable rows from the same card population."""
    from .card_cleanup_queries import card_owner_action_sql
    owner_sql = card_owner_action_sql()
    rows = board.conn.execute(
        "SELECT owner, COUNT(*) FROM (SELECT DISTINCT t.transaction_id, " + owner_sql +
        " AS owner" + _cleanup_card_where(board) + ") GROUP BY owner"
    ).fetchall()
    return dict(rows)


def _cleanup_population(board):
    """Read the card and ledger populations once for counts and paging."""
    card = _cleanup_card_breakdown(board)
    owners = _cleanup_owner_breakdown(board)
    ledger = board.conn.execute("SELECT COUNT(*)" + _cleanup_unassigned_where()).fetchone()[0]
    counts = dict(card, classification=card.get('classification', 0) + ledger,
                  all=sum(card.values()) + ledger,
                  owner_user=owners.get('user', 0),
                  owner_auto=owners.get('auto', 0) + ledger)
    return card, ledger, counts


def _cleanup_counts(board):
    return _cleanup_population(board)[2]


def _cleanup_unassigned_where():
    return (
        " FROM board_rows b WHERE b.row_kind='expense' AND b.display_tab_id IS NULL"
        " AND NOT EXISTS(SELECT 1 FROM board_manual_overrides m"
        " WHERE m.row_id=b.row_id AND m.field='display_tab_id')"
        " AND NOT (COALESCE(json_extract(b.payload_json,'$.confirmed_by'),'') IN ('owner','automatic')"
        " AND COALESCE(json_extract(b.payload_json,'$.classification_state'),'') IN ('confirmed','classified'))"
    )


def local_expense_without_trip(row):
    """현지 지출의 정상 미배정은 완료 가능하다. 예약 이용기간이 필요한 결제는 제외한다."""
    from app.rules import is_booking_or_online
    local_items = {'식비','주유비','통행료','입장료','대중교통','택시비','주차비','현지경비','편의점'}
    return (row.get('classification_state') == 'classified'
            and row.get('transaction_direction') == 'purchase'
            and row.get('item') in local_items
            and '승차권' not in str(row.get('merchant') or '')
            and not is_booking_or_online(row))


def _evidence_block(index, amount, day):
    """예약 자료 확인이 필요한 거래 옆에 같은 금액의 예약 메일 내용을 그대로 보여 준다. 배정은 하지 않는다."""
    from app import booking_evidence
    from . import ledger_board
    found, searched = booking_evidence.find(index, amount, day)
    if not found:
        return card_evidence_ui.render_booking_email_evidence([], searched, amount, esc=ledger_board.esc)
    latest = {}
    for entry in found:
        key = tuple(entry['refs']) or (entry['subject'],)
        if key not in latest or entry['sent'] > latest[key]['sent']:
            latest[key] = entry
    entries = sorted(latest.values(), key=lambda e: e['sent'], reverse=True)
    described = [booking_evidence.describe(entry) for entry in entries]
    return card_evidence_ui.render_booking_email_evidence(described, searched, amount, esc=ledger_board.esc)


def prewarm_booking_evidence(board):
    """서버 시작 때 예약 메일 색인을 미리 만들어, 첫 지출 정리 화면이 수 초 기다리지 않게 한다."""
    from app import booking_evidence
    from . import ota_catalog, ota_payment_review
    if ota_payment_review.enabled():
        # Central review reads its published snapshot; legacy inference remains
        # available on demand without competing with HTTP threads at startup.
        return
    try:
        booking_evidence.build_index(ota_catalog.configured_sources(board)['mail_directories'])
    except Exception:
        pass  # 화면에서 다시 만들며 그때 경고를 보여 준다.


def cleanup_total(board) -> int:
    """정리할 지출 건수. 지출 정리 목록과 메인 화면이 같은 기준으로 센다."""
    unassigned = board.conn.execute("SELECT COUNT(*)" + _cleanup_unassigned_where()).fetchone()[0]
    return _cleanup_card_count(board) + unassigned


def _ota_entries_by_card(board, *, transaction_ids=None) -> dict:
    """카드 거래 ID -> 중앙 OTA 스냅샷에서 투영한 OTA 상태/근거/후보/스냅샷 신선도.

    기존 ota_catalog._index의 단일 card_matches만 소비하던 방식을 대체해,
    중앙 스냅샷(fresh/stale/error)의 results·candidate_search·reservation_link를
    순수 투영 헬퍼로 변환하여 후보/사유/복수 후보를 보존합니다.
    display_context()로 원자적 current+status 획득 후 투영.
    """
    from . import ota_payment_review
    from app.ota_core_projection import project_card_ota_statuses

    # OTA 검토 모드가 비활성화되면 빈 결과 반환 (기존 동작 유지)
    if not ota_payment_review.enabled():
        return {}

    try:
        current, status_dict = ota_payment_review.snapshot_service(board).display_context()
    except Exception:
        current, status_dict = None, {'status': 'error', 'fresh': False}
    is_fresh = status_dict.get('fresh', False)
    snapshot_status = status_dict.get('status', 'unknown')

    if current is None:
        # 스냅샷이 없는 경우: loading/error 상태를 모든 OTA 대상 카드에 전달
        return {'__snapshot_status__': {
            'status': snapshot_status,
            'fresh': False,
            'generation': None,
            'enabled': True,
            'current': None,
        }}

    # Stale evidence may explain what was seen before, but cannot establish a current link.
    statuses, generation, _ = project_card_ota_statuses(current) if is_fresh else ({}, None, {})
    wanted = None if transaction_ids is None else set(map(str, transaction_ids))
    entries = _index_ota_display_candidates(current, transaction_ids=wanted)
    if wanted is not None:
        statuses = {tid: status for tid, status in statuses.items() if tid in wanted}
    snapshot = {'generation': generation, 'fresh': bool(is_fresh),
                'status': snapshot_status, 'enabled': True}
    result = {tid: {'ota_status': statuses.get(tid, 'UNLINKED') if is_fresh else 'UNKNOWN',
                    'ota_notes': notes, 'snapshot': snapshot}
              for tid, notes in entries.items()}
    for tid, status in statuses.items():
        result.setdefault(tid, {'ota_status': status, 'ota_notes': [], 'snapshot': snapshot})
    for entry in result.values():
        if entry['ota_status'] != 'UNLINKED':
            continue
        candidates = {note.partition(' · ')[0] for note in entry['ota_notes'] if ' · 후보' in note}
        if candidates:
            entry['ota_status'] = 'MULTIPLE_CANDIDATES' if len(candidates) > 1 else 'CANDIDATE'
    result['__snapshot_status__'] = dict(snapshot, current=current)
    return result


def _index_ota_display_candidates(current: dict, *, transaction_ids=None) -> dict:
    """카드 ID별 OTA 후보와 거절 이유를 전부 모으는 화면 전용 역색인."""
    return card_ota_projection.index_ota_display_candidates(
        current,
        transaction_ids=transaction_ids,
        link_diagnosis_label_fn=_link_diagnosis_label,
    )


def ota_catalog_summary(entry) -> str:
    """기존 ota_catalog entry가 주어졌을 때 요약 문자열을 반환.
    새로운 _ota_entries_by_card가 반환하는 dict 형태도 처리.
    """
    if not isinstance(entry, dict):
        return ''
    # 새 형식: {'ota_status': ..., 'ota_notes': [...], 'snapshot': {...}}
    if 'ota_status' in entry:
        status = entry.get('ota_status', '')
        notes = entry.get('ota_notes', [])
        snap = entry.get('snapshot', {})
        fresh = snap.get('fresh', False)
        parts = []
        if status:
            label_map = {
                'EXACT': 'OTA 결제 확정 연결',
                'INFERRED': 'OTA 결제 자동 연결',
                'GROUP_RECONCILED': 'OTA 반복 결제 그룹 대응 (개별 연결 미확정)',
                'GROUP_LINKED': 'OTA M:N 연결',
                'USER_CONFIRMED': '사용자 확정 OTA 연결',
                'RESERVATION_INFERRED': '예약 자동 연결 · 결제 미검증',
                'RESERVATION_CONFIRMED': '사용자 확인 예약 관계 · 결제 미검증',
                'RESERVATION_NEEDS_REVIEW': '예약 후보 경합/충돌 · 자료를 확인해 주세요',
                'RESERVATION_STALE': '저장된 예약 관계 근거 변경 · 원본을 확인해 주세요',
                'REVIEW_REQUIRED': 'OTA 그룹 부분 대응 · 개별 연결 전 확인',
                'CANDIDATE': 'OTA 예약 후보 존재 · 연결 미확정',
                'MULTIPLE_CANDIDATES': 'OTA 복수 후보 · 개별 연결 미확정',
                'UNLINKED': 'OTA 연결 미확정', 'UNKNOWN': 'OTA 상태 확인 대기',
            }
            parts.append(label_map.get(status, 'OTA 상태 확인 대기'))
        if notes:
            parts.extend(notes)
        if not fresh:
            parts.append('(예약 근거 갱신 중)')
        return ' / '.join(parts) if parts else 'OTA 연결 정보 없음'
    # 기존 ota_catalog entry 형식 호환
    from . import ota_catalog
    return ota_catalog._summary(entry, bool(entry.get('rule')))


def _catalog_block(entry) -> str:
    """OTA 예약의 판단에 필요한 줄: 예약번호·상태, 이용기간, 후보 여행, 연결 카드 결제."""
    from . import ledger_board
    return card_evidence_ui.render_catalog_block(entry, esc=ledger_board.esc)


def _render_ota_snapshot_evidence(entry: dict, tid: str) -> str:
    """중앙 OTA 스냅샷 엔트리에서 근거 HTML을 생성.
    OTA exact/inferred/multiple/unlinked, snapshot refreshing/input error,
    여행 없음/무효, 원문충돌/중복/환불미완료/수동보류, 준비/기록완료/금융보호 상태 표시.
    """
    from . import ledger_board
    return card_evidence_ui.render_ota_snapshot_evidence(entry, tid, esc=ledger_board.esc)


_refund_merchant_key = card_evidence_ui.refund_merchant_key


def _refund_merchant_candidates_readonly(board, tid: str, *, max_rows=10):
    """Read-only Kakao taxi alias evidence; same card, bounded time, no auto-link."""
    return card_refund_query.refund_merchant_candidates_readonly(
        board.conn,
        tid,
        max_rows=max_rows,
        merchant_key_fn=_refund_merchant_key,
    )


def _kakao_merchant_inventory_readonly(board):
    """All currently stored Kakao-labeled rows, grouped without personal/card IDs.

    This is an owner-facing diagnostic inventory, NOT a matching or rule table.
    """
    return card_refund_query.kakao_merchant_inventory_readonly(
        board.conn,
        merchant_key_fn=_refund_merchant_key,
    )


def _render_refund_merchant_candidates(board, tid: str) -> str:
    """Show review candidates only. Nothing is saved or automatically linked."""
    from . import ledger_board
    refund, candidates, count = _refund_merchant_candidates_readonly(board, tid)
    if not refund:
        return ""
    key = _refund_merchant_key(refund[2])
    inventory = _kakao_merchant_inventory_readonly(board) if key == "카카오택시" else None
    existing = set()
    ids = [r[0] for r in candidates] if candidates else []
    if ids:
        marks = ",".join("?" for _ in ids)
        existing = {row[0] for row in board.conn.execute(
            "SELECT transaction_id FROM ledger_entries WHERE transaction_id IN (" + marks + ")",
            ids)}
    return card_evidence_ui.render_refund_merchant_candidates(
        refund,
        candidates,
        count,
        existing_ledger_ids=existing,
        kakao_inventory=inventory,
        esc=ledger_board.esc,
    )


def _refund_basis_label(value, *, inferred=False):
    labels = {
        'original_approval_number': '원승인번호 기준 연결',
        'merchant_card_foreign_amount': '외화 금액·동일 카드 기준 연결',
        'kakao_same_card_exact_amount': '동일 카드·카카오 가맹점·기간·동액 기준 연결',
        'same_card_merchant_day_exact_amount': '동일 카드·가맹점·이용일·동액 기준 연결',
    }
    label = labels.get(str(value or '').removesuffix('_inferred'))
    if not label:
        label = '저장된 연결 근거 정보 없음'
    if inferred or str(value or '').endswith('_inferred'):
        label += ' · 추론 상태'
    return label


def _build_refund_evidence_content(board, tid: str, link: dict, *, held_cancellations=None) -> tuple[str, list[str]]:
    """원결제 연결과 실제 기록 상태를 분석하여 화면 표시용 title과 lines를 반환한다."""
    if link:
        recorded = {r[0] for r in board.conn.execute(
            'SELECT transaction_id FROM ledger_entries WHERE transaction_id IN (?,?)',
            (tid, link['original_id']))}
        title = ('환불 기록 완료' if len(recorded) == 2 else
                 '원결제 연결 완료 · 환불 기록 처리 대기')
        if link.get('inferred'):
            title = '원결제 추론 연결 · 기록 전 확인 (환급 완료 아님)'
        basis_value = link.get('basis')
        if not basis_value and not link.get('inferred'):
            reference = board.conn.execute(
                'SELECT original_approval_number FROM transactions WHERE transaction_id=?', (tid,)
            ).fetchone()
            if reference and reference[0]:
                basis_value = 'original_approval_number'
        basis = _refund_basis_label(basis_value, inferred=bool(link.get('inferred')))
        lines = [{'full': '순액 0원', 'partial': '부분 환불',
                  'excess': '환불 합계가 원결제를 초과해 기록 전 확인이 필요합니다.'}.get(link['status'], '연결 상태를 확인해 주세요'),
                 f"{basis} · 취소/환불 {link['refund_count']}건",
                 f"원결제 {link['gross_krw']:,}원 · 환불 합계 {link['refunds_total_krw']:,}원 · 순액 {link['net_krw']:,}원"]
        if link['original_id'] in recorded and tid not in recorded:
            lines.append('원결제는 이미 기록됐으며 환불 기록은 보호 검사 후 처리합니다.')
    else:
        from app.partial_refund import count_held_cancellations, _foreign_amount
        row = board.conn.execute('SELECT issuer,card_tail,original_approval_number FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
        originals = []
        if row and row[2]:
            originals = board.conn.execute(
                "SELECT duplicate_of,conflict_reason,parse_error FROM transactions WHERE transaction_direction='purchase' AND issuer=? AND card_tail=? AND approval_number=? AND amount_krw>0", row).fetchall()
        elif row:
            foreign = board.conn.execute('SELECT merchant_normalized,foreign_currency,foreign_amount FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
            if foreign and foreign[1] and _foreign_amount(foreign[2]) is not None:
                originals = [candidate[:3] for candidate in board.conn.execute(
                    "SELECT duplicate_of,conflict_reason,parse_error,foreign_amount FROM transactions WHERE transaction_direction='purchase' AND issuer=? AND card_tail=? AND merchant_normalized=? AND foreign_currency=? AND amount_krw>0",
                    (row[0], row[1], foreign[0], foreign[1]))
                    if _foreign_amount(candidate[3]) == _foreign_amount(foreign[2])]
        if any(any(v for v in candidate) for candidate in originals):
            title, lines = '원결제 원본 충돌 · 확인해 주세요', ['원결제 후보의 중복·원본 오류를 먼저 확인해 주세요.']
        elif len(originals) > 1 or tid in (count_held_cancellations(board.conn)
                                         if held_cancellations is None else held_cancellations):
            title, lines = '원결제 후보를 하나로 정할 수 없습니다', ['승인 정보와 원결제·환불 건수를 함께 확인해 주세요.']
        elif originals:
            title, lines = '원결제 후보의 대응을 확인해 주세요', ['원결제 후보는 있지만 날짜·점유·환불 조건을 충족하는 연결은 확인되지 않았습니다.']
        else:
            title, lines = '원결제 자료 미확인', ['승인 참조 또는 동일 카드·가맹점·날짜·금액 등의 조건을 충족하는 원결제가 없습니다. 원승인번호는 필수조건이 아닙니다. 아래 가맹점 검색 결과를 비교해 주세요.']
        if row and not str(row[2] or '').strip():
            # A card authorization cancellation is not proof of money returned.
            # Diagnose from the entire same-card statement without writing or
            # promoting similar merchant names to verified financial links.
            refund_row = board.conn.execute(
                "SELECT issuer,card_tail,merchant FROM transactions WHERE transaction_id=?",
                (tid,)).fetchone()
            if refund_row:
                issuer, tail, refund_merchant = refund_row
                original_matches = board.conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE transaction_direction='purchase'"
                    " AND issuer=? AND card_tail=? AND approval_number IS NOT NULL"
                    " AND TRIM(approval_number)!='' AND amount_krw>0"
                    " AND duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"
                    " AND approval_number=(SELECT approval_number FROM transactions WHERE transaction_id=?)",
                    (issuer, tail, tid)).fetchone()[0]
                if original_matches:
                    lines.append('취소 승인번호와 같은 구매 승인번호는 있지만, 카드·가맹점·날짜·금액·유일성 조건을 충족하는 연결은 확인되지 않았습니다.')
                else:
                    lines.append('카드 원본에 원승인번호가 없어 다른 대조 조건을 확인했습니다. 조건을 충족하는 원결제가 없으며 취소 승인번호만으로 연결하지 않습니다.')
            if refund_row and '카카오' in str(refund_merchant or ''):
                lines.append('카카오T 가승인 해제는 실제 환급 완료와 다릅니다. 원본 결제 참조가 확보되면 자동 재대사됩니다.')
            else:
                lines.append('취소 원행과 실제 현금 환급 완료는 별도입니다. 원결제 근거를 확인해 주세요.')
    if not link:
        from app.partial_refund import kakao_refund_candidates
        candidate = kakao_refund_candidates(board.conn, {tid}).get(tid)
        if candidate:
            lines.append('동일 카드·카카오 가맹점·동액 기준 원결제 연결이 있습니다. 카드 연결과 실제 환급 완료는 별개입니다.')
    return title, lines


def _render_refund_evidence(board, tid: str, link: dict, *, held_cancellations=None) -> str:
    """원결제 연결과 실제 기록 상태를 금융 판정 변경 없이 표시한다."""
    from . import ledger_board
    title, lines = _build_refund_evidence_content(board, tid, link, held_cancellations=held_cancellations)
    comparison = _render_refund_merchant_candidates(board, tid) if not link else ''
    return card_evidence_ui.render_refund_evidence(
        title,
        lines,
        comparison_html=comparison,
        esc=ledger_board.esc,
    )


@read_scope.scoped
@refund_read_only_scope()
def render_expense_cleanup(board, csrf, *, page=1, reason='all', owner='all', diagnostics_open=False):
    """Render the shared action count and a collapsible transaction-status detail."""
    from . import ledger_board, ota_catalog
    if ledger_board.current_role() != 'owner':
        return ''
    esc = ledger_board.esc
    flow = CardFlow(board)
    from functools import cache
    # Read-only choices and previews share validation for this render only.
    # The next render and every write still validate their own current inputs.
    trip_valid = cache(flow.trip_valid)
    tab_valid = cache(flow.tab_valid)
    trips = sorted((t for t in board.list_trips()
                    if not t.get('deleted') and not t.get('archived') and trip_valid(t['tab_id'])),
                   key=lambda t: t.get('starts_on') or '', reverse=True)
    options = card_cleanup_ui.render_cleanup_trip_options(trips, esc=esc)
    trip_names = {t['tab_id']: t.get('display_key') or t['tab_id'] for t in trips}
    from . import card_cleanup_queries
    reason = card_cleanup_queries.LEGACY_REASONS.get(reason, reason)
    if reason not in card_cleanup_queries.REASONS:
        reason = 'all'
    selected_reason = reason
    selected_owner = 'all'
    card_breakdown, ledger_all, counts = _cleanup_population(board)
    all_total = counts['all']
    if selected_owner == 'all':
        filtered_card_total = sum(card_breakdown.values()) if selected_reason == 'all' else card_breakdown.get(selected_reason, 0)
        ledger_total = ledger_all if selected_reason in ('all', 'classification') else 0
    else:
        from .card_cleanup_queries import card_reason_filter, card_owner_filter, card_reason_params, card_owner_params
        filtered_card_total = board.conn.execute(
            "SELECT COUNT(DISTINCT t.transaction_id)" + _cleanup_card_where(board) +
            card_reason_filter(selected_reason) + card_owner_filter(selected_owner),
            card_reason_params(selected_reason) + card_owner_params(selected_owner)).fetchone()[0]
        ledger_total = ledger_all if (selected_owner == 'auto' and selected_reason in ('all', 'classification')) else 0
    total = filtered_card_total + ledger_total
    pages = max(1, (total + _CLEANUP_PAGE_SIZE - 1) // _CLEANUP_PAGE_SIZE)
    page = min(max(1, int(page or 1)), pages)
    offset = (page - 1) * _CLEANUP_PAGE_SIZE
    card_offset = min(offset, filtered_card_total)
    card_limit = max(0, min(_CLEANUP_PAGE_SIZE, filtered_card_total - card_offset)) if offset < filtered_card_total else 0
    rows_card = _cleanup_card_items(board, limit=card_limit, offset=card_offset, reason=selected_reason,
                                    owner=selected_owner) if card_limit else []
    ledger_offset = max(0, offset - filtered_card_total)
    ledger_limit = (_CLEANUP_PAGE_SIZE - len(rows_card)
                    if selected_reason in ('all', 'classification') and selected_owner != 'user' else 0)
    items = []
    ota_by_card = _ota_entries_by_card(board, transaction_ids=[row[0] for row in rows_card])
    snapshot_context = ota_by_card.get('__snapshot_status__', {})
    # Reuse the exact display snapshot for write guards and each read-only preview.
    # This prevents an extra held-snapshot read or a matcher run on the GET path.
    flow._request_ota_snapshot = (snapshot_context.get('current'), snapshot_context.get('fresh', False))
    preview_by_card = {}
    for batch_id in dict.fromkeys(row[1] for row in rows_card):
        try:
            holds = flow.automatic_holds(batch_id)
            preview = flow.pipeline.preview(batch_id, trip_validator=trip_valid,
                                            tab_validator=tab_valid,
                                            additional_holds=holds)
            preview_by_card.update({str(row['transaction_id']): row for row in preview.get('rows') or ()})
        except (OSError, ValueError, KeyError, TypeError):
            for card in rows_card:
                if card[1] == batch_id:
                    preview_by_card[str(card[0])] = {'blocked': 'preview_unavailable',
                        'reason': '금융 보호 검사 결과를 읽지 못했습니다. 카드 자료 전체 검토에서 다시 확인해 주세요.'}
    from app.partial_refund import refund_links, count_held_cancellations
    # A displayed original may have cancellations on another cleanup page.
    # Resolve globally once so its status does not contradict the refund card.
    all_refund_ids = [row[0] for row in board.conn.execute(
        "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
    cancellation_ids = set(all_refund_ids)
    visible_refunds = [row[0] for row in rows_card if row[0] in cancellation_ids]
    all_refund_links = refund_links(board.conn, all_refund_ids)
    refund_by_id = {tid: all_refund_links[tid] for tid in visible_refunds if tid in all_refund_links}
    original_refunds = {}
    for refund_id, link in all_refund_links.items():
        original_refunds.setdefault(link['original_id'], []).append((refund_id, link))
    held_refunds = (count_held_cancellations(board.conn)
                    if any(tid not in refund_by_id for tid in visible_refunds) else set())
    visible_card_ids = {row[0] for row in rows_card}

    inference_ids = [row[0] for row in rows_card
                     if row[7] in (None, '', 'unclassified') and row[6] == 'inference']
    basis_by_card = (dict(board.conn.execute(
        'SELECT transaction_id,classification_basis FROM transactions WHERE transaction_id IN (' +
        ','.join('?' for _ in inference_ids) + ')', inference_ids)) if inference_ids else {})
    from app.review_holds import active_holds
    from .card_actions import reason_category
    from app.classification_provenance import label as provenance_label
    cleanup_holds = active_holds(board.conn)

    for tid, batch, day, merchant, amount, item, source, current_tab, revision, held, conflict_reason, parse_error in rows_card:
        detail = '/import?batch=' + str(batch) + '&transaction=' + str(tid)
        entry = ota_by_card.get(tid)
        if entry is None and snapshot_context and _is_ota_row({'merchant': merchant}):
            entry = {'ota_status': 'UNLINKED' if snapshot_context.get('fresh') else 'UNKNOWN',
                     'ota_notes': [], 'snapshot': snapshot_context}

        # OTA 상태/근거/스냅샷 정보 추출
        if entry is not None and isinstance(entry, dict) and 'ota_status' in entry:
            # 새 중앙 스냅샷 기반 형식
            reason = ota_catalog_summary(entry)
            evidence = _render_ota_snapshot_evidence(entry, tid)
        elif entry is not None:
            # 기존 ota_catalog entry 형식 호환
            reason = ota_catalog_summary(entry)
            evidence = _catalog_block(entry)
        else:
            reason = CARD_REASON.get(source) or ('비용 항목을 확인해 주세요' if not item else
                      '여행 배정이 필요합니다' if current_tab in (None, '', 'unclassified') else
                      '여행·항목이 지정되어 있습니다. COST 내부 비용 기록은 아직 없습니다.')
            evidence = card_evidence_ui.render_no_booking_evidence(
                fresh=bool(snapshot_context.get('fresh')),
                source=source,
                is_ota=_is_ota_row({'merchant': merchant}),
            )
        # Classification confidence describes a proposal, not a persisted trip.
        # Do not present an old high-confidence basis as an active assignment.
        if tid in basis_by_card:
            basis_text = str(basis_by_card.get(tid) or '')
            if '추론 배정 · 높음' in basis_text:
                reason = ('과거 추론 근거는 높음이지만 현재 여행 배정값이 비어 있습니다.'
                          ' 유효한 여행을 자동 재검증할 때까지 배정 완료로 표시하지 않습니다.')
                evidence += ("<p class='cleanup-finance-status'>"
                             "추론 근거와 저장된 여행 배정이 불일치합니다. "
                             "재분류 시 유효한 여행 ID가 검증되면 자동 배정합니다."
                             "</p>")
        finance_label = ''
        preview_row = preview_by_card.get(str(tid))
        if preview_row:
            blocked = preview_row.get('blocked')
            blocked_labels = {
                'trip_no_longer_valid': '기록 전 확인: 이 거래에 저장된 여행 배정 ID가 현재 활성 여행 목록에서 유효하지 않습니다. 여행 삭제·보관·동기화 변경 여부를 확인해야 합니다.',
                'refund_pair_incomplete': '원결제·환불 그룹 근거가 완성되지 않아 COST 내부 기록 전 확인이 필요합니다.',
                'refund_inferred': '기록 전 확인: 원결제 자동 연결은 별도 근거 검증이 필요합니다. 환급 완료를 의미하지 않습니다.',
                'source_conflict': '기록 전 확인: 카드 원본 간 충돌을 확인해야 합니다.',
                'duplicate_possible': '기록 전 확인: 중복 가능성이 있습니다.',
                'review_hold': '기록 보류 · ' + str(preview_row.get('reason') or '검토 사유를 확인해 주세요.'),
                'item_missing': '기록 준비 전: 비용 항목 확인이 필요합니다.',
                'trip_needed': '기록 준비 전: 유효한 여행 배정이 필요합니다.',
                'preview_unavailable': '금융 보호 검사 결과를 읽지 못했습니다. 다시 확인해 주세요.',
                'trip_no_longer_valid': '기록 전 확인: 배정된 여행이 현재 유효하지 않습니다.',
            }
            finance_label = ('COST 내부 기록 있음' if preview_row.get('already_booked') else
                             blocked_labels.get(blocked, '' if not blocked else
                                                '기록 전 금융 검토가 필요합니다.'))
            if (blocked == 'review_hold' and not held
                    and preview_row.get('reason') == '비용 항목과 배정 내용을 확인해 주세요.'):
                finance_label = '여행·항목을 확인하고 변경 저장을 눌러 주세요.'
            if (tid in cancellation_ids
                    and finance_label == '여행·항목을 확인하고 변경 저장을 눌러 주세요.'):
                # A linked refund row is read-only here; do not carry the
                # purchase-side edit prompt into its financial status text.
                finance_label = '금융 관계 원행은 이 목록에서 여행·항목을 변경하지 않습니다.'
            if blocked:
                reason = finance_label
        elif source == 'booking_evidence_needed' or _is_ota_row({'merchant': merchant}):
            snapshot_message = {
                'refreshing': '예약 자료를 갱신하고 있습니다.',
                'loading': '예약 자료를 불러오고 있습니다.',
                'error': '예약 자료를 불러오지 못했습니다.',
            }.get(snapshot_context.get('status'), '예약 자료의 현재 상태를 확인할 수 없습니다.')
            evidence += "<p class='cleanup-snapshot-state'>" + esc(snapshot_message) + "</p>"
        if snapshot_context and not snapshot_context.get('fresh'):
            if entry and isinstance(entry, dict) and entry.get('ota_status') in ('EXACT', 'INFERRED', 'USER_CONFIRMED'):
                reason = '현재 OTA 연결 상태를 확인할 수 있습니다.'
        # Reflect already-proven purchase/refund pairing on the original row,
        # regardless of OTA snapshot freshness or the cancellation's page.
        if tid not in cancellation_ids and tid in original_refunds:
            pairs = original_refunds[tid]
            example = pairs[0][1]
            if example.get('inferred'):
                reason = ('원결제와 취소의 동일 카드·동액 기준 추론 연결. '
                          '별도 근거 검증 전 기록을 준비합니다 · 환급 완료 아님.')
            elif example.get('status') == 'full':
                reason = f"원결제와 취소·환불 {example['refund_count']}건의 금액을 함께 확인할 수 있습니다."
            elif example.get('status') == 'partial':
                reason = (f"원결제에 취소·환불 {example['refund_count']}건 연결 · "
                          f"순액 {example['net_krw']:,}원.")
            elif example.get('status') == 'excess':
                reason = '원결제보다 환불 합계가 커서 금액 충돌 상태입니다.'
        # 취소/환불 거래: refund pair 상태별 상세 구분
        if tid in cancellation_ids:
            link = refund_by_id.get(tid)
            if link is None:
                reason = '취소 원행에 연결된 원결제 근거가 없어 금융 연결 상태를 확인할 수 없습니다.'
            else:
                status = link.get('status')
                if link.get('inferred'):
                    reason = '원결제 추론 연결. 별도 근거 검증 전 기록을 준비합니다 · 환급 완료 아님.'
                elif status == 'full':
                    reason = '원결제와 전액 취소·환불 관계가 연결되어 있습니다. 내부 기록 상태는 별도 표시입니다.'
                elif status == 'partial':
                    reason = f'부분 환불 {link.get("refund_count", 0)}건 연결 · 현재 순액 {link.get("net_krw")}원. 실제 카드 환급 여부는 별도입니다.'
                elif status == 'excess':
                    reason = '환불 합계가 원결제를 넘어 금액 충돌이 있습니다. 쌍 전체 기록 전 확인이 필요합니다.'
                else:
                    reason = '원결제 연결과 비용 기록을 확인해야 합니다.'
            evidence = _render_refund_evidence(board, tid, link, held_cancellations=held_refunds)
            if finance_label:
                evidence += "<p class='cleanup-finance-status'>" + esc(finance_label) + "</p>"
            if preview_row and preview_row.get('blocked'):
                reason += ' ' + finance_label
        elif tid in original_refunds and original_refunds[tid]:
            # Keep the purchase-side refund relationship visible after removing
            # duplicate refund-group actions from this diagnostic list.
            linked_refunds = original_refunds[tid]
            link = linked_refunds[0][1]
            refund_count = int(link.get('refund_count') or len(linked_refunds))
            if link.get('inferred'):
                reason = (f'원결제 추론 연결 · 취소·환불 {refund_count}건. '
                          '별도 근거 검증 전 기록을 준비합니다 · 실제 카드 환급 완료 아님.')
            elif link.get('status') == 'full' and link.get('net_krw') == 0:
                basis_value = example.get('basis')
                if not basis_value:
                    parent_approval = board.conn.execute(
                        'SELECT approval_number FROM transactions WHERE transaction_id=?', (tid,)
                    ).fetchone()
                    refund_refs = [row[0] for row in board.conn.execute(
                        'SELECT original_approval_number FROM transactions WHERE transaction_id IN (' +
                        ','.join('?' for _ in linked_refunds) + ')',
                        [refund_id for refund_id, _ in linked_refunds])]
                    if parent_approval and parent_approval[0] and any(
                            str(ref or '').strip() == str(parent_approval[0]).strip() for ref in refund_refs):
                        basis_value = 'original_approval_number'
                basis = _refund_basis_label(basis_value) if basis_value else None
                relation = ('환불 상쇄 확인' if basis else '원결제·취소 연결 정보')
                reason = (f'{relation} · {basis or "저장된 연결 근거 정보 없음"} · 취소·환불 {refund_count}건. '
                          '실제 카드 환급 완료 여부와 COST 내부 기록은 별도입니다.')
            elif link.get('status') == 'partial':
                reason = (f'부분 환불 연결 {refund_count}건 · 현재 순액 {link.get("net_krw")}원. '
                          '실제 카드 환급 완료 여부와 COST 내부 기록은 별도입니다.')
            elif link.get('status') == 'excess':
                reason = (f'환불 합계가 원결제를 넘어 금액 충돌이 있습니다 · 연결 {refund_count}건. '
                          '쌍 전체 내부 기록 전 확인이 필요합니다.')
        # Keep financial, cancellation and evidence rows read-only in this detail.
        category = reason_category(dict(conflict_reason=conflict_reason, parse_error=parse_error,
            item=item, display_tab_id=current_tab,
            transaction_direction='cancellation' if tid in cancellation_ids else 'purchase',
            review_hold=cleanup_holds.get(tid)),
            dict(preview_row or {}, **({'refund_link': original_refunds[tid][0][1]} if tid in original_refunds else {})))
        finance_related = (category == 'finance' or tid in cancellation_ids or tid in original_refunds)
        review = card_cleanup_ui.render_cleanup_card_review(
            detail=detail, is_cancellation=tid in cancellation_ids,
            evidence=evidence, conflict_reason=conflict_reason,
            parse_error=parse_error, held=held, finance_related=finance_related,
            reason=reason, item=item, finance_label=finance_label, esc=esc)
        protected = bool(held or conflict_reason or parse_error)
        # The disclosure is a transaction diagnostic, not a second human task list.
        label = {'classification': '분류 상태', 'recording': '내부 기록 상태',
                 'evidence': '원본·보호 상태', 'finance': '금융 관계 상태'}.get(
                     category, '원본·보호 상태')
        if item:
            label += ' · ' + provenance_label({'classification_source': source})
        card_row = card_cleanup_ui.CleanupCardRow(
            assignment_text=(
                f"현재 여행: {trip_names[current_tab]} · 항목: {item or '기타비용'}"
                if current_tab in trip_names else ""
            ),
            tid=tid,
            batch=batch,
            revision=revision,
            held=held,
            merchant=merchant,
            current_tab=current_tab,
            protected=protected,
            label=label,
            day=day,
            amount=amount,
            reason=reason,
            review=review,
            refund_group_original=(
                (refund_by_id[tid]['original_id'] if tid in refund_by_id else tid)
                if ((tid in refund_by_id
                     and refund_by_id[tid]['original_id'] not in visible_card_ids
                     and not refund_by_id[tid].get('inferred')
                     and refund_by_id[tid].get('status') == 'full'
                     and refund_by_id[tid].get('net_krw') == 0)
                    or (tid in original_refunds and original_refunds[tid]
                        and all(not link.get('inferred') and link.get('status') == 'full'
                                and link.get('net_krw') == 0
                                for _, link in original_refunds[tid])))
                else ""
            ),
        )
        items.append(card_cleanup_ui.render_cleanup_card_row(card_row, esc=esc))
    ledger = board.conn.execute(
        "SELECT b.row_id, b.revision, b.payload_json" + _cleanup_unassigned_where() +
        " ORDER BY json_extract(b.payload_json,'$.occurred_on') DESC LIMIT ? OFFSET ?",
        (ledger_limit, ledger_offset)).fetchall() if ledger_limit else []
    for row_id, revision, payload in ledger:
        record = json.loads(payload)
        ledger_row = card_cleanup_ui.CleanupLedgerRow(
            row_id=row_id,
            revision=revision,
            merchant_or_desc=record.get('source_merchant') or record.get('description') or '지출',
            occurred_on=record.get('occurred_on'),
            item=record.get('item'),
            amount_krw=record.get('amount_krw') or 0,
        )
        items.append(card_cleanup_ui.render_cleanup_ledger_row(ledger_row, esc=esc))
    body = ''.join(items) or card_cleanup_ui.render_cleanup_empty()
    note = card_cleanup_ui.render_cleanup_snapshot_note(snapshot_context, esc=esc)
    nav = ''
    if pages > 1:
        owner_part = '' if selected_owner == 'all' else '&cleanup_owner=' + selected_owner
        query_prefix = '' if selected_reason == 'all' else '&cleanup_reason=' + selected_reason
        query_prefix += owner_part
        previous = (f"<a href='/import?cleanup_page={page - 1}{query_prefix}#expense-cleanup'>이전 20건</a>"
                    if page > 1 else '<span>이전 20건</span>')
        following = (f"<a href='/import?cleanup_page={page + 1}{query_prefix}#expense-cleanup'>다음 20건</a>"
                     if page < pages else '<span>다음 20건</span>')
        nav = (f"<nav class='cleanup-pages'><p class='muted'>{total}건 중 {min((page-1)*20+1,total)}~{min(page*20,total)}건 · {page}/{pages}페이지</p>"
               f"{previous} · {following}</nav>")
    diagnostic_labels = {
        'classification': '분류 상태', 'recording': '내부 기록 상태',
        'evidence': '원본·보호 상태', 'finance': '금융 관계 상태',
    }
    labels = [('all', '전체 거래·장부 행', counts['all'])] + [
        (key, diagnostic_labels[key], counts.get(key, 0))
        for key in ('classification', 'recording', 'evidence', 'finance')]
    chips = []
    for key, label, count in labels:
        if not count and key not in ('all', selected_reason):
            continue
        query_part = '?cleanup_reason=' + key
        current = " aria-current='page'" if key == selected_reason else ''
        chips.append(f"<a href='/import{query_part}#expense-cleanup'{current}>{label} "
                     f"<span class='cleanup-filter-count'>{count:,}건</span></a>")
    breakdown = (f"<p class='cleanup-filter-total'>{esc(dict((key, label) for key, label, _ in labels).get(selected_reason, '전체 거래·장부 행'))} "
                 f"{total:,}건 중 {min((page-1)*20+1,total) if total else 0}~{min(page*20,total)}건 표시</p>"
                 + "<nav class='cleanup-breakdown' aria-label='거래·장부 상태 필터'>" + ''.join(chips) + '</nav>')
    if pages == 1 and selected_reason == 'all' and selected_owner == 'all':
        breakdown = breakdown[breakdown.index("<nav"):]
    if total == 0:
        empty_labels = dict((key, label) for key, label, _ in labels)
        body = f"<li class='muted'>{esc(empty_labels.get(selected_reason, '거래·장부 행'))}에 해당하는 항목이 없습니다.</li>"
    script_html = CLEANUP_SCRIPT.replace('__CSRF__', json.dumps(csrf))
    return card_cleanup_ui.render_cleanup_section(
        total=all_total,
        action_summary_html='',
        diagnostics_open=(diagnostics_open or selected_reason != 'all' or page > 1),
        breakdown_html=breakdown,
        note_html=note,
        options_html=options,
        body_html=body,
        nav_html=nav,
        script_html=script_html,
        style_html=card_cleanup_ui.CLEANUP_STYLE +
        "<style>#expense-cleanup .cleanup-breakdown a{display:inline-flex;align-items:center;min-height:44px;padding:7px 12px;border:1px solid var(--shell-line);border-radius:var(--r-pill);background:var(--shell-hover);color:inherit;text-decoration:none}"
        "#expense-cleanup .cleanup-breakdown .cleanup-filter-count{white-space:nowrap}"
        "#expense-cleanup .cleanup-breakdown a[aria-current='page']{border:2px solid var(--shell-accent);font-weight:750}"
        "#expense-cleanup .cleanup-owner{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 8px}"
        "#expense-cleanup .cleanup-owner a{display:inline-flex;align-items:center;min-height:44px;padding:7px 14px;border:1px solid var(--shell-line);border-radius:var(--r-pill);background:var(--shell-hover);color:inherit;text-decoration:none}"
        "#expense-cleanup .cleanup-owner .cleanup-user-cta{border:2px solid var(--shell-accent);font-weight:750}"
        "#expense-cleanup .cleanup-owner a[aria-current='page']{outline:3px solid var(--shell-accent);outline-offset:2px}"
        "#expense-cleanup .cleanup-breakdown a:focus-visible,#expense-cleanup .cleanup-owner a:focus-visible{outline:3px solid var(--shell-accent);outline-offset:2px}"
        "#expense-cleanup .cleanup-filter-total{font-weight:700;margin:8px 0}"
        "#expense-cleanup .cleanup-auto-state{color:var(--shell-muted,var(--c-text-secondary));font-size:var(--t-body-sm);margin:4px 0 0}</style>",
    )


def page(csrf):
    from . import ui_icons
    markup = PAGE.replace('__CSRF__', json.dumps(csrf))
    document, separator, script = markup.partition('<script>')
    for token, name in (
            ('__ICON_UPLOAD__', 'upload'), ('__ICON_SAVE__', 'save'),
            ('__ICON_PENCIL__', 'pencil'), ('__ICON_SEARCH__', 'search'),
            ('__ICON_CHECK__', 'check'), ('__ICON_COPY__', 'copy'),
            ('__ICON_ROTATE__', 'rotate-ccw'),
            ('__ICON_CHEVRON_LEFT__', 'chevron-left'),
            ('__ICON_CHEVRON_RIGHT__', 'chevron-right'),
            ('__ICON_CIRCLE_MINUS__', 'circle-minus')):
        icon = ui_icons.icon(name)
        document = document.replace(token, icon)
        # Dynamic buttons live in single-quoted JavaScript strings. Keep SVG
        # attribute quotes from terminating those strings during parsing.
        script = script.replace(token, icon.replace("'", r"\u0027"))
    from .ledger_design import _merchant_icon, _category_icon
    script = script.replace('__REVIEW_ICONS__', json.dumps({
        'agoda': _merchant_icon({'source_merchant': 'AGODA.COM'}),
        'trip': _merchant_icon({'source_merchant': 'TRIP.COM'}),
        'merchant': ui_icons.icon('receipt'),
        **{item: _category_icon({'item': item}) for item in
           ('항공료', '숙박비', '교통비', '식비', '현지경비')},
    }, ensure_ascii=False))
    from .expense_workspace import decorate
    return decorate(document + separator + script, page_title='카드 거래 상세')


PAGE = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>카드 거래 상세</title><style>
#upload-results .upload-result-list{list-style:none;padding:0;margin:0;border:1px solid var(--shell-line);border-radius:var(--r-md);overflow:hidden}#upload-results .upload-result-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(140px,.7fr) auto;align-items:center;gap:8px 16px;padding:10px 14px;border-bottom:1px solid var(--shell-line);font-size:var(--t-body-sm);line-height:1.5}#upload-results .upload-result-row:last-child{border-bottom:0}#upload-results .upload-result-name{font-weight:600;overflow-wrap:anywhere;word-break:break-word}#upload-results .upload-result-state{color:var(--shell-muted)}#upload-results [data-state=auth] .upload-result-state{color:var(--shell-warn)}#upload-results .upload-result-link{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 12px;white-space:nowrap;border:1px solid var(--shell-line);border-radius:var(--r-sm);text-decoration:none;font-weight:600}#upload-results .upload-result-link:hover{background:var(--shell-hover)}#upload-results .upload-result-link:focus-visible{outline:2px solid var(--shell-accent);outline-offset:2px}#upload-results .upload-result-notice{margin:0 0 12px;color:var(--shell-muted)}#upload-results .upload-result-row>details{grid-column:1/-1}@media(max-width:600px){#upload-results .upload-result-row{grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;padding:12px}#upload-results .upload-result-name{grid-column:1}#upload-results .upload-result-state{grid-column:1;font-size:var(--t-meta)}#upload-results .upload-result-link{grid-column:2;grid-row:1/3}}
@font-face{font-family:"Pretendard Variable";src:url("/assets/fonts/PretendardVariable.woff2") format("woff2-variations"),url("/assets/fonts/PretendardVariable.woff2") format("woff2");font-weight:100 900;font-style:normal;font-display:swap}
*{box-sizing:border-box}body{margin:0;padding:16px;font:400 var(--t-body-sm)/1.5 "Pretendard Variable","Pretendard",system-ui,-apple-system,"Segoe UI",Roboto,"Malgun Gothic",sans-serif;background:var(--shell-bg);color:var(--shell-ink)}main{max-width:900px;margin:auto;min-width:0}
article,section{background:var(--shell-paper);border:1px solid var(--shell-line);border-radius:var(--r-sm);padding:16px;margin:12px 0;min-width:0}input,select,textarea{font:inherit;max-width:100%;min-width:0;padding:0 8px;border:1px solid var(--shell-line);border-radius:var(--r-sm);background:var(--shell-paper);color:var(--shell-ink)}input:not([type=checkbox]),select{height:34px}input:not([type=checkbox]),select,textarea{width:100%;margin:6px 0}textarea{height:auto;min-height:64px;padding:8px}button{font:inherit;max-width:100%;padding:0 12px;min-height:34px;border:1px solid var(--shell-line);border-radius:var(--r-sm);background:var(--shell-paper);color:var(--shell-ink);font-weight:600;cursor:pointer}button:disabled{opacity:.5}button .ic{width:16px;height:16px;vertical-align:-3px;pointer-events:none}button .ic:first-child{margin-right:6px}button .ic:last-child:not(:first-child){margin-left:6px}@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}form[data-index] button,#commit,#upload,#ruleform button:not([type=button]){background:var(--c-accent-solid);border-color:var(--c-accent-solid);color:var(--c-on-accent)}h1{font-size:var(--t-h1)}h2{font-size:var(--t-body)}.small{font-size:var(--t-meta);color:var(--shell-muted)}.amount{font-size:var(--t-body);font-weight:700}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.hidden{display:none}table{width:100%;table-layout:fixed;border-collapse:collapse}h1,h2,button,p,span,td,th,summary{overflow-wrap:anywhere;word-break:keep-all;min-width:0}td button{padding:0 8px;min-height:34px}td,th{padding:7px 10px;text-align:left;border-bottom:1px solid var(--shell-line);overflow-wrap:anywhere}a{color:var(--shell-accent)}.pv-label{display:none}
.review-item{background:var(--shell-paper);border:1px solid var(--shell-line);border-radius:var(--r-sm);margin:0 0 8px;min-width:0}.review-item summary{min-height:44px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 12px;font-size:var(--t-body-sm);font-weight:600;cursor:pointer}.review-item summary .ri-date{font-size:var(--t-meta);color:var(--shell-muted);font-weight:400;white-space:nowrap}.review-item summary h2{font-size:var(--t-body-sm);font-weight:600;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.review-item summary .amount{font-size:var(--t-body-sm);margin-left:auto;white-space:nowrap}.ri-flag{font-size:var(--t-caption);font-weight:600;color:var(--shell-warn);max-width:100%;white-space:normal}.ri-body{padding:4px 12px 12px;min-width:0}
#holds:empty{display:none}#batches{display:grid;gap:8px}#batches p{margin:0;min-width:0}.batch-choice{width:100%;min-height:48px;text-align:left;line-height:1.5;font-size:var(--t-body-sm)}.batch-choice span{font-size:var(--t-meta);color:var(--shell-muted)}summary{cursor:pointer;padding:10px 0;min-height:44px;display:flex;align-items:center}details{min-width:0}nav{font-size:var(--t-body-sm)}details>summary{list-style:none}details>summary::-webkit-details-marker{display:none}details>summary::after{content:'';display:inline-block;width:7px;height:7px;margin-inline-start:auto;border-inline-end:1.5px solid currentColor;border-block-end:1.5px solid currentColor;transform:rotate(45deg);transition:transform var(--motion-fast);flex:0 0 7px}details[open]>summary::after{transform:rotate(225deg)}@media(prefers-reduced-motion:reduce){details>summary::after{transition:none}}
.flow{margin:12px 0;font-size:var(--t-meta);color:var(--shell-muted);border:1px solid var(--shell-line);border-radius:var(--r-sm);background:var(--shell-paper);padding:8px 12px}
@media(max-width:550px){.grid{grid-template-columns:1fr}body{padding:10px}main{min-width:0}article,section{padding:14px;margin:10px 0}h1{font-size:var(--t-h3)}input:not([type=checkbox]),select,textarea{font-size:var(--t-body);min-height:44px}input:not([type=checkbox]),select{height:44px}button{min-height:44px;font-size:var(--t-body-sm)}td button,form[data-index] button,[data-edit],#commit,#upload{width:100%;min-height:44px}.batch-choice{min-height:56px}#preview table,#preview tbody,#preview tr,#preview td{display:block;width:100%}#preview thead{display:none}#preview tr{border:1px solid var(--shell-line);border-radius:var(--r-sm);padding:10px 12px;margin:0 0 10px;min-width:0}#preview td{border-bottom:0;padding:5px 0;min-width:0}.pv-label{display:block;font-size:var(--t-caption);color:var(--shell-muted)}.review-item summary{min-height:48px;font-size:var(--t-body-sm)}.ri-flag{flex-basis:100%}}
.upload-table{overflow-x:auto}.upload-table table{min-width:650px}.upload-result{border:1px solid var(--shell-line);border-radius:var(--r-sm);padding:12px;margin:8px 0}.upload-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.upload-metrics div{border:1px solid var(--shell-line);padding:8px}.upload-metrics b{color:var(--shell-muted);margin-right:6px}.upload-metrics strong{font-size:var(--t-h3)}.financial-warning{border:2px solid var(--shell-warn);padding:10px;margin-top:10px}@media(max-width:550px){.upload-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
#newupload #upload{min-height:44px}#newupload section{display:grid;gap:12px}.upload-lede{margin:0;max-width:68ch}.upload-drop{display:grid;gap:4px;min-height:112px;padding:18px;border:2px dashed var(--shell-line);border-radius:var(--r-md);background:var(--shell-bg);cursor:pointer;transition:border-color .16s ease,background-color .16s ease}.upload-drop:hover,.upload-drop:focus-visible,.upload-drop.is-dragover{border-color:var(--shell-accent);background:var(--shell-selected);outline:2px solid var(--c-focus);outline-offset:2px}.upload-drop strong{color:var(--shell-accent);font-size:var(--t-body-sm)}.upload-drop small{color:var(--shell-muted)}.upload-drop.is-dragover strong{text-decoration:underline}.upload-file-list{display:grid;gap:2px;margin:0;padding-left:18px;color:var(--shell-ink);font-size:var(--t-meta)}.upload-file-list li{overflow-wrap:anywhere}.upload-file-count{font-weight:700}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
#file.sr-only{width:1px;height:1px;min-height:0;min-width:0}.upload-failure-pages{display:flex;align-items:center;justify-content:center;gap:12px;padding:10px 0}.upload-system-error{border:2px solid var(--shell-warn)}.upload-failure-pages button{min-width:80px;min-height:44px}.upload-failure-pages button:disabled{cursor:not-allowed}
#review-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0}#review-metrics button{text-align:left;padding:10px;line-height:1.5}#review-metrics button[aria-pressed=true]{background:var(--shell-selected);border-color:var(--shell-accent)}#review-metrics strong{display:block;font-size:var(--t-h1)}.ota-icon,.review-icon .ic{width:18px;height:18px;vertical-align:-3px;margin-right:6px}.review-state{font-size:var(--t-caption);color:var(--shell-muted)}.review-money{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}#review-controls{margin:12px 0}#review-controls label{display:block}#preview th button{padding:0;border:0;background:transparent}#review-empty{padding:20px;text-align:center;color:var(--shell-muted)}@media(max-width:550px){#review-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}#preview thead{display:table-header-group}#preview thead tr{display:table-row;border:0;padding:0}#preview th{display:table-cell;padding:4px;font-size:var(--t-caption)}#preview td.review-money{text-align:left}}

.coverage-form{display:grid;gap:10px;margin:12px 0;padding:12px;border:1px solid var(--shell-line);border-radius:var(--r-sm);max-width:100%;overflow-wrap:anywhere}.coverage-form label{display:grid;gap:4px}.coverage-form input,.coverage-form select{min-width:0;width:100%;box-sizing:border-box;min-height:44px}.coverage-form button{min-height:44px}.coverage-form .coverage-complete{display:flex;align-items:center;gap:8px}.coverage-complete input{width:22px;min-height:22px}.coverage-message{white-space:normal;overflow-wrap:anywhere}

/* Card-by-card query coverage, separate from transaction classifications. */
.coverage-dashboard{margin:14px 0 20px;min-width:0}
.coverage-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:0 0 12px}
.coverage-metric{background:var(--shell-paper);border:1px solid var(--shell-line);border-radius:var(--r-md);padding:12px;min-width:0}
.coverage-metric strong{display:block;font-size:var(--t-h1);font-variant-numeric:tabular-nums}
.coverage-metric span{display:block;color:var(--shell-muted,var(--c-text-secondary));font-size:var(--t-caption)}
.coverage-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:12px}
.coverage-card{background:var(--shell-paper);border:1px solid var(--shell-line);border-radius:var(--r-md);padding:14px;min-width:0}
.coverage-card h3{font-size:var(--t-body);margin:0 0 5px}
.coverage-status{font-weight:650;font-size:var(--t-meta);margin:8px 0}
.coverage-period{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:7px 0;padding:8px;border-inline-start:4px solid var(--c-accent-solid);border-radius:var(--r-sm);background:var(--shell-bg)}
.coverage-period.missing{border-inline-start-color:var(--c-warn-text)}
.coverage-period .period-dates{flex:1;min-width:130px;overflow-wrap:anywhere}
.coverage-period button,.coverage-card button{min-height:44px}
.coverage-files{margin-top:12px;border-top:1px solid var(--shell-line);padding-top:9px}
.coverage-files summary{cursor:pointer;padding:4px 0}
.coverage-file{padding:8px 0;border-bottom:1px solid var(--shell-line);overflow-wrap:anywhere}
.coverage-file button{display:block;margin-top:7px}
.coverage-empty{padding:14px;border:1px dashed var(--shell-line);border-radius:var(--r-md)}
.coverage-baseline{padding:8px 0}.coverage-baseline summary{cursor:pointer}.coverage-baseline-form input{min-height:44px;margin:8px 0}.coverage-baseline-form button{min-height:44px}
.gap-upload-context{padding:12px;border:1px solid var(--c-warn-text);border-radius:var(--r-md);background:var(--shell-bg);white-space:normal}
@media(max-width:740px){.coverage-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:360px){.coverage-metrics{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.coverage-period{display:block}.coverage-period button{width:100%;margin-top:8px}}
</style><body><main><h1>카드 거래 상세</h1><details id="saved-materials"><summary>기존 업로드 파일 상세</summary><section><h2>저장된 카드 자료</h2><div id="batches"></div></section></details>
<details id="newupload"><summary>카드 자료 관리·업로드</summary><section><h2>카드사별 거래일자 공백</h2><p class="small">첫 거래일부터 마지막 거래일까지 거래가 없는 날짜를 표시합니다. 정상 미사용일 수 있으며 자료 누락을 뜻하지는 않습니다.</p><div id="coverage-summary" class="coverage-dashboard" aria-live="polite"><p>카드사별 수집 현황을 불러오는 중입니다.</p></div><h2>카드 파일 추가</h2><p id="gap-upload-context" class="gap-upload-context" role="status" hidden></p><p class="small upload-lede">카드사에서 받은 XLS·XLSX 또는 CSV 파일을 여러 개 선택할 수 있습니다. 파일을 먼저 한 번에 접수한 뒤 백그라운드에서 처리하며, 기존 거래와 중복되는 내역은 다시 기록하지 않습니다.</p><label id="upload-drop" class="upload-drop file-drop" for="file" tabindex="0" role="button" aria-describedby="upload-help"><span><strong>파일을 선택하거나 이곳에 끌어다 놓으세요</strong></span><small>지원 형식: XLS, XLSX, CSV · 여러 파일 선택 가능</small><span id="upload-selection" class="small">선택된 파일 없음</span><ul id="upload-file-list" class="upload-file-list" hidden></ul></label><input id="file" class="sr-only" type="file" accept=".xls,.xlsx,.csv" multiple aria-describedby="upload-help"><p id="upload-help" class="small">전체 파일 접수가 끝나면 다른 페이지로 이동할 수 있습니다. 처리는 백그라운드에서 계속되며 결과는 저장됩니다.</p><button id="upload">__ICON_UPLOAD__<span id="upload-label">카드 사용내역 업로드</span></button><div id="upload-results" aria-label="파일별 처리 결과" aria-live="polite" hidden></div></section></details>
<details id="rules"><summary>분류 규칙 수정</summary><section><p class="small">가맹점이 정확히 일치할 때 비용 항목을 적용합니다. 여행은 가맹점만으로 자동 배정하지 않습니다.</p><form id="ruleform"><input name="rule_id" type="hidden"><input name="version" type="hidden" value="0"><label>가맹점<input name="merchant" required></label><label>카드 종류<input name="card_kind" placeholder="국내 또는 해외 · 비우면 모든 종류"></label><label>거래 구분<select name="direction"><option value="purchase">사용</option><option value="cancellation">취소·환불</option></select></label><label>여행 중 사용 조건<select name="rule_country"><option value="">여행 조건 없음</option><option value="local">국내·해외 구분과 여행 기간 일치</option><option value="overseas">해외 사용 · 해외 여행 기간 일치</option><option value="KR">국내 사용 · 국내 여행 기간 일치</option></select></label><p id="rule_scope" class="small"></p><label>비용 항목<input name="rule_item" required></label><label>내용<input name="rule_description"></label><button>__ICON_SAVE__규칙 저장하고 다시 분류</button><button type="button" id="newrule">__ICON_PENCIL__새 규칙 작성</button></form><label>저장된 규칙 찾기<input id="rulefilter" type="search" placeholder="가맹점 또는 비용 항목"></label><div id="rulelist"></div></section></details>
 <p id="status" role="status"></p><div id="review-metrics"></div><section id="review-controls"><label>거래 검색<input id="review-search" type="search" placeholder="가맹점·항목·귀속 검색"></label><div class="grid"><details id="review-date"><summary><button type="button" aria-label="거래일 정렬 및 월 선택" id="review-date-toggle">__ICON_SEARCH__거래일·월</button></summary><label>정렬<select id="review-sort"><option value="date-asc">이전 거래부터</option><option value="date-desc">최근 거래부터</option><option value="amount-desc">큰 금액부터</option></select></label><label>월<select id="review-month"><option value="">전체 월</option></select></label></details><label>비용 항목<select id="review-category"><option value="">전체 항목</option></select></label></div><button type="button" id="review-reset" aria-label="조회 조건 초기화">__ICON_ROTATE__조회 조건 초기화</button></section><section id="summary" class="hidden"></section><section id="preview" class="hidden"></section><section id="edit-panel" hidden aria-live="polite"></section>
</main><script>
const csrf=__CSRF__;let model,stamp='',page=0,editing='',batchGeneration=0,googleCopyPending=false;const PAGE_SIZE=20;const el=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// 자동갱신이 입력 중인 내용을 덮지 않게 하는 조건. 폼에 focus가 있거나 규칙 편집 중이면 그대로 둔다.
const busy=()=>!!document.activeElement?.closest('form')||el('rules').open;
const stateStamp=j=>JSON.stringify([j.batch_id,j.preview.digest,j.rows.map(r=>[r.transaction_id,r.revision,r.classification_state,r.item,r.decided,r.review_evidence_labels,r.ota_link_status,r.ota_snapshot_generation,r.ota_candidate_notes]),j.trips.map(t=>[t.id,t.available]),j.quarter_targets||[]]);
function mutationBody(target,payload){const basis=JSON.stringify(payload);if(target.pendingMutation?.basis!==basis)target.pendingMutation={basis,id:crypto.randomUUID()};return JSON.stringify({...payload,request_id:target.pendingMutation.id})}
const money=n=>n==null?'금액 미확인':Number(n).toLocaleString('ko-KR')+'원';
const evidence=r=>(r.review_evidence_labels||[]).slice(0,3).join(' · ');
function quarterForDate(value){const match=String(value||'').match(/^([0-9]{4})-([0-9]{2})/);if(!match)return null;const month=Number(match[2]);if(month<1||month>12)return null;return {id:'quarter:'+match[1]+':'+Math.ceil(month/3),name:match[1]+'년 '+Math.ceil(month/3)+'분기 기타비용'};}
function destinationLabel(j,r){const id=String(r.display_tab_id||r.trip_id||'');const quarter=(j.quarter_targets||[]).find(t=>t.id===id)||quarterForDate(reviewDate(r));if(quarter)return quarter.name||quarter.display_name||id;const trip=(j.trips||[]).find(t=>t.id===id);if(trip)return trip.name||id;return '원본 날짜 오류 · 귀속 표시 불가';}
function destinationOptions(j,r){const current=String(r.display_tab_id||r.trip_id||'');const quarter=quarterForDate(reviewDate(r));const targets=(j.quarter_targets||[]).map(t=>({id:t.id,name:t.name||t.display_name||t.id}));if(quarter&&!targets.some(t=>t.id===quarter.id))targets.unshift(quarter);const options=targets.map(t=>'<option value=\"'+esc(t.id)+'\"'+(t.id===current?' selected':'')+'>'+esc(t.name)+'</option>');return options.concat((j.trips||[]).filter(t=>t.available).map(t=>'<option value=\"'+esc(t.id)+'\"'+(t.id===current?' selected':'')+'>'+esc(t.name)+'</option>')).join('')}
function answerForm(j,r){return '<form data-index=\"'+j.rows.indexOf(r)+'\"><label>비용 항목<input name=\"item\" value=\"'+esc(r.item)+'\" required></label><label>귀속<select name=\"display_tab_id\">'+destinationOptions(j,r)+'</select></label><label>메모<textarea name=\"note\" rows=\"2\">'+esc(r.note||'')+'</textarea></label><button>저장</button></form>'}
const reviewIcons=__REVIEW_ICONS__;let reviewState='all';
const reviewDate=r=>r.approval_date||r.posting_date||'';
const reviewIcon=r=>{const m=String(r.merchant||'').toUpperCase();return /(^|[^A-Z0-9])AGODA([^A-Z0-9]|$)/.test(m)?reviewIcons.agoda:/(^|[^A-Z0-9])TRIP\\.COM([^A-Z0-9.]|$)/.test(m)||m.includes('트립닷컴')?reviewIcons.trip:reviewIcons.merchant};
const reviewStatus=r=>r.already_booked?'booked':(r.next_action?.group==='excluded'?'excluded':'');
const otaLabels={CANDIDATE:'호텔 예약 후보 · 결제 미확정',EXACT:'OTA \uc815\ud655 \uc5f0\uacb0',INFERRED:'OTA 자동 연결',UNLINKED:'OTA \ubbf8\uc5f0\uacb0',USER_CONFIRMED:'OTA \uc0ac\uc6a9\uc790 \ud655\uc815',RESERVATION_INFERRED:'예약 자동 연결 · 결제 미검증',RESERVATION_CONFIRMED:'예약 관계 확인 · 결제 미검증',RESERVATION_NEEDS_REVIEW:'예약 관계를 확인해 주세요 · 결제 미검증',RESERVATION_STALE:'저장한 예약 관계 변경 · 원본을 확인해 주세요',GROUP_RECONCILED:'OTA 그룹 대응 · 예약 개별 연결 미확정',REVIEW_REQUIRED:'OTA 자료를 확인해 주세요',UNKNOWN:'OTA \uc0c1\ud0dc \ubbf8\ud655\uc778'};
otaLabels.GROUP_LINKED='OTA M:N 연결';
const expenseLabels={READY_FOR_INTERNAL_SAVE:'COST \ub0b4\ubd80 \uae30\ub85d \uc900\ube44',SAVED:'COST \ub0b4\ubd80 \uae30\ub85d \uc644\ub8cc',HELD:'COST \ud655\uc778 \ubcf4\ub958'};
 const reviewLabel=r=>[reviewStatus(r)==='booked'?'기록 완료':reviewStatus(r)==='excluded'?'기록 제외':'',r.next_action?.reason_label].filter(Boolean).join(' / ');
function completedRefundGroups(j){const rows=new Map(j.preview.rows.map(r=>[r.transaction_id,r]));return (j.refund_groups||[]).filter(g=>!g.error&&g.status==='full'&&g.net_krw===0&&g.rows.length&&g.rows.every(r=>r.already_booked&&!r.blocked&&!rows.get(r.transaction_id)?.review_hold))}
function otherReviewRows(j){const completed=new Set(completedRefundGroups(j).flatMap(g=>g.rows.map(r=>r.transaction_id)));return j.preview.rows.filter(r=>!completed.has(r.transaction_id))}
function renderCompletedRefund(g){return '<div class="refund-group refund-complete"><h2>전액 환불 · 처리 완료</h2><p>원결제 '+money(g.gross_krw)+' · 환불 '+money(g.refund_krw)+' · 순액 '+money(g.net_krw)+'</p><p>기록 완료 '+g.rows.length+'건 · 추가 입력 없음</p></div>'}
function reviewRows(j){const originals=new Map(j.rows.map(r=>[r.transaction_id,r]));let rows=otherReviewRows(j).map(r=>({...originals.get(r.transaction_id),...r}));const focus=new URLSearchParams(location.search).get('transaction');if(location.hash==='#preview'&&focus)rows=rows.filter(r=>r.transaction_id===focus||r.refund_link?.counterpart_id===focus);const term=el('review-search').value.trim().toLowerCase(),month=el('review-month').value,category=el('review-category').value;rows=rows.filter(r=>(reviewState==='all'||reviewStatus(r)===reviewState)&&(!month||reviewDate(r).startsWith(month))&&(!category||r.item===category)&&(!term||[r.merchant,r.item,r.description,destinationLabel(j,r)].join(' ').toLowerCase().includes(term)));const sort=el('review-sort').value;return rows.sort((a,b)=>!reviewDate(a)||!reviewDate(b)?Number(!reviewDate(a))-Number(!reviewDate(b)):sort==='amount-desc'?Number(b.amount_krw)-Number(a.amount_krw):sort==='date-asc'?reviewDate(a).localeCompare(reviewDate(b)):reviewDate(b).localeCompare(reviewDate(a)))}
function renderReviewControls(j){const rows=otherReviewRows(j);el('review-metrics').innerHTML=[['all','전체 거래'],['booked','기록 완료'],['excluded','기록 제외']].map(([state,label])=>'<button type="button" data-review-state="'+state+'" aria-pressed="'+(state===reviewState)+'">'+label+'<strong>'+rows.filter(r=>state==='all'||reviewStatus(r)===state).length+'</strong></button>').join('');for(const [id,values] of [['review-month',[...new Set(j.rows.map(r=>reviewDate(r).slice(0,7)).filter(Boolean))].sort()],['review-category',[...new Set(j.rows.map(r=>r.item).filter(Boolean))].sort()]]){const select=el(id),value=select.value;select.innerHTML='<option value="">'+(id==='review-month'?'전체 월':'전체 항목')+'</option>'+values.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');select.value=values.includes(value)?value:''}document.querySelectorAll('[data-review-state]').forEach(b=>b.onclick=()=>{reviewState=b.dataset.reviewState;page=0;render(model)})}
for(const id of ['review-search','review-month','review-category','review-sort'])el(id).addEventListener(id==='review-search'?'input':'change',()=>{page=0;render(model)});
el('review-reset').onclick=()=>{el('review-search').value='';el('review-month').value='';el('review-category').value='';el('review-sort').value='date-asc';page=0;render(model)};
el('review-date-toggle').onclick=e=>{e.preventDefault();el('review-date').open=!el('review-date').open};
let rules=[];
function renderRules(list){rules=list;const term=el('rulefilter').value.toLowerCase(),matches=list.filter(r=>(r.conditions.merchant_normalized+' '+r.effects.item).toLowerCase().includes(term));el('rulelist').innerHTML='<p class="small">'+matches.length+'개 규칙 중 '+Math.min(40,matches.length)+'개 표시 · 검색으로 찾을 수 있습니다.</p>'+matches.slice(0,40).map(r=>'<p><button data-rule="'+rules.indexOf(r)+'">'+esc(r.conditions.merchant_normalized==='*'?'여행 중 현지경비 기본값':r.conditions.merchant_normalized)+' → '+esc(r.effects.item)+' · 수정</button></p>').join('');document.querySelectorAll('[data-rule]').forEach(b=>b.onclick=()=>{const r=rules[Number(b.dataset.rule)],f=el('ruleform');f.elements.rule_id.value=r.rule_id;f.elements.version.value=r.version;f.elements.merchant.value=r.conditions.merchant_normalized==='*'?'여행 중 현지경비 기본값':r.conditions.merchant_normalized;f.elements.merchant.readOnly=r.conditions.merchant_normalized==='*';f.elements.card_kind.value=r.conditions.card_kind||'';f.elements.direction.value=r.conditions.transaction_direction||'purchase';f.elements.rule_country.value=['JP','TW','AT','IT','FR'].includes(r.optional.travel_country)?'overseas':r.optional.travel_country||'';f.elements.rule_item.value=r.effects.item||'';f.elements.rule_description.value=r.effects.description||'';f.elements.rule_country.disabled=!!r.optional.inferred_assignment;el('rule_scope').textContent=r.origin==='owner-country-exception-20261003'?'사용자 지정 예외: 조지아·카자흐스탄 거래를 유럽 여행에 배정합니다.':r.optional.inferred_assignment?'이번 거래에만 적용한 추론입니다. 여행은 미리보기의 수정에서 바꿀 수 있습니다.':r.optional.source_hash?'예약 자료로 확인된 해당 원본 거래에만 적용합니다.':r.note||''})}
async function call(url,body,headers={}){const r=await fetch(url,body==null?{cache:'no-store'}:{method:'POST',headers:{'X-CSRF-Token':csrf,...headers},body}).catch(()=>{throw Error('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')});if(!(r.headers.get('Content-Type')||'').includes('application/json'))throw Error(r.status===401?'로그인이 필요합니다. 화면을 다시 열어 주세요.':'서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.');const j=await r.json();if(!r.ok)throw Error(j.message||j.code);return j}


function coverageNode(tag,klass,content){
 const node=document.createElement(tag);if(klass)node.className=klass;
 if(content!=null)node.textContent=String(content);return node;
}
async function refreshCoverageSummary(){
 const root=el('coverage-summary');if(!root)return;
 const link=coverageNode('a','','카드사별 거래일자 공백 확인');
 link.href='/cards/all?panel=coverage';root.replaceChildren(link);
}
function appendCoverageForm(root,j){
 if(j.batch_id)root.append(coverageNode('p','small','거래일자가 확인되면 카드사별 공백 현황에 반영됩니다.'));
}

let uploadFailurePage=0;const UPLOAD_FAILURE_PAGE_SIZE=50;
function renderUploadSystemError(message){
 const root=el('summary'),prior=root.querySelector('.upload-result');if(prior)prior.remove();
 const panel=document.createElement('section');panel.className='upload-result upload-system-error';panel.setAttribute('role','alert');panel.setAttribute('aria-label','업로드 검증 불가');
 const title=document.createElement('h2');title.textContent='검증 불가 (파일/시스템 오류)';
 const detail=document.createElement('p');detail.textContent=message||'업로드 결과를 확인하지 못했습니다. 파일을 확인한 뒤 다시 시도해 주세요.';
 panel.append(title,detail);root.insertBefore(panel,root.firstChild);root.className='';
}
function renderUploadSummary(j){
 const s=j.upload_summary; if(!s)return;
 const root=el('summary'),prior=root.querySelector('.upload-result');if(prior)prior.remove();
 const c=s.counts; const labels=[['T','업로드 거래'],['E','기존 일치'],['N','신규 등록'],['C','처리 완료'],['U','처리 미완료'],['H','대조 중'],['P','파싱 실패'],['R','취소 원결제 미연결']];
 const status=s.status==='passed'?'처리 완료':s.status==='empty'?'처리할 거래 없음':'처리 미완료 '+(c.U+c.H+c.P)+'건';
 let h='<h2>'+esc(status)+'</h2><div class="upload-metrics" role="list">'+labels.map(([k,n])=>'<div role="listitem"><b>'+n+' ('+k+')</b><strong>'+esc(c[k])+'</strong></div>').join('')+'</div><p>처리 완료율 <strong>'+esc(s.rate==null?'처리할 거래 없음':Number(s.rate).toFixed(1)+'%')+'</strong></p>';
 const meta=s.file; h+='<p>'+esc(meta.filename)+' · '+esc(meta.issuers.join(', '))+' · '+esc(meta.period_start||'이용일 원문 없음')+' ~ '+esc(meta.period_end)+'</p><p>파일 내부 중복 원천행 '+esc(s.duplicate_rows)+'건</p>';
 const table=(title,a)=>a.length?'<details><summary>'+title+'</summary><div class="upload-table"><table><thead><tr><th>월</th>'+labels.slice(0,7).map(([k,n])=>'<th>'+n+'</th>').join('')+'</tr></thead><tbody>'+a.map(x=>'<tr><th scope="row">'+esc(x.month)+'</th>'+labels.slice(0,7).map(([k])=>'<td>'+esc(x[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div></details>':'';
 h+=table('월별 대조',s.monthly_reconciliation)+table('날짜 미상 대조',s.unknown_date_reconciliation);
 if(s.financial_warning)h+='<aside class="financial-warning" role="alert"><strong>분류와 별도: 금융 대사 미완료</strong><p>'+esc(s.financial_warning)+'</p></aside>';
 const failures=s.failures||[],pages=Math.max(1,Math.ceil(failures.length/UPLOAD_FAILURE_PAGE_SIZE));uploadFailurePage=Math.min(uploadFailurePage,pages-1);
 if(failures.length){const start=uploadFailurePage*UPLOAD_FAILURE_PAGE_SIZE,shown=failures.slice(start,start+UPLOAD_FAILURE_PAGE_SIZE);
  h+='<details open><summary>실패 상세 ('+failures.length+'건) · '+(start+1)+'–'+(start+shown.length)+'건 표시</summary><ul>'+shown.map(x=>'<li>행 '+esc(x.row_number)+' · '+esc(x.date)+' · '+esc(x.masked_identity)+' · '+esc(x.merchant)+' · '+esc(x.amount)+' '+esc(x.currency)+' · '+(x.matched?'기존 거래 연결':'미연결')+' · '+esc(x.trip_id)+' · '+esc(x.item)+' · '+esc(x.reason)+'<p>'+esc(x.basis)+'</p><a href="'+esc(x.review_url)+'">거래 검토</a></li>').join('')+'</ul>'+(pages>1?'<nav class="upload-failure-pages" aria-label="실패 상세 페이지"><button type="button" data-upload-failure-prev'+(uploadFailurePage===0?' disabled':'')+'>이전</button><span aria-live="polite">'+(uploadFailurePage+1)+' / '+pages+' 페이지</span><button type="button" data-upload-failure-next'+(uploadFailurePage+1>=pages?' disabled':'')+'>다음</button></nav>':'')+'</details>';
 }
 const section=document.createElement('section');section.className='upload-result';section.setAttribute('role','status');section.setAttribute('aria-label','업로드 전수 대조 결과');section.innerHTML=h;root.insertBefore(section,root.firstChild);
 const changeFailurePage=(delta,preferred,fallback)=>{uploadFailurePage+=delta;renderUploadSummary({upload_summary:s});const target=el('summary').querySelector(preferred),backup=el('summary').querySelector(fallback);(target&&!target.disabled?target:backup)?.focus()};
 section.querySelector('[data-upload-failure-prev]')?.addEventListener('click',()=>changeFailurePage(-1,'[data-upload-failure-prev]','[data-upload-failure-next]'));
 section.querySelector('[data-upload-failure-next]')?.addEventListener('click',()=>changeFailurePage(1,'[data-upload-failure-next]','[data-upload-failure-prev]'));

}
  function render(j,switchBatch=false){if(model&&model.batch_id!==j.batch_id&&!switchBatch)return;if(model&&model.batch_id===j.batch_id){const older=(rows,previous,field)=>{const versions=new Map(previous.map(r=>[r.transaction_id,Number(r[field]||0)]));return rows.some(r=>Number(r[field]||0)<(versions.get(r.transaction_id)||0))};if(older(j.rows,model.rows,'revision')||older(j.preview.rows,model.preview.rows,'exclusion_revision'))return;}if(model&&stateStamp(j)!==stamp)invalidateProposal();if(model?.batch_id!==j.batch_id){page=0;editing='';reviewState='all';el('review-search').value='';el('review-month').value='';el('review-category').value=''}model=j;el('review-metrics').before(el('summary'));renderReviewControls(j);stamp=stateStamp(j);el('summary').className='';const approval=j.summary.channel==='approval',approvalInfo=j.approval_summary||{},states=approvalInfo.states||{};const reviewCounts={review:0,booked:0,excluded:0};j.preview.rows.forEach(r=>{const state=reviewStatus(r);if(state)reviewCounts[state]=(reviewCounts[state]||0)+1});el('summary').innerHTML='<h2>'+esc(j.summary.display_name||'카드 거래 결과')+'</h2>';
renderUploadSummary(j);
if(j.ota_reconciliation?.enabled&&!j.ota_reconciliation.fresh){const notice=document.createElement('p');notice.className='small';notice.setAttribute('role','status');notice.textContent=j.ota_reconciliation.status==='stale'?'OTA 대사 자료가 갱신 중입니다. 예약 연결 표시는 최신 확인 전까지 미확정으로 표시합니다.':'OTA 대사 자료를 확인하고 있습니다. 예약 연결 표시는 확인 전까지 미확정으로 표시합니다.';el('summary').append(notice)}

const ed=editing?j.rows.find(r=>r.transaction_id===editing&&!r.duplicate_of):null;const edit=el('edit-panel');
if(ed){edit.hidden=false;edit.innerHTML='<article><h2>거래 귀속 수정 · '+esc(ed.merchant)+'</h2><p class="small">저장된 귀속과 항목을 수정합니다. 원본과 금융 보호 상태는 유지됩니다.</p>'+answerForm(j,ed)+'</article>';}else{edit.hidden=true;edit.replaceChildren();}
const otaCandidateReason=note=>{const text=String(note||'');return text.startsWith('OTA 후보(미확정):')?text.split(' · ').slice(2).join(' · '):'예약 후보 근거가 있으나 결제 연결은 검증되지 않았습니다.'};const completedGroups=new Set(completedRefundGroups(j));const groups=(j.refund_groups||[]).map(g=>completedGroups.has(g)?renderCompletedRefund(g):g.error?'<p class=small>환불 쌍 자료 확인: '+esc(g.message)+'</p>':'<div class="refund-group"><h2>환불 쌍</h2><p>원결제 '+money(g.gross_krw)+' · 환불 '+money(g.refund_krw)+' · 순액 '+money(g.net_krw)+'</p><p>항목 '+esc(g.item)+' · 여행 '+esc(g.trip_name||'분기 기타비용')+'</p><button type="button" data-group-commit="'+esc(g.original_id)+'" data-digest="'+esc(g.digest)+'" '+(g.recordable&&g.rows.some(r=>!r.already_booked)?'':'disabled')+'>__ICON_CHECK__이 환불 쌍 '+g.rows.length+'건만 장부에 기록</button>'+(g.recordable?'':'<p class=small>'+esc(g.reason)+'</p>')+'</div>').join('');const p={...j.preview,rows:otherReviewRows(j)};el('preview').className='';el('preview').innerHTML=(groups?'<section aria-label="환불 처리 결과">'+groups+'</section>':'')+p.rows.filter(r=>r.excluded_from_company).map(r=>'<p>회사 경비 제외: '+esc(r.merchant)+' · '+money(r.amount_krw)+' <button type="button" data-company-restore="'+esc(r.transaction_id)+'">__ICON_ROTATE__회사 경비 제외 되돌리기</button></p>').join('')+(completedGroups.size?'<h2>그 외 거래 처리 결과</h2><p>위 전액 환불과 별개인 거래입니다.</p>':'<h2>거래 처리 결과</h2>')+'<p>완료 '+p.rows.filter(r=>r.already_booked).length+'</p><table><thead><tr><th><button type="button" data-review-date>거래일·가맹점</button></th><th>항목</th><th>금액</th><th>귀속</th><th>수정</th></tr></thead><tbody>'+reviewRows(j).map(r=>'<tr><td><span class="pv-label">거래일·가맹점</span>'+esc(reviewDate(r))+'<br><span class="review-icon">'+reviewIcon(r)+'</span>'+esc(r.merchant)+(reviewLabel(r)?'<br><span class="review-state">'+esc(reviewLabel(r))+'</span>':'')+'</td><td><span class="pv-label">항목</span><span class="review-icon">'+(reviewIcons[r.item]||reviewIcons.merchant)+'</span>'+esc(r.item)+((r.booking_ref||r.service_period)?'<br><span class=small>OTA 예약 근거 · '+esc([r.booking_ref,r.service_period].filter(Boolean).join(' · '))+'</span>':'')+(r.ota_link_status==='UNLINKED'&&r.ota_candidate_notes?.length?'<br><span class=\"ota-candidate-note\"><strong>OTA 후보 근거 · 결제 미검증</strong>'+r.ota_candidate_notes.map(otaCandidateReason).filter(Boolean).map(reason=>'<span>'+esc(reason)+'</span>').join('')+'</span>':'')+(['inference','code_inference','ai_inference','user_exception','guide_airfare_evidence'].includes(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source)?'<br><span class=small>'+esc({inference:'자동',code_inference:'자동',ai_inference:'AI 추론',user_exception:'직접',guide_airfare_evidence:'자동'}[j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source]||'자동 연결')+'</span>':'')+'</td><td class="review-money"><span class="pv-label">금액</span>'+money(r.amount_krw)+'</td><td><span class="pv-label">귀속</span>'+esc((j.quarter_targets||[]).find(t=>t.transaction_ids.includes(r.transaction_id))?.name||j.trips.find(t=>t.id===r.display_tab_id)?.name||destinationLabel(j,r))+(['inference','code_inference','ai_inference','user_exception','guide_airfare_evidence'].includes(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source)?'<details><summary>배정 근거</summary>'+esc(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_basis)+'</details>':'')+'</td><td><button type="button" data-edit="'+esc(r.transaction_id)+'">__ICON_PENCIL__'+esc(r.next_action?.required?r.next_action.label:'수정')+'</button><p class=small>'+esc(r.next_action?.reason||'')+'</p>'+(r.excluded_from_company?'<button type="button" data-company-restore="'+esc(r.transaction_id)+'">__ICON_ROTATE__회사 경비 제외 되돌리기</button>':'')+'</td></tr>').join('')+'</tbody></table><p id="review-empty"'+(reviewRows(j).length?' hidden':'')+'>조회 조건에 맞는 거래가 없습니다.</p>';
 document.querySelectorAll('[data-group-commit]').forEach(b=>b.hidden=true);el('preview').insertAdjacentHTML('beforeend',(j.quarter_targets||[]).map(t=>'<section class="quarter-copy"><h2>'+esc(t.name)+'</h2><p class="small">여행 외 비용 · '+t.transaction_ids.length+'건 · 원본과 기록 상태는 그대로 유지합니다.</p>'+(t.available?'<a href="'+esc(t.href)+'" target="_blank" rel="noopener noreferrer">Google 분기 원본 열기</a><p><button type="button" data-google-copy="'+esc(t.id)+'">__ICON_COPY__'+esc(t.name)+' 지출 7열 복사</button></p>':'<p role="status">'+esc(t.reason)+'</p>')+'</section>').join(''));
document.querySelector('[data-review-date]').onclick=()=>{el('review-date').open=true;el('review-date').scrollIntoView({block:'center'});};
document.querySelectorAll('form[data-index]').forEach(f=>f.onsubmit=async e=>{e.preventDefault();const r=model.rows[Number(f.dataset.index)],v=new FormData(f),batch=model.batch_id,generation=batchGeneration,button=f.querySelector('button');if(button.disabled)return;button.disabled=true;try{const j=await call('/api/imports/'+model.batch_id+'/decision',mutationBody(f,{transaction_id:r.transaction_id,revision:r.revision,item:v.get('item'),description:v.get('description'),display_tab_id:v.get('display_tab_id'),note:v.get('note'),reuse_rule:v.has('reuse_rule')}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(j.trip_move_learning?.status==='opened'){location.assign(j.trip_move_learning.url);return}if(editing===r.transaction_id)editing='';if(!j.refresh_required)render(j);el('status').textContent=j.refresh_required?'분류는 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 주세요.':j.ledger_recording?.status==='held'?'분류 완료 · 금융 보호 검사에서 기록할 수 없습니다: '+j.ledger_recording.reason:'저장했습니다.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message}finally{button.disabled=false}})
document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{editing=b.dataset.edit;render(model);el('edit-panel').scrollIntoView({block:'start',behavior:'smooth'});el('status').textContent='선택한 거래의 귀속을 수정할 수 있습니다.'});
if(el('prevpage'))el('prevpage').onclick=()=>{page=Math.max(0,page-1);render(model)};
if(el('nextpage'))el('nextpage').onclick=()=>{page=page+1;render(model)};}
const uploadInput=el('file'),uploadDrop=el('upload-drop'),uploadSelection=el('upload-selection'),uploadFileList=el('upload-file-list'),uploadLabel=el('upload-label'),acceptedUpload=new RegExp('\\\\.(xls|xlsx|csv)$','i');
function renderUploadSelection(){const files=Array.from(uploadInput.files||[]),valid=files.filter(f=>acceptedUpload.test(f.name));uploadSelection.innerHTML=valid.length?'<span class="upload-file-count">'+valid.length+'개 파일 선택됨</span> · '+valid.reduce((sum,f)=>sum+f.size,0).toLocaleString('ko-KR')+' bytes':'선택된 파일 없음';uploadFileList.innerHTML=valid.map(f=>'<li>'+esc(f.name)+'</li>').join('');uploadFileList.hidden=!valid.length;uploadDrop.setAttribute('aria-label',valid.length+'개 파일 선택됨. 파일을 다시 선택하려면 Enter 또는 Space를 누르세요.');if(files.length!==valid.length)el('status').textContent='지원하지 않는 파일 형식은 제외했습니다. XLS, XLSX, CSV만 선택해 주세요.';return valid}
uploadInput.onchange=renderUploadSelection;
uploadDrop.ondragover=e=>{e.preventDefault();if(uploadInput.disabled)return;uploadDrop.classList.add('is-dragover')};
uploadDrop.ondragleave=()=>uploadDrop.classList.remove('is-dragover');
uploadDrop.ondrop=e=>{e.preventDefault();uploadDrop.classList.remove('is-dragover');if(!uploadInput.disabled){uploadInput.files=e.dataTransfer.files;renderUploadSelection()}};
uploadDrop.onkeydown=e=>{if(uploadInput.disabled)return;if(e.key==='Enter'||e.key===' '){e.preventDefault();uploadInput.click()}};
const uploadJobKey='cost-card-upload-job';
function uploadRow(entry,name,message,tone='pending'){
 entry.className='upload-result-row';entry.dataset.state=tone;entry.replaceChildren();
 const filename=document.createElement('strong');filename.className='upload-result-name';filename.textContent=name||'카드 파일';
 const status=document.createElement('span');status.className='upload-result-state';status.textContent=message;
 entry.append(filename,status);
}
function uploadResultList(root){root.hidden=false;root.innerHTML='<h3>파일별 처리 결과</h3><p class="upload-result-notice" role="status"></p><ul class="upload-result-list"></ul>';return {note:root.querySelector('p'),list:root.querySelector('ul')}}
function uploadErrorRow(entry,job,error){uploadRow(entry,job.filename,(error.savedBatch?'':'접수 실패 · ')+error.message,error.auth?'auth':error.savedBatch?'pending':'error');if(error.savedBatch)savedUploadLink(entry,error.savedBatch)}
async function recoverUpload(job){
 const response=await fetch(job.status_url+'?batch='+encodeURIComponent(job.batch_id),{cache:'no-store',signal:AbortSignal.timeout(10000)});
 if(response.status===401||response.status===403)throw Object.assign(Error(response.status===401?'로그인 필요':'조회 권한 필요'),{terminal:true,auth:true});
 if(!response.ok)throw Error('저장된 결과 조회 재시도 중');
 const state=await response.json(),result=state.result;
 if(state.status!=='saved'||result?.batch_id!==job.batch_id||typeof result.recovery?.pending!=='boolean')throw Error('저장된 결과 조회 재시도 중');
 if(result.recovery.pending)throw Object.assign(Error('접수 완료 · 처리 결과 확인 필요'),{terminal:true});
 saveUploadJob(job,true);return {...result,recovered_upload:true};
}
function readUploadJobs(){try{const saved=JSON.parse(localStorage.getItem(uploadJobKey)||'null');return (Array.isArray(saved)?saved:saved?[saved]:[]).filter(job=>job?.status_url&&new RegExp('^/api/imports/upload-status/[a-f0-9]{32}$').test(job.status_url))}catch{return []}}
function saveUploadJob(job,finished=false){try{const jobs=readUploadJobs().filter(saved=>saved.status_url!==job.status_url);if(!finished)jobs.push(job);if(jobs.length)localStorage.setItem(uploadJobKey,JSON.stringify(jobs));else localStorage.removeItem(uploadJobKey)}catch{}}
async function awaitUpload(job,entry){
 saveUploadJob(job);const started=Date.now();let errors=0;
 while(true){
  try{
   const r=await fetch(job.status_url,{cache:'no-store',signal:AbortSignal.timeout(10000)});
   if(r.status===401||r.status===403)throw Object.assign(Error(r.status===401?'로그인 필요':'조회 권한 필요'),{terminal:true,auth:true});
   if(r.status===404)return await recoverUpload(job);
   if(!r.ok)throw Error('진행 상태 연결 재시도 중');
   const state=await r.json();
   if(state.status==='done'){if(state.result?.refresh_required)return await recoverUpload(job);saveUploadJob(job,true);return state.result}
   if(state.status==='error'){saveUploadJob(job,true);throw Object.assign(Error(state.message),{terminal:true})}
   errors=0;
   uploadRow(entry,job.filename,(state.message||'처리 중')+' · '+Math.floor((Date.now()-started)/1000)+'초');
  }catch(e){
   if(e.terminal){e.savedBatch=job.batch_id;throw e}
   errors++;uploadRow(entry,job.filename,'접수 완료 · 연결 재시도 중');
   if(errors>=5){const error=Error('접수 완료 · 결과 조회 대기');error.savedBatch=job.batch_id;throw error}
  }
  await new Promise(resolve=>setTimeout(resolve,Math.min(10000,errors?1000*2**errors:1500)));
 }
}
function savedUploadLink(entry,batch){const link=document.createElement('a');link.className='upload-result-link';link.href='/cards/all?panel=upload&batch='+encodeURIComponent(batch)+'#summary';link.textContent='처리 결과 보기';link.setAttribute('aria-label',(entry.querySelector('strong')?.textContent||'카드 파일')+' 처리 결과');entry.append(link)}
async function resumeUpload(){const jobs=readUploadJobs();if(!jobs.length)return;
 const root=el('upload-results');el('newupload').open=true;const {note,list}=uploadResultList(root);
 note.textContent=jobs.length+'개 파일 접수 완료 · 저장된 결과를 확인하고 있습니다.';
 let checked=0,waiting=0,auth=0,next=0;
 const entries=jobs.map(job=>{const entry=document.createElement('li');uploadRow(entry,job.filename,'결과 확인 대기');list.append(entry);return entry});
 const worker=async()=>{while(next<jobs.length){const i=next++,job=jobs[i],entry=entries[i];
  try{const result=await awaitUpload(job,entry);checked++;uploadRow(entry,job.filename,uploadOutcome(result),'saved');savedUploadLink(entry,job.batch_id)}
  catch(e){waiting++;if(e.auth)auth++;uploadErrorRow(entry,job,e)}
 }};
 await Promise.all(Array.from({length:Math.min(4,jobs.length)},worker));
 note.textContent=checked+'개 결과 조회 · '+waiting+'개 조회 대기. 접수된 파일은 다시 올릴 필요가 없습니다.'+(auth?' 로그인 또는 소유자 권한을 확인한 뒤 이 화면을 다시 열어 주세요.':'');
}
resumeUpload();
function uploadOutcome(j){if(j.recovered_upload)return '저장된 결과 조회 완료';const summary=j.upload_summary||j.recovery||{};let text='처리 완료';const count=summary.transaction_count??summary.unique_transactions??summary.saved_count;const duplicate=summary.duplicate_count??summary.duplicate_rows??summary.duplicates;if(Number.isFinite(Number(count)))text+=' · 거래 '+Number(count).toLocaleString('ko-KR')+'건 저장';if(Number.isFinite(Number(duplicate)))text+=' · 중복 '+Number(duplicate).toLocaleString('ko-KR')+'건';return text}
el('upload').onclick=async()=>{
 if(el('upload').disabled)return;
 const files=renderUploadSelection();if(!files.length){el('status').textContent='업로드할 카드 파일을 먼저 선택해 주세요.';uploadDrop.focus();return}
 const generation=++batchGeneration;uploadFailurePage=0;invalidateProposal();el('upload').disabled=true;uploadInput.disabled=true;uploadDrop.setAttribute('aria-disabled','true');
 const results=[],failures=[],pending=[],root=el('upload-results');const {note:notice,list}=uploadResultList(root);
 const entries=files.map(f=>{const entry=document.createElement('li');uploadRow(entry,f.name,'접수 중');list.append(entry);return entry});
 let received;
 try{
  if(files.length>100||files.reduce((sum,f)=>sum+f.size,0)>99*1024*1024)throw Error('한 번에 100개, 총 99MB 이하로 나누어 올려 주세요.');
  notice.textContent=files.length+'개 파일 전송 중 · 접수 완료 안내가 나올 때까지 이 페이지를 유지해 주세요.';uploadLabel.textContent='파일 접수 중';
  const body=new FormData();for(const file of files)body.append('files',file);
  received=await call('/api/imports/upload-batch',body);
  if(!Array.isArray(received.files)||received.files.length!==files.length)throw Error('접수 결과를 확인하지 못했습니다. 저장된 파일 목록을 확인해 주세요.');
  for(const job of received.files)if(job.status_url)saveUploadJob(job);
  const accepted=received.files.filter(job=>job.status_url).length;
  notice.textContent=accepted+'개 파일 접수 완료 · 다른 페이지로 이동해도 처리는 계속됩니다. 이 화면으로 돌아오면 진행 상태를 이어서 확인합니다.';
  if(generation===batchGeneration)el('status').textContent=notice.textContent;
  uploadInput.value='';renderUploadSelection();
 }catch(error){notice.textContent=error.message;entries.forEach((entry,i)=>entry.textContent=files[i].name+' · 접수 결과를 확인해 주세요');if(generation===batchGeneration){el('status').textContent=error.message;renderUploadSystemError(error.message)}return;
 }finally{el('upload').disabled=false;uploadInput.disabled=false;uploadDrop.removeAttribute('aria-disabled');uploadLabel.textContent='카드 사용내역 업로드'}
 const processFile=async (job,i)=>{
   const f=files[i],entry=entries[i];
   try{
    if(!job.status_url)throw Error(job.message||'파일을 접수하지 못했습니다.');
   uploadRow(entry,f.name,'처리 중');let j=await awaitUpload(job,entry);results[i]=j;uploadRow(entry,f.name,uploadOutcome(j),'saved');
    if(j.batch_id)savedUploadLink(entry,j.batch_id);
    appendCoverageForm(entry,j);
   }catch(e){(e.savedBatch?pending:failures).push({name:f.name,message:e.message});uploadErrorRow(entry,{filename:f.name},e)}
  };
  await Promise.all(received.files.map(processFile));
  notice.textContent=results.filter(Boolean).length+'개 파일 처리 완료'+(failures.length?' · '+failures.length+'개 파일 접수 실패':'')+(pending.length?' · '+pending.length+'개 파일 상세 결과를 확인해 주세요':'');
  if(generation!==batchGeneration)return;
  if(typeof refreshCoverageSummary==='function')await refreshCoverageSummary();
  const completed=results.filter(Boolean),displayable=completed.filter(j=>!j.recovered_upload);if(displayable.length)render(displayable[displayable.length-1],true);
  const incomplete=completed.filter(j=>j.upload_summary&&!['passed','empty'].includes(j.upload_summary.status)).length;
  el('status').textContent=completed.length+'개 파일 처리 · '+failures.length+'개 파일 업로드 실패'+(pending.length?' · '+pending.length+'개 파일 접수 완료 · 상세 결과를 확인해 주세요':'')+(incomplete?' · '+incomplete+'개 파일 처리 미완료':'')+' · 파일별 결과를 확인해 주세요.';
  if(!completed.length&&failures.length)renderUploadSystemError(failures[0].message);
};
el('ruleform').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target),conditions={merchant_normalized:f.get('merchant'),transaction_direction:f.get('direction')};if(f.get('card_kind'))conditions.card_kind=f.get('card_kind');const old=rules.find(r=>r.rule_id===f.get('rule_id'));if(old?.conditions.merchant_normalized==='*')conditions.merchant_normalized='*';const draft={conditions,optional:structuredClone(old?.optional||{}),effects:{item:f.get('rule_item')},note:old?.note||''};delete draft.optional.travel_country;if(f.get('rule_country'))draft.optional.travel_country=f.get('rule_country');if(f.get('rule_description'))draft.effects.description=f.get('rule_description');if(f.get('rule_id'))draft.rule_id=f.get('rule_id');try{const j=await call('/api/imports/rules',JSON.stringify({draft,expected_revision:Number(f.get('version')),batch_id:model?.batch_id,request_id:crypto.randomUUID()}),{'Content-Type':'application/json'});if(j.rules)renderRules(j.rules);e.target.elements.rule_id.value=j.result.rule_id;e.target.elements.version.value=j.result.version;if(j.refresh_required){el('status').textContent='규칙은 저장됐지만 분류 갱신을 확인하지 못했습니다. 규칙을 다시 저장하지 말고 거래를 새로고침해 주세요.';return}try{if(model)render(await call('/api/imports/'+model.batch_id+'/auto-record','{}',{'Content-Type':'application/json'}))}catch(error){if(error.message==='소유자만 자동 반영할 수 있습니다.'){let refreshed=false;try{const updated=await call('/api/imports/'+model.batch_id);render(updated);refreshed=true}catch{}el('status').textContent=refreshed?'규칙은 저장되고 분류도 다시 계산됐습니다. 자동 장부 기록은 소유자만 할 수 있습니다.':'규칙은 저장되고 분류도 다시 계산됐지만 화면을 갱신하지 못했습니다. 자동 장부 기록은 소유자만 할 수 있습니다. 새로고침해서 확인해 주세요.';return}el('status').textContent='규칙은 저장됐습니다. 자동 기록 결과를 확인하지 못했습니다: '+error.message+' 규칙을 다시 저장하지 말고 최신 거래를 확인해 주세요.';return}el('status').textContent='규칙을 저장했습니다.'}catch(e){el('status').textContent=e.message}};
el('rulefilter').oninput=()=>renderRules(rules);el('newrule').onclick=()=>{el('ruleform').reset();el('ruleform').elements.merchant.readOnly=false;el('rule_scope').textContent=''};
if(location.hash==='#newupload'){var _up=document.getElementById('newupload');if(_up)_up.open=true;}
function focusReservationCard(transaction){const root=el('ota-review');if(!root)return;root.scrollIntoView({block:'start'});root.focusObserver?.disconnect();let scrolled=false;const mark=()=>{const radio=[...root.querySelectorAll('input[type=radio]')].find(r=>r.value===transaction);if(radio){radio.closest('label').style.outline='2px solid var(--c-accent-solid)';if(!scrolled){radio.closest('label').scrollIntoView({block:'center'});radio.focus({preventScroll:true});scrolled=true;root.focusObserver?.disconnect()}}};root.focusObserver=new MutationObserver(mark);root.focusObserver.observe(root,{childList:true,subtree:true});mark();}
async function loadBatch(id){const generation=++batchGeneration;invalidateProposal();try{const response=await fetch('/api/imports/'+encodeURIComponent(id));const j=await response.json();if(!response.ok)throw Error(j.message||'거래 자료를 불러오지 못했습니다');if(generation===batchGeneration){render(j,true);const focus=new URLSearchParams(location.search).get('transaction');if(focus&&j.rows.some(r=>r.transaction_id===focus)){if(location.hash==='#ota-review'){focusReservationCard(focus)}else if(location.hash==='#preview'){reviewState='all';render(j);el('preview').scrollIntoView({block:'start'})}else{editing=focus;render(j);el('edit-panel').scrollIntoView({block:'start'});el('edit-panel').querySelector('select[name=display_tab_id]')?.focus()}}}}catch(e){if(generation===batchGeneration)el('status').textContent=e.message}}const pollCard=async()=>{let wait=2000;if(model&&!document.hidden&&true&&!el('upload').disabled){const started=Date.now(),batch=model.batch_id,generation=batchGeneration,version=stamp;try{const j=await call('/api/imports/'+batch);if(generation===batchGeneration&&model.batch_id===batch&&stamp===version&&stateStamp(j)!==stamp){if(busy()){el('status').textContent='다른 기기에서 내용이 바뀌었습니다. 입력 중인 답변과 수정은 유지됩니다. 저장할 때 최신 버전을 확인합니다.'}else{render(j);el('status').textContent='다른 기기의 변경을 불러왔습니다.'}}}catch(e){if(generation===batchGeneration&&model.batch_id===batch&&stamp===version)el('status').textContent=e.message}wait=Math.max(2000,4*(Date.now()-started))}setTimeout(pollCard,wait)};setTimeout(pollCard,2000);
async function companyExclude(id,excluded,btn){const r=model.preview.rows.find(r=>r.transaction_id===id);if(!r)return;if(!confirm(excluded?'이 거래를 회사 경비 집계와 구글 복사에서 제외할까요? 원본은 유지합니다.':'회사 경비 제외를 되돌릴까요?'))return;const batch=model.batch_id,generation=batchGeneration;btn.disabled=true;try{const j=await call('/api/imports/'+batch+'/company-exclusion',mutationBody(btn,{transaction_id:id,revision:r.revision,exclusion_revision:r.exclusion_revision||0,excluded:excluded,confirmed:true,note:excluded?'회사 경비 아님':'회사 경비 제외 되돌리기'}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(j.state)render(j.state);el('rule-result')?.replaceChildren();el('status').textContent=j.refresh_required?'회사 경비 변경은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':excluded?'회사 경비에서 제외했습니다. 원본 거래는 보존했습니다.':'회사 경비 제외를 되돌렸습니다.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message;btn.disabled=false}}document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('[data-company-restore]');if(b)companyExclude(b.dataset.companyRestore,false,b)});
let proposalGeneration=0;function invalidateProposal(){proposalGeneration++;window.ruleProposal=null}
document.addEventListener('click',async e=>{const b=e.target.closest&&e.target.closest('[data-group-commit]');if(!b||!model||b.disabled)return;const batch=model.batch_id,generation=batchGeneration;b.disabled=true;try{const x=await call('/api/imports/'+batch+'/refund-groups/'+encodeURIComponent(b.dataset.groupCommit)+'/commit',mutationBody(b,{digest:b.dataset.digest}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(!x.refresh_required)render(x);el('status').textContent=x.refresh_required?'장부 기록은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':'환불 쌍을 장부에 기록했습니다.'}catch(err){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=err.message;b.disabled=false}});
function loadCardReviewBatches(){call('/api/imports').then(j=>{
 const groups=new Map();for(const b of j.batches||[]){const label=b.display_name||'식별되지 않은 카드 자료';
  if(!groups.has(label))groups.set(label,[]);groups.get(label).push(b);}
 const container=el('batches');container.replaceChildren();
 for(const [label,files] of groups){
  const group=coverageNode('div','batch-group');
  group.append(coverageNode('h3','',label+' · '+files.length+'개 파일'));
  const items=coverageNode('div','batch-list');
  for(const b of files){
   const wrap=coverageNode('p','');const button=coverageNode('button','batch-choice',
     b.display_name+' · 거래 발생기간 '+(b.period_start||'확인 불가')+' ~ '+(b.period_end||'확인 불가')+
     ' · '+b.rows+'건'+(b.questions?' · 확인 '+b.questions+'건':''));
   button.dataset.batch=b.batch_id;button.type='button';
   button.addEventListener('click',()=>loadBatch(b.batch_id));wrap.append(button);items.append(wrap);
  }group.append(items);container.append(group);
 }
 if(!groups.size)container.append(coverageNode('p','','아직 저장된 카드 자료가 없습니다.'));
 if(!(j.batches||[]).length)el('newupload').open=true;
 const requested=new URLSearchParams(location.search).get('batch');
 const initial=(j.batches||[]).some(b=>b.batch_id===requested)?requested:j.batches?.[0]?.batch_id;
 return initial&&!model&&batchGeneration===0?loadBatch(initial):null;
 }).catch(e=>el('status').textContent=e.message);}

let cardReviewStarted=false;
const cardReviewDetail=document.getElementById('card-review-detail');
function startCardReview(){
 if(cardReviewStarted)return;
 cardReviewStarted=true;
 loadCardReviewBatches();refreshCoverageSummary();
 call('/api/imports/rules').then(j=>renderRules(j.rules)).catch(e=>el('status').textContent=e.message);
}
if(!cardReviewDetail){startCardReview();}
else{
 cardReviewDetail.addEventListener('toggle',()=>{if(cardReviewDetail.open)startCardReview();});
 if(new URLSearchParams(location.search).has('batch')||['#preview','#ota-review'].includes(location.hash))cardReviewDetail.open=true;
 if(cardReviewDetail.open)startCardReview();
}
</script></body></html>'''
