// 자격 증명 pipe 클라이언트 통합探针. 비밀 값 대신 SHA-256 해시와 길이만 출력한다.
// 사용: node tests/card_login/read_probe.mjs <issuer> <storeRoot>
// argv 에는 비밀이 아닌 issuer/storeRoot 만 전달된다. 출력에 평문 비밀 없음.
import { createHash } from 'node:crypto';
import { readCredentials } from '../../tools/card_login/credentials.mjs';

const issuer = process.argv[2];
const storeRoot = process.argv[3] || null;
const sha = (s) => (s == null ? null : createHash('sha256').update(String(s), 'utf8').digest('hex'));

const cred = await readCredentials(issuer, { storeRoot, timeoutMs: 30000 });
if (cred.status !== 'ok') {
  console.log(JSON.stringify({ status: cred.status, reason: cred.reason ?? null }));
} else {
  console.log(JSON.stringify({
    status: 'ok',
    idSha256: sha(cred.id), passwordSha256: sha(cred.password), certSha256: sha(cred.certPassword),
    idLen: cred.id.length, passwordLen: cred.password.length,
    certLen: cred.certPassword == null ? null : cred.certPassword.length,
  }));
}
