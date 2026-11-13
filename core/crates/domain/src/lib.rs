//! 판정 타입·우선순위·불변식 (DB·프로세스·네트워크를 모른다). 설계 `docs/design/m3-core.md` §2.

//! 발급 경로는 기본 빌드(해당 기능이 꺼진 상태)에서만 없다. 아래 시험은 기능이 꺼졌을 때만 문서에 실린다.
#![cfg_attr(
    not(feature = "refund-issuer"),
    doc = "```compile_fail\nlet _ = cost_domain::issue_refund::refund_group(\"forged\", vec![]);\n```\n"
)]
#![cfg_attr(
    not(feature = "scope-issuer"),
    doc = "```compile_fail\nlet _ = cost_domain::issue_scope::open_quarter(1999, cost_domain::Quarter::Q1);\n```\n"
)]
//!
//! (`cargo test --all-features`에서는 발급 모듈이 존재하므로 위 시험이 빠진다.)
//!//! P2·AI 검수 판정은 `Decision::new`가 아니라 `OpenScope`가 필요한 `new_machine`으로만 만든다.

mod decision;
mod error;
mod ids;
mod money;
mod priority;

#[cfg(test)]
mod tests;

pub use decision::*;
pub use error::DomainError;
pub use ids::*;
pub use money::*;
pub use priority::*;
