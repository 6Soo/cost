//! 가맹점 표기·카드 식별·공급자 호환·보강 근거와 쌍 검사(`_descriptor_matches`·`_strict_card_identity`·
//! `provider_compatible`·`_has_corroborator`·`_undated_exact_identity`·`_eligible_cards`·`pair_check`).

use super::Matcher;
use super::pyval::{
    first_text, first_truthy, get, is_str, pystr, rule_inactive, same, text, truthy,
};
use super::rule_scope::{four_digits, rule_scope_valid};
use crate::rules::casefold;
use serde_json::Value;

const MERCHANT_KEYS: [&str; 10] = [
    "merchant_normalized",
    "merchant",
    "merchant_extended",
    "merchant_name_extended",
    "extended_merchant_name",
    "expanded_merchant_name",
    "merchant_name",
    "가맹점명",
    "가맹점명(확장)",
    "확장가맹점명",
];

/// `unicodedata.normalize('NFKC')`의 근사: 전각 ASCII(U+FF01..FF5E)와 전각 공백만 접는다.
fn nfkc_lite(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            '\u{3000}' => ' ',
            '\u{FF01}'..='\u{FF5E}' => char::from_u32(u32::from(c) - 0xFEE0).unwrap_or(c),
            _ => c,
        })
        .collect()
}

/// `re.search(rf"(?<![^\W_]){name}(?![^\W_])")`(`underscore_blocks=false`) 또는 `(?<!\w){name}(?!\w)`(`true`).
fn contains_bounded(hay: &str, needle: &str, underscore_blocks: bool) -> bool {
    let blocks = |c: char| c.is_alphanumeric() || (underscore_blocks && c == '_');
    hay.char_indices().any(|(i, _)| {
        hay[i..].starts_with(needle)
            && !hay[..i].chars().next_back().is_some_and(blocks)
            && !hay[i + needle.len()..].chars().next().is_some_and(blocks)
    })
}

/// `re.sub(r"\W", "", s).casefold()`.
fn word_chars(s: &str) -> String {
    casefold(
        &s.chars()
            .filter(|c| c.is_alphanumeric() || *c == '_')
            .collect::<String>(),
    )
}

impl Matcher<'_> {
    /// `_merchant_descriptors`: 가져온 표기와 확장 표기를 접어 중복 없이 모은다.
    pub(super) fn merchant_descriptors(row: &Value) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for key in MERCHANT_KEYS {
            if truthy(get(row, key)) {
                let folded = casefold(&nfkc_lite(&text(row, key)));
                if !out.contains(&folded) {
                    out.push(folded);
                }
            }
        }
        out
    }

    /// `_descriptor_matches`: 승인된 공급자 별칭(기본 설정 기록 + 승인 규칙)이 가맹점 표기에 들어 있는가.
    pub(super) fn descriptor_matches(&self, event: &Value, row: &Value) -> bool {
        let merchants = Matcher::merchant_descriptors(row);
        let provider = casefold(&text(event, "provider"));
        let mut approved: Vec<String> = self
            .defaults
            .approved_aliases
            .get(&provider)
            .cloned()
            .unwrap_or_default();
        for rule in self.rules {
            let c = get(rule, "conditions").unwrap_or(&Value::Null);
            if rule_inactive(rule) {
                continue;
            }
            if get(c, "rule_kind").and_then(Value::as_str) == Some("provider_alias")
                && rule_scope_valid(c)
                && casefold(&text(c, "provider")) == provider
                && truthy(get(c, "approval_source"))
                && truthy(get(c, "alias_version"))
                && truthy(get(rule, "approved_by"))
            {
                approved.push(pystr(&c["alias"]));
            }
        }
        approved.iter().filter(|n| !n.is_empty()).any(|name| {
            let name = casefold(name);
            merchants.iter().any(|m| contains_bounded(m, &name, false))
        })
    }

    /// `_strict_card_identity`: 이벤트가 말하는 끝 4자리·발급사·승인번호가 카드 행과 모순되지 않는가.
    pub(super) fn strict_card_identity(&self, event: &Value, row: &Value) -> bool {
        let hint = text(event, "card_last4");
        let card_tail = first_text(row, &["card_tail", "card_last4"]);
        if !hint.is_empty() && (!four_digits(&hint) || card_tail != hint) {
            return false;
        }
        let issuer = first_truthy(event, &["card_issuer", "issuer"]);
        let row_issuer = text(row, "issuer");
        if let Some(issuer) = issuer {
            let issuer = pystr(issuer);
            if casefold(&issuer) != casefold(&row_issuer)
                && !self.issuer_alias_approved(event, &issuer, &row_issuer)
            {
                return false;
            }
        }
        let ota_auth = first_truthy(event, &["authorization_number", "approval_number"]);
        let card_auth = first_truthy(
            row,
            &[
                "authorization_number",
                "approval_number",
                "authorization_id",
            ],
        );
        let ota_scheme = first_truthy(
            event,
            &["authorization_scheme", "authorization_number_scheme"],
        );
        let card_scheme = first_truthy(
            row,
            &["authorization_scheme", "authorization_number_scheme"],
        );
        if let (Some(a), Some(b), Some(s1), Some(s2)) =
            (ota_auth, card_auth, ota_scheme, card_scheme)
            && s1 == s2
            && pystr(a).trim() != pystr(b).trim()
        {
            return false;
        }
        true
    }

    fn issuer_alias_approved(&self, event: &Value, issuer: &str, row_issuer: &str) -> bool {
        self.rules.iter().any(|rule| {
            let c = get(rule, "conditions")
                .filter(|c| truthy(Some(c)))
                .unwrap_or(&Value::Null);
            Matcher::rule_approved(rule)
                && (!super::pyval::has(rule, "active") || truthy(get(rule, "active")))
                && !matches!(
                    text(rule, "status").to_lowercase().as_str(),
                    "inactive" | "revoked"
                )
                && get(c, "rule_kind").and_then(Value::as_str) == Some("issuer_alias")
                && rule_scope_valid(c)
                && pystr(c.get("provider").unwrap_or(&Value::Null))
                    == pystr(get(event, "provider").unwrap_or(&Value::Null))
                && casefold(&text_or_empty(c, "event_issuer_alias")) == casefold(issuer)
                && casefold(&text_or_empty(c, "issuer")) == casefold(row_issuer)
                && truthy(get(c, "approval_source"))
                && truthy(get(c, "alias_version"))
        })
    }

    /// `_same_day_exact_amount`: 결제일과 원통화 금액이 같으면 보강 근거가 된다(소유자 2026-10-29).
    pub(super) fn same_day_exact_amount(&self, event: &Value, row: &Value) -> bool {
        let paid_on = get(event, "paid_on");
        if !truthy(paid_on)
            || !same(get(row, "approval_date"), paid_on)
            || !Matcher::event_is_paid(event)
            || crate::dates::parse_iso(&text(event, "paid_on")).is_err()
        {
            return false;
        }
        let want = if is_str(get(event, "event_type"), "refund") {
            "refund"
        } else {
            "purchase"
        };
        Matcher::direction(row) == want && self.compare_with(event, row, &[]).is_match()
    }

    /// `provider_compatible`: 서로 모순되는 OTA 브랜드를 걸러낸다(표기를 모르면 날짜·금액으로 진행).
    pub fn provider_compatible(&self, event: &Value, row: &Value) -> bool {
        let provider = casefold(&text(event, "provider"));
        if provider == "toyoko" {
            return true;
        }
        let merchant = casefold(&first_text(row, &["merchant_normalized", "merchant"]));
        let descriptors = Matcher::merchant_descriptors(row);
        let known: Vec<&str> = descriptors
            .iter()
            .filter_map(|d| self.defaults.provider_for_merchant(d))
            .filter(|p| !p.is_empty())
            .collect();
        if known.iter().any(|p| *p != provider) {
            return false;
        }
        if provider == "forest" && is_str(get(event, "evidence_kind"), "forest_portal") {
            let facility = word_chars(&text(event, "hotel_name"));
            return !facility.is_empty() && descriptors.iter().any(|d| facility == word_chars(d));
        }
        if matches!(
            provider.as_str(),
            "asiana" | "skyticket" | "jeju" | "traveloka"
        ) {
            return known.contains(&provider.as_str());
        }
        if provider == "trip" {
            return self.same_day_exact_amount(event, row)
                || self.undated_exact_identity(event, row)
                || self.descriptor_matches(event, row)
                || self
                    .defaults
                    .aliases
                    .get("trip")
                    .into_iter()
                    .flatten()
                    .filter(|a| !a.is_empty())
                    .any(|a| contains_bounded(&merchant, &casefold(a), true));
        }
        true
    }

    /// `_has_corroborator`: 금액·날짜 말고 이 쌍을 뒷받침하는 근거가 있는가.
    pub(super) fn has_corroborator(&self, event: &Value, row: &Value) -> bool {
        if !self.provider_compatible(event, row) {
            return false;
        }
        if get(event, "provider").and_then(Value::as_str) == Some("forest")
            && is_str(
                get(event, "evidence_kind"),
                "authenticated_forest_pg_card_receipt",
            )
        {
            return is_str(get(event, "authorization_scheme"), "issuer_card_approval")
                && truthy(get(row, "issuer"))
                && four_digits(&text(row, "card_tail"))
                && same(get(row, "approval_date"), get(event, "paid_on"))
                && Matcher::card_amount(row) == Matcher::event_amount(event)
                && truthy(get(event, "approval_number"))
                && text(event, "approval_number").trim() == text(row, "approval_number").trim();
        }
        if self.same_day_exact_amount(event, row) {
            return true;
        }
        let hint = text(event, "card_last4");
        if !hint.is_empty() && first_text(row, &["card_tail", "card_last4"]) == hint {
            return true;
        }
        let ota_auth = first_truthy(event, &["authorization_number", "approval_number"]);
        let card_auth = first_truthy(
            row,
            &[
                "authorization_number",
                "approval_number",
                "authorization_id",
            ],
        );
        let ota_scheme = first_truthy(
            event,
            &["authorization_scheme", "authorization_number_scheme"],
        );
        let card_scheme = first_truthy(
            row,
            &["authorization_scheme", "authorization_number_scheme"],
        );
        if let (Some(a), Some(b), Some(s1)) = (ota_auth, card_auth, ota_scheme)
            && Some(s1) == card_scheme
            && pystr(a) == pystr(b)
        {
            return true;
        }
        let ota_payment = get(event, "payment_id").filter(|v| truthy(Some(v)));
        let card_payment = first_truthy(row, &["payment_id", "ota_payment_id"]);
        let ota_pay_scheme = first_truthy(event, &["payment_id_scheme", "payment_scheme"]);
        let card_pay_scheme = first_truthy(row, &["payment_id_scheme", "payment_scheme"]);
        if let (Some(a), Some(b), Some(s1)) = (ota_payment, card_payment, ota_pay_scheme)
            && Some(s1) == card_pay_scheme
            && pystr(a) == pystr(b)
        {
            return true;
        }
        if casefold(&text(event, "provider")) == "trip" {
            return self.provider_compatible(event, row);
        }
        self.descriptor_matches(event, row) || self.rule_matches(event, row)
    }

    /// `_undated_exact_identity`: 결제일이 없는 이벤트는 가맹점·원금액·카드 끝 4자리가 날짜를 대신한다(소유자 2026-11-01).
    pub(super) fn undated_exact_identity(&self, event: &Value, row: &Value) -> bool {
        let tail = text(event, "card_last4");
        if truthy(get(event, "paid_on"))
            || !Matcher::event_is_paid(event)
            || !four_digits(&tail)
            || tail != first_text(row, &["card_tail", "card_last4"])
            || !self.compare_with(event, row, &[]).is_match()
        {
            return false;
        }
        if text(event, "currency").to_uppercase() == "KRW"
            && Matcher::card_amount(row).map(super::decimal::Dec::abs)
                != Matcher::event_amount(event)
        {
            return false;
        }
        if self.descriptor_matches(event, row) {
            return true;
        }
        let provider = casefold(&text(event, "provider"));
        let descriptors = Matcher::merchant_descriptors(row);
        self.defaults
            .aliases
            .get(&provider)
            .into_iter()
            .flatten()
            .filter(|a| !a.is_empty())
            .any(|alias| {
                let alias = casefold(alias);
                descriptors
                    .iter()
                    .any(|d| contains_bounded(d, &alias, false))
            })
    }

    fn row_flagged(row: &Value) -> bool {
        ["duplicate_of", "parse_error", "conflict_reason"]
            .iter()
            .any(|k| truthy(get(row, k)))
    }

    fn date_ok(&self, event: &Value, row: &Value) -> bool {
        let paid_on = get(event, "paid_on");
        !truthy(paid_on)
            || same(get(row, "approval_date"), paid_on)
            || self.approved_lag_match(event, row)
            || self.foreign_day_lag_match(event, row)
    }

    /// `_eligible_cards`: 이벤트에 대해 모든 승인 조건을 통과한 카드 행의 위치(입력 순서).
    /// 결제 미확인 이벤트와 결제일·끝 4자리가 모두 없는 이벤트는 후보가 없다.
    pub fn eligible_cards(&self, event: &Value, transactions: &[Value]) -> Vec<usize> {
        if !Matcher::event_is_paid(event)
            || (!truthy(get(event, "paid_on")) && !four_digits(&text(event, "card_last4")))
        {
            return Vec::new();
        }
        let want = if is_str(get(event, "event_type"), "refund") {
            "refund"
        } else {
            "purchase"
        };
        let last4 = text(event, "card_last4");
        let dated = truthy(get(event, "paid_on"));
        transactions
            .iter()
            .enumerate()
            .filter(|(_, row)| {
                !Matcher::row_flagged(row)
                    && Matcher::direction(row) == want
                    && self.date_ok(event, row)
                    && (last4.is_empty()
                        || first_text(row, &["card_tail", "card_last4"]).ends_with(&last4))
                    && self.amount_matches(event, row)
                    && self.strict_card_identity(event, row)
                    && self.provider_compatible(event, row)
                    && (dated || self.undated_exact_identity(event, row))
                    && self.has_corroborator(event, row)
            })
            .map(|(i, _)| i)
            .collect()
    }

    /// `pair_check`: 이벤트와 카드 행 한 쌍을 코어 규칙으로만 확인한다. 통과하면 `None`, 막히면 사유 코드.
    pub fn pair_check(&self, event: &Value, row: &Value) -> Option<&'static str> {
        if Matcher::row_flagged(row) {
            return Some("row_flagged");
        }
        if !self.provider_compatible(event, row) {
            return Some("provider");
        }
        if !truthy(get(event, "paid_on"))
            && self.defaults.portal_payment_date_required
            && !self.undated_exact_identity(event, row)
        {
            return Some("payment_date_unknown");
        }
        if !self.strict_card_identity(event, row) {
            return Some("card_identity");
        }
        let want = if is_str(get(event, "event_type"), "refund") {
            "refund"
        } else {
            "purchase"
        };
        if Matcher::direction(row) != want {
            return Some("direction");
        }
        if !self.amount_matches(event, row) {
            return Some("amount");
        }
        if !self.date_ok(event, row) {
            return Some("date");
        }
        let last4 = text(event, "card_last4");
        if !last4.is_empty() && !first_text(row, &["card_tail", "card_last4"]).ends_with(&last4) {
            return Some("card_identity");
        }
        if !self.has_corroborator(event, row) {
            return Some("corroboration");
        }
        None
    }
}

/// `str(c.get(key, ""))`: 키가 없을 때만 빈 문자열이고 null은 `"None"`이다.
fn text_or_empty(c: &Value, key: &str) -> String {
    c.get(key).map_or_else(String::new, pystr)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_search_matches_python_lookarounds() {
        assert!(contains_bounded("agoda_nice", "agoda", false)); // 밑줄은 경계
        assert!(!contains_bounded("agoda_nice", "agoda", true)); // \w 는 밑줄 포함
        assert!(contains_bounded("a agoda b", "agoda", true));
        assert!(!contains_bounded("nottrip.commercial", "trip.com", true));
        assert!(contains_bounded("aaagoda agoda", "agoda", false));
    }

    #[test]
    fn nfkc_lite_folds_fullwidth_ascii() {
        assert_eq!(nfkc_lite("ＡＧＯＤＡ\u{3000}１"), "AGODA 1");
    }
}
