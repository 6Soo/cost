//! 비공개 상세 파일은 보호 경로(`<host>/data/backups`) 아래에만 쓴다. 밖이면 거부한다.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Component, Path, PathBuf};

#[derive(Debug, thiserror::Error)]
pub enum GuardError {
    #[error("PRIVATE_PATH_REJECTED")]
    PrivatePathRejected,
    #[error("입출력 오류: {0}")]
    Io(#[from] std::io::Error),
}

impl GuardError {
    /// 공개 출력에 내는 고정 코드.
    pub fn code(&self) -> &'static str {
        match self {
            Self::PrivatePathRejected => "PRIVATE_PATH_REJECTED",
            Self::Io(_) => "IO_ERROR",
        }
    }
}

pub fn protected_root(host_root: &Path) -> Result<PathBuf, GuardError> {
    host_root
        .join("data")
        .join("backups")
        .canonicalize()
        .map_err(|_| GuardError::PrivatePathRejected)
}

/// 아직 없는 파일 경로도 검사한다: 가장 깊은 기존 조상을 정규화하고 나머지를 붙인다(`..` 불허).
pub fn ensure_private_path(path: &Path, host_root: &Path) -> Result<PathBuf, GuardError> {
    let root = protected_root(host_root)?;
    let absolute = std::path::absolute(path).map_err(|_| GuardError::PrivatePathRejected)?;
    if absolute
        .components()
        .any(|c| matches!(c, Component::ParentDir))
    {
        return Err(GuardError::PrivatePathRejected);
    }
    let mut existing = absolute.as_path();
    let mut rest = Vec::new();
    while !existing.exists() {
        match (existing.file_name(), existing.parent()) {
            (Some(name), Some(parent)) => {
                rest.push(name.to_owned());
                existing = parent;
            }
            _ => return Err(GuardError::PrivatePathRejected),
        }
    }
    let mut resolved = existing
        .canonicalize()
        .map_err(|_| GuardError::PrivatePathRejected)?;
    resolved.extend(rest.iter().rev());
    if resolved.starts_with(&root) && resolved != root {
        Ok(resolved)
    } else {
        Err(GuardError::PrivatePathRejected)
    }
}

/// 검사를 통과한 새 파일 하나에 줄 단위로 쓴다. 기존 파일은 덮어쓰지 않는다.
pub fn write_private_lines(
    path: &Path,
    host_root: &Path,
    lines: &[String],
) -> Result<PathBuf, GuardError> {
    let target = ensure_private_path(path, host_root)?;
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&target)?;
    for line in lines {
        writeln!(file, "{line}")?;
    }
    Ok(target)
}
