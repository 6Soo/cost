//! 계획 결과를 `Judgement`로 바꾼다. 정상 거래의 P1 결과는 `Decided`뿐이고, 표현할 수 없는 경우만 `Protected`로 닫힌다.

use super::POLICY;
use super::input::{Row, text};
use crate::dates::parse_iso;
use crate::domain::{
    Actor, ActorKind, Amount, Attribution, Basis, CompletedPeriod, Confidence, Decision,
    DecisionDraft, Direction, EvidenceKind, EvidenceRef, ItemAllowList, Judgement, ManualEventRef,
    Mapped, ParseError, ParseErrorKind, ProtectionReason, Quarter, RefundGroupId, RuleId,
    ServicePeriod, SourceHash, SourceInput, SourceTxn, Subject, TripCatalog, TxnId, map_source,
};
use crate::period;
use serde_json::Value;
use time::{Date, Month};

/// P1이 새로 판정하지 않고 기존 기록을 그대로 두는 이유.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Keep {
    /// 기록된 P2·AI 검수 판정은 P1이 덮지 않는다(`supersede` 표의 P2 × P1Inferred).
    RecordedAiJudgement,
    /// 이미 완결된 환불 원결제.
    CompleteRefundOriginal,
    /// 판정 열이 이미 맞다.
    Current,
}

#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    Judged(Judgement),
    Kept(Keep),
}

pub(super) struct Judger {
    catalog: TripCatalog,
    items: ItemAllowList,
}

/// 코드가 직접 내는 항목 어휘(`infer_item`·분기 종결·환불·사용자 예외).
const CODE_ITEMS: [&str; 14] = [
    "주차비",
    "주유비",
    "통행료",
    "항공료",
    "렌터카",
    "숙박비",
    "식비",
    "교통비",
    "입장료",
    "여행경비",
    "취소·환불",
    "현지경비",
    "기타경비",
    "분기 기타비용",
];

impl Judger {
    pub(super) fn new(
        trip_ids: impl Iterator<Item = String>,
        listed: &[String],
        used: &[String],
    ) -> Self {
        let items = CODE_ITEMS
            .iter()
            .map(|s| (*s).to_string())
            .chain(listed.iter().cloned())
            .chain(used.iter().cloned());
        Self {
            catalog: TripCatalog::from_snapshot(trip_ids),
            items: ItemAllowList::from_items(items),
        }
    }
}

pub(super) fn token_error() -> ParseError {
    ParseError {
        kind: ParseErrorKind::NotNumeric,
    }
}

/// 날짜 칸이 비었거나 해석되지 않으면 `DateBroken`, 완료 기간이면 `Preserved`.
pub(super) fn completed(period: &str) -> Judgement {
    let (from, to) = if period == "2025" {
        ((2025, Month::January, 1), (2025, Month::December, 31))
    } else {
        ((2026, Month::January, 1), (2026, Month::March, 31))
    };
    let day = |(y, m, d): (i32, Month, u8)| Date::from_calendar_date(y, m, d).expect("고정 날짜");
    Judgement::Preserved(CompletedPeriod {
        starts_on: day(from),
        ends_on: day(to),
    })
}

fn attribution(
    judger: &Judger,
    tab: &str,
    original: Option<&str>,
    tid: &str,
) -> Option<Attribution> {
    if tab == "refunds" {
        return Some(Attribution::RefundPair(RefundGroupId::for_original(
            original.unwrap_or(tid),
        )));
    }
    if let Some(rest) = tab.strip_prefix("quarter:") {
        let (year, number) = rest.split_once(':')?;
        let quarter = Quarter::from_number(number.parse().ok()?).ok()?;
        return Some(Attribution::QuarterOther {
            year: year.parse().ok()?,
            quarter,
        });
    }
    judger.catalog.resolve(tab).map(Attribution::Trip)
}

impl Judger {
    /// 판정 열이 정해진 거래 하나를 `Decision`으로 만든다. 만들 수 없으면 이유가 있는 `Protected`.
    pub(super) fn decide(
        &self,
        row: &Row,
        chosen: &Row,
        tid: &str,
        has_history: bool,
        original: Option<&str>,
        (fact, found): (Option<&Value>, &period::Found),
    ) -> Judgement {
        let amount = row
            .get("amount_krw")
            .and_then(Value::as_i64)
            .map_or(Amount::Unreadable(token_error()), |a| {
                Amount::Readable(crate::domain::KrwAmount::new(a))
            });
        let hash_text = text(row, "source_hash");
        let day = [text(row, "approval_date"), text(row, "posting_date")]
            .into_iter()
            .find(|d| !d.is_empty())
            .unwrap_or_default();
        let Ok(id) = TxnId::new(tid) else {
            return Judgement::Protected(ProtectionReason::IdInvalid);
        };
        let Ok(hash) = SourceHash::new(hash_text) else {
            return Judgement::Protected(ProtectionReason::SourceHashInvalid);
        };
        let Ok(occurred_on) = parse_iso(&day) else {
            return Judgement::Protected(ProtectionReason::DateBroken);
        };
        let Some(revision) = row
            .get("revision")
            .and_then(Value::as_u64)
            .and_then(|r| u32::try_from(r).ok())
        else {
            return Judgement::Protected(ProtectionReason::RevisionInvalid);
        };
        let direction = if text(row, "transaction_direction") == "purchase" {
            Direction::Purchase
        } else {
            Direction::Refund
        };
        let txn = SourceTxn::new(
            id.clone(),
            hash.clone(),
            revision,
            amount,
            direction,
            occurred_on,
            text(row, "merchant"),
        );
        let subject = match Subject::card(&txn) {
            Ok(subject) => subject,
            Err(reason) => return Judgement::Protected(reason),
        };
        let unattributable = Judgement::Protected(ProtectionReason::Unattributable);
        let Some(attribution) = attribution(self, &text(chosen, "display_tab_id"), original, tid)
        else {
            return unattributable;
        };
        let Ok(item) = self.items.item(&text(chosen, "item")) else {
            return unattributable;
        };
        let basis_text = text(chosen, "classification_basis");
        let basis = if basis_text.is_empty() {
            "기존 판정 보존 · 근거 칸이 비어 있음".to_string()
        } else {
            basis_text
        };
        let Ok(basis) = Basis::new(basis) else {
            return unattributable;
        };
        let source = text(chosen, "classification_source");
        let decided = row.get("decided_at").is_some_and(|v| !v.is_null());
        let basis_raw = text(chosen, "classification_basis");
        let mapped = map_source(SourceInput {
            source: &source,
            basis: &basis_raw,
            has_decided_at: decided,
            ..SourceInput::default()
        });
        let kind = match mapped.mapped {
            Mapped::Actor { kind, .. } if !has_history => kind,
            _ if has_history => ActorKind::Manual,
            _ => ActorKind::P1Inferred,
        };
        let actor = match kind {
            ActorKind::Manual => ManualEventRef::new(tid).map(|event| Actor::Manual { event }),
            ActorKind::P1Exact =>
            // 입력에 규칙 ID 칸이 없다. 정확 판정의 근거는 기록된 출처 이름이라 source: 접두로 그 사실을 드러낸다.
            {
                RuleId::new(format!("source:{source}")).map(|rule_id| Actor::P1Exact {
                    rule_id,
                    rule_version: 1,
                })
            }
            _ => RuleId::new(POLICY).map(|rule_id| Actor::P1Inferred {
                rule_id,
                rule_version: 1,
                confidence: Confidence::Low,
            }),
        };
        let Ok(actor) = actor else {
            return unattributable;
        };
        let from_evidence = fact
            .filter(|_| basis.as_str().contains("예약 이용기간 근거 우선:"))
            .and_then(|f| f.get("service_period"))
            .and_then(|p| {
                let get = |k: &str| {
                    p.get(k)
                        .and_then(Value::as_str)
                        .and_then(|d| parse_iso(d).ok())
                };
                ServicePeriod::known(get("starts_on")?, get("ends_on")?).ok()
            });
        // 저장 값·검증된 연결·항공 구간의 기간이 먼저, 분류 근거의 예약 기간이 그다음, 추론 기간, 없으면 사유가 있는 미상.
        let period = match period::decided_period(found, item.as_str()) {
            known @ ServicePeriod::Known { .. } => known,
            other => from_evidence.unwrap_or(other),
        };
        let draft = DecisionDraft {
            subject,
            attribution,
            item,
            description: text(chosen, "description"),
            service_period: period,
            evidence: vec![EvidenceRef {
                kind: EvidenceKind::ImportBatchRow,
                sha256: hash,
                locator: id.to_string(),
            }],
            actor,
            basis,
            uncertainty: Vec::new(),
            policy_refs: Vec::new(),
        };
        Decision::new(draft).map_or(unattributable, Judgement::Decided)
    }
}

/// 보류·제외·원본 오류의 보호 사유.
pub(super) fn protection(row: &Row, held: bool, excluded: bool) -> ProtectionReason {
    if !text(row, "parse_error").is_empty() {
        ProtectionReason::AmountUnreadable(token_error())
    } else if !text(row, "duplicate_of").is_empty() {
        ProtectionReason::Duplicate
    } else if !text(row, "conflict_reason").is_empty() {
        ProtectionReason::SourceConflict
    } else if held {
        ProtectionReason::UserHold
    } else if excluded {
        ProtectionReason::CompanyExcluded
    } else {
        ProtectionReason::SourceConflict
    }
}
