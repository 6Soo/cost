use super::{amount, decimal, digest, is_paid, text, truthy, union};
use crate::dates::parse_iso;
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn day(event: &Value, key: &str) -> Option<time::Date> {
    parse_iso(event[key].as_str()?).ok()
}

fn attach_evidence(receipt: &mut Value, portals: &[Value]) {
    for key in ["source_ids", "source_digests", "observation_ids"] {
        let mut group = vec![receipt.clone()];
        group.extend_from_slice(portals);
        receipt[key] = json!(union(&group, key, false));
    }
    receipt["source_digest"] = json!(digest(&receipt["source_digests"]));
}

pub(super) fn attach_periods(
    mut events: Vec<Value>,
    portals: &[Value],
    names: &BTreeMap<String, String>,
) -> Vec<Value> {
    let mut remaining = Vec::new();
    for portal in portals {
        let receipts: Vec<usize> = events
            .iter()
            .enumerate()
            .filter_map(|(i, e)| {
                (text(e, "evidence_kind") == "authenticated_forest_pg_card_receipt"
                    && truthy(&portal["order_number"])
                    && e["order_number"] == portal["order_number"]
                    && is_paid(portal)
                    && is_paid(e)
                    && e["paid_on"] == portal["paid_on"]
                    && amount(e) == amount(portal))
                .then_some(i)
            })
            .collect();
        if receipts.is_empty() {
            remaining.push(portal.clone());
            continue;
        }
        for i in receipts {
            let receipt = &mut events[i];
            if truthy(&receipt["service_period"])
                && receipt["service_period"] != portal["service_period"]
            {
                receipt["service_period_conflict"] = json!(true);
                continue;
            }
            for key in [
                "service_period",
                "reservation_status",
                "booking_ref",
                "item",
            ] {
                receipt[key] = portal[key].clone();
            }
            attach_evidence(receipt, std::slice::from_ref(portal));
        }
    }
    for receipt in &mut events {
        if text(receipt, "evidence_kind") != "authenticated_forest_pg_card_receipt"
            || !is_paid(receipt)
            || text(receipt, "event_type") != "charge"
            || truthy(&receipt["service_period"])
            || truthy(&receipt["service_period_conflict"])
        {
            continue;
        }
        let mut candidates = Vec::new();
        let mut application_unknown = false;
        for portal in portals {
            let reservation = decimal(&portal["reservation_amount_krw"]);
            if truthy(&portal["paid_on"])
                || !reservation.as_ref().is_some_and(|v| v.is_positive())
                || reservation != amount(receipt)
                || portal["currency"] != receipt["currency"]
                || (truthy(&portal["card_last4"]) && portal["card_last4"] != receipt["card_last4"])
            {
                continue;
            }
            let name = &names[text(portal, "hotel_name")];
            if name.is_empty() || name != &names[text(receipt, "merchant_name")] {
                continue;
            }
            let Some(lag) = day(receipt, "paid_on")
                .zip(day(portal, "booked_on"))
                .map(|(a, b)| (a - b).whole_days())
            else {
                application_unknown = true;
                continue;
            };
            if (0..=7).contains(&lag) {
                candidates.push(portal.clone());
            }
        }
        let Some(first) = candidates.first() else {
            continue;
        };
        if application_unknown
            || candidates.iter().any(|p| {
                p["service_period"] != first["service_period"]
                    || p["evidence_status"] == "conflict"
                    || !matches!(
                        text(p, "reservation_status"),
                        "confirmed" | "completed" | "observed"
                    )
            })
        {
            continue;
        }
        let period = &first["service_period"];
        let Some((start, end)) = day(period, "starts_on").zip(day(period, "ends_on")) else {
            continue;
        };
        if start >= end {
            continue;
        }
        receipt["service_period"] = period.clone();
        receipt["service_period_basis"] = json!("LINK-108");
        receipt["reservation_status"] = json!("observed");
        receipt["item"] = json!("숙박비");
        attach_evidence(receipt, &candidates);
    }
    events.extend(remaining);
    events
}
