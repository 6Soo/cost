use super::{decimal, digest, event_id, strings, truthy, union};
use serde_json::{Value, json};
use std::collections::BTreeMap;

pub fn event_semantic_conflict(left: &Value, right: &Value) -> bool {
    for key in [
        "provider",
        "booking_ref",
        "event_type",
        "currency",
        "card_last4",
        "service_period",
        "payment_id",
        "paid_on",
    ] {
        if !left[key].is_null() && !right[key].is_null() && left[key] != right[key] {
            return true;
        }
    }
    if !left["amount"].is_null() && !right["amount"].is_null() {
        let a = decimal(&left["amount"]);
        let b = decimal(&right["amount"]);
        if a.is_none() || b.is_none() || a != b {
            return true;
        }
    }
    false
}

/// Preserve first-source fields and identity; combine only evidence lists.
/// Callers supply a nonempty group. An empty group returns null.
pub fn combine_evidence(group: &[Value], conflict: bool) -> Value {
    let Some(first) = group.first() else {
        return Value::Null;
    };
    let mut item = first.clone();
    item["source_ids"] = json!(union(group, "source_ids", false));
    let mut digests = std::collections::BTreeSet::new();
    for event in group {
        let mut values = strings(event, "source_digests");
        if values.is_empty()
            && let Some(d) = event["source_digest"].as_str()
        {
            values.push(d.to_owned());
        }
        digests.extend(values.into_iter().filter(|s| !s.is_empty()));
    }
    let digests: Vec<String> = digests.into_iter().collect();
    item["source_digests"] = json!(digests);
    item["source_digest"] = json!(if digests.len() == 1 {
        digests[0].clone()
    } else {
        digest(&json!(digests))
    });
    for key in [
        "source_binding_ids",
        "source_lineage_ids",
        "observation_ids",
    ] {
        item[key] = json!(union(group, key, key == "source_lineage_ids"));
    }
    if !conflict
        && first["_portal_reservation_provenance"].is_object()
        && group
            .iter()
            .all(|e| e["_portal_reservation_provenance"] == first["_portal_reservation_provenance"])
    {
        if !first["reservation_identity_attestation"].is_object()
            || !group.iter().all(|e| {
                e["reservation_identity_attestation"] == first["reservation_identity_attestation"]
            })
        {
            remove(&mut item, "reservation_identity_attestation");
        }
    } else {
        remove(&mut item, "_portal_reservation_provenance");
        remove(&mut item, "reservation_identity_attestation");
    }
    combine_mail_identity(&mut item, group, conflict);
    if conflict {
        item["evidence_status"] = json!("evidence_conflict");
    }
    let identity = if truthy(&item["identity_source_ids"]) {
        &item["identity_source_ids"]
    } else {
        &item["source_ids"]
    };
    item["ota_event_id"] = json!(event_id(identity));
    item
}

fn remove(value: &mut Value, key: &str) {
    if let Some(object) = value.as_object_mut() {
        object.remove(key);
    }
}

fn combine_mail_identity(item: &mut Value, group: &[Value], conflict: bool) {
    let first = &group[0];
    let proof = &first["_mail_reservation_provenance"];
    let valid = !conflict
        && proof.is_object()
        && group.iter().all(|event| {
            let p = &event["_mail_reservation_provenance"];
            let a = &event["reservation_identity_attestation"];
            p.is_object()
                && a.is_object()
                && [
                    "kind",
                    "provider",
                    "identity",
                    "booking_ref",
                    "source_lineage_id",
                ]
                .iter()
                .all(|key| p[key] == proof[key])
                && a["identity"] == proof["identity"]
                && ["identity_status", "evidence_status", "source_status"]
                    .iter()
                    .all(|key| a[key] == "verified")
        });
    if !valid {
        remove(item, "_mail_reservation_provenance");
        return;
    }
    item["_mail_reservation_provenance"] = proof.clone();
    item["_mail_reservation_provenance"]["source_digest"] = item["source_digest"].clone();
    item["reservation_identity_attestation"] = first["reservation_identity_attestation"].clone();
    let attestations: Vec<Value> = group
        .iter()
        .map(|e| e["reservation_identity_attestation"].clone())
        .collect();
    item["reservation_identity_attestation"]["evidence_link_ids"] =
        json!(union(&attestations, "evidence_link_ids", false));
}

fn compatible(left: &Value, right: &Value) -> bool {
    if truthy(&left["payment_id"]) && truthy(&right["payment_id"]) {
        return left["payment_id"] == right["payment_id"];
    }
    let left_bindings = strings(left, "source_binding_ids");
    let right_bindings = strings(right, "source_binding_ids");
    strings(right, "source_ids")
        .iter()
        .any(|s| left_bindings.contains(s))
        || strings(left, "source_ids")
            .iter()
            .any(|s| right_bindings.contains(s))
}

/// Merge only mutually unique proof edges. Even a three-observation clique is
/// ambiguous and stays separate; equal amounts alone never supply an edge.
pub fn merge_proven_duplicate_payments(events: &[Value]) -> Vec<Value> {
    let mut buckets: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for (i, event) in events.iter().enumerate() {
        buckets
            .entry(super::digest(&json!([
                event["provider"],
                event["booking_ref"],
                event["event_type"]
            ])))
            .or_default()
            .push(i);
    }
    let mut paired = Vec::new();
    let mut degree = vec![0; events.len()];
    for members in buckets.values() {
        for (position, &i) in members.iter().enumerate() {
            for &j in &members[position + 1..] {
                if compatible(&events[i], &events[j]) {
                    paired.push((i, j));
                    degree[i] += 1;
                    degree[j] += 1;
                }
            }
        }
    }
    paired.sort_unstable();
    let mut parent: Vec<usize> = (0..events.len()).collect();
    for (i, j) in paired {
        if degree[i] == 1 && degree[j] == 1 {
            parent[j] = i;
        }
    }
    let mut groups: BTreeMap<usize, Vec<Value>> = BTreeMap::new();
    for (i, event) in events.iter().enumerate() {
        groups.entry(parent[i]).or_default().push(event.clone());
    }
    groups
        .into_values()
        .map(|group| {
            if group.len() == 1 {
                group[0].clone()
            } else {
                let conflict = group[1..]
                    .iter()
                    .any(|other| event_semantic_conflict(&group[0], other));
                combine_evidence(&group, conflict)
            }
        })
        .collect()
}
