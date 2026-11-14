//! 판정 1건(설계 §2.1)과 판정 상태(§2.2).

use std::collections::HashSet;
use std::sync::OnceLock;

use regex::Regex;
use time::Date;

use super::error::DomainError;
use super::ids::{
    CashUseId, ManualEventRef, ModelName, PolicyRef, Quarter, ReceiptId, RefundGroupId, RuleId,
    RunId, SourceHash, TripId, TxnId, Uncertainty,
};
use super::money::{Amount, KrwAmount, ParseError, SourceTxn};

/// 비용 항목. 허용 목록(`ItemAllowList`)으로만 만들 수 있다.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Item(String);

impl Item {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// 운영 장부 실사용 항목 목록(데이터). 항목이 늘어도 코드는 그대로다.
#[derive(Debug, Clone, Default)]
pub struct ItemAllowList {
    allowed: HashSet<String>,
}

impl ItemAllowList {
    pub fn from_items(items: impl IntoIterator<Item = String>) -> Self {
        let allowed = items
            .into_iter()
            .map(|i| i.trim().to_owned())
            .filter(|i| !i.is_empty())
            .collect();
        Self { allowed }
    }

    pub fn item(&self, name: &str) -> Result<Item, DomainError> {
        let name = name.trim();
        if self.allowed.contains(name) {
            Ok(Item(name.to_owned()))
        } else {
            Err(DomainError::ItemNotAllowed)
        }
    }
}

/// 근거 문장. 비어 있으면 만들 수 없다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Basis(String);

const BASIS_MAX_CHARS: usize = 600;

fn private_identifier() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\d(?:[ -]?\d){4,}|[\w.+-]+@[\w.-]+").expect("고정 정규식"))
}

impl Basis {
    pub fn new(text: impl Into<String>) -> Result<Self, DomainError> {
        let text = text.into();
        if text.trim().is_empty() {
            return Err(DomainError::BasisEmpty);
        }
        Ok(Self(text))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// P2·AI 검수 근거 검사(`tools/p2_batch/layer1.py`와 같은 조건).
    pub fn check_machine_authored(&self) -> Result<(), DomainError> {
        if self.0.chars().count() > BASIS_MAX_CHARS {
            return Err(DomainError::BasisTooLong);
        }
        if private_identifier().is_match(&self.0) {
            return Err(DomainError::BasisPrivateIdentifier);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvidenceKind {
    ImportBatchRow,
    OtaEvidence,
    Receipt,
    Manual,
}

/// 원본 참조. 원문 사본은 두지 않는다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceRef {
    pub kind: EvidenceKind,
    pub sha256: SourceHash,
    pub locator: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnknownPeriodReason {
    NoEvidence,
    EvidenceAmbiguous,
    NotApplicable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServicePeriod {
    Known { starts_on: Date, ends_on: Date },
    Unknown { reason: UnknownPeriodReason },
}

impl ServicePeriod {
    pub fn known(starts_on: Date, ends_on: Date) -> Result<Self, DomainError> {
        if ends_on < starts_on {
            return Err(DomainError::PeriodReversed);
        }
        Ok(Self::Known { starts_on, ends_on })
    }

    pub fn unknown(reason: UnknownPeriodReason) -> Self {
        Self::Unknown { reason }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Confidence {
    High,
    Low,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Actor {
    Manual {
        event: ManualEventRef,
    },
    P1Exact {
        rule_id: RuleId,
        rule_version: u32,
    },
    AiReview {
        run_id: RunId,
        model: ModelName,
    },
    P2 {
        run_id: RunId,
        model: ModelName,
    },
    P1Inferred {
        rule_id: RuleId,
        rule_version: u32,
        confidence: Confidence,
    },
}

/// 우선순위 종류(작을수록 강하다). 표는 `supersede`에 있다.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum ActorKind {
    Manual,
    P1Exact,
    AiReview,
    P2,
    P1Inferred,
}

impl ActorKind {
    pub const ALL: [ActorKind; 5] = [
        Self::Manual,
        Self::P1Exact,
        Self::AiReview,
        Self::P2,
        Self::P1Inferred,
    ];
}

impl Actor {
    pub fn kind(&self) -> ActorKind {
        match self {
            Self::Manual { .. } => ActorKind::Manual,
            Self::P1Exact { .. } => ActorKind::P1Exact,
            Self::AiReview { .. } => ActorKind::AiReview,
            Self::P2 { .. } => ActorKind::P2,
            Self::P1Inferred { .. } => ActorKind::P1Inferred,
        }
    }

    /// 규칙집 `DECISION_POLICY.md:24` 순서. 0이 가장 강하다.
    pub fn rank(&self) -> u8 {
        self.kind() as u8
    }
}

/// 판정 대상. 카드 거래는 금액을 읽을 수 있는 `SourceTxn`으로만 만들 수 있다.
///
/// ```compile_fail
/// let _ = cost_core::domain::Subject(todo!());
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Subject(SubjectInner);

#[derive(Debug, Clone, PartialEq, Eq)]
enum SubjectInner {
    CardTxn {
        transaction_id: TxnId,
        source_hash: SourceHash,
        revision: u32,
    },
    Receipt {
        receipt_id: ReceiptId,
    },
    CashUse {
        use_id: CashUseId,
    },
}
/// 같은 대상인지 비교하는 키(카드 거래는 개정 번호를 무시한다).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum SubjectKey {
    CardTxn(TxnId),
    Receipt(ReceiptId),
    CashUse(CashUseId),
}

impl Subject {
    /// 금액을 읽지 못한 거래는 판정 대상이 될 수 없고 `Protected` 사유가 된다.
    pub fn card(txn: &SourceTxn) -> Result<Self, ProtectionReason> {
        match txn.amount() {
            Amount::Readable(_) => Ok(Self(SubjectInner::CardTxn {
                transaction_id: txn.transaction_id().clone(),
                source_hash: txn.source_hash().clone(),
                revision: txn.revision(),
            })),
            Amount::Unreadable(e) => Err(ProtectionReason::AmountUnreadable(e)),
        }
    }

    pub fn receipt(receipt_id: ReceiptId) -> Self {
        Self(SubjectInner::Receipt { receipt_id })
    }

    pub fn cash_use(use_id: CashUseId) -> Self {
        Self(SubjectInner::CashUse { use_id })
    }

    pub fn card_txn_id(&self) -> Option<&TxnId> {
        match &self.0 {
            SubjectInner::CardTxn { transaction_id, .. } => Some(transaction_id),
            _ => None,
        }
    }

    /// 카드 거래의 원천 개정 번호.
    pub fn revision(&self) -> Option<u32> {
        match &self.0 {
            SubjectInner::CardTxn { revision, .. } => Some(*revision),
            _ => None,
        }
    }

    pub fn key(&self) -> SubjectKey {
        match &self.0 {
            SubjectInner::CardTxn { transaction_id, .. } => {
                SubjectKey::CardTxn(transaction_id.clone())
            }
            SubjectInner::Receipt { receipt_id } => SubjectKey::Receipt(receipt_id.clone()),
            SubjectInner::CashUse { use_id } => SubjectKey::CashUse(use_id.clone()),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Attribution {
    Trip(TripId),
    QuarterOther { year: u16, quarter: Quarter },
    RefundPair(RefundGroupId),
}

impl Attribution {
    /// 현 장부 표기 `display_tab_id`.
    pub fn display_tab_id(&self) -> String {
        match self {
            Self::Trip(t) => t.as_str().to_owned(),
            Self::QuarterOther { year, quarter } => format!("quarter:{year}:{}", quarter.number()),
            Self::RefundPair(_) => "refunds".to_owned(),
        }
    }

    /// 현 장부 표기 `trip_id`(여행만 값이 있다).
    pub fn trip_id(&self) -> String {
        match self {
            Self::Trip(t) => t.as_str().to_owned(),
            _ => String::new(),
        }
    }
}

/// 판정 1건. 금액·부호·승인번호 필드가 **없다**(원천은 `SourceTxn`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Decision {
    subject: Subject,
    attribution: Attribution,
    item: Item,
    description: String,
    service_period: ServicePeriod,
    evidence: Vec<EvidenceRef>,
    actor: Actor,
    basis: Basis,
    uncertainty: Vec<Uncertainty>,
    policy_refs: Vec<PolicyRef>,
}

/// `Decision::new` 입력.
#[derive(Debug, Clone)]
pub struct DecisionDraft {
    pub subject: Subject,
    pub attribution: Attribution,
    pub item: Item,
    pub description: String,
    pub service_period: ServicePeriod,
    pub evidence: Vec<EvidenceRef>,
    pub actor: Actor,
    pub basis: Basis,
    pub uncertainty: Vec<Uncertainty>,
    pub policy_refs: Vec<PolicyRef>,
}

impl Decision {
    /// 수동·P1 판정용. P2·AI 검수 판정은 `new_machine`(열린 범위 토큰 필요)으로만 만든다.
    pub fn new(d: DecisionDraft) -> Result<Self, DomainError> {
        if matches!(d.actor.kind(), ActorKind::P2 | ActorKind::AiReview) {
            return Err(DomainError::MachineActorNeedsScope);
        }
        Ok(Self::build(d))
    }

    /// P2·AI 검수 판정용. 열린 범위가 귀속을 덮어야 하고 환불 짝은 만들 수 없다.
    pub fn new_machine(d: DecisionDraft, scope: &OpenScope) -> Result<Self, DomainError> {
        if !matches!(d.actor.kind(), ActorKind::P2 | ActorKind::AiReview) {
            return Err(DomainError::NotMachineActor);
        }
        d.basis.check_machine_authored()?;
        if matches!(d.attribution, Attribution::RefundPair(_)) {
            return Err(DomainError::RefundPairNotAllowedForActor);
        }
        if !scope.covers(&d.attribution) {
            return Err(DomainError::OutsideOpenScope);
        }
        Ok(Self::build(d))
    }

    fn build(d: DecisionDraft) -> Self {
        Self {
            subject: d.subject,
            attribution: d.attribution,
            item: d.item,
            description: d.description,
            service_period: d.service_period,
            evidence: d.evidence,
            actor: d.actor,
            basis: d.basis,
            uncertainty: d.uncertainty,
            policy_refs: d.policy_refs,
        }
    }

    pub fn subject(&self) -> &Subject {
        &self.subject
    }
    pub fn attribution(&self) -> &Attribution {
        &self.attribution
    }
    pub fn item(&self) -> &Item {
        &self.item
    }
    pub fn description(&self) -> &str {
        &self.description
    }
    pub fn service_period(&self) -> &ServicePeriod {
        &self.service_period
    }
    pub fn evidence(&self) -> &[EvidenceRef] {
        &self.evidence
    }
    pub fn actor(&self) -> &Actor {
        &self.actor
    }
    pub fn basis(&self) -> &Basis {
        &self.basis
    }
    pub fn uncertainty(&self) -> &[Uncertainty] {
        &self.uncertainty
    }
    pub fn policy_refs(&self) -> &[PolicyRef] {
        &self.policy_refs
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtectionReason {
    DateBroken,
    AmountUnreadable(ParseError),
    Duplicate,
    SourceConflict,
    ExcessRefund,
    /// 사용자 보류(`transaction_review_holds`).
    UserHold,
    /// 회사 제외(`transaction_company_exclusions`).
    CompanyExcluded,
    /// 닫힌 분기 검수가 끝낸 거래.
    ClosedReview,
    /// 수동 결정이 있는 거래(자동 판정이 덮지 않는다).
    ManualDecision,
    /// 귀속·항목·근거를 판정으로 표현할 수 없다(분기도 여행도 정해지지 않은 거래).
    Unattributable,
}

/// PROC-072 완료 기간 자료.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CompletedPeriod {
    pub starts_on: Date,
    pub ends_on: Date,
}

/// 거래 하나의 상태. "판정 대기" 변형이 없다.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Judgement {
    Decided(Decision),
    Protected(ProtectionReason),
    Preserved(CompletedPeriod),
}

impl Judgement {
    /// 금액을 읽지 못하면 판정을 만들지 않고 `Protected`로 보낸다.
    pub fn from_amount(amount: Amount, decide: impl FnOnce(KrwAmount) -> Decision) -> Self {
        match amount {
            Amount::Readable(a) => Self::Decided(decide(a)),
            Amount::Unreadable(e) => Self::Protected(ProtectionReason::AmountUnreadable(e)),
        }
    }

    pub fn decision(&self) -> Option<&Decision> {
        match self {
            Self::Decided(d) => Some(d),
            _ => None,
        }
    }
}

/// 열린 분기·열린 여행 토큰. P2·AI 검수 교정 적용의 필수 인자. 외부에서 만들 수 없다.
///
/// ```compile_fail
/// let _ = cost_core::domain::OpenScope::quarter(2026, cost_core::domain::Quarter::Q4);
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenScope(OpenInner);

#[derive(Debug, Clone, PartialEq, Eq)]
enum OpenInner {
    Trip(TripId),
    Quarter { year: u16, quarter: Quarter },
}

impl OpenScope {
    pub fn covers(&self, attribution: &Attribution) -> bool {
        match (&self.0, attribution) {
            (OpenInner::Trip(open), Attribution::Trip(t)) => open == t,
            (
                OpenInner::Quarter { year, quarter },
                Attribution::QuarterOther {
                    year: y,
                    quarter: q,
                },
            ) => year == y && quarter == q,
            _ => false,
        }
    }

    pub(crate) fn trip(trip: &TripId) -> Self {
        Self(OpenInner::Trip(trip.clone()))
    }

    pub(crate) fn quarter(year: u16, quarter: Quarter) -> Self {
        Self(OpenInner::Quarter { year, quarter })
    }
}
/// P2 제안이 고를 수 있는 귀속. 환불 짝이 없다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProposedAttribution {
    Trip(TripId),
    QuarterOther { year: u16, quarter: Quarter },
}

/// P2 제안: 귀속·항목·이용기간·근거·불확실성만 가진다(금액·부호·환불 관계 없음).
#[derive(Debug, Clone)]
pub struct P2Proposal {
    pub attribution: ProposedAttribution,
    pub item: Item,
    pub service_period: ServicePeriod,
    pub basis: Basis,
    pub uncertainty: Vec<Uncertainty>,
}

/// 제안을 판정으로 바꿀 때 붙는 호출 맥락.
#[derive(Debug, Clone)]
pub struct P2Context {
    pub subject: Subject,
    pub description: String,
    pub evidence: Vec<EvidenceRef>,
    pub policy_refs: Vec<PolicyRef>,
    pub run_id: RunId,
    pub model: ModelName,
}

impl P2Proposal {
    /// `Actor::P2` 판정만 만든다. 열린 범위 밖 귀속은 거부한다.
    pub fn into_decision(self, ctx: P2Context, scope: &OpenScope) -> Result<Decision, DomainError> {
        let attribution = match self.attribution {
            ProposedAttribution::Trip(t) => Attribution::Trip(t),
            ProposedAttribution::QuarterOther { year, quarter } => {
                Attribution::QuarterOther { year, quarter }
            }
        };
        Decision::new_machine(
            DecisionDraft {
                subject: ctx.subject,
                attribution,
                item: self.item,
                description: ctx.description,
                service_period: self.service_period,
                evidence: ctx.evidence,
                actor: Actor::P2 {
                    run_id: ctx.run_id,
                    model: ctx.model,
                },
                basis: self.basis,
                uncertainty: self.uncertainty,
                policy_refs: ctx.policy_refs,
            },
            scope,
        )
    }
}

/// 환불 묶음. 외부에서 만들 수 없다(생성자는 `pub(crate)`, 발급은 후속 연결 모듈).
///
/// ```compile_fail
/// let _ = cost_core::domain::RefundGroup::new(todo!(), vec![]);
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RefundGroup {
    id: RefundGroupId,
    members: Vec<TxnId>,
}

impl RefundGroup {
    #[cfg_attr(not(test), allow(dead_code))] // 발급은 후속 연결 모듈(U12)
    pub(crate) fn new(id: RefundGroupId, members: Vec<TxnId>) -> Result<Self, DomainError> {
        if members.is_empty() {
            return Err(DomainError::EmptyGroup);
        }
        Ok(Self { id, members })
    }

    pub fn id(&self) -> &RefundGroupId {
        &self.id
    }
    pub fn members(&self) -> &[TxnId] {
        &self.members
    }
}

/// 환불 묶음 전체 게시 단위. 저장 계층은 이 값을 한 트랜잭션에 쓰거나 아무것도 쓰지 않는다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GroupPublication {
    group: RefundGroup,
    decisions: Vec<Decision>,
}

impl GroupPublication {
    /// 판정이 구성원 전부를 정확히 한 번씩 덮고 모두 이 묶음의 `RefundPair`여야 한다.
    pub fn new(group: RefundGroup, decisions: Vec<Decision>) -> Result<Self, DomainError> {
        let mut seen: HashSet<&TxnId> = HashSet::new();
        for d in &decisions {
            let Some(transaction_id) = d.subject().card_txn_id() else {
                return Err(DomainError::GroupPublicationMismatch);
            };
            let bound = matches!(d.attribution(), Attribution::RefundPair(g) if g == group.id());
            if !bound || !group.members.contains(transaction_id) || !seen.insert(transaction_id) {
                return Err(DomainError::GroupPublicationMismatch);
            }
        }
        if seen.len() != group.members.len() {
            return Err(DomainError::GroupPublicationMismatch);
        }
        Ok(Self { group, decisions })
    }

    pub fn group(&self) -> &RefundGroup {
        &self.group
    }
    pub fn decisions(&self) -> &[Decision] {
        &self.decisions
    }
}
