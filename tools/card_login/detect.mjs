// 로그인 후 화면 신호 분류(보수적). 실제 사이트 문자열은 라이브 검증으로 확정해야 한다.
// 여기 키워드는 초안이며, 오탐을 줄이려면 로그인 전 기준 화면과 비교하거나 오류 컨테이너를 지정한다.
export const AUTH_SIGNALS = /OTP|원타임|휴대폰|휴대전화|간편인증|인증번호|보안카드|씨크리트|생체인증|앱에서\s*승인|푸시\s*승인|추가\s*인증/;
export const FAIL_SIGNALS = /일치하지|로그인\s*오류|로그인\s*실패|잠금|잠겼|이용\s*정지|횟수\s*초과|오류\s*횟수|잘못\s*입력|비밀번호를\s*확인|아이디를\s*확인|다시\s*입력/;

// 텍스트만으로 1차 분류. 'additional_auth' | 'failed' | 'unknown'
export function classifyLoginText(text) {
  const t = String(text || '');
  if (AUTH_SIGNALS.test(t)) return 'additional_auth';
  if (FAIL_SIGNALS.test(t)) return 'failed';
  return 'unknown';
}

// 비밀번호 오류 횟수 경고가 보이면 즉시 멈춰야 하므로 별도 신호로 탐지.
export function hasPasswordAttemptWarning(text) {
  return /오류\s*횟수|횟수\s*초과|잠금|잠겼|이용\s*정지|\d+\s*회\s*(오류|실패|남았)/.test(String(text || ''));
}
