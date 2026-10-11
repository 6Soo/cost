"""카드 파일부터 장부까지 이어지는 단일 사용자 흐름."""
import hashlib
import json
import os
import threading
from pathlib import Path
from urllib.parse import unquote


_OTA_MARKERS = ('TRIP.COM', '트립닷컴', 'KLOOK', '클룩', 'AGODA', '아고다', 'BOOKING', '부킹닷컴')
_OTA_REPORT_LOCK = threading.Lock()


def _is_ota_row(row):
    merchant = str(row.get('merchant') or row.get('merchant_normalized') or '').upper()
    return any(marker.upper() in merchant for marker in _OTA_MARKERS)


def _unchanged_workbook_schedule(record, current_bytes, cache):
    """원본 증거와 최신 명시 제목을 함께 검증하며 비용 셀 변경만 분리한다."""
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
        key = (record.source_sha256, hashlib.sha256(current_bytes).hexdigest())
        if key not in cache:
            for contents in (original_bytes, current_bytes):
                books.append(load_workbook(io.BytesIO(contents), read_only=True, data_only=False))
            original, current = books
            originals = {page.title:{address:page[address].value for address in ('C2', 'D2')}
                         for page in original}
            current_titles = {page.title:{value.value for row in page.iter_rows(min_row=2, max_row=2)
                              for value in row if isinstance(value.value, str) and '매출 확인자료' in value.value}
                              for page in current}
            current_cells = {page.title:{address:page[address].value for address in ('C2', 'D2')}
                             for page in current}
            cache[key] = (originals, current_titles, current_cells)
        originals, current_titles, current_cells = cache[key]
        if sheet not in originals or sheet not in current_titles:
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
        return current_cells[sheet][cell] == title and current_titles[sheet] == {title}
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

    if not row.get('user_confirmed') and hold.get('kind') != 'refund_pending':
        if row.get('classification_source') == 'inference':
            target = row.get('trip_id') or row.get('display_tab_id') or ''
            if target not in ('', 'unclassified'):
                labels.append('여행 배정 확인 권장')
            elif row.get('classification_state') == 'classified' and row.get('item'):
                labels.append('비용 항목 확인 권장')
            else:
                labels.append('분류 확인 권장')
        elif row.get('classification_state') == 'needs_review':
            labels.append('분류 확인 권장')

    return list(dict.fromkeys(labels))[:3]


def enabled():
    return os.environ.get('WEBLEDGER_CARD_FLOW') == '1'


def reclassify_pending(board):
    """장부 규칙을 미래 적용으로 켠 직후, 아직 기록하지 않은 카드 거래를 다시 분류한다.

    사용자가 확정한 거래는 분류가 건드리지 않는다."""
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
    with board._lock:
        hold_filter = ("AND NOT EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
                       if board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else '')
        rows = board.conn.execute(
            "SELECT b.batch_id,b.filename,COUNT(*),b.status,GROUP_CONCAT(DISTINCT t.issuer),"
            "MIN(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
            "MAX(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
            "SUM(CASE WHEN (t.classification_state='needs_review' OR "
            "(t.classification_source='inference' AND t.classification_basis LIKE ?)) "
            "AND t.user_confirmed=0 AND COALESCE(t.duplicate_of,'')='' "
            "AND t.classification_state!='booked' " + hold_filter + "THEN 1 ELSE 0 END) AS questions "
            "FROM import_batches b JOIN import_batch_rows x ON x.batch_id=b.batch_id "
            "JOIN transactions t ON t.transaction_id=x.transaction_id "
            "WHERE t.classification_state!='preserved' "
            "AND (?='' OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)='' "
            "OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)>=?) "
            "GROUP BY b.batch_id ORDER BY questions DESC,b.received_at DESC,b.batch_id",
            ('추론 배정 · 낮음 ·%', review_from, review_from)).fetchall()
    return [dict(batch_id=r[0], filename=r[1], rows=r[2], status=r[3], questions=r[7],
                 **batch_display_info((r[4] or '').split(','), r[5], r[6])) for r in rows]


def home_page(board):
    from . import ledger_board, ledger_design
    from app import ledger as ledger_preview
    from app.db import StoreError
    import sqlite3
    from app.reserve_trips import registrations, sync_status, today, KST
    import datetime as dt
    esc = ledger_board.esc
    review_from = os.environ.get('WEBLEDGER_REVIEW_FROM', '')
    # 여러 파일이 같은 거래를 포함해도 메인 건수는 거래 정본에서 한 번만 센다.
    with board._lock:
        hold_filter = ("AND NOT EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
                       if board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else '')
        saved, questions = board.conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(CASE WHEN (t.classification_state='needs_review' OR "
            "(t.classification_source='inference' AND t.classification_basis LIKE ?)) "
            "AND t.user_confirmed=0 AND COALESCE(t.duplicate_of,'')='' "
            "AND t.classification_state!='booked' " + hold_filter + "THEN 1 ELSE 0 END),0) "
            "FROM transactions t WHERE t.classification_state!='preserved' "
            "AND (?='' OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)='' "
            "OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)>=?)",
            ('추론 배정 · 낮음 ·%', review_from, review_from)).fetchone()
    pending_booking_ids = set()
    pending_unknown = False
    try:
        flow = CardFlow(board)
        ota_group_holds = flow.ota_group_holds()
        trips = board.list_trips()
        authority_cache = {
            trip['tab_id']: flow.trip_valid(trip['tab_id'])
            for trip in trips
        }

        def trip_validator(tab_id):
            return authority_cache.get(tab_id, False)

        def tab_validator(tab_id):
            return tab_id in ('', 'unclassified') or authority_cache.get(tab_id, False)

        for batch in batch_catalog(board):
            result = ledger_preview.preview(
                board,
                batch['batch_id'],
                trip_validator=trip_validator,
                tab_validator=tab_validator,
                review_from=review_from or None,
                additional_holds=ota_group_holds,
            )
            for entry in ledger_preview.recordable_rows(result.get('rows', [])):
                transaction_id = entry.get('transaction_id')
                if transaction_id:
                    pending_booking_ids.add(transaction_id)
    except (OSError, ValueError, KeyError, TypeError, StoreError, sqlite3.Error):
        pending_unknown = True
    pending_bookings = None if pending_unknown else len(pending_booking_ids)

    trips = board.list_trips()
    registered = registrations(board)
    upcoming = sorted((t for t in trips if t['tab_id'] in registered
                       and registered[t['tab_id']]['departure_status']=='scheduled'
                       and t['starts_on'] >= today()), key=lambda t:(t['starts_on'], t['display_key']))
    posted = len(ledger_board._expense_rows()) + len(ledger_board._income_rows())
    board_tab = upcoming[0]['tab_id'] if upcoming else ledger_board.default_board_tab()
    def short_date(value):
        parts = str(value).split('-')
        return f"{parts[1]}.{parts[2]}" if len(parts) == 3 else str(value)

    items = ''.join(
        f"<li><a class='home-trip' href='/board?tab={esc(t['tab_id'])}'>"
        f"<strong>{esc(t['display_key'])}</strong>"
        f"<span class='home-date' title='{esc(t['starts_on'])} ~ {esc(t['ends_on'])}'>"
        f"<span class='home-date-full'>{esc(t['starts_on'])} ~ {esc(t['ends_on'])}</span>"
        f"<span class='home-date-short' aria-hidden='true'>{esc(short_date(t['starts_on']))}–{esc(short_date(t['ends_on']))}</span>"
        "</span></a></li>"
        for t in upcoming[:6])
    state = sync_status(board)
    next_run = state.get('next_run_at')
    next_note = (dt.datetime.fromisoformat(next_run).astimezone(KST).strftime('%Y-%m-%d %H:%M')
                 if next_run else '')
    body = ("<style>"
            ".home-overview{padding:20px 24px 16px;border-bottom:1px solid var(--line)}"
            ".home-status{font-size:13px;color:var(--mut);margin:0 0 12px}"
            ".home-status b{color:var(--ink);font-weight:700}"
            ".page-body a.home-review{margin:0!important;background:var(--grn);border-color:var(--grn);color:#fff}"
            ".page-body a.home-review:hover{background:var(--grn-dk);border-color:var(--grn-dk);color:#fff}"
            ".home-secondary{display:none}"
            ".home-travel-section{padding:18px 24px 22px}"
            ".home-travel-heading{font-size:18px!important;margin:0 0 8px!important}"
            ".home-trips{list-style:none!important;margin:0 0 8px!important;padding:0!important;border-top:1px solid var(--line)}"
            ".home-trips li{margin:0!important}"
            ".home-trip{display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:42px;padding:8px 0;border-bottom:1px solid var(--line2);font-size:13.5px;text-decoration:none}"
            ".home-trip strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;color:var(--ink)}"
            ".home-date{flex:0 0 auto;font-size:12.5px;color:var(--mut);white-space:nowrap}"
            ".home-date-short{display:none}"
            ".home-all{font-size:13px;margin:8px 0 0!important}"
            "@media(max-width:759px){"
            ".home-main .page-hd{padding:20px 16px 6px;border-bottom:0;display:block}"
            ".home-main .page-hd h1{font-size:24px;line-height:1.2}"
            ".home-main .page-hd .synth,.home-main .page-hd .meta,.home-main .page-hd .act{display:none}"
            ".home-overview{padding:0 16px 10px;border-bottom:0}"
            ".home-status{font-size:13px;line-height:1.35;margin:0 0 12px;white-space:normal}"
            ".page-body .home-review{display:flex;width:100%;height:46px;margin:0 0 8px!important;justify-content:center;font-size:14px}"
            ".home-secondary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:0}"
            ".page-body .home-secondary .btn{width:100%;height:36px;margin:0;padding:0 5px;font-size:12.5px;font-weight:600;background:var(--paper);border-color:var(--line-strong);color:var(--ink)}"
            ".home-travel-section{padding:12px 16px 18px}"
            ".home-travel-heading{font-size:19px!important;line-height:1.25;margin:0 0 6px!important}"
            ".home-trip{min-height:48px;padding:0;font-size:14px}"
            ".home-date{font-size:12.5px}"
            ".home-date-full{display:none}"
            ".home-date-short{display:inline}"
            ".home-all{margin:7px 0 0!important;font-size:12.5px}"
            ".home-next-note{display:none}"
            "}"
            "</style>"
            "<section class='home-overview' aria-label='장부 상태와 주요 작업'>"
            f"<p class='home-status'>카드 <b>{saved:,}</b> · 확인 필요 <b>{questions:,}</b> · 장부 반영 대기 <b>{'-' if pending_bookings is None else f'{pending_bookings:,}'}</b> · 장부 <b>{posted:,}</b></p>"
            f"<a class='home-review btn primary' href='/import'>카드 검토 {questions:,}건</a>"
            "<nav class='home-secondary' aria-label='장부 보조 작업'>"
            "<a class='btn' href='/import'>새 카드 가져오기</a>"
            "<a class='btn' href='/export'>XLSX 출력</a>"
            f"<a class='btn' href='/board?tab={esc(board_tab)}'>장부</a>"
            "</nav></section>"
            + ledger_design.work_menu_html()
            + f"<section class='home-travel-section'><h2 class='home-travel-heading'>출발 예정 여행 {len(upcoming)}</h2>"
            + (f"<ul class='home-trips'>{items}</ul>"
               if items else "<p>등록된 출발 예정 여행이 없습니다.</p>")
            + "<p class='home-all'><a href='/trips'>전체 여행 보기</a></p>"
            + (f"<p class='muted home-next-note'>여행글은 한국 시간 매일 0시에 조회합니다. 다음 조회: {next_note}</p>" if next_note else '')
            + "</section>")
    return ledger_design.render(ledger_design.shell(
        '장부 현황', tab_id='', heading='장부 현황', body=body, home=True))


class CardFlow:
    def __init__(self, board):
        from app import Pipeline
        self.board = board
        self._ota_group_holds_cache = None
        with board._lock:
            pipeline=getattr(board,'_card_pipeline',None)
            if pipeline is None or pipeline.store.conn is not board.conn:
                pipeline=Pipeline(board.conn)
                pipeline.store.lock=board._lock
                board._card_pipeline=pipeline
            self.pipeline=pipeline

    def trip_valid(self, trip_id):
        """화면용 여행 탭과 원본으로 검증한 명시 일정이 일치해야 한다."""
        from ledger.domain.direct_trip_schedule_authority import load_document
        from . import real_review
        path = os.environ.get('WEBLEDGER_TRIP_AUTHORITY')
        service = real_review.active_service()
        if not path or service is None:
            return False
        trip = self.board.get_trip(trip_id)
        if not trip or trip['deleted'] or trip['archived']:
            return False
        records, _ = load_document(Path(path))
        matches = [r for r in records if r.trip_code == trip['display_key']]
        if len(matches)!=1:
            return False
        record=matches[0]
        locator=record.source_locator.partition('#')[0]
        if record.trip_code=='5월_유럽' or Path(locator).name.startswith(('reserve-', 'owner-schedule-')):
            source=Path(record.source_locator.partition('#')[0])
            evidence=Path(os.environ.get('WEBLEDGER_EVIDENCE_ROOT','D:/WebLedgerHost/data/evidence'))
            if not source.resolve().is_relative_to(evidence.resolve()):
                return False
            try:
                raw=source.read_bytes()
                digest=hashlib.sha256(raw).hexdigest()
                if source.name.startswith('owner-schedule-'):
                    snapshot=json.loads(raw)
                    expected=record.as_dict()
                    expected.pop('source_locator')
                    expected.pop('source_sha256')
                    if snapshot.get('schema_version')!='owner-trip-schedule-v1' or snapshot.get('schedule')!=expected:
                        return False
                if source.name.startswith('reserve-'):
                    from app.reserve_trips import validate_record, SCHEMA
                    snapshot=json.loads(raw)
                    validate_record(snapshot['record'])
                    if (snapshot['schema_version']!=SCHEMA or snapshot['registered_trip_code']!=record.trip_code
                            or snapshot['record']['starts_on']!=record.starts_on.isoformat()
                            or snapshot['record']['ends_on']!=record.ends_on.isoformat()
                            or snapshot['record']['departure_status']!='scheduled'):
                        return False
            except (OSError, ValueError, KeyError, TypeError):
                return False
        else:
            source=Path(service.manifest['snapshot_path'])
            current_bytes=source.read_bytes()
            digest=hashlib.sha256(current_bytes).hexdigest()
            if digest!=service.manifest['snapshot_sha256']:
                return False
            if digest!=record.source_sha256:
                if not hasattr(self,'_schedule_title_cache'):
                    self._schedule_title_cache={}
                if not _unchanged_workbook_schedule(record,current_bytes,self._schedule_title_cache):
                    return False
                digest=record.source_sha256
        return len(matches) == 1 and all((
            matches[0].is_authoritative,
            matches[0].source_sha256 == digest == trip['source_sha256'],
            matches[0].starts_on.isoformat() == trip['starts_on'],
            matches[0].ends_on.isoformat() == trip['ends_on'],
            matches[0].event_year == trip['event_year'],
        ))

    def tab_valid(self, tab):
        return tab in ('', 'unclassified') or self.trip_valid(tab)

    def retail_trip(self, transaction, country):
        from app.rules import merchant_country
        if isinstance(country,dict):
            if 'inferred_trip_id' in country:
                target=country['inferred_trip_id']
                return target if self.trip_valid(target) else ''
            return self.booking_trip(transaction,country)
        if merchant_country(transaction) != country or not transaction.get('approval_date'):
            return ''
        if not hasattr(self, '_retail_trips'):
            # 명시된 일정의 지역만 사용한다. 새 지역은 자동으로 국가를 만들어 붙이지 않는다.
            countries = {'KR':{'부산','의왕','금오도','호남','군산','화순'}, 'TW':{'대만'},'MN':{'몽골'},
                         'JP':{'에히메','교토','나가센도','아오모리','오사카','알펜루트','북해도',
                               '레분토&리시리','묘코','묘코고원','아키타','오제','야마가타','세토우치',
                               '야마구치','북큐슈','도고','가루이자와','야쿠시마','도쿄','노리쿠라','다테시나','도쿠시마'}}
            self._retail_trips = []
            for trip in self.board.list_trips():
                location = trip['destination']
                known_country = next((code for code,regions in countries.items() if location in regions), '')
                if self.trip_valid(trip['tab_id']):
                    if location=='유럽':
                        self._retail_trips.extend((code,trip) for code in ('AT','IT','FR'))
                    elif known_country:
                        self._retail_trips.append((known_country,trip))
        occurred = transaction['approval_date']
        candidates = [trip for code,trip in self._retail_trips if code == country
                      and trip['starts_on'] <= occurred <= trip['ends_on']]
        if not candidates:
            return ''
        candidates.sort(key=lambda t:(t['starts_on']==occurred,t['starts_on'],t['ends_on']),reverse=True)
        top = candidates[0]
        if len(candidates)>1 and (top['starts_on'],top['ends_on']) == (candidates[1]['starts_on'],candidates[1]['ends_on']):
            return ''
        return top['tab_id']

    def booking_trip(self, transaction, period):
        candidates = [t for t in self.board.list_trips() if self.trip_valid(t['tab_id'])
                      and t['display_key']==period['target_code']
                      and t['starts_on']<=period['starts_on']<=period['ends_on']<=t['ends_on']]
        return candidates[0]['tab_id'] if len(candidates)==1 else ''

    def classify(self, batch_id, *, transaction_ids=None):
        with self.board._lock:
            return self._classify(batch_id,transaction_ids=transaction_ids)

    def _classify(self, batch_id, *, transaction_ids=None):
        ota_rules=[]
        blocked_inference_sources=set()
        selected=None if transaction_ids is None else set(transaction_ids)
        sources={source for source,identity,merchant in self.board.conn.execute(
            'SELECT t.source_hash,t.transaction_id,t.merchant FROM transactions t '
            'JOIN import_batch_rows b ON b.transaction_id=t.transaction_id '
            'WHERE b.batch_id=? AND t.user_confirmed=0 AND t.classification_state!=? '
            'AND t.conflict_reason=? AND t.parse_error=?',(batch_id,'preserved','',''))
            if (selected is None or identity in selected) and _is_ota_row({'merchant':merchant})}
        from app import StoreError, ota_sources
        import sqlite3
        try:
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
                if period and fact.get('reservation_status')!='cancelled' and not fact.get('period_conflict'):
                    if verified_trips is None:
                        verified_trips=[trip for trip in self.board.list_trips() if self.trip_valid(trip['tab_id'])]
                    candidates=[trip for trip in verified_trips
                                if trip['starts_on']<=period['starts_on']<=period['ends_on']<=trip['ends_on']]
                    digests=fact.get('source_digests') or fact.get('evidence_digests') or [fact.get('source_sha256')]
                    if len(candidates)==1 and digests and digests[0]:
                        draft['optional']['booking_period']=dict(period,target_code=candidates[0]['display_key'],source_sha256=digests[0])
                    else:
                        # 명시 이용기간과 맞지 않는 과거 추론 여행을 다시 붙이지 않는다.
                        blocked_inference_sources.add(source)
                draft['origin']='ota-portal-live' if fact.get('evidence_kind')=='portal_payment_claim' else 'ota-mail-live'
                draft['rule_id']=('ota-portal-' if draft['origin']=='ota-portal-live' else 'ota-mail-')+source
                ota_rules.append(draft)
        ota_rules += self._guide_airfare_rules(batch_id, selected)
        board_rules = self._board_future_rules()
        if ota_rules or blocked_inference_sources or board_rules:
            from app.classify import classify_batch
            active=[rule for rule in self.pipeline.list_rules() if not
                    (rule.get('optional',{}).get('inferred_assignment')
                     and rule['optional'].get('source_hash') in blocked_inference_sources)]
            active, board_rules = self._board_rules_supersede(active, board_rules)
            return classify_batch(self.pipeline.store,batch_id,
                rules=active+board_rules+ota_rules,trip_resolver=self.retail_trip,
                review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),transaction_ids=selected)
        return self.pipeline.classify_batch(batch_id, trip_resolver=self.retail_trip,
                                           review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),transaction_ids=selected)

    def _board_future_rules(self):
        """장부에서 확정해 '미래 적용'으로 켠 규칙을 카드 분류 규칙으로 옮긴다.

        가맹점 조건만 가진 규칙만 옮기고(카드 구분·방향 조건이나 제외 조건이 있으면 건너뛴다),
        여행 배정은 규칙의 연도 범위로 제한한다. 사용자가 확정한 답변은 분류가 덮지 않는다."""
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
        current, fresh = ota_payment_review.snapshot_service(self.board).held()
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
            'WHERE b.batch_id=? AND t.user_confirmed=0 AND t.classification_state!=? '
            'AND t.conflict_reason=? AND t.parse_error=? AND t.transaction_direction=?',
            (batch_id, 'preserved', '', '', 'purchase')).fetchall()
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
                origin='guide-airfare-live', rule_id='guide-airfare-' + source_hash))
        return rules

    def preview_metadata(self):
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
                    report = self._ota_report()
                except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,ota_sources.OtaSourcesError):
                    report = {'ota_source_errors':[{'error':'source_read_failed'}]}
                loaded = True
            return ledger_metadata(report, entry)

        return metadata

    def project(self, entry):
        """새 전기와 기존 장부 화면의 행을 같은 트랜잭션에서 저장한다."""
        from app.db import StoreError
        trip = entry.get('trip_id') or ''
        tab = entry.get('display_tab_id') or ''
        if not self.tab_valid(tab) or (trip and not self.trip_valid(trip)):
            raise StoreError('TRIP_AUTHORITY_CHANGED', '여행 일정 근거를 다시 확인해 주세요')
        if trip and tab != trip:
            raise StoreError('TRIP_TARGET_CONFLICT', '여행과 장부 탭이 다릅니다')
        row_id = 'card-' + entry['transaction_id']
        board_tab = None if tab in ('','unclassified') else tab
        conn = self.board.conn
        if conn.execute('SELECT 1 FROM board_rows WHERE row_id=?', (row_id,)).fetchone():
            raise StoreError('BOARD_ROW_CONFLICT', '이미 존재하는 장부 행입니다')
        source = conn.execute('SELECT issuer,card_tail,approval_number,posting_date,'
                              'foreign_amount,foreign_currency,transaction_kind,approval_date FROM transactions '
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
                      event_kind=source[6], classification_state='confirmed',
                      confirmed_by='owner', memo='')
        if entry.get('ota_evidence'):
            record['classification_basis'] = 'OTA 예약 메타데이터 근거 · ' + json.dumps(
                entry['ota_evidence'], ensure_ascii=False, sort_keys=True)
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                     (row_id, 'expense', board_tab, 1, payload))
        conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,'
                     'change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                     (row_id,1,'{}',payload,'','exception','owner',entry['now'],row_id))

    def _already_projected(self, source, entry):
        """같은 거래를 두 번 기록하지 않으면서 실제 여러 건은 함께 남긴다.

        카드 행이 스스로 가진 거래 ID를 정본으로 삼는다. 같은 승인번호라도 거래 ID가 다른
        결제와 취소는 서로 다른 거래이므로 합치지 않는다. 거래 ID가 없는 과거 장부 행에만
        발급사·카드·승인번호·일자·부호 있는 금액·거래 종류가 모두 같은 좁은 조건을 적용한다.
        원문 해시만으로는 구분하지 않는다. 해시에 행 위치가 들어가지 않아 정당한 여러 건이
        같은 해시를 공유하기 때문이다.
        """
        conn = self.board.conn
        if conn.execute("SELECT 1 FROM board_rows WHERE json_extract(payload_json,'$.source_event_id')=? "
                        "LIMIT 1", (entry['transaction_id'],)).fetchone():
            return True
        if not source[2]:
            # 승인번호가 없으면 거래 ID가 유일한 정본이다. 좁은 조건을 쓸 근거가 없다.
            return False
        row = conn.execute(
            "SELECT 1 FROM board_rows WHERE COALESCE(json_extract(payload_json,'$.source_event_id'),'')='' "
            "AND json_extract(payload_json,'$.source_issuer')=? "
            "AND json_extract(payload_json,'$.source_card_last4')=? "
            "AND json_extract(payload_json,'$.source_approval_number')=? "
            "AND json_extract(payload_json,'$.occurred_on')=? "
            "AND json_extract(payload_json,'$.amount_krw')=? "
            "AND COALESCE(json_extract(payload_json,'$.event_kind'),'')=? LIMIT 1",
            (source[0], source[1], source[2], entry['occurred_on'],
             entry['amount_krw'], source[6] or '')).fetchone()
        return bool(row)

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
        memo = getattr(self, '_request_report', None)
        if memo is None:
            return self._compute_ota_report()
        if not memo:
            memo.append(self._compute_ota_report())
        return memo[0]

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
                 'duplicate_of','parse_error','conflict_reason')
        with self.board._lock:
            rows=[tuple(row) for row in self.board.conn.execute(
                'SELECT '+','.join(columns)+' FROM transactions ORDER BY transaction_id').fetchall()]
        fingerprint=hashlib.sha256(json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        # manifest 자체와 추가 소스의 추가·삭제·변경이 모두 지문에 들어간다.
        key = (str([str(path) for path in mail_dirs]),
               str([str(path) for path in portal_dbs]),
               str([str(path) for path in sources['reference_documents']]),
               sources['manifest_stamp'], stamps, fingerprint)
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

    def saved_state(self, batch_id, *, classify=False):
        """Only call after the write committed; refresh failure cannot undo that write."""
        try:
            if classify:
                self.classify(batch_id)
            return self.state(batch_id)
        except Exception:
            return {'saved': True, 'refresh_required': True}

    def state(self, batch_id):
        self._request_report = []
        try:
            return self._state(batch_id)
        finally:
            self._request_report = None

    def _state(self, batch_id):
        result = self.pipeline.get_batch(batch_id)
        approval_batch = result['summary'].get('status') == 'approval_evidence'
        review_from = os.environ.get('WEBLEDGER_REVIEW_FROM','')
        result['rows'] = [r for r in result['rows'] if r['classification_state'] != 'preserved'
                          and (not review_from or not (r['approval_date'] or r['posting_date'])
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
                                                  entry_metadata=self.preview_metadata(),
                                                  additional_holds=self.ota_group_holds())
        result['trips'] = [dict(id=t['tab_id'],name=t['display_key'],available=available[t['tab_id']]) for t in trips]
        result['refund_groups'] = self.refund_group_views(result['preview'], result['trips'])
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
            "WHERE classification_source='guide_airfare_evidence' AND user_confirmed=0").fetchall()
        if not rows:
            return {}
        from . import guide_airfare_review, ota_payment_review
        allowed, code = guide_airfare_review.write_authorization(self.board)
        supported = {}
        if allowed:
            current, fresh = (ota_payment_review.snapshot_service(self.board).held()
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
            current, fresh = ota_payment_review.snapshot_service(self.board).held()
            results = current["results"] if current is not None else []
            holds = {}
            for result in results:
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
            if current is None or ota_payment_review.authority():
                # Unresolved means HOLD. With no reconciled snapshot nothing is settled; with a stale one only
                # the held links (manual and exact) stay settled, so no new automatic link can be booked.
                if current is None:
                    settled = set()
                elif fresh:
                    settled = {str(r.get("transaction_id")) for r in results
                               if r.get("transaction_id") and r.get("status") in ("MATCHED_AUTO", "MATCHED_USER")}
                else:
                    settled = {str(transaction_id) for transaction_id in current["links"].values() if transaction_id}
                for card in backend._transactions():
                    identity = str(card.get("transaction_id") or "")
                    if identity and identity not in settled and identity not in holds and _is_ota_row(card):
                        holds[identity] = {"kind":"ota_authority_unresolved",
                                           "reason":"OTA-first 연결이 확정되지 않은 OTA 카드 거래라 기록하지 않아요",
                                           "ota_event_ids":[]}
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
    if not enabled() or not ((parsed.path == '/' and raw is None) or parsed.path == '/import' or parsed.path == '/api/imports'
                            or parsed.path.startswith('/api/imports/')):
        return False
    from .ledger_board import _active_store
    from app import StoreError, ParseError
    from app import ota_sources
    board = _active_store()
    if board is None:
        handler._send_json({'code':'STORE_UNBOUND','message':'장부를 열 수 없습니다'}, 503)
        return True
    try:
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
                    handler._send_json(google_tsv_adapter.tsv_for_tab(flow.state(parts[2])['preview']['rows'], tab))
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
        if parsed.path == '/api/imports':
            received = flow.pipeline.receive(raw, unquote(handler.headers.get('X-Filename') or 'card.xlsx'))
            flow.classify(received['batch_id'])
            result = flow.state(received['batch_id'])
            if ota_payment_review.enabled():
                try:
                    backend = ota_payment_review.backend_for_request(board, handler, read_only=False)
                    refresh = getattr(backend, 'refresh_after_import', None)
                    if refresh:
                        transaction_ids = [str(row.get('transaction_id') or '')
                                           for row in result.get('rows', []) if row.get('transaction_id')]
                        refresh(transaction_ids)
                    result['ota_refresh_status'] = 'refreshed'
                except Exception:
                    result['ota_refresh_status'] = 'unavailable'
                finally:
                    closer = getattr(locals().get('backend'), 'close', None)
                    if closer:
                        closer()
            handler._send_json(result)
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
        if len(parts) == 4 and parts[3] == 'decision':
            row = board.conn.execute('SELECT 1 FROM import_batch_rows WHERE transaction_id=? AND batch_id=?',
                                     (payload['transaction_id'], batch_id)).fetchone()
            if not row:
                raise StoreError('NOT_FOUND', '이 파일에 없는 거래입니다')
            tab = str(payload.get('display_tab_id') or '')
            if not flow.tab_valid(tab):
                raise StoreError('TRIP_AUTHORITY_REQUIRED', '원본 일정이 확인된 여행을 선택해 주세요')
            flow.pipeline.save_decision(payload['transaction_id'], payload['revision'],
                item=payload['item'], description=payload.get('description',''), display_tab_id=tab,
                trip_id=tab if tab not in ('','unclassified') else '', trip_validator=flow.trip_valid,
                tab_validator=flow.tab_valid,
                note=payload.get('note',''), reuse_rule=bool(payload.get('reuse_rule')),
                resolve_hold=payload.get('resolve_hold') is True,
                request_id=payload['request_id'])
            handler._send_json(flow.saved_state(batch_id, classify=True))
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


def page(csrf):
    return PAGE.replace('__CSRF__', json.dumps(csrf))


PAGE = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>카드 내역 검토</title><style>
@font-face{font-family:"Pretendard Variable";src:url("/assets/fonts/PretendardVariable.woff2") format("woff2-variations"),url("/assets/fonts/PretendardVariable.woff2") format("woff2");font-weight:100 900;font-style:normal;font-display:swap}
*{box-sizing:border-box}body{margin:0;padding:16px;font:400 14px/1.5 "Pretendard Variable","Pretendard",system-ui,-apple-system,"Segoe UI",Roboto,"Malgun Gothic",sans-serif;background:#F7F8F7;color:#202521}main{max-width:900px;margin:auto;min-width:0}
article,section{background:#FFFFFF;border:1px solid #E3E7E3;border-radius:4px;padding:16px;margin:12px 0;min-width:0}input,select,textarea{font:inherit;max-width:100%;min-width:0;padding:0 8px;border:1px solid #E3E7E3;border-radius:4px;background:#FFFFFF}input:not([type=checkbox]),select{height:34px}input:not([type=checkbox]),select,textarea{width:100%;margin:6px 0}textarea{height:auto;min-height:64px;padding:8px}button{font:inherit;max-width:100%;padding:0 12px;min-height:34px;border:1px solid #E3E7E3;border-radius:4px;background:#FFFFFF;color:#202521;font-weight:600;cursor:pointer}button:disabled{opacity:.5}form[data-index] button,#commit,#upload,#ruleform button:not([type=button]){background:#1C7A52;border-color:#1C7A52;color:#fff}h1{font-size:20px}h2{font-size:16px}.small{font-size:13px;color:#657068}.amount{font-size:17px;font-weight:700}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.hidden{display:none}table{width:100%;table-layout:fixed;border-collapse:collapse}h1,h2,button,p,span,td,th,summary{overflow-wrap:anywhere;word-break:keep-all;min-width:0}td button{padding:0 8px;min-height:34px}td,th{padding:7px 10px;text-align:left;border-bottom:1px solid #EEF1EE;overflow-wrap:anywhere}a{color:#166444}.pv-label{display:none}
.review-item{background:#FFFFFF;border:1px solid #E3E7E3;border-radius:4px;margin:0 0 8px;min-width:0}.review-item summary{min-height:44px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 12px;font-size:14px;font-weight:600;cursor:pointer}.review-item summary .ri-date{font-size:13px;color:#657068;font-weight:400;white-space:nowrap}.review-item summary h2{font-size:14px;font-weight:600;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.review-item summary .amount{font-size:14px;margin-left:auto;white-space:nowrap}.ri-flag{font-size:12px;font-weight:600;color:#8A5A12;max-width:100%;white-space:normal}.ri-body{padding:4px 12px 12px;min-width:0}
#holds:empty{display:none}#batches{display:grid;gap:8px}#batches p{margin:0;min-width:0}.batch-choice{width:100%;min-height:48px;text-align:left;line-height:1.5;font-size:14px}.batch-choice span{font-size:13px;color:#657068}summary{cursor:pointer;padding:10px 0;min-height:44px;display:flex;align-items:center}details{min-width:0}nav{font-size:14px}
.flow{margin:12px 0;font-size:13px;color:#657068;border:1px solid #E3E7E3;border-radius:4px;background:#FFFFFF;padding:8px 12px}
@media(max-width:550px){.grid{grid-template-columns:1fr}body{padding:10px}main{min-width:0}article,section{padding:14px;margin:10px 0}h1{font-size:19px}input:not([type=checkbox]),select,textarea{font-size:16px;min-height:44px}input:not([type=checkbox]),select{height:44px}button{min-height:44px;font-size:14px}td button,form[data-index] button,[data-edit],#commit,#upload{width:100%;min-height:44px}.batch-choice{min-height:56px}#preview table,#preview tbody,#preview tr,#preview td{display:block;width:100%}#preview thead{display:none}#preview tr{border:1px solid #E3E7E3;border-radius:4px;padding:10px 12px;margin:0 0 10px;min-width:0}#preview td{border-bottom:0;padding:5px 0;min-width:0}.pv-label{display:block;font-size:12px;color:#657068}.review-item summary{min-height:48px;font-size:14px}.ri-flag{flex-basis:100%}}
</style><body><main><nav><a href="/">홈</a> · <a href="/board">장부</a> · <a href="/trips">여행 관리</a></nav><h1>카드 내역 검토</h1>
<p class="flow">카드 자료 → 확인할 거래 → 미리보기 → 장부 기록</p>
<section><h2>저장된 카드 자료</h2><p class="small">확인할 거래가 많은 자료부터 표시합니다. 자료를 선택하면 저장된 분류 결과를 이어서 볼 수 있습니다.</p><div id="batches"></div></section>
<details id="newupload"><summary>새 카드 파일 추가</summary><section><p class="small">카드사에서 받은 XLS·XLSX 또는 CSV 파일을 올려 주세요. 기존 거래와 중복되는 내역은 다시 기록하지 않습니다.</p><input id="file" type="file" accept=".xls,.xlsx,.csv"><button id="upload">업로드하고 분류</button></section></details>
<details id="rules"><summary>분류 규칙 수정</summary><section><p class="small">가맹점이 정확히 일치할 때 비용 항목을 적용합니다. 여행은 가맹점만으로 자동 배정하지 않습니다.</p><form id="ruleform"><input name="rule_id" type="hidden"><input name="version" type="hidden" value="0"><label>가맹점<input name="merchant" required></label><label>카드 종류<input name="card_kind" placeholder="국내 또는 해외 · 비우면 모든 종류"></label><label>거래 구분<select name="direction"><option value="purchase">사용</option><option value="cancellation">취소·환불</option></select></label><label>여행 중 사용 조건<select name="rule_country"><option value="">여행 조건 없음</option><option value="local">사용 국가와 해당 여행이 일치할 때</option><option value="AT">오스트리아 현지 사용 · 유럽 여행 일치</option><option value="IT">이탈리아 현지 사용 · 유럽 여행 일치</option><option value="FR">프랑스 현지 사용 · 유럽 여행 일치</option><option value="JP">일본 현지 사용 · 명시 여행 일치</option><option value="KR">국내 사용 · 국내 여행 일치</option><option value="TW">대만 현지 사용 · 명시 여행 일치</option></select></label><p id="rule_scope" class="small"></p><label>비용 항목<input name="rule_item" required></label><label>내용<input name="rule_description"></label><button>규칙 저장하고 다시 분류</button><button type="button" id="newrule">새 규칙 작성</button></form><label>저장된 규칙 찾기<input id="rulefilter" type="search" placeholder="가맹점 또는 비용 항목"></label><div id="rulelist"></div></section></details>
<p id="status" role="status"></p><section id="summary" class="hidden"></section><section id="holds"></section><div id="questions"></div><section id="preview" class="hidden"></section><section id="rule-panel"><h2>자연어 지시로 분류 제안</h2><p class="small">예: 이 가맹점은 앞으로 현지잡비로 분류해 줘. 제안만 만들고, 승인하면 기존 답변 저장 경로로 적용합니다. 사용자가 확정한 거래는 바뀌지 않습니다.</p><label>대상 거래 <select id="rule-focus"></select></label><textarea id="rule-text" rows="2" style="width:100%"></textarea><p><button type="button" id="rule-propose">제안 보기</button></p><div id="rule-result" role="status"></div></section>
</main><script>
const csrf=__CSRF__;let model,stamp='',page=0,editing='',batchGeneration=0,googleCopyPending=false;const PAGE_SIZE=20;const el=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// 자동갱신이 입력 중인 내용을 덮지 않게 하는 조건. 폼에 focus가 있거나 규칙 편집 중이면 그대로 둔다.
const busy=()=>!!document.activeElement?.closest('form')||el('rules').open;
const stateStamp=j=>JSON.stringify([j.batch_id,j.preview.digest,j.rows.map(r=>[r.transaction_id,r.revision,r.classification_state,r.item,r.user_confirmed,r.review_evidence_labels]),j.trips.map(t=>[t.id,t.available])]);
function mutationBody(target,payload){const basis=JSON.stringify(payload);if(target.pendingMutation?.basis!==basis)target.pendingMutation={basis,id:crypto.randomUUID()};return JSON.stringify({...payload,request_id:target.pendingMutation.id})}
const money=n=>n==null?'금액 확인 필요':Number(n).toLocaleString('ko-KR')+'원';
const evidence=r=>(r.review_evidence_labels||[]).slice(0,3).join(' · ');
// 질문과 자동분류 수정창이 함께 쓰는 답변 폼. 기존 저장 경로(form[data-index])를 그대로 쓴다.
function answerForm(j,r){const hold=r.review_hold?'<p>'+esc(r.review_hold.reason)+'</p><label><input type="checkbox" name="resolve_hold"> 자료 확인을 마쳤으며 보류를 해제하고 이 금액을 기록합니다</label>':'';return '<form data-index="'+j.rows.indexOf(r)+'">'+hold+'<div class="grid"><label>비용 항목<input name="item" value="'+esc(r.item)+'" required></label><label>여행 또는 미배정<select name="display_tab_id"><option value="unclassified">여행 미배정</option>'+j.trips.filter(t=>t.available).map(t=>'<option value="'+esc(t.id)+'"'+(t.id===r.display_tab_id?' selected':'')+'>'+esc(t.name)+'</option>').join('')+'</select></label></div><label>내용<input name="description" value="'+esc(r.description)+'"></label><label>내 답변·수정 이유<textarea name="note" rows="2">'+esc(r.note||'')+'</textarea></label><p><label><input type="checkbox" name="reuse_rule"> 같은 가맹점·카드 종류·거래 구분에 이 비용 항목을 다시 적용</label></p><button '+(r.conflict_reason||r.parse_error?'disabled':'')+'>답변 저장하고 다시 분류</button></form>'}
let rules=[];
function renderRules(list){rules=list;const term=el('rulefilter').value.toLowerCase(),matches=list.filter(r=>(r.conditions.merchant_normalized+' '+r.effects.item).toLowerCase().includes(term));el('rulelist').innerHTML='<p class="small">'+matches.length+'개 규칙 중 '+Math.min(40,matches.length)+'개 표시 · 검색으로 찾을 수 있습니다.</p>'+matches.slice(0,40).map(r=>'<p><button data-rule="'+rules.indexOf(r)+'">'+esc(r.conditions.merchant_normalized==='*'?'여행 중 현지경비 기본값':r.conditions.merchant_normalized)+' → '+esc(r.effects.item)+' · 수정</button></p>').join('');document.querySelectorAll('[data-rule]').forEach(b=>b.onclick=()=>{const r=rules[Number(b.dataset.rule)],f=el('ruleform');f.elements.rule_id.value=r.rule_id;f.elements.version.value=r.version;f.elements.merchant.value=r.conditions.merchant_normalized==='*'?'여행 중 현지경비 기본값':r.conditions.merchant_normalized;f.elements.merchant.readOnly=r.conditions.merchant_normalized==='*';f.elements.card_kind.value=r.conditions.card_kind||'';f.elements.direction.value=r.conditions.transaction_direction||'purchase';f.elements.rule_country.value=r.optional.travel_country||'';f.elements.rule_item.value=r.effects.item||'';f.elements.rule_description.value=r.effects.description||'';f.elements.rule_country.disabled=!!r.optional.inferred_assignment;el('rule_scope').textContent=r.origin==='owner-country-exception-20261003'?'사용자 지정 예외: 조지아·카자흐스탄 거래를 유럽 여행에 배정합니다.':r.optional.inferred_assignment?'이번 거래에만 적용한 추론입니다. 여행은 미리보기의 수정에서 바꿀 수 있습니다.':r.optional.source_hash?'예약 자료로 확인된 해당 원본 거래에만 적용합니다.':r.note||''})}
async function call(url,body,headers={}){const r=await fetch(url,body==null?{cache:'no-store'}:{method:'POST',headers:{'X-CSRF-Token':csrf,...headers},body}).catch(()=>{throw Error('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')});if(!(r.headers.get('Content-Type')||'').includes('application/json'))throw Error(r.status===401?'로그인이 필요합니다. 화면을 다시 열어 주세요.':'서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.');const j=await r.json();if(!r.ok)throw Error(j.message||j.code);return j}
function render(j,switchBatch=false){if(model&&model.batch_id!==j.batch_id&&!switchBatch)return;if(model&&model.batch_id===j.batch_id){const older=(rows,previous,field)=>{const versions=new Map(previous.map(r=>[r.transaction_id,Number(r[field]||0)]));return rows.some(r=>Number(r[field]||0)<(versions.get(r.transaction_id)||0))};if(older(j.rows,model.rows,'revision')||older(j.preview.rows,model.preview.rows,'exclusion_revision'))return;}if(model&&stateStamp(j)!==stamp)invalidateProposal();if(model?.batch_id!==j.batch_id){page=0;editing=''}model=j;fillFocus();stamp=stateStamp(j);const counts=j.summary.counts;el('summary').className='';const approval=j.summary.channel==='approval',approvalInfo=j.approval_summary||{},states=approvalInfo.states||{};el('summary').innerHTML='<h2>'+esc(j.summary.display_name||'카드 사용내역')+'</h2><p class="small">'+esc(j.summary.period_start||'거래 기간 미확인')+(j.summary.period_end?' ~ '+esc(j.summary.period_end):'')+'</p><p>'+(approval?'승인 증거 '+(approvalInfo.source_rows??j.summary.row_count)+'행 · 1:1 연결 '+(states.linked||0)+'건 · 묶음 연결 '+((states.group_linked||0)+(states.group_partial||0))+'건 · 추가 확인 '+((states.ambiguous||0)+(states.approval_only||0)+(approvalInfo.conflict_rows||0))+'건 · 비용 행 생성 0건':'이번 자료 '+j.summary.row_count+'건 · 자동분류 '+(counts.classified||0)+'건 · 확인 필요 '+(counts.needs_review||0)+'건 · 답변 확정 '+(counts.confirmed||0)+'건')+'</p><details><summary>원본 파일 정보</summary><p>'+esc(j.summary.filename)+'</p></details>';
const held=j.rows.filter(r=>r.review_hold);const holdNames={cancelled:'취소·환불 관리',refund_pending:'환불 확인 대기',user_hold:'사용자 보류',evidence_pending:'예약·결제 확인 대기'};el('holds').innerHTML=held.length?'<details><summary>취소·환불과 보류 '+held.length+'건 · 일반 비용 기록에서 제외</summary>'+held.map(r=>'<article><strong>'+esc(holdNames[r.review_hold.kind])+'</strong><p>'+esc(r.merchant)+' · '+money(r.amount_krw)+'</p>'+(evidence(r)?'<p class="small">'+esc(evidence(r))+'</p>':'')+'<p>'+esc(r.review_hold.reason)+'</p><button type="button" data-edit="'+esc(r.transaction_id)+'">확인 후 수정</button></article>').join('')+'</details>':'';
const asked=j.rows.filter(r=>!r.review_hold&&(r.classification_state==='needs_review'||(r.classification_source==='inference'&&r.classification_basis.startsWith('추론 배정 · 낮음 ·')))&&!r.user_confirmed&&!r.duplicate_of);const pages=Math.max(1,Math.ceil(asked.length/PAGE_SIZE));if(page>=pages)page=pages-1;const slice=asked.slice(page*PAGE_SIZE,page*PAGE_SIZE+PAGE_SIZE);const ed=editing?j.rows.find(r=>r.transaction_id===editing&&!r.duplicate_of):null;
el('questions').innerHTML=(ed?'<article><h2>수정 · '+esc(ed.merchant)+'</h2><p class="small">지금 확정된 항목과 여행을 고쳐 쓰면 됩니다.</p>'+answerForm(j,ed)+'</article>':'')+slice.map((r,i)=>'<details class="review-item"'+(i===0?' open':'')+'><summary><span class="ri-date">'+esc(r.approval_date||r.posting_date)+(r.approval_date?'':' (매입일)')+'</span><h2>'+esc(r.merchant)+'</h2><span class="amount">'+money(r.amount_krw)+'</span>'+(evidence(r)?'<span class="ri-flag">'+esc(evidence(r))+'</span>':'')+'</summary><div class="ri-body"><p class="small">'+esc(r.conflict_reason||r.parse_error||r.classification_basis)+'</p>'+answerForm(j,r)+'</div></details>').join('')+(pages>1?'<nav><p class="small">확인하거나 수정할 '+asked.length+'건을 '+PAGE_SIZE+'건씩 봅니다 · '+(page+1)+'/'+pages+'페이지</p><button type="button" id="prevpage"'+(page?'':' disabled')+'>이전 20건</button> <button type="button" id="nextpage"'+(page+1<pages?'':' disabled')+'>다음 20건</button></nav>':'');
const groups=(j.refund_groups||[]).map(g=>g.error?'<p class=small>환불 쌍 확인 필요: '+esc(g.message)+'</p>':'<div class="refund-group"><h2>환불 쌍</h2><p>원결제 '+money(g.gross_krw)+' · 환불 '+money(g.refund_krw)+' · 순액 '+money(g.net_krw)+'</p><p>항목 '+esc(g.item)+' · 여행 '+esc(g.trip_name||'미배정')+'</p><button type="button" data-group-commit="'+esc(g.original_id)+'" data-digest="'+esc(g.digest)+'" '+(g.recordable&&g.rows.some(r=>!r.already_booked)?'':'disabled')+'>이 환불 쌍 '+g.rows.length+'건만 장부에 기록</button>'+(g.recordable?'':'<p class=small>'+esc(g.reason)+'</p>')+'</div>').join('');const p=j.preview,ready=p.rows.filter(r=>!r.blocked&&!r.already_booked);el('preview').className='';el('preview').innerHTML=groups+p.rows.filter(r=>r.excluded_from_company).map(r=>'<p>회사 경비 제외: '+esc(r.merchant)+' · '+money(r.amount_krw)+' <button type="button" data-company-restore="'+esc(r.transaction_id)+'">회사 경비 제외 되돌리기</button></p>').join('')+'<h2>장부 미리보기</h2><p>기록 가능 '+ready.length+'건 · 나머지는 보류됩니다. 잘못 분류된 항목은 수정해 고칠 수 있습니다.</p><table><thead><tr><th>가맹점</th><th>항목</th><th>금액</th><th>여행</th><th>수정</th></tr></thead><tbody>'+ready.map(r=>'<tr><td><span class="pv-label">가맹점</span>'+esc(r.merchant)+'</td><td><span class="pv-label">항목</span>'+esc(r.item)+((r.booking_ref||r.service_period)?'<br><span class=small>OTA 예약 근거 · '+esc([r.booking_ref,r.service_period].filter(Boolean).join(' · '))+'</span>':'')+(['inference','user_exception','guide_airfare_evidence'].includes(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source)?'<br><span class=small>'+esc({user_exception:'사용자 예외',guide_airfare_evidence:'대장 항공권 근거'}[j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source]||'추론 배정')+'</span>':'')+'</td><td><span class="pv-label">금액</span>'+money(r.amount_krw)+'</td><td><span class="pv-label">여행</span>'+esc(j.trips.find(t=>t.id===r.display_tab_id)?.name||'여행 미배정')+(['inference','user_exception','guide_airfare_evidence'].includes(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source)?'<details><summary>배정 근거</summary>'+esc(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_basis)+'</details>':'')+'</td><td><button type="button" data-edit="'+esc(r.transaction_id)+'">수정</button>'+(r.excluded_from_company?'<button type="button" data-company-restore="'+esc(r.transaction_id)+'">회사 경비 제외 되돌리기</button>':'')+'</td></tr>').join('')+'</tbody></table><p><button id="commit" '+(!ready.length?'disabled':'')+'>미리본 '+ready.length+'건을 장부에 기록</button></p>'+[...new Set(p.rows.filter(r=>!r.blocked).map(r=>r.display_tab_id).filter(Boolean))].map(t=>'<p><button type="button" data-google-copy="'+esc(t)+'">'+esc(j.trips.find(x=>x.id===t)?.name||'여행')+' 구글 지출 7열 복사</button></p>').join('');
el('commit').onclick=async event=>{const button=event.currentTarget,batch=model.batch_id,generation=batchGeneration;if(button.disabled)return;button.disabled=true;try{const x=await call('/api/imports/'+batch+'/commit',mutationBody(button,{digest:model.preview.digest}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(!x.refresh_required)render(x);el('status').textContent=x.refresh_required?'장부 기록은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':'장부 기록 결과를 저장했습니다. 장부 화면에서 확인할 수 있습니다.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message}finally{button.disabled=false}};
document.querySelectorAll('form[data-index]').forEach(f=>f.onsubmit=async e=>{e.preventDefault();const r=model.rows[Number(f.dataset.index)],v=new FormData(f),batch=model.batch_id,generation=batchGeneration,button=f.querySelector('button');if(button.disabled)return;button.disabled=true;try{const j=await call('/api/imports/'+model.batch_id+'/decision',mutationBody(f,{transaction_id:r.transaction_id,revision:r.revision,item:v.get('item'),description:v.get('description'),display_tab_id:v.get('display_tab_id'),note:v.get('note'),reuse_rule:v.has('reuse_rule'),resolve_hold:v.has('resolve_hold')}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(editing===r.transaction_id)editing='';if(!j.refresh_required)render(j);el('status').textContent=j.refresh_required?'답변은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':'답변을 적용했습니다. 다시 분류한 결과를 확인해 주세요.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message}finally{button.disabled=false}})
document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{editing=b.dataset.edit;render(model);el('questions').scrollIntoView({block:'start',behavior:'smooth'});el('status').textContent='선택한 거래의 답변을 고쳐 쓸 수 있습니다.'});
if(el('prevpage'))el('prevpage').onclick=()=>{page=Math.max(0,page-1);render(model)};
if(el('nextpage'))el('nextpage').onclick=()=>{page=page+1;render(model)};}
el('upload').onclick=async()=>{const f=el('file').files[0];if(!f)return;const generation=++batchGeneration;invalidateProposal();el('upload').disabled=true;el('status').textContent='파일을 읽고 분류하고 있습니다.';try{const j=await call('/api/imports',await f.arrayBuffer(),{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(f.name)});if(generation!==batchGeneration)return;render(j,true);el('status').textContent='분류가 끝났습니다.'}catch(e){if(generation===batchGeneration)el('status').textContent=e.message}finally{el('upload').disabled=false}};
el('ruleform').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target),conditions={merchant_normalized:f.get('merchant'),transaction_direction:f.get('direction')};if(f.get('card_kind'))conditions.card_kind=f.get('card_kind');const old=rules.find(r=>r.rule_id===f.get('rule_id'));if(old?.conditions.merchant_normalized==='*')conditions.merchant_normalized='*';const draft={conditions,optional:structuredClone(old?.optional||{}),effects:{item:f.get('rule_item')},note:old?.note||''};delete draft.optional.travel_country;if(f.get('rule_country'))draft.optional.travel_country=f.get('rule_country');if(f.get('rule_description'))draft.effects.description=f.get('rule_description');if(f.get('rule_id'))draft.rule_id=f.get('rule_id');try{const j=await call('/api/imports/rules',JSON.stringify({draft,expected_revision:Number(f.get('version')),batch_id:model?.batch_id,request_id:crypto.randomUUID()}),{'Content-Type':'application/json'});if(j.rules)renderRules(j.rules);e.target.elements.rule_id.value=j.result.rule_id;e.target.elements.version.value=j.result.version;if(j.refresh_required){el('status').textContent='규칙은 저장됐습니다. 분류 결과를 불러오지 못했으니 규칙 저장을 다시 시도해 주세요.';return}try{if(model)render(await call('/api/imports/'+model.batch_id))}catch{el('status').textContent='규칙은 저장됐습니다. 분류 결과를 불러오지 못했으니 규칙 저장을 다시 시도해 주세요.';return}el('status').textContent='규칙을 저장하고 분류에 적용했습니다. 이미 확정한 답변은 유지됩니다.'}catch(e){el('status').textContent=e.message}};
el('rulefilter').oninput=()=>renderRules(rules);el('newrule').onclick=()=>{el('ruleform').reset();el('ruleform').elements.merchant.readOnly=false;el('rule_scope').textContent=''};
call('/api/imports/rules').then(j=>renderRules(j.rules)).catch(e=>el('status').textContent=e.message);
async function loadBatch(id){const generation=++batchGeneration;invalidateProposal();try{const j=await call('/api/imports/'+id);if(generation===batchGeneration)render(j,true)}catch(e){if(generation===batchGeneration)el('status').textContent=e.message}}const pollCard=async()=>{let wait=2000;if(model&&!document.hidden&&!el('upload').disabled){const started=Date.now(),batch=model.batch_id,generation=batchGeneration,version=stamp;try{const j=await call('/api/imports/'+batch);if(generation===batchGeneration&&model.batch_id===batch&&stamp===version&&stateStamp(j)!==stamp){if(busy()){el('status').textContent='다른 기기에서 내용이 바뀌었습니다. 입력 중인 답변과 수정은 유지됩니다. 저장할 때 최신 버전을 확인합니다.'}else{render(j);el('status').textContent='다른 기기의 변경을 불러왔습니다.'}}}catch(e){if(generation===batchGeneration&&model.batch_id===batch&&stamp===version)el('status').textContent=e.message}wait=Math.max(2000,4*(Date.now()-started))}setTimeout(pollCard,wait)};setTimeout(pollCard,2000);
async function companyExclude(id,excluded,btn){const r=model.preview.rows.find(r=>r.transaction_id===id);if(!r)return;if(!confirm(excluded?'이 거래를 회사 경비 집계와 구글 복사에서 제외할까요? 원본은 유지합니다.':'회사 경비 제외를 되돌릴까요?'))return;const batch=model.batch_id,generation=batchGeneration;btn.disabled=true;try{const j=await call('/api/imports/'+batch+'/company-exclusion',mutationBody(btn,{transaction_id:id,revision:r.revision,exclusion_revision:r.exclusion_revision||0,excluded:excluded,confirmed:true,note:excluded?'회사 경비 아님':'회사 경비 제외 되돌리기'}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(j.state)render(j.state);el('rule-result').innerHTML='';el('status').textContent=j.refresh_required?'회사 경비 변경은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':excluded?'회사 경비에서 제외했습니다. 원본 거래는 보존했습니다.':'회사 경비 제외를 되돌렸습니다.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message;btn.disabled=false}}document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('[data-company-restore]');if(b)companyExclude(b.dataset.companyRestore,false,b)});
let proposalGeneration=0;function invalidateProposal(){proposalGeneration++;window.ruleProposal=null;el('rule-result').innerHTML=''}el('rule-focus').onchange=invalidateProposal;el('rule-text').oninput=invalidateProposal;const fillFocus=()=>{if(!model||el('rule-focus').dataset.focusBatch===model.batch_id)return;el('rule-focus').dataset.focusBatch=model.batch_id;el('rule-focus').innerHTML=model.preview.rows.map(r=>'<option value="'+esc(r.transaction_id)+'">'+esc(r.merchant)+' · '+money(r.amount_krw)+(r.blocked?' (보류)':'')+'</option>').join('')};el('rule-propose').onclick=async()=>{if(!model){el('status').textContent='거래 자료를 먼저 불러오세요';return}fillFocus();const text=el('rule-text').value.trim();const tx=el('rule-focus').value;if(!text||!tx){el('status').textContent='지시와 대상 거래를 입력하세요';return}const batch=model.batch_id,generation=++proposalGeneration;window.ruleProposal=null;el('rule-result').innerHTML='';try{const p=await call('/api/imports/'+batch+'/rule-proposal',JSON.stringify({text:text,transaction_id:tx,request_id:crypto.randomUUID()}),{'Content-Type':'application/json'});if(generation!==proposalGeneration||model.batch_id!==batch||el('rule-focus').value!==tx||el('rule-text').value.trim()!==text){el('status').textContent='현재 선택이 바뀌었습니다. 다시 제안하세요.';return}window.ruleProposal={...p,batch_id:batch};const lines=p.changes.map(c=>'<li>'+esc(c.before_item||'(없음)')+' → '+esc(c.after_item||'회사 경비 제외')+'</li>').join('');const note=p.status!=='proposed'?'이 지시는 해석하지 못했거나 원본 값 변경을 요청했습니다. 아무 것도 바꾸지 않습니다.':p.needs_confirmation?'원본 거래를 보존하고 회사 경비 집계와 복사에서만 제외합니다. 별도 확인이 필요합니다.':'확정된 거래 '+p.skipped_confirmed+'건은 바꾸지 않습니다. 아래 '+p.payloads.length+'건만 바뀝니다.';el('rule-result').innerHTML='<p>'+note+'</p><ul>'+lines+'</ul>'+(p.needs_confirmation&&p.changes.length?'<button type="button" id="company-exclude">회사 경비 제외 확인</button>':p.payloads.length?'<button type="button" id="rule-approve">승인하고 적용</button>':'');const ap=el('rule-approve');if(ap)ap.onclick=ruleApprove;const ce=el('company-exclude');if(ce)ce.onclick=()=>companyExclude(p.transaction_id,true,ce)}catch(e){if(generation===proposalGeneration&&model.batch_id===batch)el('status').textContent=e.message}};async function ruleApprove(){const p=window.ruleProposal;if(!p||p.batch_id!==model.batch_id||p.transaction_id!==el('rule-focus').value||p.text!==el('rule-text').value.trim()){invalidateProposal();return}const btn=el('rule-approve'),batch=p.batch_id,generation=batchGeneration;if(btn)btn.disabled=true;try{const j=await call('/api/imports/'+batch+'/rule-proposal/approve',JSON.stringify({text:p.text,transaction_id:p.transaction_id,digest:p.digest,approved:true,request_id:(p.request_id??=crypto.randomUUID())}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(j.state)render(j.state);el('status').textContent=j.refresh_required?'승인은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':j.applied.length+'건을 한 번에 적용했습니다. 실패하면 한 건도 바뀌지 않습니다.';el('rule-result').innerHTML=''}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message;if(btn)btn.disabled=false}}document.addEventListener('click',async e=>{const b=e.target.closest&&e.target.closest('[data-google-copy]');if(!b||!model||googleCopyPending)return;const key='gcopy-trip:'+b.dataset.googleCopy;let before=null;try{before=localStorage.getItem(key)}catch{if(!confirm('복사 이력을 읽을 수 없습니다. 이미 Google에 붙여넣었는지 확인해 주세요. 중복 붙여넣기에 주의하고 계속 복사할까요?'))return;}if(before&&!confirm('이 여행은 '+before+'에 이미 구글 시트용으로 복사했습니다. 시트에 이미 붙여넣었다면 다시 붙여넣지 마세요. 그래도 복사할까요?'))return;googleCopyPending=true;document.querySelectorAll('[data-google-copy]').forEach(button=>button.disabled=true);const batch=model.batch_id,version=stamp,generation=batchGeneration;try{const x=await call('/api/imports/'+batch+'/google-tsv?tab='+encodeURIComponent(b.dataset.googleCopy));if(model.batch_id!==batch||stamp!==version||batchGeneration!==generation)throw Error('자료가 바뀌었습니다. 현재 자료에서 다시 복사해 주세요.');if(!x.row_count){el('status').textContent='복사할 행이 없습니다. 보류 '+x.held.length+'건은 시트에 넣지 않습니다.';return}await navigator.clipboard.writeText(x.tsv);let historyWarning='';try{localStorage.setItem(key,new Date().toLocaleString('ko-KR'))}catch{historyWarning=' 복사 이력을 저장하지 못했습니다. 중복 붙여넣기에 주의해 주세요.'}el('status').textContent='구글 지출 '+x.row_count+'행, 합계 '+money(x.total_krw)+'을 클립보드에 복사했습니다. 보류 '+x.held.length+'건은 복사하지 않았습니다. 이 복사는 장부를 바꾸지 않습니다. 구글 시트에 붙여넣은 뒤에만 반영됩니다.'+historyWarning}catch(err){el('status').textContent=err.message}finally{googleCopyPending=false;document.querySelectorAll('[data-google-copy]').forEach(button=>button.disabled=false)}});
document.addEventListener('click',async e=>{const b=e.target.closest&&e.target.closest('[data-group-commit]');if(!b||!model||b.disabled)return;const batch=model.batch_id,generation=batchGeneration;b.disabled=true;try{const x=await call('/api/imports/'+batch+'/refund-groups/'+encodeURIComponent(b.dataset.groupCommit)+'/commit',mutationBody(b,{digest:b.dataset.digest}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(!x.refresh_required)render(x);el('status').textContent=x.refresh_required?'장부 기록은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':'환불 쌍을 장부에 기록했습니다.'}catch(err){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=err.message;b.disabled=false}});
call('/api/imports').then(j=>{el('batches').innerHTML=j.batches.map(b=>'<p><button class="batch-choice" data-batch="'+esc(b.batch_id)+'"><strong>'+esc(b.display_name)+'</strong><br><span>'+esc(b.period_start||'거래 기간 미확인')+(b.period_end?' ~ '+esc(b.period_end):'')+' · '+b.rows+'건'+(b.questions?' · 확인 '+b.questions+'건':'')+'</span></button></p>').join('')||'<p>저장된 카드 자료가 없습니다. 아래에서 새 파일을 추가하세요.</p>';document.querySelectorAll('[data-batch]').forEach(b=>b.onclick=()=>loadBatch(b.dataset.batch).catch(e=>el('status').textContent=e.message));if(!j.batches.length)el('newupload').open=true;return j.batches.length&&!model&&batchGeneration===0?loadBatch(j.batches[0].batch_id):null}).catch(e=>el('status').textContent=e.message);
</script></body></html>'''
