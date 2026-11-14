//! Python `Decimal`의 필요한 부분만: 파싱·비교·뺄셈. 유한한 값만 다룬다(NaN·Infinity는 파싱 실패).
//! 가수가 `i128`에 안 들어가는 극단값(약 1e38 초과)은 파싱 실패로 닫힌다.

use std::cmp::Ordering;

#[derive(Debug, Clone, Copy)]
pub struct Dec {
    m: i128,
    scale: u32,
}

fn pow10(n: u32) -> Option<i128> {
    10i128.checked_pow(n)
}

impl Dec {
    pub fn from_int(value: i64) -> Dec {
        Dec {
            m: i128::from(value),
            scale: 0,
        }
    }

    /// `Decimal(text)`(앞뒤 공백 허용, 지수 표기 허용). 실패하면 `None`.
    pub fn parse(text: &str) -> Option<Dec> {
        let t = text.trim();
        let (neg, rest) = match t.as_bytes().first()? {
            b'-' => (true, &t[1..]),
            b'+' => (false, &t[1..]),
            _ => (false, t),
        };
        let (mant, exp) = match rest.find(['e', 'E']) {
            Some(i) => (&rest[..i], rest[i + 1..].parse::<i32>().ok()?),
            None => (rest, 0),
        };
        let (int_part, frac_part) = match mant.split_once('.') {
            Some((a, b)) => (a, b),
            None => (mant, ""),
        };
        if int_part.len() + frac_part.len() == 0
            || !int_part
                .bytes()
                .chain(frac_part.bytes())
                .all(|b| b.is_ascii_digit())
        {
            return None;
        }
        let digits = format!("{int_part}{frac_part}");
        let mut m: i128 = digits.parse().ok()?;
        let mut scale = i64::try_from(frac_part.len()).ok()? - i64::from(exp);
        if scale < 0 {
            m = m.checked_mul(pow10(u32::try_from(-scale).ok()?)?)?;
            scale = 0;
        }
        Some(Dec {
            m: if neg { -m } else { m },
            scale: u32::try_from(scale).ok().filter(|s| *s <= 38)?,
        })
    }

    pub fn abs(self) -> Dec {
        Dec {
            m: self.m.abs(),
            scale: self.scale,
        }
    }

    pub fn is_zero(self) -> bool {
        self.m == 0
    }

    pub fn is_positive(self) -> bool {
        self.m > 0
    }

    fn align(a: Dec, b: Dec) -> Option<(i128, i128)> {
        let s = a.scale.max(b.scale);
        Some((
            a.m.checked_mul(pow10(s - a.scale)?)?,
            b.m.checked_mul(pow10(s - b.scale)?)?,
        ))
    }

    /// `self - other`(넘치면 `None`).
    pub fn checked_sub(self, other: Dec) -> Option<Dec> {
        let (a, b) = Dec::align(self, other)?;
        Some(Dec {
            m: a.checked_sub(b)?,
            scale: self.scale.max(other.scale),
        })
    }

    /// `self + other`(넘치면 `None`).
    pub fn checked_add(self, other: Dec) -> Option<Dec> {
        let (a, b) = Dec::align(self, other)?;
        Some(Dec {
            m: a.checked_add(b)?,
            scale: self.scale.max(other.scale),
        })
    }

    /// `str(Decimal)`(지수 표기 없는 값): 자릿수를 그대로 둔 평문.
    pub fn plain(self) -> String {
        let sign = if self.m < 0 { "-" } else { "" };
        let digits = self.m.unsigned_abs().to_string();
        if self.scale == 0 {
            return format!("{sign}{digits}");
        }
        let width = self.scale as usize;
        let padded = format!("{digits:0>w$}", w = width + 1);
        let (int_part, frac) = padded.split_at(padded.len() - width);
        format!("{sign}{int_part}.{frac}")
    }

    /// `format(value.normalize(), "f")`: 양수만. 뒤쪽 0을 줄인 평문 표기(`_canonical_group_amount`).
    pub fn canonical_positive(self) -> Option<String> {
        if self.m <= 0 {
            return None;
        }
        let (mut m, mut scale) = (self.m, self.scale);
        while scale > 0 && m % 10 == 0 {
            m /= 10;
            scale -= 1;
        }
        let digits = m.to_string();
        if scale == 0 {
            return Some(digits);
        }
        let width = scale as usize;
        let padded = format!("{digits:0>width$}", width = width + 1);
        let (int_part, frac) = padded.split_at(padded.len() - width);
        Some(format!("{int_part}.{frac}"))
    }

    /// 정수 `step`으로 나눈 나머지가 0인가(`Decimal % int == 0`, `step != 0`).
    pub fn divisible_by(self, step: i64) -> bool {
        let Some(unit) = pow10(self.scale).and_then(|p| p.checked_mul(i128::from(step))) else {
            return false;
        };
        unit != 0 && self.m % unit == 0
    }

    /// `int(self)`(0 쪽으로 자름).
    pub fn trunc(self) -> Option<i64> {
        i64::try_from(self.m / pow10(self.scale)?).ok()
    }

    /// `(self * rate / 10000)` 를 정수로 맞춘다. `mode`: floor·half_up·ceiling(양수 값 전제).
    pub fn discount(self, rate: i64, mode: &str) -> Option<i128> {
        let num = self.m.checked_mul(i128::from(rate))?;
        let den = pow10(self.scale)?.checked_mul(10_000)?;
        let (q, r) = (num.div_euclid(den), num.rem_euclid(den));
        match mode {
            "floor" => Some(q),
            "ceiling" => Some(q + i128::from(r > 0)),
            "half_up" => Some(q + i128::from(2 * r >= den)),
            _ => None,
        }
    }

    pub fn from_i128(m: i128) -> Dec {
        Dec { m, scale: 0 }
    }
}

impl PartialEq for Dec {
    fn eq(&self, other: &Dec) -> bool {
        self.partial_cmp(other) == Some(Ordering::Equal)
    }
}

impl PartialOrd for Dec {
    fn partial_cmp(&self, other: &Dec) -> Option<Ordering> {
        let (a, b) = Dec::align(*self, *other)?;
        Some(a.cmp(&b))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(s: &str) -> Dec {
        Dec::parse(s).unwrap()
    }

    #[test]
    fn parse_and_compare() {
        assert_eq!(d("30000"), d("30000.00"));
        assert_eq!(d(" 3e3 "), d("3000"));
        assert_eq!(d("-0"), d("0"));
        assert!(d("2.5") < d("3"));
        for bad in ["", "abc", "NaN", "Infinity", "1.2.3", "--1", "1e", "."] {
            assert!(Dec::parse(bad).is_none(), "{bad}");
        }
    }

    #[test]
    fn rounding_modes() {
        let a = d("1050");
        assert_eq!(a.discount(125, "floor"), Some(13)); // 13.125
        assert_eq!(a.discount(125, "ceiling"), Some(14));
        assert_eq!(d("1000").discount(125, "half_up"), Some(13)); // 12.5 -> 13
        assert_eq!(a.discount(125, "other"), None);
    }

    #[test]
    fn divisibility_and_difference() {
        assert!(d("-3000").divisible_by(1000));
        assert!(!d("-3500").divisible_by(1000));
        assert!(!d("-3000").divisible_by(0));
        assert_eq!(
            d("29000").checked_sub(d("30000")),
            Some(Dec::from_int(-1000))
        );
        assert_eq!(d("12.9").trunc(), Some(12));
        assert_eq!(d("-12.9").trunc(), Some(-12));
    }
}
