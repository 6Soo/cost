"""Evidence-backed query intervals, independent of transaction dates and decisions."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import sqlite3

from .db import StoreError

COVERAGE_KIND = 'card.query_coverage.v1'
BASELINE_KIND = 'card.query_baseline.v1'

DATE_BASIS_ALIASES = {
 '승인일': ('승인일', '승인일자', 'approval_date', 'approvaldate'),
 '이용일': ('이용일', '사용일', '거래일', 'transactiondate', 'date'),
 '매입일': ('매입일', '매입일자', '정산일', 'posting_date', 'postdate', 'settlementdate'),
}


def normalize_date_basis(raw):
    value = re.sub(r'\s+', '', str(raw or '')).casefold()
    return next((key for key, aliases in DATE_BASIS_ALIASES.items() if value in aliases), '')


def parse_iso_date(value):
    value = str(value or '').strip().split('T')[0].replace('.', '-').replace('/', '-')
    if re.fullmatch(r'\d{8}', value):
        value = value[:4] + '-' + value[4:6] + '-' + value[6:]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def normalize_card_tail(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return digits[-4:] if len(digits) >= 4 else ''


@dataclass(order=True)
class Period:
    start: str
    end: str


def merge_periods(periods):
    result = []
    for interval in sorted(periods):
        if result and (date.fromisoformat(interval.start)-date.fromisoformat(result[-1].end)).days <= 1:
            result[-1] = Period(result[-1].start, max(result[-1].end, interval.end))
        else:
            result.append(Period(interval.start, interval.end))
    return result


def find_gaps(periods, management_start, through):
    periods = merge_periods(periods)
    end = parse_iso_date(through) if through is not None else date.today().isoformat()
    start = parse_iso_date(management_start) if management_start else (periods[0].start if periods else None)
    if not end or not start or start > end:
        return []
    cursor, limit = date.fromisoformat(start).toordinal(), date.fromisoformat(end).toordinal()
    result = []
    for period in periods:
        lo, hi = date.fromisoformat(period.start).toordinal(), date.fromisoformat(period.end).toordinal()
        if hi < cursor:
            continue
        if lo > limit:
            break
        if lo > cursor:
            result.append(Period(date.fromordinal(cursor).isoformat(), date.fromordinal(min(lo-1, limit)).isoformat()))
        cursor = max(cursor, hi+1)
        if cursor > limit:
            break
    if cursor <= limit:
        result.append(Period(date.fromordinal(cursor).isoformat(), end))
    return result


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def inspect(content, filename, parsed=None):
    """Inspect only labeled query preamble; never treat merchant dates as metadata."""
    from .import_card import parse_card_file, read_cells, _build_header_map
    parsed = parsed or parse_card_file(content, filename)
    _, cells = read_cells(content)
    header = next((i for i, row in enumerate(cells[:20])
                   if 'merchant' in _build_header_map(row) and 'approval_date' in _build_header_map(row)), None)
    preamble = cells[:header] if header is not None else []
    metadata = {}
    metadata_conflicts = []

    def remember(key, value):
        if key in metadata and metadata[key] != value:
            metadata_conflicts.append(key)
        metadata[key] = value

    for row in preamble:
        if not row:
            continue
        label = re.sub(r'\s+', '', str(row[0] or '')).rstrip(':：').casefold()
        value = ' '.join(str(v or '') for v in row[1:]).strip()
        if label in ('조회기간', 'queryperiod', '조회일범위'):
            match = re.fullmatch(r'(\d{4}[-./]\d{2}[-./]\d{2})\s*[~–—]\s*(\d{4}[-./]\d{2}[-./]\d{2})', value)
            if match:
                start, end = map(parse_iso_date, match.groups())
                remember('start_date', start)
                remember('end_date', end)
                if not start or not end or start > end:
                    metadata_conflicts.append('query_period')
            else:
                metadata_conflicts.append('query_period')
        elif label in ('조회기준', 'querybasis'):
            remember('date_basis', normalize_date_basis(value))
            if not metadata['date_basis']:
                metadata_conflicts.append('date_basis')
        elif label in ('카드사', 'issuer'):
            remember('issuer', value)
        elif label in ('카드번호', 'maskedcardno'):
            remember('card_mask', re.sub(r'[\s-]', '', value).upper())
        elif label in ('조회유형', 'querytype'):
            if value.strip().casefold() in ('전체', 'all'):
                metadata['full_query_explicit'] = True
            else:
                metadata['restricted'] = True
        elif label in ('조회필터', 'queryfilter') and value.casefold() not in ('전체', 'all', '없음', 'none'):
            metadata['restricted'] = True
        elif label in ('다운로드상태', 'downloadstatus') and value not in ('완료', 'complete'):
            metadata['restricted'] = True
    source_hash = hashlib.sha256(content).hexdigest()
    masks = {}
    if header is not None:
        index = _build_header_map(cells[header]).get('card_mask')
        if index is not None:
            for row in parsed.rows:
                if index < len(row.source_row):
                    mask = re.sub(r'[\s-]', '', str(row.source_row[index] or '')).upper()
                    masks[(row.issuer, row.card_tail)] = masks.get((row.issuer, row.card_tail), set()) | {mask}
    pairs = {(row.issuer, row.card_tail) for row in parsed.rows if row.issuer and row.card_tail}
    if not parsed.rows and metadata.get('issuer') and metadata.get('card_mask'):
        pair = (metadata['issuer'], normalize_card_tail(metadata['card_mask']))
        if pair[1]:
            pairs.add(pair)
        masks[pair] = {re.sub(r'[\s-]', '', metadata['card_mask']).upper()}
    identities = []
    for issuer, tail in sorted(pairs):
        signatures = masks.get((issuer, tail), set())
        # A tail alone cannot identify the same physical card across files.
        strong = len(signatures) == 1 and len(re.sub(r'\D', '', next(iter(signatures)))) > 4
        scope = 'masked_card' if strong else 'source_file'
        context = next(iter(signatures)) if strong else source_hash
        card_id = _digest(json.dumps([issuer, tail, scope, context], ensure_ascii=False))
        identities.append(dict(issuer=issuer, card_tail=tail, card_id=card_id, identity_scope=scope))
    identity = identities[0] if len(identities) == 1 else {}
    errors = bool(parsed.issues or any(row.parse_error for row in parsed.rows))
    conflicting_masks = any(len(values) > 1 for values in masks.values())
    missing_identity = any(not row.issuer or not row.card_tail for row in parsed.rows)
    if metadata.get('issuer') and any(issuer != metadata['issuer'] for issuer, _ in pairs):
        metadata_conflicts.append('issuer')
    if metadata.get('card_mask') and any(
            mask != metadata['card_mask'] for values in masks.values() for mask in values):
        metadata_conflicts.append('card_mask')
    reasons = []
    if errors:
        reasons.append('파일 파싱 오류')
    if metadata.get('restricted'):
        reasons.append('제한된 조회 또는 불완전 다운로드')
    if metadata_conflicts:
        reasons.append('원본 조회 조건 충돌 또는 형식 오류')
    if len(identities) != 1 or conflicting_masks or missing_identity:
        reasons.append('단일 카드 식별 불가')
    evidence = dict(identity, date_basis=metadata.get('date_basis', ''),
                    start_date=metadata.get('start_date') or '', end_date=metadata.get('end_date') or '',
                    evidence_source='metadata', confirmed=False, complete=not reasons,
                    reason=' · '.join(reasons), management_start='')
    if identity.get('identity_scope') == 'source_file':
        evidence['reason'] = ' · '.join(filter(None, [evidence['reason'], '끝4만 식별되어 이 파일 범위에서만 확인합니다. 다른 파일과 합치지 않습니다.']))
    return dict(source_hash=source_hash, filename=filename, parser=parsed.parser, channel=parsed.channel,
                row_count=len(parsed.rows), ok_rows=len(parsed.ok_rows), evidence=evidence,
                identities=identities, blocked=bool(reasons), metadata=metadata)


class CoverageStore:
    def __init__(self, conn):
        self.conn = conn

    def available(self):
        names = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {'change_log', 'import_batches'} <= names

    def prepare_schema(self):
        """Compatibility seam: existing upload history only; no new schema or DDL."""
        if not self.available():
            raise StoreError('COVERAGE_NOT_READY', '기존 업로드 이력을 준비해 주세요.')

    def _records(self):
        if not self.available():
            return []
        records = {}
        for subject, detail in self.conn.execute(
                'SELECT subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (COVERAGE_KIND,)):
            try:
                record = json.loads(detail)
                if isinstance(record, dict) and record.get('coverage_id') == subject:
                    records[subject] = record
            except (ValueError, TypeError):
                continue
        return list(records.values())

    def _baselines(self):
        """Latest auditable card/axis management baseline. Never infer it from transactions."""
        records = {}
        for subject, detail in self.conn.execute(
                'SELECT subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (BASELINE_KIND,)):
            try:
                row = json.loads(detail)
                if (isinstance(row, dict) and row.get('baseline_id') == subject
                        and parse_iso_date(row.get('management_start'))):
                    records[(row.get('card_id'), row.get('date_basis'))] = row
            except (ValueError, TypeError):
                continue
        return records

    def set_baseline(self, *, card_id, issuer, card_tail, date_basis,
                     management_start, expected_revision=0):
        """Owner-confirmed starting boundary. Does not change financial records."""
        start = parse_iso_date(management_start)
        basis = normalize_date_basis(date_basis)
        if not start or not basis or start > date.today().isoformat():
            raise StoreError('INVALID_COVERAGE_PERIOD', '올바른 관리 시작일과 조회 기준을 선택해 주세요.')
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise StoreError('INVALID_REVISION', '관리 시작일을 다시 불러와 주세요.')
        identity = next((r for r in self._records()
                         if r.get('confirmed') and r.get('card_id') == card_id
                         and r.get('issuer') == issuer and r.get('card_tail') == card_tail
                         and r.get('date_basis') == basis), None)
        if not identity:
            raise StoreError('CARD_IDENTITY_REQUIRED', '확인된 카드 조회자료가 필요합니다.')
        previous = self._baselines().get((card_id, basis))
        revision = previous['revision'] if previous else 0
        if expected_revision != revision:
            raise StoreError('REVISION_CONFLICT', '관리 기간이 변경됐습니다. 새로고침 후 다시 확인해 주세요.')
        if previous and previous['management_start'] == start:
            return dict(management_start=start, revision=revision, updated=False)
        now = datetime.now(timezone.utc).isoformat()
        baseline_id = _digest(json.dumps([card_id, basis], ensure_ascii=False))
        row = dict(baseline_id=baseline_id, card_id=card_id, issuer=issuer,
                   card_tail=card_tail, date_basis=basis, management_start=start,
                   revision=revision + 1, updated_at=now)
        self.conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES(?,?,?,?)',
                          (now, BASELINE_KIND, baseline_id, json.dumps(row, ensure_ascii=False, sort_keys=True)))
        return dict(management_start=start, revision=revision + 1, updated=True)

    def record(self, batch_id, evidence):
        if not self.available():
            raise StoreError('COVERAGE_NOT_READY', '조회기간 저장 구조를 준비해 주세요.')
        if not isinstance(evidence, dict):
            raise StoreError('INVALID_INPUT', '조회 조건을 확인해 주세요.')
        row = self.conn.execute('SELECT content_bytes,filename,content_sha256,status,error_count FROM import_batches WHERE batch_id=?', (batch_id,)).fetchone()
        if row is None:
            raise StoreError('BATCH_NOT_FOUND', '업로드 자료를 찾을 수 없습니다.')
        content, filename, source_hash, status, error_count = row
        if hashlib.sha256(content).hexdigest() != source_hash:
            raise StoreError('SOURCE_HASH_MISMATCH', '보관 원본의 무결성을 확인해 주세요.')
        report = inspect(content, filename)
        actual = report['evidence']
        needs_recheck = bool(report['blocked'] or status == 'rejected' or error_count)
        for key in ('issuer', 'card_tail', 'card_id'):
            supplied = evidence.get(key)
            if supplied and supplied != actual.get(key):
                raise StoreError('CARD_IDENTITY_MISMATCH', '보관 원본의 카드 식별과 일치하지 않습니다.')
        if not actual.get('card_id'):
            raise StoreError('CARD_IDENTITY_REQUIRED', '보관 원본에서 카드를 식별할 수 없습니다.')
        start, end = (parse_iso_date(evidence.get(k)) for k in ('start_date', 'end_date'))
        basis = normalize_date_basis(evidence.get('date_basis'))
        management_start = parse_iso_date(evidence.get('management_start')) if evidence.get('management_start') else None
        if not start or not end or start > end or not basis or (evidence.get('management_start') and not management_start):
            raise StoreError('INVALID_COVERAGE_PERIOD', '실제 조회 기준과 올바른 시작·종료일을 확인해 주세요.')
        source = evidence.get('evidence_source', 'user')
        if source not in ('user', 'metadata'):
            raise StoreError('INVALID_EVIDENCE_SOURCE', '조회 근거를 확인해 주세요.')
        if source == 'metadata' and any(evidence.get(key) != actual.get(key) for key in ('start_date', 'end_date', 'date_basis')):
            raise StoreError('METADATA_MISMATCH', '원본에 명시된 조회 조건과 다릅니다.')
        if evidence.get('confirmed') is not True or evidence.get('complete') is not True:
            raise StoreError('COVERAGE_RECHECK_REQUIRED', '카드·조회 기준·전체 조회 결과를 확인해 주세요.')
        identity = _digest(json.dumps([actual['card_id'], basis, start, end, source_hash]))
        now = datetime.now(timezone.utc).isoformat()
        previous = next((r for r in self._records() if r['coverage_id'] == identity), None)
        confirmed = not needs_recheck
        record = dict(coverage_id=identity, card_id=actual['card_id'], issuer=actual['issuer'],
                      card_tail=actual['card_tail'], identity_scope=actual['identity_scope'], date_basis=basis,
                      start_date=start, end_date=end, management_start=management_start, batch_id=batch_id,
                      source_hash=source_hash, evidence_source=source, confirmed=confirmed, complete=confirmed,
                      reason=actual['reason'] or ('업로드 오류를 재확인해 주세요.' if needs_recheck else ''))
        unchanged = previous and all(previous.get(key) == value for key, value in record.items())
        if not unchanged:
            record['created_at'] = previous['created_at'] if previous else now
            record['updated_at'] = now
            self.conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES(?,?,?,?)',
                              (now, COVERAGE_KIND, identity, json.dumps(record, ensure_ascii=False, sort_keys=True)))
        return dict(coverage_id=identity, inserted=not bool(previous), confirmed=confirmed, reason=record['reason'])

    def summary(self, *, issuer=None, card_tail=None, date_basis=None, through=None):
        if through is not None and not parse_iso_date(through):
            raise StoreError('INVALID_COVERAGE_PERIOD', '기준일을 확인해 주세요.')
        if not self.available():
            return dict(available=False, coverages=[], gaps=[], rechecks=[])
        groups = defaultdict(list)
        rechecks = []
        for record in self._records():
            if (issuer and issuer != record['issuer'] or card_tail and card_tail != record['card_tail']
                    or date_basis and normalize_date_basis(date_basis) != record['date_basis']):
                continue
            if not record['confirmed']:
                rechecks.append(dict(record, periods=[{'start': record['start_date'], 'end': record['end_date']}]))
                continue
            key = tuple(record[k] for k in ('card_id','issuer','card_tail','identity_scope','date_basis'))
            groups[key].append(tuple(record[k] for k in ('start_date','end_date','management_start','reason')))
        coverages, gaps = [], []
        baselines = self._baselines()
        for (card_id, card_issuer, tail, scope, basis), values in groups.items():
            intervals = merge_periods([Period(value[0], value[1]) for value in values])
            baseline = baselines.get((card_id, basis))
            management = (baseline['management_start'] if baseline else
                          min((value[2] for value in values if value[2]), default=None))
            info = dict(card_id=card_id, issuer=card_issuer, card_tail=tail, identity_scope=scope, date_basis=basis,
                        management_start=management, baseline_revision=(baseline['revision'] if baseline else 0),
                        reason=values[-1][3])
            coverages.append(dict(info, periods=[vars(period) for period in intervals]))
            missing = find_gaps(intervals, management, through)
            if missing:
                gaps.append(dict(info, gaps=[vars(period) for period in missing]))
        return dict(available=True, coverages=coverages, gaps=gaps, rechecks=rechecks)

    def inspect(self, content, filename, parsed=None):
        return inspect(content, filename, parsed)

    def get_coverage_for_batch(self, batch_id):
        return [record for record in self._records() if record['batch_id'] == batch_id]
