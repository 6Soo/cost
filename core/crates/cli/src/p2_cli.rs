use std::io::Read;
use std::path::PathBuf;

use cost_core::p2::{self, CodexExec, P2Runner, Replay};
use serde_json::{Value, json};

pub fn run(args: &[String]) -> Result<(u8, Value), &'static str> {
    if !args.len().is_multiple_of(2) {
        return Err("USAGE_INVALID");
    }
    let mut operation = None;
    let mut python = "python".to_owned();
    let mut repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    for pair in args.chunks(2) {
        if pair.len() != 2 {
            return Err("USAGE_INVALID");
        }
        match pair[0].as_str() {
            "--operation" => operation = Some(pair[1].as_str()),
            "--python" => python.clone_from(&pair[1]),
            "--repo-root" => repo_root = PathBuf::from(&pair[1]),
            _ => return Err("USAGE_INVALID"),
        }
    }
    let mut input = String::new();
    std::io::stdin()
        .take(4 * 1024 * 1024 + 1)
        .read_to_string(&mut input)
        .map_err(|_| "P2_INPUT_INVALID")?;
    if input.len() > 4 * 1024 * 1024 {
        return Err("P2_INPUT_INVALID");
    }
    let body: Value = serde_json::from_str(&input).map_err(|_| "P2_INPUT_INVALID")?;
    let result = match operation {
        Some("prepare") => p2::prepare(&body)?,
        Some("validate") => p2::validate(&body["request"], &body["answer"])?,
        Some("replay") => Replay {
            answer: body["answer"].clone(),
        }
        .run(&body["request"])?,
        Some("codex") => CodexExec { python, repo_root }.run(&body["request"])?,
        _ => return Err("USAGE_INVALID"),
    };
    Ok((0, json!({"ok":true,"result":result})))
}
