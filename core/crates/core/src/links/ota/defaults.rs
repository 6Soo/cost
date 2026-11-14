//! `config/ota-matching-defaults.json`(`app/ota_matching_defaults.py`)의 U13이 쓰는 부분.

use super::pyval::{get, is_int, pystr, text, truthy};
use crate::rules::casefold;
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Debug, thiserror::Error)]
pub enum DefaultsError {
    #[error("OTA_MATCHING_DEFAULTS_SCHEMA_INVALID")]
    Schema,
}

#[derive(Debug, Clone)]
pub struct TripDelta {
    pub enabled: bool,
    pub item_values: Vec<String>,
    pub currency: Option<String>,
    pub direction: Option<Value>,
    pub minimum: i64,
    pub maximum: i64,
    pub step: i64,
}

#[derive(Debug, Clone)]
pub struct Defaults {
    /// 공급자 → 가맹점 별칭(원문).
    pub aliases: BTreeMap<String, Vec<String>>,
    /// 공급자 → 승인된 별칭 기록의 별칭(상태 approved, 버전·출처 있음).
    pub approved_aliases: BTreeMap<String, Vec<String>>,
    pub trip_delta: TripDelta,
    pub foreign_date_lag_days: i64,
    pub portal_payment_date_required: bool,
    /// `provider_for_merchant` 해소 순서: 별칭 길이 내림차순(같으면 공급자 이름순, 별칭 등록순).
    resolution: Vec<(String, String)>,
}

fn string_list(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array)
        .map(|a| a.iter().map(pystr).collect())
        .unwrap_or_default()
}

impl Defaults {
    pub fn from_value(value: &Value) -> Result<Defaults, DefaultsError> {
        if get(value, "schema_version").and_then(Value::as_str) != Some("ota-matching-defaults-v1")
        {
            return Err(DefaultsError::Schema);
        }
        let mut aliases = BTreeMap::new();
        if let Some(map) = get(value, "provider_merchant_aliases").and_then(Value::as_object) {
            for (provider, list) in map {
                aliases.insert(provider.clone(), string_list(Some(list)));
            }
        }
        let mut approved_aliases = BTreeMap::new();
        if let Some(map) = get(value, "provider_merchant_alias_records").and_then(Value::as_object)
        {
            for (provider, records) in map {
                let list: Vec<String> = records
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|r| {
                        get(r, "status").and_then(Value::as_str) == Some("approved")
                            && truthy(get(r, "version"))
                            && truthy(get(r, "source"))
                    })
                    .map(|r| text(r, "alias"))
                    .collect();
                approved_aliases.insert(provider.clone(), list);
            }
        }
        let delta = get(value, "trip_flight_charge_delta")
            .cloned()
            .unwrap_or(Value::Null);
        let int_or = |key: &str, default: i64| {
            get(&delta, key)
                .and_then(|v| is_int(v).then(|| v.as_i64()).flatten())
                .unwrap_or(default)
        };
        let trip_delta = TripDelta {
            enabled: truthy(get(&delta, "enabled")),
            item_values: string_list(get(&delta, "item_values")),
            currency: get(&delta, "currency").map(pystr),
            direction: get(&delta, "direction").cloned(),
            minimum: int_or("minimum_delta_krw", -10_000),
            maximum: int_or("maximum_delta_krw", -1_000),
            step: int_or("step_krw", -1_000),
        };
        let lag = get(value, "foreign_date_lag_days")
            .filter(|v| is_int(v))
            .and_then(Value::as_i64)
            .filter(|n| (0..=7).contains(n))
            .unwrap_or(0);
        let required = get(value, "portal_payment_date_required").is_none_or(|v| truthy(Some(v)));
        let mut resolution: Vec<(usize, String, String)> = Vec::new();
        for (provider, list) in &aliases {
            resolution.extend(
                list.iter()
                    .map(|a| (a.chars().count(), a.clone(), provider.clone())),
            );
        }
        for (provider, list) in &approved_aliases {
            resolution.extend(
                list.iter()
                    .map(|a| (a.chars().count(), a.clone(), provider.clone())),
            );
        }
        resolution.sort_by_key(|(len, _, _)| std::cmp::Reverse(*len));
        let resolution = resolution
            .into_iter()
            .filter(|(_, alias, _)| !alias.is_empty())
            .map(|(_, alias, provider)| (casefold(&alias), provider))
            .collect();
        Ok(Defaults {
            aliases,
            approved_aliases,
            trip_delta,
            foreign_date_lag_days: lag,
            portal_payment_date_required: required,
            resolution,
        })
    }

    /// `provider_for_merchant`: 별칭이 가맹점 문자열에 들어 있는 공급자.
    pub fn provider_for_merchant(&self, merchant: &str) -> Option<&str> {
        let value = casefold(merchant);
        if value.is_empty() {
            return None;
        }
        self.resolution
            .iter()
            .find(|(alias, _)| value.contains(alias.as_str()))
            .map(|(_, provider)| provider.as_str())
    }
}
