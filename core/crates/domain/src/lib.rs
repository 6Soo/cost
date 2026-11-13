//! 판정 타입·우선순위·불변식 (DB·프로세스·네트워크를 모른다). 설계 `docs/design/m3-core.md` §2.

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
