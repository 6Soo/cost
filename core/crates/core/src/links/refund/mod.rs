//! 환불 짝 도출과 환불 묶음 판정(M3 U12). 원본: `app/partial_refund.py`(짝 도출), `app/ledger.py`(묶음 판정).
//!
//! 입력 행은 읽기만 한다. 금액·부호·원문은 어떤 경로로도 바뀌지 않고 순잔액은 연결에서 파생한다(RFND-003).
//! `RefundGroup`은 이 모듈의 `issue_group`만 만든다(초과 환불·추론 연결·누락·완료 기간·깨끗하지 않은 구성원은 거부).
//! 입력 행의 순서는 Python의 SQL 행 순서와 같다고 본다(연결 처리 순서가 거기서 나온다).

mod group;
mod pairing;

use std::collections::{BTreeMap, HashMap};
use std::fmt;

#[cfg_attr(not(test), allow(unused_imports))] // 게시 단위(U14)가 쓴다
pub(crate) use group::issue_group;
pub use group::{
    Authority, Block, Entry, RefundNote, Refusal, Role, Scope, apply_pairs, check_groups,
    extension, scope_group,
};
use serde_json::Value;

/// 외화 짝 설정(`config/refund-pairing.json`의 `foreign_amount_pairing`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PairingConfig {
    pub enabled: bool,
    pub max_days_after_purchase: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigError(pub &'static str);

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for ConfigError {}

impl PairingConfig {
    /// 설정 파일 본문을 읽는다. 스키마 버전이 다르면 `REFUND_PAIRING_SCHEMA_INVALID`.
    pub fn from_json(text: &str) -> Result<Self, ConfigError> {
        let value: Value =
            serde_json::from_str(text).map_err(|_| ConfigError("REFUND_PAIRING_SCHEMA_INVALID"))?;
        if value.get("schema_version").and_then(Value::as_str) != Some("refund-pairing-v1") {
            return Err(ConfigError("REFUND_PAIRING_SCHEMA_INVALID"));
        }
        let pairing = value
            .get("foreign_amount_pairing")
            .ok_or(ConfigError("REFUND_PAIRING_SCHEMA_INVALID"))?;
        Ok(Self {
            enabled: pairing
                .get("enabled")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            max_days_after_purchase: pairing
                .get("max_days_after_purchase")
                .and_then(Value::as_i64)
                .ok_or(ConfigError("REFUND_PAIRING_SCHEMA_INVALID"))?,
        })
    }
}

/// 짝 도출이 읽는 카드 원행의 칸. 빈 칸은 빈 문자열(Python의 `COALESCE(x,'')`)이다.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RefundTxn {
    pub transaction_id: String,
    pub issuer: String,
    pub card_tail: String,
    /// `purchase`·`cancellation`·`refund` 외 값도 올 수 있고, 그런 행은 짝에 쓰이지 않는다.
    pub direction: String,
    pub approval_number: String,
    pub original_approval_number: String,
    /// 금액 없는 행은 금액 조건에서 빠진다(SQL의 NULL 비교).
    pub amount_krw: Option<i64>,
    pub approval_date: String,
    pub posting_date: String,
    pub merchant: String,
    pub merchant_normalized: String,
    pub foreign_amount: String,
    pub foreign_currency: String,
    pub duplicate_of: Option<String>,
    pub conflict_reason: String,
    pub parse_error: String,
}

/// 누적 환불로 파생한 상태(RFND-017). 순잔액이 음수면 초과 환불이다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Full,
    Partial,
    Excess,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Status::Full => "full",
            Status::Partial => "partial",
            Status::Excess => "excess",
        }
    }
}

/// 원승인번호 없는 연결의 근거. 원승인번호 연결은 근거 표시가 없다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Basis {
    MerchantCardForeignAmount,
    KakaoSameCardExactAmount,
    SameCardMerchantDayExactAmount,
}

impl Basis {
    pub fn as_str(self) -> &'static str {
        match self {
            Basis::MerchantCardForeignAmount => "merchant_card_foreign_amount",
            Basis::KakaoSameCardExactAmount => "kakao_same_card_exact_amount",
            Basis::SameCardMerchantDayExactAmount => "same_card_merchant_day_exact_amount",
        }
    }
}

/// 환불(취소) 한 건과 원결제의 연결. 짝 도출은 `inferred`를 항상 거짓으로 낸다(Python과 같다).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Link {
    pub refund_id: String,
    pub original_id: String,
    pub gross_krw: i64,
    pub refund_krw: i64,
    pub refunds_total_krw: i64,
    pub net_krw: i64,
    pub status: Status,
    pub refund_count: u32,
    pub basis: Option<Basis>,
    pub inferred: bool,
}

impl Link {
    /// 원승인번호 1:N 연결(RFND-004)의 부분환불. 추론은 아니고 근거 표시가 없고 순잔액이 양수다.
    pub fn is_numbered_partial(&self) -> bool {
        !self.inferred && self.basis.is_none() && self.status == Status::Partial && self.net_krw > 0
    }

    /// 계획이 읽는 칸만 옮긴다.
    pub fn to_plan(&self) -> crate::plan::RefundLink {
        crate::plan::RefundLink {
            original_id: self.original_id.clone(),
            inferred: self.inferred,
            status: self.status.as_str().to_string(),
        }
    }

    /// 묶음으로 넓힐 수 있는 검증 연결: 추론이 아니고 (순액 0 전액 상쇄 또는 원승인번호 부분환불).
    pub(crate) fn is_verified(&self) -> bool {
        !self.inferred
            && ((self.status == Status::Full && self.net_krw == 0) || self.is_numbered_partial())
    }
}

/// 개수 보호: 같은 조건의 구매가 있는데 짝을 정하지 못한 남는 외화 취소(RFND-014).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Held {
    pub purchases: usize,
    pub cancellations: usize,
}

/// 짝을 맺지 않은 이유(`partial_group_exclusion`). 완료 기간이 먼저다(PROC-072).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Exclusion {
    CompletedPeriod,
    UncleanMember,
}

impl Exclusion {
    pub fn as_str(self) -> &'static str {
        match self {
            Exclusion::CompletedPeriod => "completed_period",
            Exclusion::UncleanMember => "unclean_member",
        }
    }
}

/// 한 번 도출한 환불 짝 분석. 행을 빌려 읽기만 한다.
#[derive(Debug)]
pub struct Refunds<'a> {
    rows: &'a [RefundTxn],
    by_id: HashMap<&'a str, usize>,
    links: Vec<Link>,
    held: BTreeMap<String, Held>,
    config: PairingConfig,
}

impl<'a> Refunds<'a> {
    /// 번호 → 외화 → 추론 순서로 연결을 도출한다.
    pub fn derive(rows: &'a [RefundTxn], config: &PairingConfig) -> Self {
        let analysis = pairing::analyse(rows, config);
        let mut by_id = HashMap::new();
        for (i, row) in rows.iter().enumerate() {
            by_id.entry(row.transaction_id.as_str()).or_insert(i);
        }
        Self {
            rows,
            by_id,
            links: analysis.links,
            held: analysis.held,
            config: config.clone(),
        }
    }

    /// 연결 전부. Python 사전 순서(번호, 외화, 추론)다.
    pub fn links(&self) -> &[Link] {
        &self.links
    }

    pub fn link_of(&self, refund_id: &str) -> Option<&Link> {
        self.links.iter().find(|l| l.refund_id == refund_id)
    }

    pub fn held(&self) -> &BTreeMap<String, Held> {
        &self.held
    }

    /// 원결제와 연결된 모든 취소(추론 포함): `[원결제] + 정렬한 취소`.
    pub fn group(&self, original_id: &str) -> Vec<String> {
        let mut siblings: Vec<&str> = self
            .links
            .iter()
            .filter(|l| l.original_id == original_id)
            .map(|l| l.refund_id.as_str())
            .collect();
        siblings.sort_unstable();
        std::iter::once(original_id)
            .chain(siblings)
            .map(str::to_string)
            .collect()
    }

    /// 연결된 원결제 ID(정렬·중복 제거).
    pub fn originals(&self) -> Vec<String> {
        let mut originals: Vec<String> = self.links.iter().map(|l| l.original_id.clone()).collect();
        originals.sort_unstable();
        originals.dedup();
        originals
    }

    pub fn exclusion(&self, original_id: &str) -> Option<Exclusion> {
        pairing::exclusion(self, original_id)
    }

    /// 실제 연결과 미해결 후보의 원결제(가맹점 전체가 아니라 거래별 보호). 검토 대기열의 읽기 전용 경계.
    pub fn review_originals(&self) -> Vec<String> {
        pairing::review_originals(self)
    }

    /// 계획(`plan::plan`)이 읽는 연결. 환불 ID → 원결제·추론 여부·상태. 2차 전환 전에는 Python 어댑터가 이 자리에 선다.
    pub fn plan_links(&self) -> BTreeMap<String, crate::plan::RefundLink> {
        self.links
            .iter()
            .map(|l| (l.refund_id.clone(), l.to_plan()))
            .collect()
    }

    pub(crate) fn row(&self, id: &str) -> Option<&RefundTxn> {
        self.by_id.get(id).map(|&i| &self.rows[i])
    }
}

#[cfg(test)]
mod tests;
