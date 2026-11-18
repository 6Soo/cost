//! P2 요청 결속·결과 검증의 합성 단위 검사. 실제 모델 호출은 없다.
//! digest 결속, run_id 분리, 범위·형식·근거 보호, Replay 실행기를 검증한다.

use cost_core::p2::{self, P2Runner, Replay};
use serde_json::{Value, json};

fn input() -> Value {
    json!({
        "merchants": [{"merchant_id": "synthetic-a"}],
        "allowed_items": ["사무용품비"],
        "policy": "합성 규칙",
        "run_id": "abc123"
    })
}

fn answer(request: &Value) -> Value {
    json!({
        "request_digest": request["request_digest"],
        "run_id": request["run_id"],
        "results": [{
            "merchant_id": "synthetic-a",
            "item": "사무용품비",
            "confidence": "높음",
            "basis": "합성 문구류 구매 근거"
        }]
    })
}

#[test]
fn prepare_binds_digest_and_excludes_run_id() {
    let first = p2::prepare(&input()).unwrap();
    let digest = first["request_digest"].as_str().unwrap();
    assert_eq!(digest.len(), 64);
    assert!(digest.bytes().all(|b| b.is_ascii_hexdigit()));

    let mut other_run = input();
    other_run["run_id"] = json!("def456");
    let second = p2::prepare(&other_run).unwrap();
    assert_eq!(
        second["request_digest"], first["request_digest"],
        "run_id는 digest에 포함되지 않아야 한다"
    );

    let mut other_policy = input();
    other_policy["policy"] = json!("다른 규칙");
    assert_ne!(
        p2::prepare(&other_policy).unwrap()["request_digest"],
        first["request_digest"]
    );
    assert_eq!(
        p2::validate(&first, &answer(&first)).unwrap(),
        answer(&first)
    );
}

#[test]
fn prepare_rejects_invalid_request_shapes() {
    let mut extra = input();
    extra["unexpected"] = json!(true);
    assert_eq!(p2::prepare(&extra), Err("BATCH_REQUEST_INVALID"));

    let mut missing_run = input();
    missing_run.as_object_mut().unwrap().remove("run_id");
    assert_eq!(p2::prepare(&missing_run), Err("BATCH_REQUEST_INVALID"));

    let mut duplicate = input();
    duplicate["merchants"]
        .as_array_mut()
        .unwrap()
        .push(json!({"merchant_id": "synthetic-a"}));
    assert_eq!(p2::prepare(&duplicate), Err("BATCH_REQUEST_INVALID"));

    let mut bad_run = input();
    bad_run["run_id"] = json!("not-hex");
    assert_eq!(p2::prepare(&bad_run), Err("BATCH_REQUEST_INVALID"));

    let mut empty_policy = input();
    empty_policy["policy"] = json!("  ");
    assert_eq!(p2::prepare(&empty_policy), Err("BATCH_REQUEST_INVALID"));

    let mut too_many = input();
    too_many["merchants"] = json!(
        (0..51)
            .map(|i| json!({"merchant_id": format!("m-{i}")}))
            .collect::<Vec<_>>()
    );
    assert_eq!(p2::prepare(&too_many), Err("BATCH_REQUEST_INVALID"));
}

#[test]
fn validate_rejects_binding_and_envelope_mismatch() {
    let request = p2::prepare(&input()).unwrap();

    let mut wrong_digest = answer(&request);
    wrong_digest["request_digest"] = json!("0".repeat(64));
    assert_eq!(
        p2::validate(&request, &wrong_digest),
        Err("BATCH_BINDING_INVALID")
    );

    let mut wrong_run = answer(&request);
    wrong_run["run_id"] = json!("def456");
    assert_eq!(
        p2::validate(&request, &wrong_run),
        Err("BATCH_BINDING_INVALID")
    );

    let mut extra_key = answer(&request);
    extra_key["extra"] = json!(true);
    assert_eq!(
        p2::validate(&request, &extra_key),
        Err("BATCH_BINDING_INVALID")
    );

    assert_eq!(
        p2::validate(&request, &json!("not-an-object")),
        Err("BATCH_BINDING_INVALID")
    );
}

#[test]
fn validate_rejects_tampered_bound_request() {
    let mut request = p2::prepare(&input()).unwrap();
    request["policy"] = json!("변조된 규칙");
    assert_eq!(
        p2::validate(&request, &answer(&request)),
        Err("BATCH_BINDING_INVALID"),
        "digest와 다른 요청 본문은 거부해야 한다"
    );
}

#[test]
fn validate_rejects_coverage_gaps_and_duplicates() {
    let mut two = input();
    two["merchants"] = json!([{"merchant_id": "synthetic-a"}, {"merchant_id": "synthetic-b"}]);
    let request = p2::prepare(&two).unwrap();

    let mut missing = answer(&request);
    missing["results"] = json!([{
        "merchant_id": "synthetic-a", "item": "사무용품비",
        "confidence": "높음", "basis": "합성 근거"
    }]);
    assert_eq!(
        p2::validate(&request, &missing),
        Err("BATCH_COVERAGE_INVALID")
    );

    let mut duplicate = answer(&request);
    duplicate["results"] = json!([
        {"merchant_id": "synthetic-a", "item": "사무용품비", "confidence": "높음", "basis": "합성 근거"},
        {"merchant_id": "synthetic-a", "item": "사무용품비", "confidence": "높음", "basis": "합성 근거"}
    ]);
    assert_eq!(
        p2::validate(&request, &duplicate),
        Err("BATCH_COVERAGE_INVALID")
    );

    let mut unknown = answer(&request);
    unknown["results"] = json!([
        {"merchant_id": "synthetic-a", "item": "사무용품비", "confidence": "높음", "basis": "합성 근거"},
        {"merchant_id": "synthetic-z", "item": "사무용품비", "confidence": "높음", "basis": "합성 근거"}
    ]);
    assert_eq!(
        p2::validate(&request, &unknown),
        Err("BATCH_COVERAGE_INVALID")
    );

    let mut not_array = answer(&request);
    not_array["results"] = json!({});
    assert_eq!(
        p2::validate(&request, &not_array),
        Err("BATCH_COVERAGE_INVALID")
    );
}

#[test]
fn validate_rejects_unknown_item_and_bad_confidence_but_allows_keep() {
    let request = p2::prepare(&input()).unwrap();

    let mut unknown_item = answer(&request);
    unknown_item["results"][0]["item"] = json!("허용되지 않은 항목");
    assert_eq!(
        p2::validate(&request, &unknown_item),
        Err("BATCH_ITEM_INVALID")
    );

    let mut keep = answer(&request);
    keep["results"][0]["item"] = json!("기존 항목 유지");
    assert!(p2::validate(&request, &keep).is_ok());

    let mut bad_confidence = answer(&request);
    bad_confidence["results"][0]["confidence"] = json!("중간");
    assert_eq!(
        p2::validate(&request, &bad_confidence),
        Err("BATCH_ITEM_INVALID")
    );
}

#[test]
fn validate_rejects_empty_long_or_private_basis() {
    let request = p2::prepare(&input()).unwrap();

    let mut empty = answer(&request);
    empty["results"][0]["basis"] = json!("   ");
    assert_eq!(p2::validate(&request, &empty), Err("BATCH_BASIS_INVALID"));

    let mut long = answer(&request);
    long["results"][0]["basis"] = json!("가".repeat(601));
    assert_eq!(p2::validate(&request, &long), Err("BATCH_BASIS_INVALID"));

    let mut number = answer(&request);
    number["results"][0]["basis"] = json!("카드 12345-67890 결제");
    assert_eq!(
        p2::validate(&request, &number),
        Err("BATCH_BASIS_PRIVATE_IDENTIFIER")
    );

    let mut email = answer(&request);
    email["results"][0]["basis"] = json!("담당자 user@example.com 문의");
    assert_eq!(
        p2::validate(&request, &email),
        Err("BATCH_BASIS_PRIVATE_IDENTIFIER")
    );
}

#[test]
fn validate_rejects_malformed_result_objects() {
    let request = p2::prepare(&input()).unwrap();

    let mut missing_key = answer(&request);
    missing_key["results"][0]
        .as_object_mut()
        .unwrap()
        .remove("basis");
    assert_eq!(
        p2::validate(&request, &missing_key),
        Err("BATCH_RESULT_INVALID")
    );

    let mut extra_key = answer(&request);
    extra_key["results"][0]["extra"] = json!(1);
    assert_eq!(
        p2::validate(&request, &extra_key),
        Err("BATCH_RESULT_INVALID")
    );

    let mut not_object = answer(&request);
    not_object["results"] = json!(["synthetic-a"]);
    assert_eq!(
        p2::validate(&request, &not_object),
        Err("BATCH_RESULT_INVALID")
    );
}

#[test]
fn replay_runner_validates_without_starting_a_process() {
    let request = p2::prepare(&input()).unwrap();
    let good = answer(&request);
    assert_eq!(
        Replay {
            answer: good.clone()
        }
        .run(&request)
        .unwrap(),
        good
    );

    let mut bad = answer(&request);
    bad["run_id"] = json!("def456");
    assert_eq!(
        Replay { answer: bad }.run(&request),
        Err("BATCH_BINDING_INVALID")
    );
}
