//! 판정 타입·우선순위·불변식 (DB·프로세스·네트워크를 모른다). 설계 `docs/design/m3-core.md` §2.

//! 발급 경로는 기본 빌드에 없다(비허용 크레이트에서 호출 불가):
//!
//! ```compile_fail
//! let _ = cost_domain::issue_refund::refund_group("forged", vec![]);
//! ```
//!
//! ```compile_fail
//! let _ = cost_domain::issue_scope::open_quarter(1999, cost_domain::Quarter::Q1);
//! ```
//!
//! P2·AI 검수 판정은 `Decision::new`가 아니라 `OpenScope`가 필요한 `new_machine`으로만 만든다.

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
