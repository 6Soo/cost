//! 식별자·이름 newtype. 빈 값은 만들 수 없다.

use std::fmt;

use super::error::DomainError;

macro_rules! text_id {
    ($(#[$m:meta])* $name:ident, $what:literal) => {
        $(#[$m])*
        #[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, DomainError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(DomainError::Empty($what));
                }
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(&self.0)
            }
        }
    };
}

text_id!(
    /// 카드 거래 ID.
    TxnId,
    "TxnId"
);
text_id!(ReceiptId, "ReceiptId");
text_id!(CashUseId, "CashUseId");
text_id!(RuleId, "RuleId");
text_id!(RunId, "RunId");
text_id!(ModelName, "ModelName");
text_id!(
    /// 수동 교정 이벤트 참조(`overrides` 행).
    ManualEventRef,
    "ManualEventRef"
);
text_id!(
    /// 확인하지 못한 것 한 줄.
    Uncertainty,
    "Uncertainty"
);

/// 원본 해시(sha256 소문자 16진 64자).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SourceHash(String);

impl SourceHash {
    pub fn new(value: impl Into<String>) -> Result<Self, DomainError> {
        let value = value.into();
        if value.len() != 64
            || !value
                .bytes()
                .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(DomainError::BadSourceHash);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// 규칙집 ID. `PROC-001`, `ITEM-019`처럼 대문자 접두 + `-` + 숫자.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PolicyRef(String);

impl PolicyRef {
    pub fn new(value: impl Into<String>) -> Result<Self, DomainError> {
        let value = value.into();
        let ok = value.split_once('-').is_some_and(|(prefix, num)| {
            !prefix.is_empty()
                && prefix.bytes().all(|b| b.is_ascii_uppercase())
                && !num.is_empty()
                && num.bytes().all(|b| b.is_ascii_digit())
        });
        if !ok {
            return Err(DomainError::BadPolicyRef);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// 여행 ID. Google 시트 탭 스냅숏(`TripCatalog`)에서만 나온다. 문자열 생성자가 없다.
///
/// ```compile_fail
/// let _ = cost_core::domain::TripId("x".to_string());
/// ```

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct TripId(String);

impl TripId {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// `trip_tabs` 스냅숏. 여행을 만들어내지 않고 읽은 탭만 해석한다.
#[derive(Debug, Clone, Default)]
pub struct TripCatalog {
    tabs: Vec<String>,
}

impl TripCatalog {
    pub fn from_snapshot(tabs: impl IntoIterator<Item = String>) -> Self {
        let mut tabs: Vec<String> = tabs
            .into_iter()
            .map(|t| t.trim().to_owned())
            .filter(|t| !t.is_empty())
            .collect();
        tabs.sort();
        tabs.dedup();
        Self { tabs }
    }

    pub fn resolve(&self, tab_id: &str) -> Option<TripId> {
        let tab_id = tab_id.trim();
        self.tabs
            .binary_search_by(|t| t.as_str().cmp(tab_id))
            .ok()
            .map(|_| TripId(tab_id.to_owned()))
    }

    pub fn len(&self) -> usize {
        self.tabs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tabs.is_empty()
    }
}

/// 환불 묶음 ID. `RefundGroup`에서만 얻는다.

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RefundGroupId(pub(crate) String);

impl RefundGroupId {
    /// 원결제의 환불 묶음 ID(`refund:{원결제}`). 이 문자열을 만드는 유일한 곳이다.
    pub(crate) fn for_original(original: &str) -> Self {
        RefundGroupId(format!("refund:{original}"))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// 분기 번호 1~4.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Quarter {
    Q1 = 1,
    Q2 = 2,
    Q3 = 3,
    Q4 = 4,
}

impl Quarter {
    pub fn from_number(n: u8) -> Result<Self, DomainError> {
        match n {
            1 => Ok(Self::Q1),
            2 => Ok(Self::Q2),
            3 => Ok(Self::Q3),
            4 => Ok(Self::Q4),
            _ => Err(DomainError::BadQuarter(n)),
        }
    }

    pub fn number(self) -> u8 {
        self as u8
    }
}
