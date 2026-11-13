use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum DomainError {
    #[error("{0} 값이 비어 있다")]
    Empty(&'static str),
    #[error("원본 해시는 소문자 16진 64자여야 한다")]
    BadSourceHash,
    #[error("규칙집 ID 형식이 아니다")]
    BadPolicyRef,
    #[error("분기는 1~4여야 한다: {0}")]
    BadQuarter(u8),
    #[error("이용기간 종료일이 시작일보다 빠르다")]
    PeriodReversed,
    #[error("허용 목록에 없는 항목이다")]
    ItemNotAllowed,
    #[error("근거 문장이 비어 있다")]
    BasisEmpty,
    #[error("근거 문장이 600자를 넘는다")]
    BasisTooLong,
    #[error("근거 문장에 개인 식별값이 있다")]
    BasisPrivateIdentifier,
    #[error("이 판정 주체는 환불 짝 귀속을 만들 수 없다")]
    RefundPairNotAllowedForActor,
    #[error("환불 묶음 구성원이 비어 있다")]
    EmptyGroup,
    #[error("묶음 게시는 구성원 전체의 판정을 정확히 한 번씩 요구한다")]
    GroupPublicationMismatch,
    #[error("열린 범위 밖이라 자동 교정할 수 없다")]
    OutsideOpenScope,
}
