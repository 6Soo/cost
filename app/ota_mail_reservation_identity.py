"""Producer-only reservation identity from an authenticated provider's explicit reference.

This groups reservation views only. It never joins payment events or grants
matching, occupancy, ledger, travel or refund authority.
"""
import re
from app import ota_mail

DOMAINS = {
    'trip': ('trip.com', 'trip.co.kr'), 'agoda': ('agoda.com', 'agoda-messaging.com'),
    'booking': ('booking.com',), 'klook': ('klook.com',),
    'traveloka': ('traveloka.com',),
}


def attest(event, message, text):
    from app.ota_payments import _digest
    provider, reference = event.get('provider'), event.get('booking_ref')
    domains = DOMAINS.get(provider)
    if not domains or not reference or ota_mail.authenticated_headers(message, domains) is None:
        return event
    refs = set(re.findall(
        r'(?:예약\s*(?:확인\s*)?(?:번호|코드|ID)|예약번호|予約番号|'
        r'booking\s*(?:reference|number|ID)|reservation\s*(?:number|ID)|confirmation\s*number)'
        r'\s*[:：#]?\s*([A-Z0-9-]{6,32})', text, re.I))
    if provider == 'traveloka':
        from app.traveloka_mail import references
        # The OTA Booking ID is distinct from each airline's segment PNR.
        refs = references(message)
    if refs != {reference}:
        return event
    source_id = 'mail:' + str(message['id'])
    if source_id not in event.get('source_ids', ()) or not event.get('source_digest'):
        return event
    # These providers issue globally scoped booking references. This is the
    # authenticated provider's reservation namespace, not a mailbox path or
    # an observation's message ID. Hotel-local numbers are deliberately excluded.
    lineage = 'authenticated-mail-provider:' + provider
    identity = _digest(['mail-reservation-identity-v1', provider, reference, lineage])
    event['_mail_reservation_provenance'] = {
        'kind': 'authenticated_provider_booking', 'provider': provider,
        'identity': identity, 'booking_ref': reference, 'source_lineage_id': lineage,
        'source_digest': event['source_digest'],
    }
    event['reservation_identity_attestation'] = {
        'provider': provider, 'identity': identity, 'source_lineage_id': lineage,
        'identity_status': 'verified', 'evidence_status': 'verified', 'source_status': 'verified',
        'evidence_link_ids': [source_id],
    }
    return event


def combine(item, group, *, conflict):
    """Keep binding on already-combined evidence only when every member agrees."""
    proofs = [event.get('_mail_reservation_provenance') for event in group]
    attestations = [event.get('reservation_identity_attestation') for event in group]
    fields = ('kind', 'provider', 'identity', 'booking_ref', 'source_lineage_id')
    if (conflict or not proofs or not all(isinstance(p, dict) for p in proofs)
            or not all(isinstance(a, dict) for a in attestations)
            or any(any(p.get(k) != proofs[0].get(k) for k in fields) for p in proofs)
            or any(a.get('identity') != proofs[0].get('identity') or
                   any(a.get(k) != 'verified' for k in ('identity_status', 'evidence_status', 'source_status'))
                   for a in attestations)):
        item.pop('_mail_reservation_provenance', None)
        return
    item['_mail_reservation_provenance'] = dict(proofs[0], source_digest=item['source_digest'])
    item['reservation_identity_attestation'] = dict(attestations[0], evidence_link_ids=sorted({
        link for a in attestations for link in a.get('evidence_link_ids', ())}))
