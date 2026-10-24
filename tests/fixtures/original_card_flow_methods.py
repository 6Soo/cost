# Frozen copy of _ota_card_statuses and _ota_candidate_notes from BASE fe340481ed5783d23f678d6a3df542ae8e6ce437.
# Used for golden regression testing. Do not modify.
# The methods are extracted via AST to preserve original behavior exactly.
# Relative imports (from . import ota_payment_review) are replaced with absolute imports.


class _OriginalCardFlowMethods:
    """Frozen original methods for golden regression testing."""

    def _ota_card_statuses(self, rows):
        """Read OTA resolution labels from the published matcher generation; never run a matcher here."""
        from webapp import ota_payment_review
        if not ota_payment_review.enabled():
            return {}, None, {'enabled': False, 'fresh': False, 'status': 'disabled',
                              'generation': None}
        current, fresh = self._held_ota_snapshot()
        reconciliation = {
            'enabled': True,
            'fresh': bool(current is not None and fresh),
            'status': ('ready' if current is not None and fresh else
                       'stale' if current is not None else 'loading'),
            'generation': current.get('generation') if current else None,
        }
        if current is None or not fresh:
            return {}, None, reconciliation
        states = {}
        for result in current.get('results') or ():
            transaction_id = str(result.get('transaction_id') or '')
            group_only = (result.get('allocation_basis') in
                          ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                          and result.get('individual_payment_evidence') is False)
            state = ('GROUP_RECONCILED' if group_only else
                     'USER_CONFIRMED' if result.get('status') == 'MATCHED_USER' else
                     'INFERRED' if result.get('inferred_link') else
                     'EXACT' if result.get('status') == 'MATCHED_AUTO' else None)
            if transaction_id and state:
                states[transaction_id] = state
            for reserved in result.get('reserved_card_ids') or ():
                states[str(reserved)] = 'REVIEW_REQUIRED'
        return states, current.get('generation'), reconciliation

    def _ota_candidate_notes(self, rows):
        """Attach unresolved canonical OTA candidates as review-only screen notes."""
        from webapp import ota_payment_review
        if not ota_payment_review.enabled():
            return {}
        current, fresh = self._held_ota_snapshot()
        if current is None or not fresh:
            return {}
        data = current.get('data') or {}
        wanted = {str(row.get('transaction_id')) for row in rows}
        events = {str(event.get('ota_event_id')): event for event in data.get('events', [])}
        notes = {}
        for result in data.get('results', []):
            group_only = (result.get('allocation_basis') in
                          ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                          and result.get('individual_payment_evidence') is False)
            if group_only:
                event = events.get(str(result.get('ota_event_id') or ''), {})
                note = ('OTA 반복 결제 그룹은 대응됐지만 이 카드와 예약의 개별 연결 근거는 확인되지 않았습니다.'
                        if event else 'OTA 반복 결제 그룹 대응이며 개별 예약 연결은 미확정입니다.')
                identity = str(result.get('transaction_id') or '')
                if identity in wanted:
                    notes.setdefault(identity, set()).add(note)
                continue
            if result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER'):
                continue
            event = events.get(str(result.get('ota_event_id') or ''), {})
            provider = str(event.get('provider') or 'OTA')
            booking_ref = str(event.get('booking_ref') or '')
            status = ota_payment_review._OTA_STATUS.get(str(result.get('status') or ''),
                                                       str(result.get('status') or '확인 필요'))
            reason = ota_payment_review._OTA_REASON.get(str(result.get('reason') or ''),
                                                        str(result.get('reason') or '추가 근거 확인 필요').replace('_', ' '))
            note = f"OTA 후보(미확정): {provider} {booking_ref} · {status} · {reason}".strip()
            search_candidates = [candidate.get('transaction_id')
                                 for candidate in (result.get('candidate_search') or {}).get('candidates') or ()]
            search_rejections = (result.get('candidate_search') or {}).get('rejected') or ()
            rejected_ids = [candidate.get('transaction_id') for candidate in search_rejections]
            for transaction_id in [*(result.get('candidates') or ()), *search_candidates, *rejected_ids]:
                identity = str(transaction_id or '')
                if identity and identity in wanted:
                    notes.setdefault(identity, set()).add(note)
            for rejected in search_rejections:
                identity = str(rejected.get('transaction_id') or '')
                if identity not in wanted:
                    continue
                rejected_reason = ota_payment_review._OTA_REASON.get(
                    str(rejected.get('reason') or ''), '같은 카드 조건에서 금액 또는 통화가 다릅니다.')
                notes.setdefault(identity, set()).add(f'OTA 후보 제외 사유: {rejected_reason}')
        return {identity: sorted(values)[:2] for identity, values in notes.items()}

    def _held_ota_snapshot(self):
        """To be overridden by tests: returns (current_snapshot, fresh_bool)."""
        raise NotImplementedError
