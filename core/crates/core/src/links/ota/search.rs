//! 진단용 후보 탐색(`search_card_candidates`·`_preauthorization_candidates`·`_price_change_candidates`).
//! 후보는 연결이 아니다. 결제 확인과 배정은 U14와 Python 어댑터가 맡는다.

use super::Matcher;
use super::pyval::{first_text, get, is_str, pystr, text, truthy};
use serde::Serialize;
use serde_json::{Map, Value};
use std::collections::BTreeMap;

/// Python `max_comparisons`의 기본값.
pub const DEFAULT_MAX_COMPARISONS: usize = 250_000;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Candidate {
    pub transaction_id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub date_status: Option<&'static str>,
    pub resolution_allowed: bool,
    pub basis: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payment_verified: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Rejected {
    pub transaction_id: Value,
    pub reason: &'static str,
    pub display_relevant: bool,
}

/// Python 결과 dict와 같은 모양(분기마다 있는 키만 직렬화한다).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SearchResult {
    pub status: &'static str,
    pub candidates: Vec<Candidate>,
    pub comparisons: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rejected: Option<Vec<Rejected>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rejection_counts: Option<BTreeMap<&'static str, usize>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub date_status: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hard_identity_filter_applied: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reservation_only: Option<bool>,
}

impl SearchResult {
    fn bare(status: &'static str, comparisons: usize) -> Self {
        SearchResult {
            status,
            candidates: Vec::new(),
            comparisons,
            limit: None,
            rejected: None,
            rejection_counts: None,
            date_status: None,
            hard_identity_filter_applied: None,
            reservation_only: None,
        }
    }
}

/// 탐색 결과. 숲나들e·토요코인·라쿠텐 예약 이벤트의 전용 탐색은 U13 범위 밖이라 Python 경로를 쓰도록 넘긴다.
#[derive(Debug, Clone, PartialEq)]
pub enum Search {
    Done(SearchResult),
    /// 공급자 전용 탐색(`forest`·`toyoko`·`rakuten` 예약). Python 어댑터가 처리한다.
    Delegated(&'static str),
}

fn valid_day(v: Option<&Value>) -> bool {
    v.is_some_and(|v| crate::dates::parse_iso(&pystr(v)).is_ok())
}

impl Matcher<'_> {
    fn display_relevant(&self, event: &Value, row: &Value) -> bool {
        let (paid, card) = (get(event, "paid_on"), get(row, "approval_date"));
        truthy(paid)
            && truthy(card)
            && (paid == card
                || self.approved_lag_match(event, row)
                || self.foreign_day_lag_match(event, row))
    }

    /// `search_card_candidates`. `existing_links`는 이벤트 id → 연결(고정)이다.
    pub fn search_card_candidates(
        &self,
        event: &Value,
        transactions: &[Value],
        existing_links: &Map<String, Value>,
        max_comparisons: usize,
    ) -> Search {
        if existing_links.contains_key(&text(event, "ota_event_id")) {
            return Search::Done(SearchResult::bare("USER_PINNED", 0));
        }
        let provider = get(event, "provider").and_then(Value::as_str);
        let reservation = is_str(get(event, "event_type"), "reservation");
        if provider == Some("trip")
            && reservation
            && is_str(get(event, "evidence_status"), "preauthorized")
        {
            return Search::Done(self.preauthorization_candidates(
                event,
                transactions,
                existing_links,
                max_comparisons,
            ));
        }
        if provider == Some("trip") && reservation && truthy(get(event, "price_change_amount_krw"))
        {
            return Search::Done(self.price_change_candidates(event, transactions));
        }
        if reservation {
            for name in ["forest", "toyoko", "rakuten"] {
                if provider == Some(name) {
                    return Search::Delegated(name);
                }
            }
        }
        if !Matcher::event_is_paid(event) {
            return Search::Done(SearchResult::bare("PAYMENT_STATE_UNVERIFIED", 0));
        }
        let want = if is_str(get(event, "event_type"), "refund") {
            "refund"
        } else {
            "purchase"
        };
        let expected_last4 = text(event, "card_last4");
        let mut counts: BTreeMap<&'static str, usize> = BTreeMap::new();
        let mut narrowed: Vec<&Value> = Vec::new();
        for row in transactions {
            if !self.provider_compatible(event, row) {
                continue;
            }
            if truthy(get(row, "duplicate_of")) {
                *counts.entry("CARD_DUPLICATE").or_default() += 1;
                continue;
            }
            if truthy(get(row, "parse_error")) || truthy(get(row, "conflict_reason")) {
                *counts.entry("CARD_FINANCIAL_HOLD").or_default() += 1;
                continue;
            }
            if Matcher::direction(row) != want {
                continue;
            }
            if !self.strict_card_identity(event, row) {
                if !expected_last4.is_empty() || truthy(get(event, "card_issuer")) {
                    *counts.entry("CARD_IDENTITY_MISMATCH").or_default() += 1;
                }
                continue;
            }
            narrowed.push(row);
            if narrowed.len() > max_comparisons {
                let mut r = SearchResult::bare("SEARCH_LIMIT_EXCEEDED", narrowed.len());
                r.limit = Some(max_comparisons);
                return Search::Done(r);
            }
        }
        let mut candidates = Vec::new();
        let mut rejected = Vec::new();
        for row in &narrowed {
            let comparison = self.compare_payment_amount(event, row);
            let id = row.get("transaction_id").cloned().unwrap_or(Value::Null);
            if !comparison.is_match() {
                let reason = comparison.reason.unwrap_or("AMOUNT_MISMATCH");
                *counts.entry(reason).or_default() += 1;
                rejected.push(Rejected {
                    transaction_id: id,
                    reason,
                    display_relevant: self.display_relevant(event, row),
                });
                continue;
            }
            if !self.has_corroborator(event, row) {
                *counts.entry("PROVIDER_ALIAS_MISSING").or_default() += 1;
                rejected.push(Rejected {
                    transaction_id: id,
                    reason: "PROVIDER_ALIAS_MISSING",
                    display_relevant: self.display_relevant(event, row),
                });
                continue;
            }
            let paid_on = truthy(get(event, "paid_on"));
            let date_status = if !paid_on {
                "UNKNOWN"
            } else if get(row, "approval_date") == get(event, "paid_on")
                || self.approved_lag_match(event, row)
                || self.foreign_day_lag_match(event, row)
            {
                "MATCH"
            } else {
                "MISMATCH"
            };
            candidates.push(Candidate {
                transaction_id: id,
                date_status: Some(date_status),
                resolution_allowed: (paid_on && date_status == "MATCH")
                    || self.undated_exact_identity(event, row),
                basis: "EXACT_AMOUNT_AND_CARD_EVIDENCE",
                payment_verified: None,
            });
        }
        Search::Done(SearchResult {
            status: if candidates.is_empty() {
                "NO_CANDIDATE"
            } else {
                "CANDIDATES_FOUND"
            },
            candidates,
            comparisons: narrowed.len(),
            limit: None,
            rejected: Some(rejected),
            rejection_counts: Some(counts),
            date_status: Some(if truthy(get(event, "paid_on")) {
                "KNOWN"
            } else {
                "UNKNOWN"
            }),
            hard_identity_filter_applied: Some(
                !expected_last4.is_empty() || truthy(get(event, "card_issuer")),
            ),
            reservation_only: None,
        })
    }

    /// `_price_change_candidates`: 트립 가격 변경 통지일에 카드에 청구된 인상분(결제 확인이 아니다).
    fn price_change_candidates(&self, event: &Value, transactions: &[Value]) -> SearchResult {
        let empty = || SearchResult {
            rejected: Some(Vec::new()),
            reservation_only: Some(true),
            ..SearchResult::bare("NO_CANDIDATE", 0)
        };
        let (amount, day) = (
            get(event, "price_change_amount_krw"),
            get(event, "price_change_on"),
        );
        let blocked = [
            "evidence_missing",
            "evidence_changed",
            "period_conflict",
            "service_period_conflict",
        ]
        .iter()
        .any(|k| truthy(get(event, k)));
        if !truthy(amount)
            || !truthy(day)
            || is_str(get(event, "reservation_status"), "cancelled")
            || blocked
        {
            return empty();
        }
        // Decimal은 문자열과 같아질 수 없으므로 숫자가 아니면 어떤 카드도 일치하지 않는다.
        let amount = amount
            .filter(|v| v.is_number())
            .and_then(|v| super::decimal::Dec::parse(&pystr(v)));
        let mut candidates = Vec::new();
        let mut comparisons = 0;
        for row in transactions {
            if Matcher::direction(row) != "purchase" || !self.provider_compatible(event, row) {
                continue;
            }
            comparisons += 1;
            let flagged = ["duplicate_of", "parse_error", "conflict_reason"]
                .iter()
                .any(|k| truthy(get(row, k)));
            if get(row, "approval_date") != day
                || amount.is_none()
                || Matcher::card_amount(row) != amount
                || !truthy(get(row, "source_hash"))
                || flagged
            {
                continue;
            }
            candidates.push(Candidate {
                transaction_id: row.get("transaction_id").cloned().unwrap_or(Value::Null),
                date_status: None,
                resolution_allowed: false,
                basis: "PRICE_CHANGE_RISE_AND_DAY",
                payment_verified: Some(false),
            });
        }
        SearchResult {
            status: if candidates.is_empty() {
                "NO_CANDIDATE"
            } else {
                "CANDIDATES_FOUND"
            },
            candidates,
            comparisons,
            rejected: Some(Vec::new()),
            reservation_only: Some(true),
            ..SearchResult::bare("NO_CANDIDATE", 0)
        }
    }

    /// `_preauthorization_candidates`: 같은 날 같은 금액의 카드 원본(결제를 주장하지 않는다).
    fn preauthorization_candidates(
        &self,
        event: &Value,
        transactions: &[Value],
        links: &Map<String, Value>,
        limit: usize,
    ) -> SearchResult {
        let day = get(event, "preauthorized_on");
        if !valid_day(day) {
            return SearchResult::bare("PAYMENT_STATE_UNVERIFIED", 0);
        }
        let occupied: Vec<String> = links
            .values()
            .map(|link| {
                if link.is_object() {
                    pystr(link.get("transaction_id").unwrap_or(&Value::Null))
                } else {
                    pystr(link)
                }
            })
            .collect();
        let probe = {
            let mut e = event.clone();
            if let Some(map) = e.as_object_mut() {
                map.insert(
                    "amount_krw".into(),
                    event
                        .get("preauthorized_amount_krw")
                        .cloned()
                        .unwrap_or(Value::Null),
                );
            }
            e
        };
        let mut candidates = Vec::new();
        let mut comparisons = 0;
        for row in transactions {
            comparisons += 1;
            if comparisons > limit {
                return SearchResult::bare("SEARCH_LIMIT_EXCEEDED", comparisons);
            }
            let known = self
                .defaults
                .provider_for_merchant(&first_text(row, &["merchant_normalized", "merchant"]));
            let flagged = [
                "duplicate_of",
                "parse_error",
                "conflict_reason",
                "ota_review_held",
            ]
            .iter()
            .any(|k| truthy(get(row, k)));
            let id = get(row, "transaction_id");
            if get(row, "approval_date") != day
                || Matcher::direction(row) != "purchase"
                || !truthy(id)
                || flagged
                || id.is_some_and(|i| occupied.contains(&pystr(i)))
                || known.is_some_and(|p| Some(p) != get(event, "provider").and_then(Value::as_str))
                || !self.strict_card_identity(event, row)
            {
                continue;
            }
            if self.compare_with(&probe, row, &[]).is_match() {
                candidates.push(Candidate {
                    transaction_id: row.get("transaction_id").cloned().unwrap_or(Value::Null),
                    date_status: Some("MATCH"),
                    resolution_allowed: false,
                    basis: "PREAUTHORIZATION_SAME_DAY_EXACT_AMOUNT",
                    payment_verified: Some(false),
                });
            }
        }
        SearchResult {
            status: if candidates.is_empty() {
                "NO_CANDIDATE"
            } else {
                "CANDIDATES_FOUND"
            },
            candidates,
            comparisons,
            date_status: Some("KNOWN"),
            ..SearchResult::bare("NO_CANDIDATE", 0)
        }
    }
}
