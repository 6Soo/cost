//! 판정 타입·우선순위·불변식 (DB·프로세스·네트워크를 모른다). 설계 `docs/design/m3-core.md` §2.
//!
//! 봉인 타입(`RefundGroup`·`OpenScope`·`TripId`·`Subject`)의 생성자는 `pub(crate)`이거나 없다.
//! 크레이트 밖 생성은 가시성이, 크레이트 안 다른 모듈의 생성은 비공개 필드가 막는다.
//! P2·AI 검수 판정은 `Decision::new`가 아니라 `OpenScope`가 필요한 `Decision::new_machine`으로만 만든다.

mod decision;
mod error;
mod ids;
mod money;
mod priority;
mod source_map;

#[cfg(test)]
mod tests;

pub use decision::*;
pub use error::DomainError;
pub use ids::*;
pub use money::*;
pub use priority::*;
pub use source_map::{Mapped, Mapping, SourceInput, map_source};
