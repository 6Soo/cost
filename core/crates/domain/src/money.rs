//! 금액과 원천 거래. 금액 해석 실패는 0원이 아니라 `Unreadable`이다.

use time::Date;

use crate::ids::{SourceHash, TxnId};

/// 원화 금액(부호 있음).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct KrwAmount(i64);

impl KrwAmount {
    pub fn new(value: i64) -> Self {
        Self(value)
    }

    pub fn get(self) -> i64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParseErrorKind {
    Empty,
    NotNumeric,
    Overflow,
}

/// 금액 해석 오류. 원문은 담지 않는다.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ParseError {
    pub kind: ParseErrorKind,
}

/// 금액. `Default`를 구현하지 않는다(해석 실패를 0원으로 쓰지 않는다).
///
/// ```compile_fail
/// let _ = <cost_domain::Amount as Default>::default();
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Amount {
    Readable(KrwAmount),
    Unreadable(ParseError),
}

impl Amount {
    /// 쉼표·공백을 허용하는 정수 금액 해석. 그 밖은 `Unreadable`.
    pub fn parse(raw: &str) -> Self {
        let cleaned: String = raw
            .chars()
            .filter(|c| *c != ',' && !c.is_whitespace())
            .collect();
        let fail = |kind| Self::Unreadable(ParseError { kind });
        if cleaned.is_empty() {
            return fail(ParseErrorKind::Empty);
        }
        let digits = cleaned.strip_prefix(['-', '+']).unwrap_or(&cleaned);
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
            return fail(ParseErrorKind::NotNumeric);
        }
        match cleaned.parse::<i64>() {
            Ok(v) => Self::Readable(KrwAmount(v)),
            Err(_) => fail(ParseErrorKind::Overflow),
        }
    }

    pub fn readable(self) -> Option<KrwAmount> {
        match self {
            Self::Readable(a) => Some(a),
            Self::Unreadable(_) => None,
        }
    }
}

/// 거래 방향.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    Purchase,
    Refund,
}

/// 카드 원천 거래. 필드는 비공개이며 getter만 있다(수정 경로 없음).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceTxn {
    transaction_id: TxnId,
    source_hash: SourceHash,
    revision: u32,
    amount: Amount,
    direction: Direction,
    occurred_on: Date,
    merchant: String,
}

impl SourceTxn {
    pub fn new(
        transaction_id: TxnId,
        source_hash: SourceHash,
        revision: u32,
        amount: Amount,
        direction: Direction,
        occurred_on: Date,
        merchant: String,
    ) -> Self {
        Self {
            transaction_id,
            source_hash,
            revision,
            amount,
            direction,
            occurred_on,
            merchant,
        }
    }

    pub fn transaction_id(&self) -> &TxnId {
        &self.transaction_id
    }
    pub fn source_hash(&self) -> &SourceHash {
        &self.source_hash
    }
    pub fn revision(&self) -> u32 {
        self.revision
    }
    pub fn amount(&self) -> Amount {
        self.amount
    }
    pub fn direction(&self) -> Direction {
        self.direction
    }
    pub fn occurred_on(&self) -> Date {
        self.occurred_on
    }
    pub fn merchant(&self) -> &str {
        &self.merchant
    }
}
