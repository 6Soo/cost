//! `costcore links ota [--input FILE|-] [--repo-root ROOT]`: 풀이기 입력(`events`·`transactions`·`existing_links`·`rules`·
//! `frozen_groups`, `costcore shadow-links --ota-input`과 같은 형식)을 받아 연결 칸만 낸다. DB는 읽지 않는다.
//! 출력은 한 줄 JSON `{"ok":true,"result":{"results":[...]}}`이며 이벤트 원문 복사 칸은 담지 않는다(Python 어댑터가 이벤트에 덧씌운다).
//! 오류는 고정 코드만 낸다.

use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use cost_core::links::ota::{Defaults, Matcher};
use serde_json::{Map, Value, json};

fn list(input: &Value, key: &str) -> Result<Vec<Value>, &'static str> {
    match input.get(key) {
        None | Some(Value::Null) => Ok(Vec::new()),
        Some(Value::Array(items)) => Ok(items.clone()),
        Some(_) => Err("INPUT_INVALID"),
    }
}

fn read_input(path: Option<&str>) -> Result<Value, &'static str> {
    let mut text = String::new();
    match path {
        None | Some("-") => {
            std::io::stdin()
                .read_to_string(&mut text)
                .map_err(|_| "IO_ERROR")?;
        }
        Some(path) => text = std::fs::read_to_string(path).map_err(|_| "IO_ERROR")?,
    }
    serde_json::from_str(&text).map_err(|_| "INPUT_INVALID")
}

fn solve(args: &[String]) -> Result<Value, &'static str> {
    let (mut input_path, mut repo) = (None, PathBuf::from("."));
    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        let value = iter.next().ok_or("USAGE_INVALID")?;
        match arg.as_str() {
            "--input" => input_path = Some(value.as_str()),
            "--repo-root" => repo = PathBuf::from(value),
            _ => return Err("USAGE_INVALID"),
        }
    }
    let input = read_input(input_path)?;
    if !input.is_object() {
        return Err("INPUT_INVALID");
    }
    let events = list(&input, "events")?;
    let cards = list(&input, "transactions")?;
    let rules = list(&input, "rules")?;
    let frozen = list(&input, "frozen_groups")?;
    let existing: Map<String, Value> = match input.get("existing_links") {
        None | Some(Value::Null) => Map::new(),
        Some(Value::Object(map)) => map.clone(),
        Some(_) => return Err("INPUT_INVALID"),
    };
    let config = std::fs::read_to_string(repo.join("config").join("ota-matching-defaults.json"))
        .map_err(|_| "CONFIG_INVALID")?;
    let config: Value = serde_json::from_str(&config).map_err(|_| "CONFIG_INVALID")?;
    let defaults = Defaults::from_value(&config).map_err(|_| "CONFIG_INVALID")?;
    let results: Vec<Value> = Matcher::new(&defaults, &rules)
        .match_events(&events, &cards, &existing, &frozen)
        .iter()
        .map(|link| link.to_value())
        .collect();
    Ok(json!({"results": results}))
}

pub fn run(args: &[String]) -> ExitCode {
    match solve(args) {
        Ok(result) => {
            println!("{}", json!({"ok": true, "result": result}));
            ExitCode::SUCCESS
        }
        Err(code) => {
            println!("{}", json!({"ok": false, "error": {"code": code}}));
            ExitCode::from(2)
        }
    }
}
