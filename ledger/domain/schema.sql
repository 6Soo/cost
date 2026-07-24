PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_versions(version) VALUES (1);
INSERT OR IGNORE INTO schema_versions(version) VALUES (2);
INSERT OR IGNORE INTO schema_versions(version) VALUES (3);
INSERT OR IGNORE INTO schema_versions(version) VALUES (4);

-- 원천은 불변이다. 같은 파일의 같은 행을 다시 해석하더라도 원문은 이 계층에 남는다.
CREATE TABLE IF NOT EXISTS source_documents (
    id INTEGER PRIMARY KEY,
    source_kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path, sha256)
);

CREATE TABLE IF NOT EXISTS source_records (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES source_documents(id),
    row_number INTEGER NOT NULL CHECK(row_number > 0),
    natural_key TEXT,
    raw_payload TEXT NOT NULL,
    UNIQUE(document_id, row_number)
);

-- 결제수단은 카드 소유·유효기간 같은 결제 주체 정보만 가진다.
CREATE TABLE IF NOT EXISTS payment_methods (
    id INTEGER PRIMARY KEY,
    method_key TEXT NOT NULL UNIQUE,
    issuer TEXT,
    last4 TEXT,
    holder_name TEXT,
    ownership_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK(ownership_type IN ('company', 'guide', 'personal', 'cash', 'transfer', 'points', 'unknown')),
    valid_from TEXT,
    valid_to TEXT
);

-- 카드/현금 원천에서 정규화한 결제 사실. 여행·계정과목은 넣지 않는다.
CREATE TABLE IF NOT EXISTS payment_transactions (
    id INTEGER PRIMARY KEY,
    external_key TEXT NOT NULL UNIQUE,
    source_event_id TEXT NOT NULL,
    identity_fingerprint TEXT NOT NULL,
    payment_method_id INTEGER REFERENCES payment_methods(id),
    source_system TEXT NOT NULL,
    occurred_on TEXT,
    posted_on TEXT,
    merchant TEXT NOT NULL DEFAULT '',
    business_category TEXT,
    country TEXT,
    currency TEXT,
    foreign_amount TEXT,
    amount_krw INTEGER NOT NULL,
    approval_number TEXT,
    transaction_type TEXT NOT NULL
        CHECK(transaction_type IN ('purchase', 'cancellation', 'refund', 'adjustment')),
    record_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transaction_sources (
    transaction_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    PRIMARY KEY(transaction_id, source_record_id)
);

-- P6 직접 적재 원천. legacy classified CSV를 거치지 않고 카드·수기·OTA 구조화
-- 레코드를 멱등 저장하며 원문 전체나 개인정보는 넣지 않는다.
CREATE TABLE IF NOT EXISTS direct_source_records (
    id INTEGER PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    redaction_version TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_kind, source_key, source_sha256)
);

CREATE TABLE IF NOT EXISTS direct_card_events (
    source_record_id INTEGER PRIMARY KEY REFERENCES direct_source_records(id),
    card_event_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    identity_status TEXT NOT NULL
        CHECK(identity_status IN ('unique', 'collision', 'legacy_fallback')),
    source_system TEXT NOT NULL,
    amount_krw INTEGER NOT NULL,
    approval_number TEXT,
    occurred_on TEXT,
    merchant TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS direct_normalized_payments (
    source_record_id INTEGER PRIMARY KEY REFERENCES direct_source_records(id),
    card_event_id TEXT NOT NULL,
    amount_krw INTEGER NOT NULL,
    transaction_type TEXT NOT NULL
        CHECK(transaction_type IN ('purchase', 'cancellation', 'refund', 'adjustment')),
    normalization_version TEXT NOT NULL,
    normalized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS direct_card_events_by_identity
ON direct_card_events(card_event_id);

-- 카드 이벤트의 안정 식별자는 legacy UID 및 비교용 fingerprint와 분리한다.
-- 구조 정보가 부족해 같은 키가 나온 경우 자동 병합하지 않고 collision 상태로 보존한다.
CREATE TABLE IF NOT EXISTS card_event_identities (
    transaction_id INTEGER PRIMARY KEY REFERENCES payment_transactions(id),
    card_event_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    identity_status TEXT NOT NULL DEFAULT 'unique'
        CHECK(identity_status IN ('unique', 'collision', 'legacy_fallback')),
    structural_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS card_event_identities_by_event
ON card_event_identities(card_event_id);

-- payment_transactions는 현재 투영이고, 실제 결제 사실 변경 이력은 이 표에
-- append-only로 보존한다. 같은 transaction/version을 수정하거나 덮어쓰지 않는다.
CREATE TABLE IF NOT EXISTS payment_transaction_versions (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    record_version INTEGER NOT NULL CHECK(record_version > 0),
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    source_event_id TEXT NOT NULL,
    identity_fingerprint TEXT NOT NULL,
    payment_method_id INTEGER REFERENCES payment_methods(id),
    source_system TEXT NOT NULL,
    occurred_on TEXT,
    posted_on TEXT,
    merchant TEXT NOT NULL DEFAULT '',
    business_category TEXT,
    country TEXT,
    currency TEXT,
    foreign_amount TEXT,
    amount_krw INTEGER NOT NULL,
    approval_number TEXT,
    transaction_type TEXT NOT NULL
        CHECK(transaction_type IN ('purchase', 'cancellation', 'refund', 'adjustment')),
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(transaction_id, record_version)
);

-- 취소/환불의 원승인 관계. 상대 거래가 아직 없더라도 참조값은 보존한다.
CREATE TABLE IF NOT EXISTS transaction_relations (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    related_transaction_id INTEGER REFERENCES payment_transactions(id),
    relation_type TEXT NOT NULL CHECK(relation_type IN ('cancels', 'refunds', 'adjusts')),
    reference_value TEXT,
    match_method TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    relation_status TEXT NOT NULL DEFAULT 'legacy'
        CHECK(relation_status IN ('legacy', 'proposed', 'confirmed', 'rejected', 'superseded')),
    resolution_code TEXT,
    rationale TEXT,
    first_seen_document_id INTEGER REFERENCES source_documents(id),
    last_seen_document_id INTEGER REFERENCES source_documents(id),
    superseded_by_document_id INTEGER REFERENCES source_documents(id),
    UNIQUE(transaction_id, relation_type, reference_value)
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'unknown',
    booking_number TEXT NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK(product_type IN ('lodging', 'flight', 'rental', 'package', 'unknown')),
    label TEXT,
    service_start_on TEXT,
    service_end_on TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    UNIQUE(provider, booking_number)
);

CREATE TABLE IF NOT EXISTS payment_booking_links (
    payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    relation_type TEXT NOT NULL DEFAULT 'pays_for',
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    link_status TEXT NOT NULL DEFAULT 'legacy'
        CHECK(link_status IN ('legacy', 'proposed', 'confirmed', 'rejected', 'superseded')),
    first_seen_document_id INTEGER REFERENCES source_documents(id),
    last_seen_document_id INTEGER REFERENCES source_documents(id),
    superseded_by_document_id INTEGER REFERENCES source_documents(id),
    PRIMARY KEY(payment_id, booking_id, relation_type)
);

-- 공급자 정정으로 예약 객체를 새로 만들지 않도록 식별자를 별도 이력으로 관리한다.
CREATE TABLE IF NOT EXISTS booking_identifiers (
    id INTEGER PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    provider TEXT NOT NULL DEFAULT 'unknown',
    identifier TEXT NOT NULL,
    identifier_type TEXT NOT NULL DEFAULT 'booking_number',
    identifier_status TEXT NOT NULL DEFAULT 'legacy'
        CHECK(identifier_status IN ('legacy', 'proposed', 'confirmed', 'rejected', 'superseded')),
    rule_id TEXT,
    first_seen_document_id INTEGER REFERENCES source_documents(id),
    last_seen_document_id INTEGER REFERENCES source_documents(id),
    superseded_by_document_id INTEGER REFERENCES source_documents(id),
    UNIQUE(booking_id, provider, identifier, identifier_type)
);

CREATE INDEX IF NOT EXISTS booking_identifiers_by_value
ON booking_identifiers(identifier);

CREATE TABLE IF NOT EXISTS booking_provider_reviews (
    booking_id INTEGER PRIMARY KEY REFERENCES bookings(id),
    proposed_provider TEXT NOT NULL,
    review_status TEXT NOT NULL
        CHECK(review_status IN ('confirmed', 'needs_review')),
    reason_code TEXT NOT NULL,
    rationale TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 월일만 확인된 기간을 임의의 2026년 날짜로 확정하지 않는다.
CREATE TABLE IF NOT EXISTS booking_service_period_evidence (
    id INTEGER PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    start_on TEXT,
    end_on TEXT,
    date_precision TEXT NOT NULL
        CHECK(date_precision IN ('day', 'month_day', 'unknown')),
    original_text TEXT,
    source_record_id INTEGER REFERENCES source_records(id),
    evidence_status TEXT NOT NULL DEFAULT 'legacy'
        CHECK(evidence_status IN ('legacy', 'proposed', 'confirmed', 'rejected', 'superseded')),
    redaction_version TEXT,
    UNIQUE(booking_id, source_record_id, original_text)
);

-- 예약 표시액과 카드 청구액을 섞지 않고 대사 결과를 명시한다.
CREATE TABLE IF NOT EXISTS payment_amount_reconciliations (
    id INTEGER PRIMARY KEY,
    payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    booking_id INTEGER REFERENCES bookings(id),
    card_charge_krw INTEGER NOT NULL,
    booking_display_amount TEXT,
    booking_currency TEXT,
    discount_amount TEXT,
    points_amount TEXT,
    onsite_amount TEXT,
    reconciliation_type TEXT NOT NULL
        CHECK(reconciliation_type IN (
            'exact', 'discount_adjusted', 'within_2_percent', 'mismatch', 'unknown'
        )),
    difference_ratio REAL,
    rule_id TEXT NOT NULL,
    source_record_id INTEGER REFERENCES source_records(id),
    reconciliation_status TEXT NOT NULL DEFAULT 'proposed'
        CHECK(reconciliation_status IN ('proposed', 'confirmed', 'rejected', 'superseded')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    region TEXT,
    starts_on TEXT,
    ends_on TEXT,
    status TEXT NOT NULL DEFAULT 'planned'
);

-- bucket은 여행만 뜻하지 않는다. 판관비·대장·미배정·정산도 같은 인터페이스로 배분한다.
CREATE TABLE IF NOT EXISTS allocation_targets (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL
        CHECK(target_type IN ('trip', 'overhead', 'leader', 'unassigned', 'clearing', 'other')),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    trip_id INTEGER REFERENCES trips(id)
);

CREATE TABLE IF NOT EXISTS booking_target_links (
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    target_id INTEGER NOT NULL REFERENCES allocation_targets(id),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    link_status TEXT NOT NULL DEFAULT 'legacy'
        CHECK(link_status IN ('legacy', 'proposed', 'confirmed', 'rejected', 'superseded')),
    first_seen_document_id INTEGER REFERENCES source_documents(id),
    last_seen_document_id INTEGER REFERENCES source_documents(id),
    superseded_by_document_id INTEGER REFERENCES source_documents(id),
    PRIMARY KEY(booking_id, target_id)
);

-- 근거는 note 문자열에 묻지 않고 판정과 별도로 보존한다.
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    evidence_type TEXT NOT NULL,
    source_record_id INTEGER REFERENCES source_records(id),
    reference_value TEXT,
    observed_value TEXT,
    summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 비용성격·귀속·계정·증빙·세무판정은 독립 차원의 버전 있는 판단이다.
CREATE TABLE IF NOT EXISTS classification_decisions (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL CHECK(target_type IN ('payment', 'booking', 'allocation')),
    target_id INTEGER NOT NULL,
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    confidence_label TEXT,
    decision_status TEXT NOT NULL
        CHECK(decision_status IN ('legacy', 'proposed', 'confirmed', 'needs_review', 'rejected', 'superseded')),
    rule_id TEXT,
    rationale TEXT,
    superseded_by_id INTEGER REFERENCES classification_decisions(id),
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS one_current_decision_per_dimension
ON classification_decisions(target_type, target_id, dimension)
WHERE superseded_by_id IS NULL AND decision_status <> 'superseded';

CREATE TABLE IF NOT EXISTS decision_evidence (
    decision_id INTEGER NOT NULL REFERENCES classification_decisions(id),
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    evidence_role TEXT NOT NULL DEFAULT 'supporting'
        CHECK(evidence_role IN ('primary', 'supporting', 'conflicting')),
    PRIMARY KEY(decision_id, evidence_id)
);

-- 수동 확정·거부·연결은 외부 append-only JSONL 변경 원장을 정본으로 삼고,
-- 이 표에는 멱등 적용 상태만 투영한다.
CREATE TABLE IF NOT EXISTS ledger_change_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    actor TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 배분은 행이 아니라 plan 단위로 버전 관리한다. 1행→N행 재배분도 이력이 보존된다.
CREATE TABLE IF NOT EXISTS allocation_plans (
    id INTEGER PRIMARY KEY,
    payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    plan_version INTEGER NOT NULL,
    plan_status TEXT NOT NULL
        CHECK(plan_status IN ('legacy', 'proposed', 'confirmed', 'rejected')),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    source_decision_id INTEGER REFERENCES classification_decisions(id),
    supersedes_plan_id INTEGER REFERENCES allocation_plans(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(payment_id, plan_version)
);

-- 한 plan 안에서 결제금액을 여러 대상·예약으로 나눈다.
CREATE TABLE IF NOT EXISTS cost_allocations (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES allocation_plans(id),
    booking_id INTEGER REFERENCES bookings(id),
    target_id INTEGER NOT NULL REFERENCES allocation_targets(id),
    amount_krw INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS allocation_review_cases (
    payment_id INTEGER PRIMARY KEY REFERENCES payment_transactions(id),
    outcome TEXT NOT NULL
        CHECK(outcome IN ('trip', 'overhead', 'cancellation_settlement', 'insufficient_evidence')),
    reason_code TEXT NOT NULL,
    rationale TEXT NOT NULL,
    review_status TEXT NOT NULL
        CHECK(review_status IN ('confirmed', 'needs_review')),
    rule_id TEXT NOT NULL,
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payment_quality_audits (
    payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
    audit_type TEXT NOT NULL
        CHECK(audit_type IN ('low_confidence', 'zero_amount')),
    category TEXT NOT NULL,
    rationale TEXT NOT NULL,
    recognition_amount_krw INTEGER,
    posting_eligibility TEXT NOT NULL
        CHECK(posting_eligibility IN ('allowed', 'blocked', 'not_applicable')),
    audit_status TEXT NOT NULL
        CHECK(audit_status IN ('confirmed', 'needs_review')),
    rule_id TEXT NOT NULL,
    audited_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(payment_id, audit_type)
);

CREATE INDEX IF NOT EXISTS allocation_plans_by_payment ON allocation_plans(payment_id);
CREATE INDEX IF NOT EXISTS allocations_by_plan ON cost_allocations(plan_id);
CREATE INDEX IF NOT EXISTS allocations_by_target ON cost_allocations(target_id);
CREATE INDEX IF NOT EXISTS payment_versions_by_transaction
ON payment_transaction_versions(transaction_id, record_version);
CREATE INDEX IF NOT EXISTS payments_by_identity_fingerprint
ON payment_transactions(identity_fingerprint);

-- 장부는 확정된 배분을 소비하는 출력이다. 원천·판정과 독립적으로 롤백/재생성한다.
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY,
    allocation_id INTEGER NOT NULL REFERENCES cost_allocations(id),
    ledger_name TEXT NOT NULL,
    ledger_tab TEXT NOT NULL,
    account_code TEXT NOT NULL,
    evidence_label TEXT,
    amount_krw INTEGER NOT NULL,
    posting_status TEXT NOT NULL
        CHECK(posting_status IN ('draft', 'posted', 'reversed')),
    posting_version INTEGER NOT NULL DEFAULT 1,
    posted_at TEXT
);

CREATE VIEW IF NOT EXISTS current_classification_decisions AS
SELECT *
FROM classification_decisions
WHERE superseded_by_id IS NULL;

CREATE VIEW IF NOT EXISTS current_payment_booking_links AS
SELECT *
FROM payment_booking_links
WHERE link_status NOT IN ('rejected', 'superseded');

CREATE VIEW IF NOT EXISTS current_booking_target_links AS
SELECT *
FROM booking_target_links
WHERE link_status NOT IN ('rejected', 'superseded');

CREATE VIEW IF NOT EXISTS current_transaction_relations AS
SELECT *
FROM transaction_relations
WHERE relation_status NOT IN ('rejected', 'superseded');

CREATE VIEW IF NOT EXISTS current_cost_allocations AS
SELECT
    a.*,
    p.payment_id,
    p.plan_version,
    p.plan_status AS allocation_status,
    p.confidence,
    p.source_decision_id,
    p.created_at
FROM allocation_plans p
JOIN cost_allocations a ON a.plan_id=p.id
WHERE p.plan_status <> 'rejected'
  AND NOT EXISTS (
      SELECT 1
      FROM allocation_plans newer
      WHERE newer.supersedes_plan_id=p.id
        AND newer.plan_status <> 'rejected'
  );

CREATE VIEW IF NOT EXISTS payment_allocation_summary AS
SELECT
    p.id AS payment_id,
    p.external_key,
    p.amount_krw AS payment_amount_krw,
    COALESCE(SUM(a.amount_krw), 0) AS allocated_amount_krw,
    p.amount_krw - COALESCE(SUM(a.amount_krw), 0) AS difference_krw
FROM payment_transactions p
LEFT JOIN current_cost_allocations a ON a.payment_id = p.id
GROUP BY p.id;
