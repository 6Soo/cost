//! 연결 계산(M3 U12~U14). 환불 짝·환불 묶음은 `refund`, OTA↔카드 연결은 `ota`. DB를 모르고 `store`가 읽은 투영만 받는다.

pub mod ota;
pub mod refund;
