//! 국가·지역·온라인 판정. 기대값은 Python `merchant_country`·`transaction_region`·`is_booking_or_online` 출력이다.

use cost_core::rules::{Transaction, is_booking_or_online, merchant_country, transaction_region};
use serde_json::json;

#[test]
fn country_region_and_online_match_python() {
    let cases = [
        (
            json!({"merchant": "SYN CAFE JP", "card_kind": "해외"}),
            "JP",
            "overseas",
            false,
        ),
        (
            json!({"merchant": "X", "raw_row": {"country": "JPN"}}),
            "JP",
            "overseas",
            false,
        ),
        (
            json!({"merchant": "SHOP  TOKYO JP", "card_kind": "해외"}),
            "JP",
            "overseas",
            false,
        ),
        (
            json!({"merchant": "A", "issuer": "국민", "raw_row": {"c8": "usa"}}),
            "US",
            "overseas",
            false,
        ),
        (
            json!({"merchant": "A", "card_kind": "국내"}),
            "KR",
            "KR",
            false,
        ),
        (
            json!({"merchant": "A", "foreign_currency": "JPY"}),
            "",
            "overseas",
            false,
        ),
        (json!({"merchant": "Agoda Hotel"}), "", "", true),
        (
            json!({"merchant": "Z", "description_raw": "card-category:통신판매"}),
            "",
            "",
            true,
        ),
        (
            json!({"merchant": "Z", "raw_row": {"c11": "해외사용"}}),
            "",
            "overseas",
            false,
        ),
        (json!({"merchant": "SHOP SGP"}), "SG", "overseas", false),
    ];
    for (value, country, region, online) in cases {
        let txn = Transaction::from_value(&value);
        assert_eq!(merchant_country(&txn), country, "{value}");
        assert_eq!(transaction_region(&txn), region, "{value}");
        assert_eq!(is_booking_or_online(&txn), online, "{value}");
    }
}
