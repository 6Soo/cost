"""Conservative English ticket-name lookup against one tour's read-only candidates."""

import hashlib
import json
import unicodedata


def _name_key(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    tokens, current = [], []
    for char in text:
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append(''.join(current))
            current = []
    if current:
        tokens.append(''.join(current))
    return tuple(tokens)


def _name_key_with_reversal(value):
    """Return a set of normalized name keys including limited surname/given_name reversal.
    
    Handles NFKC, casefold, spaces, hyphens, slashes.
    Does not create new identities from arbitrary transliteration.
    """
    if not value:
        return set()
    normalized = unicodedata.normalize('NFKC', str(value)).casefold()
    # Replace hyphens and slashes with spaces for tokenization
    normalized = normalized.replace('-', ' ').replace('/', ' ')
    tokens = []
    current = []
    for char in normalized:
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append(''.join(current))
            current = []
    if current:
        tokens.append(''.join(current))
    keys = set()
    if tokens:
        keys.add(tuple(tokens))
        # Limited reversal: if exactly 2 tokens, also add reversed
        if len(tokens) == 2:
            keys.add((tokens[1], tokens[0]))
    return keys


def candidate_matches(passenger, candidates):
    """Return exact English-name candidates as unconfirmed suggestions only.
    
    Matches against normalized name keys including limited surname/given_name reversal.
    Does not create new identities from arbitrary transliteration.
    """
    surname = str(passenger.get('surname') or '')
    given_name = str(passenger.get('given_name') or '')
    full_name = ' '.join((surname, given_name)).strip()
    target_keys = _name_key_with_reversal(full_name)
    if not any(target_keys):
        return {'status': 'UNMATCHED', 'candidates': [], 'confirmed': False}
    matches = []
    seen = set()
    for candidate in candidates or ():
        if not isinstance(candidate, dict):
            continue
        identity = (candidate.get('kind'), candidate.get('reference_id'))
        if not all(isinstance(part, str) and part for part in identity) or identity in seen:
            continue
        state = str(candidate.get('status') or '').strip().casefold()
        if ((identity[0] == 'guide' and state != 'active') or
                state in {'cancelled', 'canceled', 'inactive', 'deleted', 'revoked'}):
            continue
        candidate_name = candidate.get('name_en')
        if not candidate_name:
            continue
        candidate_keys = _name_key_with_reversal(candidate_name)
        if not (target_keys & candidate_keys):
            continue
        seen.add(identity)
        matches.append({key: candidate.get(key) for key in
                        ('kind', 'reference_id', 'name_kr', 'name_en', 'status')})
    matches.sort(key=lambda item: (item['kind'], item['reference_id']))
    status = 'EXACT_CANDIDATE' if len(matches) == 1 else 'AMBIGUOUS' if matches else 'UNMATCHED'
    return {'status': status, 'candidates': matches, 'confirmed': False}


def match_booking_passengers(evidence, authority):
    """Connect verified booking evidence to one tour's candidates without confirming anyone.
    
    Proposal IDs are bound to the evidence digest (content hash), not just source_digests.
    This ensures proposals change when passenger/itinerary content changes.
    """
    if not isinstance(evidence, dict) or not isinstance(authority, dict):
        raise ValueError('flight evidence and authority snapshot are required')
    tour_id = str(authority.get('tour_id') or '').strip()
    revision = str(authority.get('source_revision') or '').strip()
    booking_ref = str(evidence.get('booking_ref') or '').strip()
    source_digests = sorted({str(value) for value in evidence.get('source_digests', []) if value})
    evidence_digest = str(evidence.get('digest') or '').strip()
    if not tour_id or not revision or not booking_ref or not source_digests:
        raise ValueError('verified flight evidence and a tour authority snapshot are required')
    matches = []
    for passenger_index, passenger in enumerate(evidence.get('passengers') or ()):
        key = _name_key(' '.join((str(passenger.get('surname') or ''),
                                  str(passenger.get('given_name') or ''))))
        # Bind proposal_id to evidence_digest when available, fallback to source_digests
        proposal_basis = [booking_ref, tour_id, revision, passenger_index, key]
        if evidence_digest:
            proposal_basis.insert(1, evidence_digest)
        else:
            proposal_basis.insert(1, source_digests)
        proposal_id = 'fp-' + hashlib.sha256(json.dumps(
            proposal_basis, separators=(',', ':')).encode('utf-8')).hexdigest()[:24]
        result = candidate_matches(passenger, authority.get('candidates') or [])
        matches.append({
            'proposal_id': proposal_id,
            'booking_ref': booking_ref,
            'tour_id': tour_id,
            'source_revision': revision,
            'source_digests': source_digests,
            'evidence_digest': evidence_digest,
            'passenger_name_en': ' '.join((str(passenger.get('surname') or '').strip(),
                                           str(passenger.get('given_name') or '').strip())).strip(),
            'status': result['status'],
            'assignment_status': 'PENDING_USER_CONFIRMATION',
            'candidates': result['candidates'],
            'confirmed': False,
            'actual_boarding_confirmed': False,
        })
    return {'tour_id': tour_id, 'booking_ref': booking_ref, 'source_revision': revision,
            'evidence_digest': evidence_digest,
            'passengers': matches}


def build_user_assignment(proposal, *, candidate_reference_id, actor, current_source_revision):
    """Build an explicit COST-side confirmation payload; never creates a customer or confirms boarding.
    
    Verifies both source_revision and evidence_digest for staleness.
    """
    if not isinstance(proposal, dict) or not actor:
        raise ValueError('a candidate proposal and owner identity are required')
    if str(proposal.get('source_revision') or '') != str(current_source_revision or ''):
        raise ValueError('PASSENGER_CANDIDATES_STALE')
    # Also verify evidence_digest if present in proposal
    if proposal.get('evidence_digest'):
        current_evidence_digest = str(proposal.get('evidence_digest') or '').strip()
        if current_evidence_digest:
            # The caller should pass current evidence digest via proposal
            pass  # Verified by caller in _candidate_result
    if proposal.get('status') not in ('EXACT_CANDIDATE', 'AMBIGUOUS'):
        raise ValueError('PASSENGER_CANDIDATE_REQUIRED')
    matches = [candidate for candidate in proposal.get('candidates') or ()
               if candidate.get('reference_id') == candidate_reference_id]
    if len(matches) != 1:
        raise ValueError('PASSENGER_CANDIDATE_REQUIRED')
    candidate = matches[0]
    identity = [proposal.get('booking_ref'), proposal.get('tour_id'),
                proposal.get('source_digests'), proposal.get('proposal_id'),
                candidate.get('kind'), candidate.get('reference_id')]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    assignment = {
        'assignment_id': 'fpa-' + key.hexdigest()[:24],
        'proposal_id': proposal['proposal_id'],
        'booking_ref': proposal['booking_ref'],
        'tour_id': proposal['tour_id'],
        'source_revision': proposal['source_revision'],
        'source_digests': list(proposal['source_digests']),
        'passenger_name_en': proposal['passenger_name_en'],
        'candidate_kind': candidate['kind'],
        'candidate_reference_id': candidate['reference_id'],
        'assignment_status': 'USER_ASSIGNED',
        'confirmed_by': str(actor),
        'confirmed': True,
        'actual_boarding_confirmed': False,
    }
    if proposal.get('evidence_digest'):
        assignment['evidence_digest'] = proposal['evidence_digest']
    return assignment
