"""카드 파일부터 장부까지 이어지는 단일 사용자 흐름."""
import hashlib
import json
import os
import threading
from pathlib import Path
from urllib.parse import unquote

from app.db import decided_sql
from app.reconciliation import (GUIDE_AIRFARE_ORIGIN, OTA_MAIL_ORIGIN, OTA_PORTAL_ORIGIN, OWNER_COUNTRY_EXCEPTION_ORIGIN,
                                   handover_days, overlaps_stay, stay_trip)

from . import read_scope


_OTA_MARKERS = ('TRIP.COM', '트립닷컴', 'KLOOK', '클룩', 'AGODA', '아고다', 'BOOKING', '부킹닷컴')
_OTA_REPORT_LOCK = threading.Lock()
_AUTHORITY_CACHE = {}
_GOOGLE_PERIOD_CACHE = {}
# 시트에 종료일이 적히지 않은 탭. 다음 여행 직전일로 정한 종료일(사용자 확정 규칙, reconciliation.open_trip_end)은
# 여행 기간으로 검증에 그대로 쓴다. 다만 옮긴 시트의 해시 확인된 원본 제목에 종료일이 적혀 있으면 그쪽이 앞선다.
_GUESSED_PERIOD_FLAGS = frozenset({'PERIOD_END_FROM_NEXT_TRIP', 'PERIOD_END_MISSING'})


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
    return any(marker.upper() in merchant for marker in _OTA_MARKERS)


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
        'snapshot_managed': '예약 근거는 아래 OTA 검토에서 확인해 주세요',
        'payment_date_unknown': '결제일 근거 없음 · 날짜 확인 필요',
        'card_identity': '카드 끝자리나 카드사가 맞지 않음 · 확인 필요',
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

    if not row.get('decided') and hold.get('kind') != 'refund_pending':
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
    with board._lock:
        hold_filter = ("AND NOT EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
                       if board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else '')
        rows = board.conn.execute(
            "SELECT b.batch_id,b.filename,COUNT(*),b.status,GROUP_CONCAT(DISTINCT t.issuer),"
            "MIN(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
            "MAX(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
            "SUM(CASE WHEN (t.classification_state='needs_review' OR "
            "(t.classification_source='inference' AND t.classification_basis LIKE ?)) "
            "AND NOT " + decided_sql('t') + " AND COALESCE(t.duplicate_of,'')='' "
            "AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id) " + hold_filter + "THEN 1 ELSE 0 END) AS questions "
            "FROM import_batches b JOIN import_batch_rows x ON x.batch_id=b.batch_id "
            "JOIN transactions t ON t.transaction_id=x.transaction_id "
            "WHERE t.classification_state!='preserved' "
            "AND (?='' OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)='' "
            "OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)>=?) "
            "GROUP BY b.batch_id ORDER BY questions DESC,b.received_at DESC,b.batch_id",
            ('추론 배정 · 낮음 ·%', review_from, review_from)).fetchall()
    return [dict(batch_id=r[0], filename=r[1], rows=r[2], status=r[3], questions=r[7],
                 **batch_display_info((r[4] or '').split(','), r[5], r[6])) for r in rows]


@read_scope.scoped
def home_page(board):
    from . import ledger_board, ledger_design, ui_icons
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
            "AND NOT " + decided_sql('t') + " AND COALESCE(t.duplicate_of,'')='' "
            "AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id) " + hold_filter + "THEN 1 ELSE 0 END),0) "
            "FROM transactions t WHERE t.classification_state!='preserved' "
            "AND (?='' OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)='' "
            "OR COALESCE(NULLIF(t.approval_date,''),t.posting_date)>=?)",
            ('추론 배정 · 낮음 ·%', review_from, review_from)).fetchone()
    cleanup = cleanup_total(board)

    trips = board.list_trips()
    registered = registrations(board)
    upcoming = sorted((t for t in trips if t['tab_id'] in registered
                       and registered[t['tab_id']]['departure_status']=='scheduled'
                       and t['starts_on'] >= today()), key=lambda t:(t['starts_on'], t['display_key']))
    # A manually created trip is still a usable ledger entry point even when
    # no reservation feed has registered its departure. Do not call it scheduled.
    listed_trips = upcoming or sorted(
        (t for t in trips if not t.get('deleted') and not t.get('archived')),
        key=lambda t:(t['starts_on'], t['display_key']))
    trip_heading = '출발 예정 여행' if upcoming else '등록된 여행'
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
        for t in listed_trips[:6])
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
            ".home-main .work-action{min-height:44px;padding:8px}"
            ".home-main .work-action small{display:none}"
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
            f"<p class='home-status'>카드 <b>{saved:,}</b> · 정리할 지출 <b>{cleanup:,}</b> · 장부 <b>{posted:,}</b></p>"
            f"<a class='home-review btn primary' href='/import'>{ui_icons.icon('check')}지출 정리 {cleanup:,}건</a>"
            "<nav class='home-secondary' aria-label='장부 보조 작업'>"
            f"<a class='btn' href='/import#newupload'>{ui_icons.icon('upload')}새 카드 가져오기</a>"
            f"<a class='btn' href='/board?tab={esc(board_tab)}'>{ui_icons.icon('book-open')}장부</a>"
            "</nav></section>"
            + ledger_design.work_menu_html()
            + f"<section class='home-travel-section'><h2 class='home-travel-heading'>{trip_heading} {len(listed_trips)}</h2>"
            + (f"<ul class='home-trips'>{items}</ul>"
               if items else "<p>등록된 여행이 없습니다. 전체 여행 보기에서 여행을 추가해 주세요.</p>")
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
        """화면용 여행 탭의 기간이 원본 일정과 일치해야 한다.

        원본은 연결된 구글 여행 탭의 시트 기간이다. 구글 기간과 맞지 않으면 기존 일정 권한 파일로 확인한다."""
        from ledger.domain.direct_trip_schedule_authority import load_document
        from . import real_review
        trip = self.board.get_trip(trip_id)
        if not trip or trip['deleted'] or trip['archived']:
            return False
        google = _google_periods().get(trip_id, set())
        if trip['ends_on'] and any((start, end) == (trip['starts_on'], trip['ends_on']) for start, end, _ in google):
            return True
        path = os.environ.get('WEBLEDGER_TRIP_AUTHORITY')
        if not path:
            return False
        records, _ = _trip_authority(Path(path))
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
            service = real_review.active_service()
            if service is None:
                return False
            source=Path(service.manifest['snapshot_path'])
            current_bytes=source.read_bytes()
            digest=hashlib.sha256(current_bytes).hexdigest()
            if digest!=service.manifest['snapshot_sha256']:
                return False
            if digest!=record.source_sha256:
                if not hasattr(self,'_schedule_title_cache'):
                    self._schedule_title_cache={}
                # 장부를 옮기며 제목이 빈 구글 탭은 해시로 확인한 원본 제목을 쓴다. 구글에 명시된 다른 기간이 있으면 쓰지 않는다.
                moved = (google and all(guessed for _, _, guessed in google)
                         and any(start == record.starts_on.isoformat() for start, _, _ in google))
                if not (_unchanged_workbook_schedule(record,current_bytes,self._schedule_title_cache)
                        or (moved and _unchanged_workbook_schedule(record,None,self._schedule_title_cache))):
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
        from app import quarter_tab
        from app.ledger import REFUND_TAB
        return tab in ('', 'unclassified', REFUND_TAB) or bool(quarter_tab.parse_tab(tab)) or self.trip_valid(tab)

    def retail_trip(self, transaction, country):
        from app.rules import merchant_country
        if isinstance(country,dict):
            if country.get('owner_card3820_singapore'):
                candidates = [t for t in self.board.list_trips()
                              if t['destination'] == '싱가포르'
                              and (t['starts_on'], t['ends_on']) == ('2026-09-19', '2026-09-24')
                              and self.trip_valid(t['tab_id'])]
                return candidates[0]['tab_id'] if len(candidates) == 1 else ''
            if 'inferred_trip_id' in country:
                target=country['inferred_trip_id']
                if not self.trip_valid(target):
                    return ''
                return target
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
        # 한 여행이 끝나고 다음 여행이 시작하는 날이면 수입-비용 차액이 큰 여행으로 보낸다.
        handover = len(candidates)>1 and all(occurred in (t['starts_on'], t['ends_on']) for t in candidates)
        nets = _google_nets() if handover else {}
        candidates.sort(key=lambda t:(nets.get(t['tab_id'], float('-inf')),t['starts_on']==occurred,t['starts_on'],t['ends_on']),reverse=True)
        top = candidates[0]
        if len(candidates)>1 and (nets.get(top['tab_id']), top['starts_on'],top['ends_on']) == (
                nets.get(candidates[1]['tab_id']), candidates[1]['starts_on'],candidates[1]['ends_on']):
            return ''
        return top['tab_id']

    def booking_trip(self, transaction, period):
        # 이용기간에 맞는 검증된 여행이다. 저장된 여행 이름이 그 기간과 겹치는 여행이면 그 여행을 쓴다.
        verified = [t for t in self.board.list_trips() if self.trip_valid(t['tab_id'])]
        service = period.get('service', False)
        handover = handover_days(verified)
        named = [t for t in verified if t['display_key']==period.get('target_code')
                 and overlaps_stay(t['starts_on'], t['ends_on'], period['starts_on'], period['ends_on'], service=service,
                                   handover=handover)]
        if len(named)==1:
            return named[0]['tab_id']
        chosen = stay_trip(verified, period['starts_on'], period['ends_on'], service=service, nets=_google_nets())
        return chosen['tab_id'] if chosen else ''

    def classify(self, batch_id, *, transaction_ids=None):
        with self.board._lock:
            result = self._classify(batch_id,transaction_ids=transaction_ids)
            # 분류와 기록은 한 동작이다. 분류 가능한 거래는 같은 자리에서 장부에 기록한다.
            self._auto_record_locked(batch_id)
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

    def _classify(self, batch_id, *, transaction_ids=None):
        ota_rules=[]
        blocked_inference_sources=set()
        selected=None if transaction_ids is None else set(transaction_ids)
        sources={source for source,identity,merchant in self.board.conn.execute(
            'SELECT t.source_hash,t.transaction_id,t.merchant FROM transactions t '
            'JOIN import_batch_rows b ON b.transaction_id=t.transaction_id '
            'WHERE b.batch_id=? AND NOT ' + decided_sql('t') + ' AND t.classification_state!=? '
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
            # 과거 장부에서 복원한 추론은 예약 메일보다 약하므로 예약 이용기간 배정을 막지 않는다.
            taken |= {rule['optional'].get('source_hash') for rule in self.pipeline.list_rules()
                      if rule.get('optional', {}).get('inferred_assignment')
                      and not str(rule.get('origin') or '').startswith('history-recovery')}
            ota_rules += self._booking_period_assignments(report, sources, taken)
        taken = {rule['optional'].get('source_hash') for rule in ota_rules}
        ota_rules += self._evidence_period_assignments(batch_id, sources, taken, selected)
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
                review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),transaction_ids=selected,residual_policy=True)
        from app.classify import classify_batch
        return classify_batch(self.pipeline.store, batch_id, trip_resolver=self.retail_trip,
                              review_from=os.environ.get('WEBLEDGER_REVIEW_FROM'),transaction_ids=selected,
                              residual_policy=True)

    def _evidence_period_assignments(self, batch_id, sources, taken, selected):
        """결제 완료 근거는 없고 예약 확정 메일만 있는 카드 거래. 금액이 같은 확정 예약이 하나뿐이고
        이용기간을 덮는 검증된 여행이 하나면 그 여행에 숙박비로 배정한다. 결제·취소 메일과 다른 예약은 쓰지 않는다."""
        from app import booking_evidence
        from app.classify import PERIOD_OTA_ORIGIN
        from app.normalize import normalize_merchant
        from . import ota_catalog
        rows = self.board.conn.execute(
            "SELECT t.transaction_id, t.source_hash, t.amount_krw, COALESCE(NULLIF(t.approval_date,''),t.posting_date), t.merchant"
            " FROM transactions t JOIN import_batch_rows b ON b.transaction_id=t.transaction_id"
            " WHERE b.batch_id=? AND t.classification_source='booking_evidence_needed' AND t.classification_state='needs_review'"
            " AND t.transaction_direction='purchase' AND t.amount_krw > 0", (batch_id,)).fetchall()
        rows = [row for row in rows if row[1] in sources and row[1] not in taken
                and (selected is None or row[0] in selected) and _is_ota_row({'merchant': row[4] or ''})]
        if not rows:
            return []
        index = booking_evidence.build_index(ota_catalog.configured_sources(self.board)['mail_directories'])
        rules = []
        for tid, source, amount, day, merchant in rows:
            found, _ = booking_evidence.find(index, amount, day)
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
                    'trip_id': trip, 'confidence': '높음',
                    'basis': f"같은 금액의 예약 확정 메일이 있고 이용기간 {starts_on}~{ends_on}이 여행 기간 안에 있음"}},
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
        for fact in report.get('matches', []):
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
            'WHERE b.batch_id=? AND NOT ' + decided_sql('t') + ' AND t.classification_state!=? '
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
                origin=GUIDE_AIRFARE_ORIGIN, rule_id='guide-airfare-' + source_hash))
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
                 'duplicate_of','parse_error','conflict_reason','issuer','approval_number')
        from app import ota_exact
        with self.board._lock:
            rows=[tuple(row) for row in self.board.conn.execute(
                'SELECT '+','.join(columns)+' FROM transactions ORDER BY transaction_id').fetchall()]
            open_ids=sorted(ota_exact.open_transaction_ids(self.board.conn))
        fingerprint=hashlib.sha256(json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        # 장부 기록 여부가 게이트 결과를 바꾸므로 열린 거래 집합도 지문에 넣는다.
        open_digest=hashlib.sha256(json.dumps(open_ids,separators=(',',':')).encode()).hexdigest()
        # manifest 자체와 추가 소스의 추가·삭제·변경이 모두 지문에 들어간다.
        key = (str([str(path) for path in mail_dirs]),
               str([str(path) for path in portal_dbs]),
               str([str(path) for path in sources['reference_documents']]),
               sources['manifest_stamp'], stamps, fingerprint, open_digest)
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
                                        open_ids=set(open_ids))
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

    def saved_state(self, batch_id, *, classify=False):
        """Only call after the write committed; refresh failure cannot undo that write."""
        try:
            if classify:
                self.classify(batch_id)
                return self.auto_record(batch_id)
            return self.state(batch_id)
        except Exception:
            return {'saved': True, 'refresh_required': True}

    def automatic_holds(self, batch_id):
        from app import quarter_costs
        holds = dict(self.ota_group_holds())
        rows = self.pipeline.get_batch(batch_id)['rows']
        for row in rows:
            tid = row['transaction_id']
            if row.get('classification_state') != 'classified':
                holds.setdefault(tid, {'kind': 'classification_needed', 'reason': '비용 항목과 배정 내용을 확인해 주세요.'})
            elif not row.get('display_tab_id') or row['display_tab_id'] == 'unclassified':
                if not quarter_costs.destination(row):
                    holds.setdefault(tid, {'kind': 'trip_needed', 'reason': '예약 이용일과 숙소를 확인하고 여행을 선택해 주세요.'})
            source = self.board.conn.execute('SELECT issuer,card_tail,approval_number,posting_date,foreign_amount,foreign_currency,transaction_kind,approval_date FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
            if self._already_projected(source, dict(row, occurred_on=row.get('approval_date') or row.get('posting_date'))):
                holds[tid] = {'kind': 'existing_ledger', 'reason': '장부에 이미 기록되어 추가로 기록하지 않습니다.'}
        from app.partial_refund import refund_links
        booked_now = {r[0] for r in self.board.conn.execute('SELECT transaction_id FROM ledger_entries')}
        for refund, link in refund_links(self.board.conn, [r['transaction_id'] for r in rows]).items():
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
        ids = {r['transaction_id'] for r in rows}
        booked = {r[0] for r in self.board.conn.execute('SELECT transaction_id FROM ledger_entries')}
        # 이미 기록된 쪽의 "기록됨" 표시는 보류가 아니다. 빠진 쪽에 실제 보류가 있을 때만 묶음을 함께 보류한다.
        blocking = {tid for tid, hold in holds.items() if hold.get('kind') != 'existing_ledger'}
        for group in groups(self.board):
            members = {r['transaction_id'] for r in group}
            if not members & ids:
                continue
            if not members <= ids or members & (blocking | set(active)):
                for tid in members & ids:
                    holds.setdefault(tid, {'kind': 'refund_group_incomplete', 'reason': '원결제와 모든 환불을 함께 확인해야 합니다.'})
        from app.partial_refund import count_held_cancellations
        for tid in count_held_cancellations(self.board.conn):
            if tid in ids and tid not in holds:
                holds[tid] = {'kind': 'refund_count_group', 'reason': '같은 조건의 구매가 있지만 짝을 정하지 못한 취소라 개수를 명세와 맞춘 뒤 기록합니다.'}
        return holds

    def auto_record(self, batch_id):
        """소유자의 변경 요청에서만 실행한다. 조회는 쓰지 않는다."""
        with self.board._lock:
            return self._auto_record_locked(batch_id)

    def _auto_record_locked(self, batch_id):
        from app import auto_record_policy, quarter_tab
        # Only batches collected after activation are recorded. Older rows keep their recorded state.
        if not auto_record_policy.batch_is_new(self.pipeline.store.conn, batch_id):
            state = self.state(batch_id)
            state['auto_recorded'] = 0
            return state
        options = dict(trip_validator=self.trip_valid, tab_validator=self.tab_valid,
                       review_from=None, entry_metadata=self.preview_metadata(),
                       additional_holds=self.automatic_holds(batch_id))
        preview = self.pipeline.preview(batch_id, **options)
        from app.ledger import recordable_rows
        applied = 0
        if recordable_rows(preview['rows']):
            result = self.pipeline.commit(batch_id, preview['digest'],
                'auto-record:' + batch_id + ':' + preview['digest'],
                projection=lambda entry: self.project(dict(entry, automatic_record=True)), automatic_record=True, **options)
            applied = result['applied']
        applied += quarter_tab.book_batch(self.pipeline.store, batch_id, projection=self.project)
        state = self.state(batch_id)
        state['auto_recorded'] = applied
        return state

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
        from .card_actions import next_action
        originals = {r['transaction_id']: r for r in result['rows']}
        guards = self.automatic_holds(batch_id)
        for row in result['preview']['rows']:
            source = dict(originals[row['transaction_id']], batch_id=batch_id)
            row['next_action'] = next_action(source, row, guards.get(row['transaction_id']))
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
                    # 예정 자동결제 연결(결정 2)은 최신 스냅샷에서만 새로 인정한다.
                    settled |= {str(transaction_id) for transaction_id in (current.get("data") or {}).get("scheduled_card_ids", ())}
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
    if not enabled() or not ((parsed.path == '/' and raw is None) or parsed.path in ('/cards', '/import', '/api/imports')
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
        if parsed.path == '/cards':
            # 카드 내역은 카드 검토의 "모든 자료" 범위로 합쳤다. 오래된 링크도 같은 화면으로 보낸다.
            if raw is not None:
                handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
            else:
                location = '/import?scope=all' + (('&' + parsed.query) if parsed.query else '')
                handler.send_response(302)
                handler.send_header('Location', location)
                handler.send_header('Content-Length', '0')
                handler.end_headers()
            return True
        flow = CardFlow(board)
        parts = parsed.path.strip('/').split('/')
        if raw is None:
            if parsed.path == '/':
                handler._send(home_page(board))
            elif parsed.path == '/import' and (query or {}).get('scope') == ['all']:
                from . import card_catalog
                handler._send(card_catalog.render_html(card_catalog.catalog(board, query or {}), query or {}, csrf=csrf))
            elif parsed.path == '/import':
                body = page(csrf)
                try:
                    cleanup_page = int(((query or {}).get('cleanup_page') or ['1'])[0])
                except (TypeError, ValueError):
                    cleanup_page = 1
                cleanup = render_expense_cleanup(board, csrf, page=cleanup_page)
                body = body.replace('<h1>지출 정리</h1>', '<h1>지출 정리</h1>' + cleanup + "<details id='card-review-detail'><summary>카드 파일 추가 · 자료별 상세 검토</summary>", 1)
                body = body.replace('</main>', '</details></main>', 1)
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
                        handler._send_json(google_tsv_adapter.tsv_for_tab(ordinary, tab))
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
            recorded = flow.auto_record(received['batch_id'])
            if 'ota_refresh_status' in result:
                recorded['ota_refresh_status'] = result['ota_refresh_status']
            handler._send_json(recorded)
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
            flow.record_decision(batch_id, payload['transaction_id'])
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
    if(!response.ok)throw Error(result.message||'저장하지 못했어요');
    item.remove();const counter=document.getElementById('cleanup-count'),left=document.querySelectorAll('.cleanup-row').length;
    const total=Math.max(0,Number(counter.dataset.total||0)-1);counter.dataset.total=String(total);counter.textContent=total+'건';
    if(!left)document.querySelector('.cleanup-list').innerHTML='<li class="muted">'+(total?'이 페이지를 정리했습니다. 다음 항목을 보려면 새로고침해 주세요.':'정리할 지출이 없습니다.')+'</li>';
  }catch(err){button.disabled=false;error.textContent=err.message}
}))})();"""

CARD_REASON = {'booking_evidence_needed': '예약 자료로 구매 상품과 이용일을 확인해 주세요',
               'travel_location_hold': '사용 국가와 명시 여행이 맞는지 확인해 주세요'}


_CLEANUP_PAGE_SIZE = 20


def _cleanup_card_where():
    return (
        " FROM transactions t JOIN import_batch_rows r ON r.transaction_id=t.transaction_id"
        " WHERE t.classification_state IN ('needs_review','classified','booked') AND COALESCE(t.duplicate_of,'')=''"
        " AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)"
        " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM board_rows b WHERE b.row_id='card-'||t.transaction_id)"
    )


def _cleanup_card_items(board, *, limit=_CLEANUP_PAGE_SIZE, offset=0):
    """장부에 아직 없는 카드 거래를 한 페이지씩 읽는다. 충돌 거래도 숨기지 않고 검토 대상으로 보여 준다."""
    return board.conn.execute(
        "SELECT t.transaction_id, MIN(r.batch_id), COALESCE(NULLIF(t.approval_date,''),t.posting_date), t.merchant,"
        " t.amount_krw, t.item, t.classification_source, t.display_tab_id, t.revision,"
        " EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id),"
        " t.conflict_reason, t.parse_error" + _cleanup_card_where() +
        " GROUP BY t.transaction_id ORDER BY 3 DESC,t.transaction_id LIMIT ? OFFSET ?", (limit, offset)).fetchall()


def _cleanup_card_count(board):
    return board.conn.execute("SELECT COUNT(DISTINCT t.transaction_id)" + _cleanup_card_where()).fetchone()[0]


def _cleanup_unassigned_where():
    return (
        " FROM board_rows b WHERE b.row_kind='expense' AND b.display_tab_id IS NULL"
        " AND NOT EXISTS(SELECT 1 FROM board_manual_overrides m"
        " WHERE m.row_id=b.row_id AND m.field='display_tab_id')"
    )


def _evidence_block(index, amount, day):
    """예약 자료 확인이 필요한 거래 옆에 같은 금액의 예약 메일 내용을 그대로 보여 준다. 배정은 하지 않는다."""
    from app import booking_evidence
    from . import ledger_board
    esc = ledger_board.esc
    found, searched = booking_evidence.find(index, amount, day)
    if not found:
        return (f"<p class='cleanup-evidence-none'>같은 금액 {abs(int(amount or 0)):,}원의 예약 메일이 없습니다."
                f" 메일 {searched:,}통을 확인했습니다.</p>")
    latest = {}
    for entry in found:
        key = tuple(entry['refs']) or (entry['subject'],)
        if key not in latest or entry['sent'] > latest[key]['sent']:
            latest[key] = entry
    entries = sorted(latest.values(), key=lambda e: e['sent'], reverse=True)
    items = ''.join('<li>' + '<br>'.join(esc(line) for line in booking_evidence.describe(entry)) + '</li>'
                    for entry in entries)
    return (f"<details class='cleanup-evidence' open><summary>같은 금액의 예약 {len(entries)}건</summary>"
            f"<ul>{items}</ul></details>")


def prewarm_booking_evidence(board):
    """서버 시작 때 예약 메일 색인을 미리 만들어, 첫 지출 정리 화면이 수 초 기다리지 않게 한다."""
    from app import booking_evidence
    from . import ota_catalog
    try:
        booking_evidence.build_index(ota_catalog.configured_sources(board)['mail_directories'])
    except Exception:
        pass  # 화면에서 다시 만들며 그때 경고를 보여 준다.


def cleanup_total(board) -> int:
    """정리할 지출 건수. 지출 정리 목록과 메인 화면이 같은 기준으로 센다."""
    unassigned = board.conn.execute("SELECT COUNT(*)" + _cleanup_unassigned_where()).fetchone()[0]
    return _cleanup_card_count(board) + unassigned


def _ota_entries_by_card(board) -> dict:
    """카드 거래 ID -> 같은 거래와 연결된 OTA 예약 (OTA 내역 화면과 같은 자료)."""
    from . import ota_catalog
    try:
        index = ota_catalog._index(board, ota_catalog.configured_sources(board), allow_stale=True)
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {card['transaction_id']: entry for entry in index.get('entries', [])
            for card in entry.get('card_matches') or []}


def ota_catalog_summary(entry) -> str:
    from . import ota_catalog
    return ota_catalog._summary(entry, bool(entry.get('rule')))


def _catalog_block(entry) -> str:
    """OTA 예약의 판단에 필요한 줄: 예약번호·상태, 이용기간, 후보 여행, 연결 카드 결제."""
    from . import ledger_board
    esc = ledger_board.esc
    relation = {'covers': '전체 포함', 'overlaps': '일부 겹침', 'none': ''}
    lines = [f"예약 {entry['booking_ref']} · {entry.get('status') or '상태 미확인'}"]
    if entry.get('period'):
        lines.append(f"이용 {entry['period']}")
    candidates = [f"{c.get('display_key') or c.get('tab_id')}({relation.get(c.get('relation'), '')})"
                  for c in entry.get('candidates') or []]
    if candidates:
        lines.append('후보 여행: ' + ', '.join(candidates))
    cancelled = entry.get('cancelled_matches') or 0
    if cancelled:
        lines.append(f'취소 결제 {cancelled}건')
    items = ''.join(f"<li>{esc(line)}</li>" for line in lines)
    return (f"<details class='cleanup-evidence' open><summary>{esc(entry.get('provider') or 'OTA')} 예약 자료</summary>"
            f"<ul>{items}</ul></details>")


def render_expense_cleanup(board, csrf, *, page=1):
    """지출 정리 맨 위의 한 목록. 카드 거래 확인(A)과 장부 미배정 지출(B)을 같은 방식으로 여행을 지정한다."""
    from . import ledger_board, ota_catalog
    if ledger_board.current_role() != 'owner':
        return ''
    esc = ledger_board.esc
    flow = CardFlow(board)
    trips = sorted((t for t in board.list_trips()
                    if not t.get('deleted') and not t.get('archived') and flow.trip_valid(t['tab_id'])),
                   key=lambda t: t.get('starts_on') or '', reverse=True)
    options = "<option value=''>여행 선택</option>" + ''.join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t.get('display_key') or t['tab_id'])}</option>" for t in trips)
    card_total = _cleanup_card_count(board)
    ledger_total = board.conn.execute("SELECT COUNT(*)" + _cleanup_unassigned_where()).fetchone()[0]
    total = card_total + ledger_total
    pages = max(1, (total + _CLEANUP_PAGE_SIZE - 1) // _CLEANUP_PAGE_SIZE)
    page = min(max(1, int(page or 1)), pages)
    offset = (page - 1) * _CLEANUP_PAGE_SIZE
    card_offset = min(offset, card_total)
    card_limit = max(0, min(_CLEANUP_PAGE_SIZE, card_total - card_offset)) if offset < card_total else 0
    rows_card = _cleanup_card_items(board, limit=card_limit, offset=card_offset) if card_limit else []
    ledger_offset = max(0, offset - card_total)
    ledger_limit = _CLEANUP_PAGE_SIZE - len(rows_card)
    items = []
    ota_by_card = _ota_entries_by_card(board)
    for tid, batch, day, merchant, amount, item, source, current_tab, revision, held, conflict_reason, parse_error in rows_card:
        detail = '/import?batch=' + str(batch) + '&transaction=' + str(tid)
        entry = ota_by_card.get(tid)
        if entry is not None:
            reason = ota_catalog_summary(entry)
            evidence = _catalog_block(entry)
        else:
            reason = CARD_REASON.get(source) or ('비용 항목을 골라 주세요' if not item else '여행을 골라 기록해 주세요')
            evidence = (
                "<p class='cleanup-evidence-none'>예약 근거를 카드 자료에서 확인해 주세요.</p>"
                if source == 'booking_evidence_needed' or _is_ota_row({'merchant': merchant}) else ''
            )
        if conflict_reason or parse_error:
            review = (f"<details class='cleanup-review'><summary>상세 검토</summary>"
                      f"<p class='cleanup-protected'>{'원본 충돌' if conflict_reason else '파싱 오류'} · "
                      f"{esc(conflict_reason or parse_error)}</p>"
                      f"<p><a href='{esc(detail)}'>카드 자료 전체 검토</a></p></details>")
        elif held:
            review = (f"<details class='cleanup-review'><summary>상세 검토</summary>{evidence}"
                      "<p class='cleanup-protected'>보류 중 · 여행 변경과 보류 해제는 카드 자료 전체 검토에서 "
                      "명시적으로 확인해 주세요.</p>"
                      f"<p><a href='{esc(detail)}'>카드 자료 전체 검토</a></p></details>")
        else:
            review = (f"<details class='cleanup-review'><summary>상세 검토</summary>{evidence}"
                      f"<p class='cleanup-review-note'>분류 근거 · {esc(reason)}</p>"
                      f"<form class='cleanup-form'><select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select>"
                      f"<input name='item' aria-label='비용 항목' value='{esc(item or '')}' placeholder='비용 항목'>"
                      "<button type='submit'>여행 수정</button><p class='cleanup-error' role='alert'></p></form></details>")
        items.append(
            f"<li class='cleanup-row' data-kind='card' data-transaction='{esc(tid)}' data-batch='{esc(batch)}'"
            f" data-revision='{int(revision)}' data-held='{1 if held else 0}' data-current-tab='{esc(current_tab or '')}'>"
            f"<div class='cleanup-info'><strong>{esc(merchant)}</strong><span class='cleanup-amount'>{int(amount or 0):,}원</span>"
            f"<small>{esc(day or '')} · {esc(reason)}</small></div>"
            f"{review}</li>")
    ledger = board.conn.execute(
        "SELECT b.row_id, b.revision, b.payload_json" + _cleanup_unassigned_where() +
        " ORDER BY json_extract(b.payload_json,'$.occurred_on') DESC LIMIT ? OFFSET ?",
        (ledger_limit, ledger_offset)).fetchall() if ledger_limit else []
    for row_id, revision, payload in ledger:
        record = json.loads(payload)
        items.append(
            f"<li class='cleanup-row' data-kind='ledger' data-row-id='{esc(row_id)}' data-revision='{int(revision)}'>"
            f"<div class='cleanup-info'><strong>{esc(record.get('source_merchant') or record.get('description') or '지출')}</strong>"
            f"<span class='cleanup-amount'>{int(record.get('amount_krw') or 0):,}원</span>"
            f"<small>{esc(record.get('occurred_on') or '')} · {esc(record.get('item') or '항목 없음')}</small></div>"
            f"<form class='cleanup-form'><select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select>"
            "<button type='submit'>여행 지정</button><p class='cleanup-error' role='alert'></p></form></li>")
    body = ''.join(items) or '<li class="muted">정리할 지출이 없습니다.</li>'
    style = ("<style>#expense-cleanup .cleanup-list{list-style:none;padding:0;margin:8px 0}"
             "#expense-cleanup .cleanup-row{border-bottom:1px solid #E3E7E3;padding:10px 0}"
             "#expense-cleanup .cleanup-info{display:flex;flex-direction:column;gap:2px;min-width:0}"
             "#expense-cleanup .cleanup-info strong{overflow-wrap:anywhere}"
             "#expense-cleanup .cleanup-amount{font-size:17px;font-weight:700}"
             "#expense-cleanup .cleanup-info small{color:#657068}"
             "#expense-cleanup .cleanup-form{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}"
             "#expense-cleanup .cleanup-form select{flex:1 1 160px;min-width:0}"
             "#expense-cleanup .cleanup-form input{flex:1 1 120px;min-width:0;height:34px}"
             "#expense-cleanup .cleanup-error{flex:0 0 100%;margin:0;color:#b42318}"
             "#expense-cleanup .cleanup-review{margin-top:8px}"
             "#expense-cleanup .cleanup-review>summary{cursor:pointer;font-weight:700}"
             "#expense-cleanup .cleanup-review-note{margin:8px 0 0;color:#657068;font-size:13px}"
             "#expense-cleanup .cleanup-protected{margin:8px 0 0;color:#657068}"
             "#expense-cleanup .cleanup-evidence{margin-top:6px;font-size:13px}"
             "#expense-cleanup .cleanup-evidence li{margin:6px 0;overflow-wrap:anywhere}"
             "#expense-cleanup .cleanup-evidence-none{font-size:13px;color:#657068;margin:6px 0 0}</style>")
    note = ("<p class='muted'>예약 근거를 다시 계산하고 있어요. 잠시 뒤 새로고침하면 최신 근거가 보입니다.</p>"
            if ota_catalog.rebuilding() else '')
    nav = ''
    if pages > 1:
        previous = (f"<a href='/import?cleanup_page={page - 1}'>이전 20건</a>" if page > 1 else '<span>이전 20건</span>')
        following = (f"<a href='/import?cleanup_page={page + 1}'>다음 20건</a>" if page < pages else '<span>다음 20건</span>')
        nav = f"<nav class='cleanup-pages'><p class='muted'>{total}건을 20건씩 봅니다 · {page}/{pages}페이지</p>{previous} · {following}</nav>"
    return (style + "<section id='expense-cleanup' aria-label='정리할 지출'>"
            f"<h2>정리할 지출 <span id='cleanup-count' data-total='{total}'>{total}건</span></h2>{note}"
            f"<template id='cleanup-trip-options'>{options}</template>"
            f"<ul class='cleanup-list'>{body}</ul>{nav}"
            f"<script>{CLEANUP_SCRIPT.replace('__CSRF__', json.dumps(csrf))}</script></section>")


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
    return document + separator + script


PAGE = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>지출 정리</title><style>
@font-face{font-family:"Pretendard Variable";src:url("/assets/fonts/PretendardVariable.woff2") format("woff2-variations"),url("/assets/fonts/PretendardVariable.woff2") format("woff2");font-weight:100 900;font-style:normal;font-display:swap}
*{box-sizing:border-box}body{margin:0;padding:16px;font:400 14px/1.5 "Pretendard Variable","Pretendard",system-ui,-apple-system,"Segoe UI",Roboto,"Malgun Gothic",sans-serif;background:#F7F8F7;color:#202521}main{max-width:900px;margin:auto;min-width:0}
article,section{background:#FFFFFF;border:1px solid #E3E7E3;border-radius:4px;padding:16px;margin:12px 0;min-width:0}input,select,textarea{font:inherit;max-width:100%;min-width:0;padding:0 8px;border:1px solid #E3E7E3;border-radius:4px;background:#FFFFFF}input:not([type=checkbox]),select{height:34px}input:not([type=checkbox]),select,textarea{width:100%;margin:6px 0}textarea{height:auto;min-height:64px;padding:8px}button{font:inherit;max-width:100%;padding:0 12px;min-height:34px;border:1px solid #E3E7E3;border-radius:4px;background:#FFFFFF;color:#202521;font-weight:600;cursor:pointer}button:disabled{opacity:.5}button .ic{width:16px;height:16px;vertical-align:-3px;pointer-events:none}button .ic:first-child{margin-right:6px}button .ic:last-child:not(:first-child){margin-left:6px}@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}form[data-index] button,#commit,#upload,#ruleform button:not([type=button]){background:#1C7A52;border-color:#1C7A52;color:#fff}h1{font-size:20px}h2{font-size:16px}.small{font-size:13px;color:#657068}.amount{font-size:17px;font-weight:700}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.hidden{display:none}table{width:100%;table-layout:fixed;border-collapse:collapse}h1,h2,button,p,span,td,th,summary{overflow-wrap:anywhere;word-break:keep-all;min-width:0}td button{padding:0 8px;min-height:34px}td,th{padding:7px 10px;text-align:left;border-bottom:1px solid #EEF1EE;overflow-wrap:anywhere}a{color:#166444}.pv-label{display:none}
.review-item{background:#FFFFFF;border:1px solid #E3E7E3;border-radius:4px;margin:0 0 8px;min-width:0}.review-item summary{min-height:44px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 12px;font-size:14px;font-weight:600;cursor:pointer}.review-item summary .ri-date{font-size:13px;color:#657068;font-weight:400;white-space:nowrap}.review-item summary h2{font-size:14px;font-weight:600;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.review-item summary .amount{font-size:14px;margin-left:auto;white-space:nowrap}.ri-flag{font-size:12px;font-weight:600;color:#8A5A12;max-width:100%;white-space:normal}.ri-body{padding:4px 12px 12px;min-width:0}
#holds:empty{display:none}#batches{display:grid;gap:8px}#batches p{margin:0;min-width:0}.batch-choice{width:100%;min-height:48px;text-align:left;line-height:1.5;font-size:14px}.batch-choice span{font-size:13px;color:#657068}summary{cursor:pointer;padding:10px 0;min-height:44px;display:flex;align-items:center}details{min-width:0}nav{font-size:14px}
.flow{margin:12px 0;font-size:13px;color:#657068;border:1px solid #E3E7E3;border-radius:4px;background:#FFFFFF;padding:8px 12px}
@media(max-width:550px){.grid{grid-template-columns:1fr}body{padding:10px}main{min-width:0}article,section{padding:14px;margin:10px 0}h1{font-size:19px}input:not([type=checkbox]),select,textarea{font-size:16px;min-height:44px}input:not([type=checkbox]),select{height:44px}button{min-height:44px;font-size:14px}td button,form[data-index] button,[data-edit],#commit,#upload{width:100%;min-height:44px}.batch-choice{min-height:56px}#preview table,#preview tbody,#preview tr,#preview td{display:block;width:100%}#preview thead{display:none}#preview tr{border:1px solid #E3E7E3;border-radius:4px;padding:10px 12px;margin:0 0 10px;min-width:0}#preview td{border-bottom:0;padding:5px 0;min-width:0}.pv-label{display:block;font-size:12px;color:#657068}.review-item summary{min-height:48px;font-size:14px}.ri-flag{flex-basis:100%}}
#review-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0}#review-metrics button{text-align:left;padding:10px;line-height:1.5}#review-metrics button[aria-pressed=true]{background:#e9f4ed;border-color:#1c7a52}#review-metrics strong{display:block;font-size:20px}.ota-icon,.review-icon .ic{width:18px;height:18px;vertical-align:-3px;margin-right:6px}.review-state{font-size:12px;color:#657068}.review-money{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}#review-controls{margin:12px 0}#review-controls label{display:block}#preview th button{padding:0;border:0;background:transparent}#review-empty{padding:20px;text-align:center;color:#657068}@media(max-width:550px){#review-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}#preview thead{display:table-header-group}#preview thead tr{display:table-row;border:0;padding:0}#preview th{display:table-cell;padding:4px;font-size:12px}#preview td.review-money{text-align:left}}
</style><body><main><nav aria-label='지출 정리 범위'><a href="/import" aria-current="page">이 자료</a> <a href="/import?scope=all">모든 자료</a></nav><h1>지출 정리</h1><details id="saved-materials"><summary>저장된 카드 자료 선택</summary><section><h2>저장된 카드 자료</h2><div id="batches"></div></section></details>
<details id="newupload"><summary>새 카드 파일 추가</summary><section><p class="small">카드사에서 받은 XLS·XLSX 또는 CSV 파일을 올려 주세요. 기존 거래와 중복되는 내역은 다시 기록하지 않습니다.</p><input id="file" type="file" accept=".xls,.xlsx,.csv"><button id="upload">__ICON_UPLOAD__업로드하고 분류</button></section></details>
<details id="rules"><summary>분류 규칙 수정</summary><section><p class="small">가맹점이 정확히 일치할 때 비용 항목을 적용합니다. 여행은 가맹점만으로 자동 배정하지 않습니다.</p><form id="ruleform"><input name="rule_id" type="hidden"><input name="version" type="hidden" value="0"><label>가맹점<input name="merchant" required></label><label>카드 종류<input name="card_kind" placeholder="국내 또는 해외 · 비우면 모든 종류"></label><label>거래 구분<select name="direction"><option value="purchase">사용</option><option value="cancellation">취소·환불</option></select></label><label>여행 중 사용 조건<select name="rule_country"><option value="">여행 조건 없음</option><option value="local">사용 국가와 해당 여행이 일치할 때</option><option value="AT">오스트리아 현지 사용 · 유럽 여행 일치</option><option value="IT">이탈리아 현지 사용 · 유럽 여행 일치</option><option value="FR">프랑스 현지 사용 · 유럽 여행 일치</option><option value="JP">일본 현지 사용 · 명시 여행 일치</option><option value="KR">국내 사용 · 국내 여행 일치</option><option value="TW">대만 현지 사용 · 명시 여행 일치</option></select></label><p id="rule_scope" class="small"></p><label>비용 항목<input name="rule_item" required></label><label>내용<input name="rule_description"></label><button>__ICON_SAVE__규칙 저장하고 다시 분류</button><button type="button" id="newrule">__ICON_PENCIL__새 규칙 작성</button></form><label>저장된 규칙 찾기<input id="rulefilter" type="search" placeholder="가맹점 또는 비용 항목"></label><div id="rulelist"></div></section></details>
<p id="status" role="status"></p><div id="review-metrics"></div><section id="review-controls"><label>거래 검색<input id="review-search" type="search" placeholder="가맹점·항목·여행 검색"></label><div class="grid"><details id="review-date"><summary><button type="button" aria-label="거래일 정렬 및 월 선택" id="review-date-toggle">__ICON_SEARCH__거래일·월</button></summary><label>정렬<select id="review-sort"><option value="date-asc">이전 거래부터</option><option value="date-desc">최근 거래부터</option><option value="amount-desc">큰 금액부터</option></select></label><label>월<select id="review-month"><option value="">전체 월</option></select></label></details><label>비용 항목<select id="review-category"><option value="">전체 항목</option></select></label></div><button type="button" id="review-reset" aria-label="조회 조건 초기화">__ICON_ROTATE__조회 조건 초기화</button></section><section id="summary" class="hidden"></section><section id="holds"></section><section id="preview" class="hidden"></section><div id="questions"></div><section id="rule-panel"><h2>자연어 지시로 분류 제안</h2><p class="small">제안은 승인해야 적용됩니다. 직접 정한 거래는 바뀌지 않습니다.</p><label>대상 거래 <select id="rule-focus"></select></label><textarea id="rule-text" rows="2" style="width:100%"></textarea><p><button type="button" id="rule-propose">__ICON_SEARCH__제안 보기</button></p><div id="rule-result" role="status"></div></section>
</main><script>
const csrf=__CSRF__;let model,stamp='',page=0,editing='',batchGeneration=0,googleCopyPending=false;const PAGE_SIZE=20;const el=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// 자동갱신이 입력 중인 내용을 덮지 않게 하는 조건. 폼에 focus가 있거나 규칙 편집 중이면 그대로 둔다.
const busy=()=>!!document.activeElement?.closest('form')||el('rules').open;
const stateStamp=j=>JSON.stringify([j.batch_id,j.preview.digest,j.rows.map(r=>[r.transaction_id,r.revision,r.classification_state,r.item,r.decided,r.review_evidence_labels]),j.trips.map(t=>[t.id,t.available]),j.quarter_targets||[]]);
function mutationBody(target,payload){const basis=JSON.stringify(payload);if(target.pendingMutation?.basis!==basis)target.pendingMutation={basis,id:crypto.randomUUID()};return JSON.stringify({...payload,request_id:target.pendingMutation.id})}
const money=n=>n==null?'금액 확인 필요':Number(n).toLocaleString('ko-KR')+'원';
const evidence=r=>(r.review_evidence_labels||[]).slice(0,3).join(' · ');
// 질문과 자동분류 수정창이 함께 쓰는 답변 폼. 기존 저장 경로(form[data-index])를 그대로 쓴다.
function answerForm(j,r){const hold=r.review_hold?'<p>'+esc(r.review_hold.reason)+'</p><label><input type="checkbox" name="resolve_hold"> 자료 확인을 마쳤으며 보류를 해제하고 이 금액을 기록합니다</label>':'';return '<form data-index="'+j.rows.indexOf(r)+'">'+hold+'<div class="grid"><label>비용 항목<input name="item" value="'+esc(r.item)+'" required></label><label>여행 또는 미배정<select name="display_tab_id"><option value="unclassified">여행 미배정</option>'+j.trips.filter(t=>t.available).map(t=>'<option value="'+esc(t.id)+'"'+(t.id===r.display_tab_id?' selected':'')+'>'+esc(t.name)+'</option>').join('')+'</select></label></div><label>내용<input name="description" value="'+esc(r.description)+'"></label><label>내 답변·수정 이유<textarea name="note" rows="2">'+esc(r.note||'')+'</textarea></label><p><label><input type="checkbox" name="reuse_rule"> 같은 가맹점·카드 종류·거래 구분에 이 비용 항목을 다시 적용</label></p><button '+(r.conflict_reason||r.parse_error?'disabled':'')+'>__ICON_SAVE__저장하고 자동 반영</button></form>'}
const reviewIcons=__REVIEW_ICONS__;let reviewState='review';
const reviewDate=r=>r.approval_date||r.posting_date||'';
const reviewIcon=r=>{const m=String(r.merchant||'').toUpperCase();return /(^|[^A-Z0-9])AGODA([^A-Z0-9]|$)/.test(m)?reviewIcons.agoda:/(^|[^A-Z0-9])TRIP\\.COM([^A-Z0-9.]|$)/.test(m)||m.includes('트립닷컴')?reviewIcons.trip:reviewIcons.merchant};
const reviewStatus=r=>r.already_booked?'booked':(r.next_action?.group||(r.next_action?.required||r.blocked?'review':''));
const reviewLabel=r=>r.next_action?.status||{review:'확인 필요',booked:'기록 완료',excluded:'기록 제외'}[reviewStatus(r)]||'';
function reviewRows(j){const originals=new Map(j.rows.map(r=>[r.transaction_id,r]));let rows=j.preview.rows.map(r=>({...originals.get(r.transaction_id),...r}));const focus=new URLSearchParams(location.search).get('transaction');if(location.hash==='#preview'&&focus)rows=rows.filter(r=>r.transaction_id===focus||r.refund_link?.counterpart_id===focus);const term=el('review-search').value.trim().toLowerCase(),month=el('review-month').value,category=el('review-category').value;rows=rows.filter(r=>(reviewState==='all'||reviewStatus(r)===reviewState)&&(!month||reviewDate(r).startsWith(month))&&(!category||r.item===category)&&(!term||[r.merchant,r.item,r.description,j.trips.find(t=>t.id===r.display_tab_id)?.name].join(' ').toLowerCase().includes(term)));const sort=el('review-sort').value;return rows.sort((a,b)=>!reviewDate(a)||!reviewDate(b)?Number(!reviewDate(a))-Number(!reviewDate(b)):sort==='amount-desc'?Number(b.amount_krw)-Number(a.amount_krw):sort==='date-asc'?reviewDate(a).localeCompare(reviewDate(b)):reviewDate(b).localeCompare(reviewDate(a)))}
function renderReviewControls(j){const rows=j.preview.rows;el('review-metrics').innerHTML=[['all','전체 거래'],['review','확인 필요'],['booked','기록 완료'],['excluded','기록 제외']].map(([state,label])=>'<button type="button" data-review-state="'+state+'" aria-pressed="'+(state===reviewState)+'">'+label+'<strong>'+rows.filter(r=>state==='all'||reviewStatus(r)===state).length+'</strong></button>').join('');for(const [id,values] of [['review-month',[...new Set(j.rows.map(r=>reviewDate(r).slice(0,7)).filter(Boolean))].sort()],['review-category',[...new Set(j.rows.map(r=>r.item).filter(Boolean))].sort()]]){const select=el(id),value=select.value;select.innerHTML='<option value="">'+(id==='review-month'?'전체 월':'전체 항목')+'</option>'+values.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');select.value=values.includes(value)?value:''}document.querySelectorAll('[data-review-state]').forEach(b=>b.onclick=()=>{reviewState=b.dataset.reviewState;page=0;render(model)})}
for(const id of ['review-search','review-month','review-category','review-sort'])el(id).addEventListener(id==='review-search'?'input':'change',()=>{page=0;render(model)});
el('review-reset').onclick=()=>{el('review-search').value='';el('review-month').value='';el('review-category').value='';el('review-sort').value='date-asc';page=0;render(model)};
el('review-date-toggle').onclick=e=>{e.preventDefault();el('review-date').open=!el('review-date').open};
let rules=[];
function renderRules(list){rules=list;const term=el('rulefilter').value.toLowerCase(),matches=list.filter(r=>(r.conditions.merchant_normalized+' '+r.effects.item).toLowerCase().includes(term));el('rulelist').innerHTML='<p class="small">'+matches.length+'개 규칙 중 '+Math.min(40,matches.length)+'개 표시 · 검색으로 찾을 수 있습니다.</p>'+matches.slice(0,40).map(r=>'<p><button data-rule="'+rules.indexOf(r)+'">'+esc(r.conditions.merchant_normalized==='*'?'여행 중 현지경비 기본값':r.conditions.merchant_normalized)+' → '+esc(r.effects.item)+' · 수정</button></p>').join('');document.querySelectorAll('[data-rule]').forEach(b=>b.onclick=()=>{const r=rules[Number(b.dataset.rule)],f=el('ruleform');f.elements.rule_id.value=r.rule_id;f.elements.version.value=r.version;f.elements.merchant.value=r.conditions.merchant_normalized==='*'?'여행 중 현지경비 기본값':r.conditions.merchant_normalized;f.elements.merchant.readOnly=r.conditions.merchant_normalized==='*';f.elements.card_kind.value=r.conditions.card_kind||'';f.elements.direction.value=r.conditions.transaction_direction||'purchase';f.elements.rule_country.value=r.optional.travel_country||'';f.elements.rule_item.value=r.effects.item||'';f.elements.rule_description.value=r.effects.description||'';f.elements.rule_country.disabled=!!r.optional.inferred_assignment;el('rule_scope').textContent=r.origin==='owner-country-exception-20261003'?'사용자 지정 예외: 조지아·카자흐스탄 거래를 유럽 여행에 배정합니다.':r.optional.inferred_assignment?'이번 거래에만 적용한 추론입니다. 여행은 미리보기의 수정에서 바꿀 수 있습니다.':r.optional.source_hash?'예약 자료로 확인된 해당 원본 거래에만 적용합니다.':r.note||''})}
async function call(url,body,headers={}){const r=await fetch(url,body==null?{cache:'no-store'}:{method:'POST',headers:{'X-CSRF-Token':csrf,...headers},body}).catch(()=>{throw Error('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')});if(!(r.headers.get('Content-Type')||'').includes('application/json'))throw Error(r.status===401?'로그인이 필요합니다. 화면을 다시 열어 주세요.':'서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.');const j=await r.json();if(!r.ok)throw Error(j.message||j.code);return j}
function render(j,switchBatch=false){if(model&&model.batch_id!==j.batch_id&&!switchBatch)return;if(model&&model.batch_id===j.batch_id){const older=(rows,previous,field)=>{const versions=new Map(previous.map(r=>[r.transaction_id,Number(r[field]||0)]));return rows.some(r=>Number(r[field]||0)<(versions.get(r.transaction_id)||0))};if(older(j.rows,model.rows,'revision')||older(j.preview.rows,model.preview.rows,'exclusion_revision'))return;}if(model&&stateStamp(j)!==stamp)invalidateProposal();if(model?.batch_id!==j.batch_id){page=0;editing='';reviewState='review';el('review-search').value='';el('review-month').value='';el('review-category').value=''}model=j;el('review-metrics').before(el('summary'));renderReviewControls(j);fillFocus();stamp=stateStamp(j);el('summary').className='';const approval=j.summary.channel==='approval',approvalInfo=j.approval_summary||{},states=approvalInfo.states||{};const reviewCounts={review:0,booked:0,excluded:0};j.preview.rows.forEach(r=>{const state=reviewStatus(r);if(state)reviewCounts[state]=(reviewCounts[state]||0)+1});el('summary').innerHTML='<h2>'+esc(j.summary.display_name||'카드 사용내역')+'</h2><p class="small">'+esc(j.summary.period_start||'거래 기간 미확인')+(j.summary.period_end?' ~ '+esc(j.summary.period_end):'')+'</p><p>'+(approval?'승인 증거 '+(approvalInfo.source_rows??j.summary.row_count)+'행 · 1:1 연결 '+(states.linked||0)+'건 · 묶음 연결 '+((states.group_linked||0)+(states.group_partial||0))+'건 · 추가 확인 '+((states.ambiguous||0)+(states.approval_only||0)+(approvalInfo.conflict_rows||0))+'건 · 비용 행 생성 0건':'이번 자료 '+j.preview.rows.length+'건 · 확인 필요 '+reviewCounts.review+'건 · 기록 완료 '+reviewCounts.booked+'건'+(reviewCounts.excluded?' · 기록 제외 '+reviewCounts.excluded+'건':''))+'</p><details><summary>원본 파일 정보</summary><p>'+esc(j.summary.filename)+'</p></details>';
const held=j.rows.filter(r=>r.review_hold);const holdNames={cancelled:'취소·환불 관리',refund_pending:'환불 확인 대기',user_hold:'사용자 보류',evidence_pending:'예약·결제 확인 대기'};el('holds').innerHTML=held.length?'<details><summary>취소·환불과 보류 '+held.length+'건 · 일반 비용 기록에서 제외</summary>'+held.map(r=>'<article><strong>'+esc(holdNames[r.review_hold.kind])+'</strong><p>'+esc(r.merchant)+' · '+money(r.amount_krw)+'</p>'+(evidence(r)?'<p class="small">'+esc(evidence(r))+'</p>':'')+'<p>'+esc(r.review_hold.reason)+'</p><button type="button" data-edit="'+esc(r.transaction_id)+'">__ICON_PENCIL__확인 후 수정</button></article>').join('')+'</details>':'';
const asked=j.rows.filter(r=>j.preview.rows.find(p=>p.transaction_id===r.transaction_id)?.next_action?.required&&!r.duplicate_of&&r.transaction_id!==editing);const pages=Math.max(1,Math.ceil(asked.length/PAGE_SIZE));if(page>=pages)page=pages-1;const slice=asked.slice(page*PAGE_SIZE,page*PAGE_SIZE+PAGE_SIZE);const ed=editing?j.rows.find(r=>r.transaction_id===editing&&!r.duplicate_of):null;
el('questions').innerHTML=(ed?'<article><h2>'+esc(j.preview.rows.find(r=>r.transaction_id===ed.transaction_id)?.next_action?.label||'거래 수정')+' · '+esc(ed.merchant)+'</h2><p class="small">'+esc(j.preview.rows.find(r=>r.transaction_id===ed.transaction_id)?.next_action?.reason||'')+'</p>'+answerForm(j,ed)+'</article>':'')+slice.map((r,i)=>'<details class="review-item"'+(i===0?' open':'')+'><summary><span class="ri-date">'+esc(r.approval_date||r.posting_date)+(r.approval_date?'':' (매입일)')+'</span><h2>'+esc(r.merchant)+'</h2><span class="amount">'+money(r.amount_krw)+'</span>'+(evidence(r)?'<span class="ri-flag">'+esc(evidence(r))+'</span>':'')+'</summary><div class="ri-body"><p class="small">'+esc(r.conflict_reason||r.parse_error||r.classification_basis)+'</p>'+answerForm(j,r)+'</div></details>').join('')+(pages>1?'<nav><p class="small">확인하거나 수정할 '+asked.length+'건을 '+PAGE_SIZE+'건씩 봅니다 · '+(page+1)+'/'+pages+'페이지</p><button type="button" id="prevpage"'+(page?'':' disabled')+'>__ICON_CHEVRON_LEFT__이전 20건</button> <button type="button" id="nextpage"'+(page+1<pages?'':' disabled')+'>다음 20건__ICON_CHEVRON_RIGHT__</button></nav>':'');
const groups=(j.refund_groups||[]).map(g=>g.error?'<p class=small>환불 쌍 확인 필요: '+esc(g.message)+'</p>':'<div class="refund-group"><h2>환불 쌍</h2><p>원결제 '+money(g.gross_krw)+' · 환불 '+money(g.refund_krw)+' · 순액 '+money(g.net_krw)+'</p><p>항목 '+esc(g.item)+' · 여행 '+esc(g.trip_name||'미배정')+'</p><button type="button" data-group-commit="'+esc(g.original_id)+'" data-digest="'+esc(g.digest)+'" '+(g.recordable&&g.rows.some(r=>!r.already_booked)?'':'disabled')+'>__ICON_CHECK__이 환불 쌍 '+g.rows.length+'건만 장부에 기록</button>'+(g.recordable?'':'<p class=small>'+esc(g.reason)+'</p>')+'</div>').join('');const p=j.preview;el('preview').className='';el('preview').innerHTML=groups+p.rows.filter(r=>r.excluded_from_company).map(r=>'<p>회사 경비 제외: '+esc(r.merchant)+' · '+money(r.amount_krw)+' <button type="button" data-company-restore="'+esc(r.transaction_id)+'">__ICON_ROTATE__회사 경비 제외 되돌리기</button></p>').join('')+'<h2>거래 처리 결과</h2><p>기록 완료 '+p.rows.filter(r=>r.already_booked).length+'건 · 확인할 거래 '+p.rows.filter(r=>r.next_action?.required).length+'건</p><table><thead><tr><th><button type="button" data-review-date>거래일·가맹점</button></th><th>항목</th><th>금액</th><th>여행</th><th>수정</th></tr></thead><tbody>'+reviewRows(j).map(r=>'<tr><td><span class="pv-label">거래일·가맹점</span>'+esc(reviewDate(r))+'<br><span class="review-icon">'+reviewIcon(r)+'</span>'+esc(r.merchant)+(reviewLabel(r)?'<br><span class="review-state">'+esc(reviewLabel(r))+'</span>':'')+'</td><td><span class="pv-label">항목</span><span class="review-icon">'+(reviewIcons[r.item]||reviewIcons.merchant)+'</span>'+esc(r.item)+((r.booking_ref||r.service_period)?'<br><span class=small>OTA 예약 근거 · '+esc([r.booking_ref,r.service_period].filter(Boolean).join(' · '))+'</span>':'')+(['inference','user_exception','guide_airfare_evidence'].includes(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source)?'<br><span class=small>'+esc({user_exception:'사용자 예외',guide_airfare_evidence:'대장 항공권 근거'}[j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source]||'추론 배정')+'</span>':'')+'</td><td class="review-money"><span class="pv-label">금액</span>'+money(r.amount_krw)+'</td><td><span class="pv-label">여행</span>'+esc((j.quarter_targets||[]).find(t=>t.transaction_ids.includes(r.transaction_id))?.name||j.trips.find(t=>t.id===r.display_tab_id)?.name||'여행 확인 필요')+(['inference','user_exception','guide_airfare_evidence'].includes(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_source)?'<details><summary>배정 근거</summary>'+esc(j.rows.find(x=>x.transaction_id===r.transaction_id)?.classification_basis)+'</details>':'')+'</td><td><button type="button" data-edit="'+esc(r.transaction_id)+'">__ICON_PENCIL__'+esc(r.next_action?.required?r.next_action.label:'수정')+'</button><p class=small>'+esc(r.next_action?.reason||'')+'</p>'+(r.excluded_from_company?'<button type="button" data-company-restore="'+esc(r.transaction_id)+'">__ICON_ROTATE__회사 경비 제외 되돌리기</button>':'')+'</td></tr>').join('')+'</tbody></table><p id="review-empty"'+(reviewRows(j).length?' hidden':'')+'>조회 조건에 맞는 거래가 없습니다.</p>'+[...new Set(p.rows.filter(r=>!r.blocked&&!j.rows.some(x=>x.transaction_id===r.transaction_id&&x.item==='분기 기타비용')).map(r=>r.display_tab_id).filter(Boolean))].map(t=>'<p><button type="button" data-google-copy="'+esc(t)+'">__ICON_COPY__'+esc(j.trips.find(x=>x.id===t)?.name||'여행')+' 구글 지출 7열 복사</button></p>').join('');
document.querySelectorAll('[data-group-commit]').forEach(b=>b.hidden=true);el('preview').insertAdjacentHTML('beforeend',(j.quarter_targets||[]).map(t=>'<section class="quarter-copy"><h2>'+esc(t.name)+'</h2><p class="small">여행 외 비용 · '+t.transaction_ids.length+'건 · 원본과 기록 상태는 그대로 유지합니다.</p>'+(t.available?'<a href="'+esc(t.href)+'" target="_blank" rel="noopener noreferrer">Google 분기 원본 열기</a><p><button type="button" data-google-copy="'+esc(t.id)+'">__ICON_COPY__'+esc(t.name)+' 지출 7열 복사</button></p>':'<p role="status">'+esc(t.reason)+'</p>')+'</section>').join(''));
document.querySelector('[data-review-date]').onclick=()=>{el('review-date').open=true;el('review-date').scrollIntoView({block:'center'});};
document.querySelectorAll('form[data-index]').forEach(f=>f.onsubmit=async e=>{e.preventDefault();const r=model.rows[Number(f.dataset.index)],v=new FormData(f),batch=model.batch_id,generation=batchGeneration,button=f.querySelector('button');if(button.disabled)return;button.disabled=true;try{const j=await call('/api/imports/'+model.batch_id+'/decision',mutationBody(f,{transaction_id:r.transaction_id,revision:r.revision,item:v.get('item'),description:v.get('description'),display_tab_id:v.get('display_tab_id'),note:v.get('note'),reuse_rule:v.has('reuse_rule'),resolve_hold:v.has('resolve_hold')}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(editing===r.transaction_id)editing='';if(!j.refresh_required)render(j);el('status').textContent=j.refresh_required?'답변은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':'답변을 적용했습니다. 검사를 통과한 거래는 자동 반영했습니다.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message}finally{button.disabled=false}})
document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{editing=b.dataset.edit;render(model);el('questions').scrollIntoView({block:'start',behavior:'smooth'});el('status').textContent='선택한 거래의 답변을 고쳐 쓸 수 있습니다.'});
if(el('prevpage'))el('prevpage').onclick=()=>{page=Math.max(0,page-1);render(model)};
if(el('nextpage'))el('nextpage').onclick=()=>{page=page+1;render(model)};}
el('upload').onclick=async()=>{const f=el('file').files[0];if(!f)return;const generation=++batchGeneration;invalidateProposal();el('upload').disabled=true;el('status').textContent='파일을 읽고 분류하고 있습니다.';try{const j=await call('/api/imports',await f.arrayBuffer(),{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(f.name)});if(generation!==batchGeneration)return;render(j,true);el('status').textContent='분류가 끝났습니다.'}catch(e){if(generation===batchGeneration)el('status').textContent=e.message}finally{el('upload').disabled=false}};
el('ruleform').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target),conditions={merchant_normalized:f.get('merchant'),transaction_direction:f.get('direction')};if(f.get('card_kind'))conditions.card_kind=f.get('card_kind');const old=rules.find(r=>r.rule_id===f.get('rule_id'));if(old?.conditions.merchant_normalized==='*')conditions.merchant_normalized='*';const draft={conditions,optional:structuredClone(old?.optional||{}),effects:{item:f.get('rule_item')},note:old?.note||''};delete draft.optional.travel_country;if(f.get('rule_country'))draft.optional.travel_country=f.get('rule_country');if(f.get('rule_description'))draft.effects.description=f.get('rule_description');if(f.get('rule_id'))draft.rule_id=f.get('rule_id');try{const j=await call('/api/imports/rules',JSON.stringify({draft,expected_revision:Number(f.get('version')),batch_id:model?.batch_id,request_id:crypto.randomUUID()}),{'Content-Type':'application/json'});if(j.rules)renderRules(j.rules);e.target.elements.rule_id.value=j.result.rule_id;e.target.elements.version.value=j.result.version;if(j.refresh_required){el('status').textContent='규칙은 저장됐습니다. 분류 결과를 불러오지 못했으니 규칙 저장을 다시 시도해 주세요.';return}try{if(model)render(await call('/api/imports/'+model.batch_id+'/auto-record','{}',{'Content-Type':'application/json'}))}catch{el('status').textContent='규칙은 저장됐습니다. 분류 결과를 불러오지 못했으니 규칙 저장을 다시 시도해 주세요.';return}el('status').textContent='규칙을 저장하고 분류에 적용했습니다. 이미 지정한 답변은 유지됩니다.'}catch(e){el('status').textContent=e.message}};
el('rulefilter').oninput=()=>renderRules(rules);el('newrule').onclick=()=>{el('ruleform').reset();el('ruleform').elements.merchant.readOnly=false;el('rule_scope').textContent=''};
call('/api/imports/rules').then(j=>renderRules(j.rules)).catch(e=>el('status').textContent=e.message);
if(location.hash==='#newupload'){var _up=document.getElementById('newupload');if(_up)_up.open=true;}
function focusReservationCard(transaction){const root=el('ota-review');if(!root)return;root.scrollIntoView({block:'start'});root.focusObserver?.disconnect();let scrolled=false;const mark=()=>{const radio=[...root.querySelectorAll('input[type=radio]')].find(r=>r.value===transaction);if(radio){radio.closest('label').style.outline='2px solid #1C7A52';if(!scrolled){radio.closest('label').scrollIntoView({block:'center'});radio.focus({preventScroll:true});scrolled=true;root.focusObserver?.disconnect()}}};root.focusObserver=new MutationObserver(mark);root.focusObserver.observe(root,{childList:true,subtree:true});mark();}
async function loadBatch(id){const generation=++batchGeneration;invalidateProposal();try{const response=await fetch('/api/imports/'+encodeURIComponent(id));const j=await response.json();if(!response.ok)throw Error(j.message||'거래 자료를 불러오지 못했습니다');if(generation===batchGeneration){render(j,true);const focus=new URLSearchParams(location.search).get('transaction');if(focus&&j.rows.some(r=>r.transaction_id===focus)){document.getElementById('card-review-detail')?.setAttribute('open','');if(location.hash==='#ota-review'){focusReservationCard(focus)}else if(location.hash==='#preview'){reviewState='all';render(j);el('preview').scrollIntoView({block:'start'})}else{editing=focus;render(j);el('questions').scrollIntoView({block:'start'});el('questions').querySelector('select[name=display_tab_id]')?.focus()}}}}catch(e){if(generation===batchGeneration)el('status').textContent=e.message}}const pollCard=async()=>{let wait=2000;if(model&&!document.hidden&&!el('upload').disabled){const started=Date.now(),batch=model.batch_id,generation=batchGeneration,version=stamp;try{const j=await call('/api/imports/'+batch);if(generation===batchGeneration&&model.batch_id===batch&&stamp===version&&stateStamp(j)!==stamp){if(busy()){el('status').textContent='다른 기기에서 내용이 바뀌었습니다. 입력 중인 답변과 수정은 유지됩니다. 저장할 때 최신 버전을 확인합니다.'}else{render(j);el('status').textContent='다른 기기의 변경을 불러왔습니다.'}}}catch(e){if(generation===batchGeneration&&model.batch_id===batch&&stamp===version)el('status').textContent=e.message}wait=Math.max(2000,4*(Date.now()-started))}setTimeout(pollCard,wait)};setTimeout(pollCard,2000);
async function companyExclude(id,excluded,btn){const r=model.preview.rows.find(r=>r.transaction_id===id);if(!r)return;if(!confirm(excluded?'이 거래를 회사 경비 집계와 구글 복사에서 제외할까요? 원본은 유지합니다.':'회사 경비 제외를 되돌릴까요?'))return;const batch=model.batch_id,generation=batchGeneration;btn.disabled=true;try{const j=await call('/api/imports/'+batch+'/company-exclusion',mutationBody(btn,{transaction_id:id,revision:r.revision,exclusion_revision:r.exclusion_revision||0,excluded:excluded,confirmed:true,note:excluded?'회사 경비 아님':'회사 경비 제외 되돌리기'}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(j.state)render(j.state);el('rule-result').innerHTML='';el('status').textContent=j.refresh_required?'회사 경비 변경은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':excluded?'회사 경비에서 제외했습니다. 원본 거래는 보존했습니다.':'회사 경비 제외를 되돌렸습니다.'}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message;btn.disabled=false}}document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('[data-company-restore]');if(b)companyExclude(b.dataset.companyRestore,false,b)});
let proposalGeneration=0;function invalidateProposal(){proposalGeneration++;window.ruleProposal=null;el('rule-result').innerHTML=''}el('rule-focus').onchange=invalidateProposal;el('rule-text').oninput=invalidateProposal;const fillFocus=()=>{if(!model||el('rule-focus').dataset.focusBatch===model.batch_id)return;el('rule-focus').dataset.focusBatch=model.batch_id;el('rule-focus').innerHTML=model.preview.rows.map(r=>'<option value="'+esc(r.transaction_id)+'">'+esc(r.merchant)+' · '+money(r.amount_krw)+(r.blocked?' (보류)':'')+'</option>').join('')};el('rule-propose').onclick=async()=>{if(!model){el('status').textContent='거래 자료를 먼저 불러오세요';return}fillFocus();const text=el('rule-text').value.trim();const tx=el('rule-focus').value;if(!text||!tx){el('status').textContent='지시와 대상 거래를 입력하세요';return}const batch=model.batch_id,generation=++proposalGeneration;window.ruleProposal=null;el('rule-result').innerHTML='';try{const p=await call('/api/imports/'+batch+'/rule-proposal',JSON.stringify({text:text,transaction_id:tx,request_id:crypto.randomUUID()}),{'Content-Type':'application/json'});if(generation!==proposalGeneration||model.batch_id!==batch||el('rule-focus').value!==tx||el('rule-text').value.trim()!==text){el('status').textContent='현재 선택이 바뀌었습니다. 다시 제안하세요.';return}if(p.interpreted_text){el('rule-text').value=p.interpreted_text;}window.ruleProposal={...p,batch_id:batch};const lines=p.changes.map(c=>'<li>'+esc(c.before_item||'(없음)')+' → '+esc(c.after_item||'회사 경비 제외')+'</li>').join('');const note=p.status==='AI_PENDING'?'로컬 AI가 응답하지 않아 해석을 대기 중입니다. 입력값을 유지했습니다. 다시 시도하거나 예시처럼 직접 입력해 주세요.':p.status!=='proposed'?'이 지시는 해석하지 못했거나 원본 값 변경을 요청했습니다. 아무 것도 바꾸지 않습니다.':p.needs_confirmation?'원본 거래를 보존하고 회사 경비 집계와 복사에서만 제외합니다. 별도 확인이 필요합니다.':'답변한 거래 '+p.skipped_confirmed+'건은 바꾸지 않습니다. 아래 '+p.payloads.length+'건만 바뀝니다.';el('rule-result').innerHTML='<p>'+note+'</p><ul>'+lines+'</ul>'+(p.needs_confirmation&&p.changes.length?'<button type="button" id="company-exclude">__ICON_CIRCLE_MINUS__회사 경비 제외 확인</button>':p.payloads.length?'<button type="button" id="rule-approve">승인하고 적용</button>':'');if(p.future_rule){const future=document.createElement('button');future.type='button';future.id='future-rule-draft';future.textContent='향후 사용 규칙 초안';future.onclick=()=>{const form=el('ruleform');form.reset();form.elements.rule_id.value='';form.elements.version.value='0';form.elements.merchant.value=p.future_rule.merchant;form.elements.rule_item.value=p.future_rule.item;el('rules').open=true;form.scrollIntoView({block:'center'});form.elements.merchant.focus();el('status').textContent='새 거래의 사용 규칙 초안을 채웠습니다. 거래 구분과 적용 조건을 확인한 뒤 규칙 저장 버튼을 눌러 주세요.'};el('rule-result').appendChild(future)}const ap=el('rule-approve');if(ap)ap.onclick=ruleApprove;const ce=el('company-exclude');if(ce)ce.onclick=()=>companyExclude(p.transaction_id,true,ce)}catch(e){if(generation===proposalGeneration&&model.batch_id===batch)el('status').textContent=e.message}};async function ruleApprove(){const p=window.ruleProposal;if(!p||p.batch_id!==model.batch_id||p.transaction_id!==el('rule-focus').value||p.text!==el('rule-text').value.trim()){invalidateProposal();return}const btn=el('rule-approve'),batch=p.batch_id,generation=batchGeneration;if(btn)btn.disabled=true;try{const j=await call('/api/imports/'+batch+'/rule-proposal/approve',JSON.stringify({text:p.text,transaction_id:p.transaction_id,digest:p.digest,approved:true,request_id:(p.request_id??=crypto.randomUUID())}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(j.state)render(j.state);el('status').textContent=j.refresh_required?'승인은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':j.applied.length+'건을 한 번에 적용했습니다. 실패하면 한 건도 바뀌지 않습니다.';el('rule-result').innerHTML=''}catch(e){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=e.message;if(btn)btn.disabled=false}}document.addEventListener('click',async e=>{const b=e.target.closest&&e.target.closest('[data-google-copy]');if(!b||!model||googleCopyPending)return;const key='gcopy-trip:'+b.dataset.googleCopy;let before=null;try{before=localStorage.getItem(key)}catch{if(!confirm('복사 이력을 읽을 수 없습니다. 이미 Google에 붙여넣었는지 확인해 주세요. 중복 붙여넣기에 주의하고 계속 복사할까요?'))return;}if(before&&!confirm('이 여행은 '+before+'에 이미 구글 시트용으로 복사했습니다. 시트에 이미 붙여넣었다면 다시 붙여넣지 마세요. 그래도 복사할까요?'))return;googleCopyPending=true;document.querySelectorAll('[data-google-copy]').forEach(button=>button.disabled=true);const batch=model.batch_id,version=stamp,generation=batchGeneration;try{const x=await call('/api/imports/'+batch+'/google-tsv?tab='+encodeURIComponent(b.dataset.googleCopy));if(model.batch_id!==batch||stamp!==version||batchGeneration!==generation)throw Error('자료가 바뀌었습니다. 현재 자료에서 다시 복사해 주세요.');if(!x.row_count){el('status').textContent='복사할 행이 없습니다. 보류 '+x.held.length+'건은 시트에 넣지 않습니다.';return}await navigator.clipboard.writeText(x.tsv);let historyWarning='';try{localStorage.setItem(key,new Date().toLocaleString('ko-KR'))}catch{historyWarning=' 복사 이력을 저장하지 못했습니다. 중복 붙여넣기에 주의해 주세요.'}el('status').textContent='구글 지출 '+x.row_count+'행, 합계 '+money(x.total_krw)+'을 클립보드에 복사했습니다. 보류 '+x.held.length+'건은 복사하지 않았습니다. 이 복사는 장부를 바꾸지 않습니다. 구글 시트에 붙여넣은 뒤에만 반영됩니다.'+historyWarning}catch(err){el('status').textContent=err.message}finally{googleCopyPending=false;document.querySelectorAll('[data-google-copy]').forEach(button=>button.disabled=false)}});
document.addEventListener('click',async e=>{const b=e.target.closest&&e.target.closest('[data-group-commit]');if(!b||!model||b.disabled)return;const batch=model.batch_id,generation=batchGeneration;b.disabled=true;try{const x=await call('/api/imports/'+batch+'/refund-groups/'+encodeURIComponent(b.dataset.groupCommit)+'/commit',mutationBody(b,{digest:b.dataset.digest}),{'Content-Type':'application/json'});if(model.batch_id!==batch||batchGeneration!==generation)return;if(!x.refresh_required)render(x);el('status').textContent=x.refresh_required?'장부 기록은 저장됐습니다. 화면 갱신에 실패했으니 자료를 다시 선택해 결과를 확인해 주세요.':'환불 쌍을 장부에 기록했습니다.'}catch(err){if(model.batch_id===batch&&batchGeneration===generation)el('status').textContent=err.message;b.disabled=false}});
call('/api/imports').then(j=>{el('batches').innerHTML=j.batches.map(b=>'<p><button class="batch-choice" data-batch="'+esc(b.batch_id)+'"><strong>'+esc(b.display_name)+'</strong><br><span>'+esc(b.period_start||'거래 기간 미확인')+(b.period_end?' ~ '+esc(b.period_end):'')+' · '+b.rows+'건'+(b.questions?' · 확인 '+b.questions+'건':'')+'</span></button></p>').join('')||'<p>저장된 카드 자료가 없습니다. </p>';document.querySelectorAll('[data-batch]').forEach(b=>b.onclick=()=>loadBatch(b.dataset.batch).catch(e=>el('status').textContent=e.message));if(!j.batches.length)el('newupload').open=true;const requested=new URLSearchParams(location.search).get('batch');const initial=j.batches.some(b=>b.batch_id===requested)?requested:j.batches[0]?.batch_id;return initial&&!model&&batchGeneration===0?loadBatch(initial):null}).catch(e=>el('status').textContent=e.message);
</script></body></html>'''
