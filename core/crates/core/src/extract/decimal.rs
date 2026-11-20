//! Extractor comparisons need no arithmetic: retain all coefficient digits so
//! high-precision source amounts never overflow an integer or round through f64.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Decimal {
    negative: bool,
    digits: String,
    exponent: i64,
}

impl Decimal {
    pub(super) fn parse(value: &str) -> Option<Self> {
        let value = value.trim().replace('_', "");
        let (negative, value) = if let Some(v) = value.strip_prefix('-') {
            (true, v)
        } else {
            (false, value.strip_prefix('+').unwrap_or(&value))
        };
        let (coefficient, exponent) = match value.find(['e', 'E']) {
            Some(i) => (&value[..i], value[i + 1..].parse::<i64>().ok()?),
            None => (value, 0),
        };
        let (integer, fraction) = coefficient.split_once('.').unwrap_or((coefficient, ""));
        if integer.len() + fraction.len() == 0
            || !integer
                .bytes()
                .chain(fraction.bytes())
                .all(|c| c.is_ascii_digit())
        {
            return None;
        }
        let combined = format!("{integer}{fraction}");
        let digits = combined.trim_start_matches('0');
        if digits.is_empty() {
            return Some(Self {
                negative: false,
                digits: "0".into(),
                exponent: 0,
            });
        }
        let normalized = digits.trim_end_matches('0');
        let exponent = exponent
            .checked_sub(i64::try_from(fraction.len()).ok()?)?
            .checked_add(i64::try_from(digits.len() - normalized.len()).ok()?)?;
        Some(Self {
            negative,
            digits: normalized.to_owned(),
            exponent,
        })
    }

    pub(super) fn is_zero(&self) -> bool {
        self.digits == "0"
    }
    pub(super) fn is_positive(&self) -> bool {
        !self.negative && !self.is_zero()
    }
    pub(super) fn abs(mut self) -> Self {
        self.negative = false;
        self
    }
}
