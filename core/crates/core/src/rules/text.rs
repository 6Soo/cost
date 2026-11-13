//! 가맹점 이름 접기. 원본: `app/normalize.py` `normalize_merchant`.

/// Python `str.casefold()`의 근사: 소문자화에 `ß`·`ſ` 접기를 더한다.
pub fn casefold(s: &str) -> String {
    s.to_lowercase().replace('ß', "ss").replace('ſ', "s")
}

/// 대소문자와 반복 공백만 접는다. 문장부호·음역·유사 일치는 하지 않는다.
pub fn normalize_merchant(value: &str) -> String {
    casefold(&value.split_whitespace().collect::<Vec<_>>().join(" "))
}
