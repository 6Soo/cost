//! core.sqlite 스키마·이관과 board.sqlite 읽기 전용 투영 (M3 U3). 설계 `docs/design/m3-core.md` §3.

pub mod decisions;
mod error;
pub mod plan_input;
pub mod projection;
pub mod schema;
pub mod source_map;
pub mod write_columns;

#[cfg(test)]
mod tests;

pub use error::StoreError;
pub use plan_input::read_plan_input;
pub use projection::{Projection, open_board_readonly, read_projection};
pub use schema::{current_version, latest_version, migrate, open_core};
pub use source_map::{Mapped, Mapping, SourceInput, map_source};
