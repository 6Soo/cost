//! 짝 도출(`app/partial_refund.py`): 원승인번호 1:N → 외화 금액 → 동액·카카오 추론 순서, 개수 보호, 검토 원결제.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::hash::Hash;

use time::Date;

use super::{Basis, Exclusion, Held, Link, PairingConfig, RefundTxn, Refunds, Status};
use crate::dates::{RowDates, completed_period, parse_iso};

pub(super) struct Analysis {
    pub links: Vec<Link>,
    pub held: BTreeMap<String, Held>,
}

/// Python 문자열 `strip(" \t\n\v\f\r")`와 SQL `TRIM(x, char(9)||...||' ')`의 같은 문자 집합.
pub(super) fn trim_ws(s: &str) -> &str {
    s.trim_matches(|c| matches!(c, ' ' | '\t' | '\n' | '\x0b' | '\x0c' | '\r'))
}

fn clean(r: &RefundTxn) -> bool {
    r.duplicate_of.is_none() && r.conflict_reason.is_empty() && r.parse_error.is_empty()
}

fn is_cancellation(r: &RefundTxn) -> bool {
    r.direction == "cancellation" && r.amount_krw.is_some_and(|a| a < 0)
}

/// `COALESCE(NULLIF(approval_date,''),posting_date)`
fn use_day_text(r: &RefundTxn) -> &str {
    if r.approval_date.is_empty() {
        &r.posting_date
    } else {
        &r.approval_date
    }
}

/// `_day`: 앞 10글자를 `YYYY-MM-DD`로 읽는다. 읽지 못하면 없음(그 행은 이 연결에서 빠진다).
fn day(text: &str) -> Option<Date> {
    let head: String = text.chars().take(10).collect();
    parse_iso(&head).ok()
}

/// 순서를 지키는 묶음 사전(Python dict의 삽입 순서).
struct Ordered<K, V> {
    index: HashMap<K, usize>,
    items: Vec<(K, Vec<V>)>,
}

impl<K: Hash + Eq + Clone, V> Ordered<K, V> {
    fn new() -> Self {
        Self {
            index: HashMap::new(),
            items: Vec::new(),
        }
    }

    fn push(&mut self, key: K, value: V) {
        match self.index.get(&key) {
            Some(&i) => self.items[i].1.push(value),
            None => {
                self.index.insert(key.clone(), self.items.len());
                self.items.push((key, vec![value]));
            }
        }
    }

    fn get(&self, key: &K) -> Option<&Vec<V>> {
        self.index.get(key).map(|&i| &self.items[i].1)
    }
}

/// 원승인번호 1:N 연결(RFND-004·005). 깨끗한 취소를 같은 카드·같은 번호의 구매 하나에 잇는다.
fn number_links(rows: &[RefundTxn]) -> Vec<Link> {
    type Key = (String, String, String);
    let mut purchases: HashMap<Key, Vec<(&str, i64, bool)>> = HashMap::new();
    let mut cancels: HashMap<Key, Vec<(&str, i64)>> = HashMap::new();
    for r in rows {
        let (Some(amount), approval) = (r.amount_krw, trim_ws(&r.approval_number)) else {
            continue;
        };
        if r.direction == "purchase" && amount > 0 && !approval.is_empty() {
            let key = (r.issuer.clone(), r.card_tail.clone(), approval.to_string());
            purchases
                .entry(key)
                .or_default()
                .push((&r.transaction_id, amount, clean(r)));
        } else if clean(r)
            && r.direction == "cancellation"
            && !r.original_approval_number.is_empty()
            && amount < 0
        {
            let key = (
                r.issuer.clone(),
                r.card_tail.clone(),
                trim_ws(&r.original_approval_number).to_string(),
            );
            cancels
                .entry(key)
                .or_default()
                .push((&r.transaction_id, amount));
        }
    }
    let mut links = Vec::new();
    for r in rows {
        if !(is_cancellation(r) && clean(r) && !trim_ws(&r.original_approval_number).is_empty()) {
            continue;
        }
        if r.issuer.is_empty() || r.card_tail.is_empty() {
            continue;
        }
        let key = (
            r.issuer.clone(),
            r.card_tail.clone(),
            trim_ws(&r.original_approval_number).to_string(),
        );
        let [(original_id, gross, original_clean)] =
            purchases.get(&key).map(Vec::as_slice).unwrap_or(&[])
        else {
            continue;
        };
        if !original_clean {
            continue;
        }
        let siblings = cancels.get(&key).map(Vec::as_slice).unwrap_or(&[]);
        let refund_total: i64 = siblings.iter().map(|(_, a)| a).sum();
        let Some(&(_, own)) = siblings.iter().find(|(id, _)| *id == r.transaction_id) else {
            continue;
        };
        let net = gross + refund_total;
        links.push(Link {
            refund_id: r.transaction_id.clone(),
            original_id: (*original_id).to_string(),
            gross_krw: *gross,
            refund_krw: own,
            refunds_total_krw: refund_total,
            net_krw: net,
            status: match net {
                n if n < 0 => Status::Excess,
                0 => Status::Full,
                _ => Status::Partial,
            },
            refund_count: u32::try_from(siblings.len()).unwrap_or(u32::MAX),
            basis: None,
            inferred: false,
        });
    }
    links
}

/// 정규화한 10진수(유효숫자, 지수). `Decimal` 동등 비교와 같게 `1500`과 `1500.0`이 같은 키가 된다.
type Decimal = (String, i64);

/// `_foreign_amount`: 쉼표를 빼고 읽은 절댓값. 0·읽지 못함·유한하지 않음은 없음.
pub(super) fn foreign_amount(value: &str) -> Option<Decimal> {
    let cleaned = value.replace(',', "");
    let text = cleaned.trim();
    let text = text.strip_prefix(['+', '-']).unwrap_or(text);
    let (mantissa, exponent) = match text.find(['e', 'E']) {
        Some(i) => (&text[..i], text[i + 1..].parse::<i64>().ok()?),
        None => (text, 0),
    };
    let (int, frac) = mantissa.split_once('.').unwrap_or((mantissa, ""));
    if (int.is_empty() && frac.is_empty())
        || !int.bytes().chain(frac.bytes()).all(|b| b.is_ascii_digit())
    {
        return None;
    }
    let mut digits = format!("{int}{frac}").trim_start_matches('0').to_string();
    if digits.is_empty() {
        return None;
    }
    let mut scale = exponent.checked_sub(i64::try_from(frac.len()).ok()?)?;
    while digits.ends_with('0') {
        digits.pop();
        scale = scale.checked_add(1)?;
    }
    Some((digits, scale))
}

type PoolKey = (String, String, String, String, Decimal);

struct Pool {
    purchases: Ordered<PoolKey, (usize, i64, Date)>,
    cancels: Ordered<PoolKey, (usize, i64, Date)>,
}

/// `_foreign_pool`: 카드·가맹점·통화·외화 금액별 구매와 취소(승인번호 없는 취소만).
fn foreign_pool(rows: &[RefundTxn], taken: &HashSet<&str>, include_protected: bool) -> Pool {
    let mut pool = Pool {
        purchases: Ordered::new(),
        cancels: Ordered::new(),
    };
    for (i, r) in rows.iter().enumerate() {
        if !(include_protected || clean(r))
            || r.foreign_currency.is_empty()
            || r.foreign_amount.is_empty()
        {
            continue;
        }
        let Some(amount) = r.amount_krw else { continue };
        let purchase = r.direction == "purchase" && amount > 0;
        let cancel =
            r.direction == "cancellation" && amount < 0 && r.original_approval_number.is_empty();
        if !(purchase || cancel) {
            continue;
        }
        let currency = r.foreign_currency.trim().to_uppercase();
        let (Some(foreign), Some(when)) = (foreign_amount(&r.foreign_amount), day(use_day_text(r)))
        else {
            continue;
        };
        if currency.is_empty() || r.merchant_normalized.is_empty() {
            continue;
        }
        let key = (
            r.issuer.clone(),
            r.card_tail.clone(),
            r.merchant_normalized.clone(),
            currency,
            foreign,
        );
        if purchase {
            if !taken.contains(r.transaction_id.as_str()) {
                pool.purchases.push(key, (i, amount, when));
            }
        } else {
            pool.cancels.push(key, (i, amount, when));
        }
    }
    pool
}

/// 외화 금액 연결(RFND-011~013): 날짜순으로 구매 하나에 취소 하나, 구매가 취소보다 앞서고 기간 안.
fn foreign_links(rows: &[RefundTxn], pool: &Pool, config: &PairingConfig) -> Vec<Link> {
    if !config.enabled {
        return Vec::new();
    }
    let mut links = Vec::new();
    for (key, refunds) in &pool.cancels.items {
        let mut open: Vec<(usize, i64, Date)> =
            pool.purchases.get(key).cloned().unwrap_or_default();
        open.sort_by(|a, b| {
            (a.2, &rows[a.0].transaction_id).cmp(&(b.2, &rows[b.0].transaction_id))
        });
        let mut ordered = refunds.clone();
        ordered.sort_by(|a, b| {
            (a.2, &rows[a.0].transaction_id).cmp(&(b.2, &rows[b.0].transaction_id))
        });
        for (refund_index, refund_amount, refund_when) in ordered {
            let Some(position) = open.iter().position(|p| {
                let days = (refund_when - p.2).whole_days();
                (0..=config.max_days_after_purchase).contains(&days)
            }) else {
                continue;
            };
            let (original_index, gross, _) = open.remove(position);
            let net = gross + refund_amount;
            links.push(Link {
                refund_id: rows[refund_index].transaction_id.clone(),
                original_id: rows[original_index].transaction_id.clone(),
                gross_krw: gross,
                refund_krw: refund_amount,
                refunds_total_krw: refund_amount,
                net_krw: net,
                status: if net == 0 {
                    Status::Full
                } else {
                    Status::Partial
                },
                refund_count: 1,
                basis: Some(Basis::MerchantCardForeignAmount),
                inferred: false,
            });
        }
    }
    links
}

/// `_kakao_merchant_family`: 택시 표기 차이만 묶고 다른 카카오 서비스는 같은 이름만 같다.
fn kakao_family(merchant: &str) -> String {
    let compact: String = merchant
        .to_lowercase()
        .chars()
        .filter(|c| c.is_ascii_digit() || c.is_ascii_lowercase() || ('가'..='힣').contains(c))
        .collect();
    let taxi = ["카카오t", "카카오택시", "카카오모빌리티택시"]
        .iter()
        .any(|p| compact.starts_with(p))
        && !["대리", "주차", "바이크", "퀵"]
            .iter()
            .any(|w| compact.contains(w));
    if taxi {
        "카카오택시".to_string()
    } else {
        compact
    }
}

struct Candidate<'a> {
    index: usize,
    amount: i64,
    when: Date,
    merchant: &'a str,
    clean: bool,
    normalized: &'a str,
}

/// 동액 추론 연결(RFND-007~009): 같은 카드·같은 금액, 같은 가맹점 같은 날 또는 카카오 14일 안. 전역 양방향 유일해야 한다.
fn amount_inferred_links(
    rows: &[RefundTxn],
    taken: &HashSet<&str>,
    occupied: &HashSet<&str>,
) -> Vec<Link> {
    let mut purchases: HashMap<(&str, &str, i64), Vec<Candidate>> = HashMap::new();
    let mut refunds: Vec<(Candidate, &RefundTxn)> = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let Some(amount) = r.amount_krw else { continue };
        let purchase = r.direction == "purchase" && amount > 0;
        let cancel = r.direction == "cancellation"
            && amount < 0
            && trim_ws(&r.original_approval_number).is_empty();
        if !(purchase || cancel)
            || r.issuer.is_empty()
            || r.card_tail.is_empty()
            || r.merchant.is_empty()
        {
            continue;
        }
        let Some(when) = day(use_day_text(r)) else {
            continue;
        };
        let normalized = if r.merchant_normalized.is_empty() {
            &r.merchant
        } else {
            &r.merchant_normalized
        };
        let entry = Candidate {
            index: i,
            amount: amount.abs(),
            when,
            merchant: &r.merchant,
            clean: clean(r) && r.foreign_currency.is_empty() && r.foreign_amount.is_empty(),
            normalized: normalized.trim(),
        };
        if purchase {
            purchases
                .entry((&r.issuer, &r.card_tail, entry.amount))
                .or_default()
                .push(entry);
        } else {
            refunds.push((entry, r));
        }
    }
    let kakao = |a: &str, b: &str| a.contains("카카오") && b.contains("카카오");
    let mut collisions: HashMap<usize, u32> = HashMap::new();
    let mut candidates: Vec<(usize, &Candidate, Basis)> = Vec::new();
    for (refund, r) in &refunds {
        let matches: Vec<&Candidate> = purchases
            .get(&(r.issuer.as_str(), r.card_tail.as_str(), refund.amount))
            .into_iter()
            .flatten()
            .filter(|p| {
                let days = (refund.when - p.when).whole_days();
                ((0..=14).contains(&days) && kakao(refund.merchant, p.merchant))
                    || (refund.when == p.when && refund.normalized == p.normalized)
            })
            .collect();
        for p in &matches {
            *collisions.entry(p.index).or_default() += 1;
        }
        if let [purchase] = matches.as_slice()
            && refund.clean
        {
            let both = kakao(refund.merchant, purchase.merchant);
            if both && kakao_family(purchase.merchant) != kakao_family(refund.merchant) {
                continue;
            }
            let basis = if both {
                Basis::KakaoSameCardExactAmount
            } else {
                Basis::SameCardMerchantDayExactAmount
            };
            candidates.push((refund.index, *purchase, basis));
        }
    }
    let mut links = Vec::new();
    for (refund_index, purchase, basis) in candidates {
        let (refund_id, original_id) = (
            &rows[refund_index].transaction_id,
            &rows[purchase.index].transaction_id,
        );
        if !purchase.clean
            || taken.contains(original_id.as_str())
            || occupied.contains(refund_id.as_str())
            || collisions.get(&purchase.index) != Some(&1)
        {
            continue;
        }
        links.push(Link {
            refund_id: refund_id.clone(),
            original_id: original_id.clone(),
            gross_krw: purchase.amount,
            refund_krw: -purchase.amount,
            refunds_total_krw: -purchase.amount,
            net_krw: 0,
            status: Status::Full,
            refund_count: 1,
            basis: Some(basis),
            inferred: false,
        });
    }
    links
}

pub(super) fn analyse(rows: &[RefundTxn], config: &PairingConfig) -> Analysis {
    let numbered = number_links(rows);
    let mut taken: HashSet<&str> = numbered.iter().map(|l| l.original_id.as_str()).collect();
    let pool = foreign_pool(rows, &taken, false);
    let foreign = foreign_links(rows, &pool, config);
    let paired: HashSet<&str> = foreign.iter().map(|l| l.refund_id.as_str()).collect();
    let mut held = BTreeMap::new();
    if config.enabled {
        for (key, refunds) in &pool.cancels.items {
            let Some(purchases) = pool.purchases.get(key).filter(|p| !p.is_empty()) else {
                continue;
            };
            for (index, _, _) in refunds {
                let id = &rows[*index].transaction_id;
                if !paired.contains(id.as_str()) {
                    held.insert(
                        id.clone(),
                        Held {
                            purchases: purchases.len(),
                            cancellations: refunds.len(),
                        },
                    );
                }
            }
        }
    }
    taken.extend(foreign.iter().map(|l| l.original_id.as_str()));
    let occupied: HashSet<&str> = numbered
        .iter()
        .map(|l| l.refund_id.as_str())
        .chain(paired.iter().copied())
        .collect();
    let inferred = amount_inferred_links(rows, &taken, &occupied);
    let links = numbered
        .into_iter()
        .chain(foreign)
        .chain(inferred)
        .collect();
    Analysis { links, held }
}

/// `partial_group_exclusion`: 완료 기간이 먼저, 그다음 같은 원승인번호의 오류·중복·충돌 취소.
pub(super) fn exclusion(refunds: &Refunds, original_id: &str) -> Option<Exclusion> {
    for id in refunds.group(original_id) {
        if let Some(row) = refunds.row(&id) {
            let dates = RowDates {
                approval_date: Some(row.approval_date.clone()),
                posting_date: Some(row.posting_date.clone()),
            };
            if completed_period(&dates).is_some() {
                return Some(Exclusion::CompletedPeriod);
            }
        }
    }
    let original = refunds.row(original_id)?;
    let reference = trim_ws(&original.approval_number);
    let unclean = refunds.rows.iter().any(|c| {
        c.direction == "cancellation"
            && c.issuer == original.issuer
            && c.card_tail == original.card_tail
            && trim_ws(&c.original_approval_number) == reference
            && !clean(c)
    });
    unclean.then_some(Exclusion::UncleanMember)
}

/// `refund_review_originals`: 실제 연결, 해소되지 않은 참조, 외화·동액 후보의 원결제를 모두 보호한다.
pub(super) fn review_originals(refunds: &Refunds) -> Vec<String> {
    let rows = refunds.rows;
    let linked: HashSet<&str> = refunds.links.iter().map(|l| l.refund_id.as_str()).collect();
    let mut protected: BTreeSet<String> = refunds
        .links
        .iter()
        .map(|l| l.original_id.clone())
        .collect();

    // 참조는 중복 원결제로 연결이 안 되어도 보호한다.
    let mut references: HashSet<(&str, &str, &str)> = HashSet::new();
    for c in rows {
        if c.direction == "cancellation"
            || c.direction == "refund"
            || c.amount_krw.is_some_and(|a| a < 0)
        {
            references.insert((
                &c.issuer,
                &c.card_tail,
                trim_ws(&c.original_approval_number),
            ));
        }
    }
    for p in rows {
        let approval = trim_ws(&p.approval_number);
        if p.direction == "purchase"
            && !approval.is_empty()
            && references.contains(&(&*p.issuer, &*p.card_tail, approval))
        {
            protected.insert(p.transaction_id.clone());
        }
    }

    // 외화 후보: 구매 뒤 기간 안에 연결 안 된 취소가 있다.
    let pool = foreign_pool(rows, &HashSet::new(), true);
    for (key, candidates) in &pool.purchases.items {
        for (index, _, when) in candidates {
            let hit = pool.cancels.get(key).is_some_and(|cancels| {
                cancels.iter().any(|(rid, _, refund_when)| {
                    let days = (*refund_when - *when).whole_days();
                    (0..=refunds.config.max_days_after_purchase).contains(&days)
                        && !linked.contains(rows[*rid].transaction_id.as_str())
                })
            });
            if hit {
                protected.insert(rows[*index].transaction_id.clone());
            }
        }
    }

    // 국내 후보: 같은 카드·같은 금액, 같은 가맹점 같은 날 또는 카카오 14일 안(오류 행도 경쟁자로 보호).
    let mut by_amount: HashMap<(&str, &str, i64), Vec<&RefundTxn>> = HashMap::new();
    for p in rows {
        if let (true, Some(a)) = (p.direction == "purchase", p.amount_krw)
            && a > 0
            && p.foreign_currency.is_empty()
            && p.foreign_amount.is_empty()
        {
            by_amount
                .entry((&p.issuer, &p.card_tail, a))
                .or_default()
                .push(p);
        }
    }
    for c in rows {
        let Some(amount) = c.amount_krw else { continue };
        if !(c.direction == "cancellation" || c.direction == "refund")
            || !c.original_approval_number.trim_matches(' ').is_empty()
            || !c.foreign_currency.is_empty()
            || !c.foreign_amount.is_empty()
            || linked.contains(c.transaction_id.as_str())
        {
            continue;
        }
        let end = day(use_day_text(c));
        for p in by_amount
            .get(&(c.issuer.as_str(), c.card_tail.as_str(), -amount))
            .into_iter()
            .flatten()
        {
            let start = day(use_day_text(p));
            let (Some(start), Some(end)) = (start, end) else {
                continue;
            };
            let same_day = start == end
                && !p.merchant_normalized.is_empty()
                && p.merchant_normalized == c.merchant_normalized;
            let taxi = p.merchant.contains("카카오")
                && c.merchant.contains("카카오")
                && (0..=14).contains(&(end - start).whole_days());
            if same_day || taxi {
                protected.insert(p.transaction_id.clone());
            }
        }
    }
    protected.into_iter().collect()
}
