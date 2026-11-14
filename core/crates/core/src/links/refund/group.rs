//! 환불 묶음 판정(`app/ledger.py`): `_ready_rows` 확장, `_apply_refund_pairs`, `_check_refund_groups`, `scope_group`,
//! 그리고 `RefundGroup` 발급. 연결 한 쌍은 함께 정하거나 함께 보류한다.

use std::collections::{BTreeSet, HashMap, HashSet};

use thiserror::Error;

use super::{Basis, Exclusion, Link, Refunds, Status};
use crate::domain::{RefundGroup, RefundGroupId, TxnId};

const REFUND_TAB: &str = "refunds";
const PAIR_UNBLOCKABLE: [&str; 2] = ["needs_review", "item_missing"];

/// 보류 코드와 이유.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Block {
    pub code: String,
    pub reason: String,
}

impl Block {
    fn new(code: &str, reason: &str) -> Self {
        Self {
            code: code.to_string(),
            reason: reason.to_string(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    Original,
    Refund,
}

/// 미리보기 행에 붙는 환불 연결 표시. 금액은 연결에서 파생한 값이고 원행은 바뀌지 않는다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RefundNote {
    pub gross_krw: i64,
    pub refund_krw: i64,
    pub net_krw: i64,
    pub status: Status,
    pub basis: Option<Basis>,
    pub inferred: bool,
    pub role: Role,
    pub counterpart_id: String,
}

/// 미리보기 행 한 줄의 판정 입력·출력. 금액·날짜·원문 칸이 없다: 이 단계는 귀속과 보류만 정한다.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Entry {
    pub id: String,
    pub item: String,
    pub display_tab_id: String,
    pub trip_id: String,
    pub description: String,
    pub blocked: Option<Block>,
    pub already_booked: bool,
    /// 다른 접수 파일에서 온 행(`source_batch_id`가 있음).
    pub external: bool,
    pub ready: bool,
    pub refund_link: Option<RefundNote>,
}

/// 여행·항목 구분 재검증 함수. 없으면 해당 귀속이 있는 행은 보류한다.
#[derive(Clone, Copy, Default)]
pub struct Authority<'a> {
    pub trip: Option<&'a dyn Fn(&str) -> bool>,
    pub tab: Option<&'a dyn Fn(&str) -> bool>,
}

impl Authority<'_> {
    fn block(&self, entry: &Entry) -> Option<Block> {
        if !entry.trip_id.is_empty() {
            match self.trip {
                None => {
                    return Some(Block::new(
                        "trip_unverified",
                        "여행을 재검증할 함수가 필요해요",
                    ));
                }
                Some(valid) if !valid(&entry.trip_id) => {
                    return Some(Block::new(
                        "trip_no_longer_valid",
                        "지금은 기록할 수 없는 여행이에요",
                    ));
                }
                Some(_) => {}
            }
        }
        if !entry.display_tab_id.is_empty() {
            match self.tab {
                None => {
                    return Some(Block::new(
                        "tab_unverified",
                        "항목 구분을 재검증할 함수가 필요해요",
                    ));
                }
                Some(valid) if !valid(&entry.display_tab_id) => {
                    return Some(Block::new(
                        "tab_no_longer_valid",
                        "지금은 쓸 수 없는 항목 구분이에요",
                    ));
                }
                Some(_) => {}
            }
        }
        None
    }
}

fn block_pair(entries: &mut [Entry], indexes: &[usize], code: &str, reason: &str) {
    for &i in indexes {
        entries[i].blocked = Some(Block::new(code, reason));
        entries[i].ready = false;
    }
}

fn holds(entry: &Entry) -> bool {
    entry.blocked.as_ref().is_some_and(|b| !b.code.is_empty())
}

fn blocked_code(entry: &Entry) -> &str {
    entry.blocked.as_ref().map_or("", |b| b.code.as_str())
}

/// `_apply_refund_pairs`: 연결된 환불과 원결제는 함께 정하거나 함께 보류한다.
/// 환불은 자기 귀속이 없을 때만 원결제의 항목·탭·여행을 이어받고, 이미 있는 귀속은 덮지 않는다.
pub fn apply_pairs(refunds: &Refunds, entries: &mut [Entry], authority: &Authority) {
    let by_id: HashMap<String, usize> = entries
        .iter()
        .enumerate()
        .map(|(i, e)| (e.id.clone(), i))
        .collect();
    for link in refunds.links() {
        let (refund, original) = (
            by_id.get(&link.refund_id).copied(),
            by_id.get(&link.original_id).copied(),
        );
        let Some(ri) = refund else {
            if let Some(oi) = original
                && !entries[oi].already_booked
            {
                block_pair(
                    entries,
                    &[oi],
                    "refund_group_incomplete",
                    "연결된 취소가 이 접수 건에 없어 원결제를 함께 확인해야 합니다.",
                );
            }
            continue;
        };
        let Some(oi) = original else {
            block_pair(
                entries,
                &[ri],
                "refund_original_missing",
                "환불의 원거래가 이 접수 건에 없어 함께 기록할 수 없어요",
            );
            continue;
        };
        let pair = [oi, ri];
        if link.inferred {
            // 추론 연결은 표시일 뿐 장부 기록·귀속 상속·환급 완료를 허가하지 않는다(RFND-044).
            for (index, role, counterpart) in [
                (oi, Role::Original, &link.refund_id),
                (ri, Role::Refund, &link.original_id),
            ] {
                entries[index].refund_link = Some(RefundNote {
                    gross_krw: link.gross_krw,
                    refund_krw: link.refunds_total_krw,
                    net_krw: link.net_krw,
                    status: link.status,
                    basis: link.basis,
                    inferred: true,
                    role,
                    counterpart_id: counterpart.clone(),
                });
                let entry = &entries[index];
                let reopen = [
                    "needs_review",
                    "item_missing",
                    "tab_no_longer_valid",
                    "trip_no_longer_valid",
                ];
                if !entry.already_booked && (!holds(entry) || reopen.contains(&blocked_code(entry)))
                {
                    block_pair(
                        entries,
                        &[index],
                        "refund_inferred",
                        "원결제 추론 연결 · 별도 근거 검증 전 장부 기록 보류 (환급 완료 아님)",
                    );
                }
            }
            continue;
        }
        if link.status == Status::Excess {
            block_pair(
                entries,
                &pair,
                "refund_exceeds_original",
                "환불 합계가 원결제보다 커서 보류해요",
            );
            continue;
        }
        // 한쪽이 먼저 기록됐으면 기록된 쪽의 귀속을 빠진 쪽이 이어받는다.
        let (source, target) = match (entries[oi].already_booked, entries[ri].already_booked) {
            (true, false) => (oi, ri),
            (false, true) => (ri, oi),
            _ => (oi, ri),
        };
        if holds(&entries[oi]) && !entries[oi].already_booked {
            if !holds(&entries[ri]) || PAIR_UNBLOCKABLE.contains(&blocked_code(&entries[ri])) {
                block_pair(
                    entries,
                    &[ri],
                    "refund_pair_incomplete",
                    "원거래가 보류 중이라 환불도 함께 보류해요",
                );
            }
            continue;
        }
        if holds(&entries[ri])
            && !PAIR_UNBLOCKABLE.contains(&blocked_code(&entries[ri]))
            && !entries[ri].already_booked
        {
            block_pair(
                entries,
                &[oi],
                "refund_pair_incomplete",
                "환불 거래가 보류 중이라 원거래도 함께 보류해요",
            );
            continue;
        }
        // 전액 상쇄 쌍은 귀속이 달라도 된다. 어느 쪽이든 환불 탭으로 간다.
        let differs = |a: &str, b: &str| !a.is_empty() && !b.is_empty() && a != b;
        let (o, r) = (&entries[oi], &entries[ri]);
        if link.status != Status::Full
            && (differs(&r.item, &o.item)
                || differs(&r.display_tab_id, &o.display_tab_id)
                || differs(&r.trip_id, &o.trip_id))
        {
            block_pair(
                entries,
                &pair,
                "refund_pair_mismatch",
                "환불과 원거래의 분류가 달라 보류해요",
            );
            continue;
        }
        let cross_file = o.external || r.external;
        if link.status == Status::Partial
            && cross_file
            && let Some(exclusion) = refunds.exclusion(&link.original_id)
        {
            let code = format!("refund_{}", exclusion.as_str());
            block_pair(
                entries,
                &pair,
                &code,
                "완료 기간 자료이거나 오류·중복·충돌 취소가 있어 파일 간 부분환불을 기록하지 않아요",
            );
            continue;
        }
        if link.status != Status::Full
            && cross_file
            && o.trip_id.is_empty()
            && matches!(o.display_tab_id.as_str(), "" | "unclassified" | REFUND_TAB)
        {
            block_pair(
                entries,
                &pair,
                "refund_original_unattributed",
                "원결제에 여행이나 분기 기타비용 귀속이 없어 취소를 기록하지 않아요",
            );
            continue;
        }
        let from = entries[source].clone();
        let to = &mut entries[target];
        for (own, inherited) in [
            (&mut to.item, from.item),
            (&mut to.display_tab_id, from.display_tab_id),
            (&mut to.trip_id, from.trip_id),
            (&mut to.description, from.description),
        ] {
            if own.is_empty() {
                *own = inherited;
            }
        }
        if link.status == Status::Full {
            for &i in &pair {
                if !entries[i].already_booked {
                    entries[i].display_tab_id = REFUND_TAB.to_string();
                    entries[i].trip_id.clear();
                }
            }
        }
        let block = authority.block(&entries[target]);
        if block.is_some() || entries[target].item.is_empty() {
            let block = block.unwrap_or_else(|| {
                Block::new(
                    "refund_pair_incomplete",
                    "환불에 이어받을 항목이 없어 함께 보류해요",
                )
            });
            block_pair(entries, &pair, &block.code, &block.reason);
            continue;
        }
        if entries[target].blocked.is_some() {
            entries[target].blocked = None;
            entries[target].ready = true;
        }
        let note = |role, counterpart: &str| RefundNote {
            gross_krw: link.gross_krw,
            refund_krw: link.refunds_total_krw,
            net_krw: link.net_krw,
            status: link.status,
            basis: None,
            inferred: false,
            role,
            counterpart_id: counterpart.to_string(),
        };
        entries[ri].refund_link = Some(note(Role::Refund, &link.original_id));
        entries[oi].refund_link = Some(note(Role::Original, &link.refund_id));
    }
}

/// 묶음 판정이 막은 이유. `code`는 Python `StoreError` 코드와 같다.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum Refusal {
    #[error("연결된 환불이 없는 원거래다")]
    NoRefunds,
    #[error("묶음 구성원이 검증 연결이 아니다(추론·초과 환불·검증 밖 부분환불)")]
    NotVerified,
    #[error("묶인 거래가 이 접수 범위에 모두 없다: {0}")]
    MemberMissing(String),
    #[error("묶음 제외 사유가 있다: {0:?}")]
    Excluded(Exclusion),
    #[error("환불 묶음이 일부만 기록 대상이다")]
    HalfBooked,
    #[error("묶음 식별자를 만들 수 없다")]
    BadId,
}

impl Refusal {
    pub fn code(&self) -> &'static str {
        match self {
            Refusal::NoRefunds => "INVALID_INPUT",
            Refusal::NotVerified | Refusal::MemberMissing(_) | Refusal::HalfBooked => {
                "REFUND_GROUP_INCOMPLETE"
            }
            Refusal::Excluded(_) => "REFUND_GROUP_EXCLUDED",
            Refusal::BadId => "INVALID_INPUT",
        }
    }
}

/// `_check_refund_groups`: 묶음이 반쯤만 기록되게 두는 기록을 거부한다. 아무것도 쓰지 않는다.
pub fn check_groups(
    refunds: &Refunds,
    entries: &[Entry],
    booked: &BTreeSet<String>,
) -> Result<(), Refusal> {
    let ids: HashSet<&str> = entries.iter().map(|e| e.id.as_str()).collect();
    let ready: HashSet<&str> = entries
        .iter()
        .filter(|e| e.blocked.is_none() && !e.already_booked)
        .map(|e| e.id.as_str())
        .collect();
    let originals: BTreeSet<&str> = refunds
        .links()
        .iter()
        .filter(|l| ids.contains(l.refund_id.as_str()))
        .map(|l| l.original_id.as_str())
        .collect();
    for original in originals {
        let members = refunds.group(original);
        let any_booked = members.iter().any(|m| booked.contains(m));
        let ready_members = members
            .iter()
            .filter(|m| ready.contains(m.as_str()))
            .count();
        if !any_booked && 0 < ready_members && ready_members < members.len() {
            return Err(Refusal::HalfBooked);
        }
    }
    Ok(())
}

/// 한 원결제 묶음의 구성원 연결. 모두 검증 연결(추론 아님, 순액 0 전액 상쇄 또는 원승인번호 부분환불)이어야 한다.
fn verified_links<'a>(refunds: &'a Refunds, original: &str) -> Result<Vec<&'a Link>, Refusal> {
    let links: Vec<&Link> = refunds
        .links()
        .iter()
        .filter(|l| l.original_id == original)
        .collect();
    if links.is_empty() {
        return Err(Refusal::NoRefunds);
    }
    if links.iter().any(|l| !l.is_verified()) {
        return Err(Refusal::NotVerified);
    }
    Ok(links)
}

/// `scope_group`의 판정 부분: 묶음을 호출자가 줄이지 못하고, 구성원이 모두 이 범위에 있어야 하며, 보류된 묶음은 기록 불가다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Scope {
    pub recordable: bool,
}

pub fn scope_group(refunds: &Refunds, entries: &[Entry], original: &str) -> Result<Scope, Refusal> {
    verified_links(refunds, original)?;
    let members = refunds.group(original);
    let mut rows = Vec::with_capacity(members.len());
    for member in &members {
        rows.push(
            entries
                .iter()
                .rev()
                .find(|e| &e.id == member)
                .ok_or_else(|| Refusal::MemberMissing(member.clone()))?,
        );
    }
    let all_booked = rows.iter().all(|e| e.already_booked);
    let any_held = rows.iter().any(|e| holds(e));
    Ok(Scope {
        recordable: all_booked || !any_held,
    })
}

/// `_ready_rows`의 검증 묶음 확장: 이 접수 범위의 환불·원결제가 속한 검증 묶음의 나머지 구성원 ID.
/// 부분환불은 완료 기간·깨끗하지 않은 구성원이 없을 때만 넓힌다. 실제로 가져올 수 있는지는 호출자가 출처 접수로 확인한다.
pub fn extension(refunds: &Refunds, current: &BTreeSet<String>) -> BTreeSet<String> {
    let mut extra = BTreeSet::new();
    for link in refunds.links() {
        if !link.is_verified() {
            continue;
        }
        if link.is_numbered_partial() && refunds.exclusion(&link.original_id).is_some() {
            continue;
        }
        if current.contains(&link.refund_id) || current.contains(&link.original_id) {
            extra.extend(refunds.group(&link.original_id));
        }
    }
    extra.retain(|id| !current.contains(id));
    extra
}

/// `RefundGroup`의 유일한 발급처(RFND-044, SPEC §13). 아래 하나라도 해당하면 만들지 않는다.
/// 추론·초과 환불·검증 밖 연결, 이 범위에 없는 구성원, 완료 기간 구성원과 깨끗하지 않은 취소(PROC-072, RFND-006).
/// Python의 전액 상쇄 확장은 완료 기간을 거르지 않지만, 묶음 게시는 완료 자료를 건드리지 않도록 더 엄격하다.
#[cfg_attr(not(test), allow(dead_code))] // 게시 단위(U14)가 쓴다
pub(crate) fn issue_group(
    refunds: &Refunds,
    entries: &[Entry],
    original: &str,
) -> Result<RefundGroup, Refusal> {
    verified_links(refunds, original)?;
    let members = refunds.group(original);
    if let Some(missing) = members
        .iter()
        .find(|m| !entries.iter().any(|e| &e.id == *m))
    {
        return Err(Refusal::MemberMissing(missing.clone()));
    }
    if let Some(exclusion) = refunds.exclusion(original) {
        return Err(Refusal::Excluded(exclusion));
    }
    let ids = members
        .iter()
        .map(|m| TxnId::new(m.clone()))
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| Refusal::BadId)?;
    RefundGroup::new(RefundGroupId::for_original(original), ids).map_err(|_| Refusal::BadId)
}
