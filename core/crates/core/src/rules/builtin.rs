//! 내장 규칙 표(`core/rules/builtin/*.json`)의 형식·적재·평가. 설계 §4.1. 코드에 박혀 있던 가맹점 패턴·카드사 업종·
//! skyticket 기본값(`app/classify.py:49-101`, `:417-444`)과 공급자 별칭(`app/ota_matching_defaults.py`)을 데이터로 옮겼다.

use super::{RuleError, text::casefold};
use crate::domain::PolicyRef;
use regex::Regex;
use serde::Deserialize;
use serde_json::{Map, Value};
use std::collections::BTreeSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    MerchantExact,
    MerchantPattern,
    CardCategory,
    ProviderDefault,
    OwnerException,
    InferredAssignment,
    ItemKeyword,
}

impl Kind {
    /// 이 종류의 평가 단계(설계 §4.2). 적재 때 표의 `stage`와 맞는지 검사한다. U5가 옮긴 종류만 있다.
    fn stage(self) -> Option<u32> {
        match self {
            Kind::CardCategory => Some(30),
            Kind::ProviderDefault => Some(35),
            Kind::MerchantPattern => Some(40),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Strength {
    Exact,
    Inferred,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Attribution {
    None,
    VerifiedLocalTrip,
    QuarterOfPayment,
    OwnerTrip,
    InferredTripId,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct MerchantCondition {
    equals_or_prefix: Option<String>,
    compact_regex: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Conditions {
    merchant: Option<MerchantCondition>,
    card_category: Option<Vec<String>>,
    provider: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Effects {
    pub item: String,
    #[serde(default)]
    pub description: String,
}

/// 내장 규칙 한 줄(설계 §4.1 표 형식). `basis`는 판정 근거 문구(카드사 업종은 뒤에 업종명이 붙는다).
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuiltinRule {
    pub rule_id: String,
    pub version: u32,
    pub kind: Kind,
    pub strength: Strength,
    pub stage: u32,
    pub policy_refs: Vec<String>,
    conditions: Conditions,
    pub scope: Map<String, Value>,
    pub effects: Effects,
    pub attribution: Attribution,
    pub origin: String,
    pub basis: String,
}

enum Matcher {
    EqualsOrPrefix(String),
    CompactRegex(Regex),
    Category(BTreeSet<String>),
    Provider(String),
}

struct Entry {
    rule: BuiltinRule,
    matcher: Matcher,
}

#[derive(Deserialize)]
struct Alias {
    alias: String,
    provider: String,
}

/// 적재된 내장 규칙. 평가 순서는 (`stage`, 파일 순서)다.
pub struct Builtin {
    entries: Vec<Entry>,
    aliases: Vec<(String, String)>,
}

const MERCHANT_PATTERN: &str = include_str!("../../../../rules/builtin/merchant_pattern.json");
const CARD_CATEGORY: &str = include_str!("../../../../rules/builtin/card_category.json");
const PROVIDER_DEFAULT: &str = include_str!("../../../../rules/builtin/provider_default.json");
const PROVIDER_ALIASES: &str = include_str!("../../../../rules/builtin/provider_aliases.json");

fn parse<T: for<'de> Deserialize<'de>>(name: &str, json: &str) -> Result<T, RuleError> {
    serde_json::from_str(json)
        .map_err(|e| RuleError::invalid(format!("내장 규칙 {name}을 읽을 수 없어요: {e}")))
}

impl Builtin {
    /// 레포에 포함된 내장 규칙 표.
    pub fn embedded() -> Result<Builtin, RuleError> {
        Builtin::load(
            &[MERCHANT_PATTERN, CARD_CATEGORY, PROVIDER_DEFAULT],
            PROVIDER_ALIASES,
        )
    }

    /// 규칙 표 JSON들과 공급자 별칭 JSON을 읽고 검사한다. 모르는 필드·종류·단계 불일치·중복 ID·깨진 정규식은 거부한다.
    pub fn load(rule_files: &[&str], aliases_json: &str) -> Result<Builtin, RuleError> {
        let mut entries = Vec::new();
        let mut seen = BTreeSet::new();
        for json in rule_files {
            let rules: Vec<BuiltinRule> = parse("표", json)?;
            for rule in rules {
                if !seen.insert(rule.rule_id.clone()) {
                    return Err(RuleError::invalid(format!(
                        "내장 규칙 ID가 겹쳐요: {}",
                        rule.rule_id
                    )));
                }
                let matcher = validate(&rule)?;
                entries.push(Entry { rule, matcher });
            }
        }
        entries.sort_by_key(|e| e.rule.stage);
        let aliases: Vec<Alias> = parse("공급자 별칭", aliases_json)?;
        let mut aliases: Vec<(String, String)> = aliases
            .into_iter()
            .filter(|a| !a.alias.is_empty())
            .map(|a| (casefold(&a.alias), a.provider))
            .collect();
        aliases.sort_by_key(|(alias, _)| std::cmp::Reverse(alias.chars().count()));
        Ok(Builtin { entries, aliases })
    }

    pub fn rules(&self) -> impl Iterator<Item = &BuiltinRule> {
        self.entries.iter().map(|e| &e.rule)
    }

    /// `_pattern_for`: 첫 일치 가맹점 패턴. 이름이 그대로이거나 `이름 `으로 시작하는 패턴이 먼저, 정규식은 그 뒤다.
    pub(crate) fn pattern_for(&self, merchant_normalized: &str) -> Option<&BuiltinRule> {
        let name: String = casefold(merchant_normalized)
            .chars()
            .filter(|c| !(c.is_whitespace() || "._()-·,".contains(*c)))
            .collect();
        self.entries
            .iter()
            .filter(|e| e.rule.kind == Kind::MerchantPattern)
            .find(|e| match &e.matcher {
                Matcher::EqualsOrPrefix(needle) => {
                    merchant_normalized == needle
                        || merchant_normalized
                            .strip_prefix(needle.as_str())
                            .is_some_and(|rest| rest.starts_with(' '))
                }
                Matcher::CompactRegex(re) => re.is_match(&name),
                _ => false,
            })
            .map(|e| &e.rule)
    }

    /// 카드사 업종이 속한 첫 항목 묶음.
    pub(crate) fn category_for(&self, industry: &str) -> Option<&BuiltinRule> {
        self.entries
            .iter()
            .filter(|e| e.rule.kind == Kind::CardCategory)
            .find(|e| matches!(&e.matcher, Matcher::Category(set) if set.contains(industry)))
            .map(|e| &e.rule)
    }

    /// `provider_for_merchant`: 가장 긴 별칭이 이긴다(같은 길이는 표 순서).
    pub fn provider_for(&self, merchant: &str) -> Option<&str> {
        let value = casefold(merchant);
        if value.is_empty() {
            return None;
        }
        self.aliases
            .iter()
            .find(|(alias, _)| value.contains(alias.as_str()))
            .map(|(_, provider)| provider.as_str())
    }

    /// 공급자 기본값 규칙: 가맹점이 그 공급자로 풀리면 걸린다.
    pub(crate) fn provider_default_for(&self, merchant_normalized: &str) -> Option<&BuiltinRule> {
        let provider = self.provider_for(merchant_normalized)?;
        self.entries
            .iter()
            .filter(|e| e.rule.kind == Kind::ProviderDefault)
            .find(|e| matches!(&e.matcher, Matcher::Provider(p) if p == provider))
            .map(|e| &e.rule)
    }
}

fn validate(rule: &BuiltinRule) -> Result<Matcher, RuleError> {
    let bad = |m: &str| {
        Err(RuleError::invalid(format!(
            "내장 규칙 {}: {m}",
            rule.rule_id
        )))
    };
    if rule.rule_id.trim().is_empty() || rule.effects.item.trim().is_empty() {
        return bad("규칙 ID와 항목은 비어 있을 수 없어요");
    }
    match rule.kind.stage() {
        None => return bad("이 단위가 옮기지 않은 규칙 종류예요"),
        Some(stage) if stage != rule.stage => return bad("단계가 규칙 종류의 평가 순서와 달라요"),
        Some(_) => {}
    }
    if rule
        .policy_refs
        .iter()
        .any(|r| PolicyRef::new(r.as_str()).is_err())
    {
        return bad("규칙집 ID 형식이 아니에요");
    }
    let c = &rule.conditions;
    match rule.kind {
        Kind::MerchantPattern => match (&c.merchant, &c.card_category, &c.provider) {
            (Some(m), None, None) => match (&m.equals_or_prefix, &m.compact_regex) {
                (Some(needle), None) if !needle.is_empty() => {
                    Ok(Matcher::EqualsOrPrefix(needle.clone()))
                }
                (None, Some(pattern)) => Regex::new(pattern)
                    .map(Matcher::CompactRegex)
                    .or_else(|e| bad(&format!("정규식이 올바르지 않아요: {e}"))),
                _ => bad("가맹점 조건은 equals_or_prefix 또는 compact_regex 하나여야 해요"),
            },
            _ => bad("가맹점 패턴은 가맹점 조건만 가져요"),
        },
        Kind::CardCategory => match (&c.merchant, &c.card_category, &c.provider) {
            (None, Some(list), None) if !list.is_empty() => {
                Ok(Matcher::Category(list.iter().cloned().collect()))
            }
            _ => bad("카드사 업종 규칙은 업종 목록만 가져요"),
        },
        _ => match (&c.merchant, &c.card_category, &c.provider) {
            (None, None, Some(provider)) if !provider.is_empty() => {
                Ok(Matcher::Provider(provider.clone()))
            }
            _ => bad("공급자 기본값은 공급자 조건만 가져요"),
        },
    }
}
