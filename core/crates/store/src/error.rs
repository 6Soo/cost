//! 저장 계층 오류.

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error("sqlite 오류: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("core.sqlite 스키마 버전 {found}이(가) 이 빌드가 아는 최신 {known}보다 높다")]
    SchemaTooNew { found: u32, known: u32 },
    #[error("읽기 실패: {read} (롤백도 실패: {rollback})")]
    ReadFailedRollbackFailed {
        read: Box<StoreError>,
        rollback: rusqlite::Error,
    },
}
