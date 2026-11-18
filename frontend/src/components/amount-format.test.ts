import { expect, test } from 'vitest';
import { formatAmount } from './amount-format';

/** SPEC §11.2.1 계약 4 / GGL-014: an unknown amount is a state word, not money.
 * The server now sends "미확인" for income it cannot confirm, and a currency
 * unit appended to that word turns an unknown into a claimed figure
 * ("미확인 KRW" reads like a currency amount). Only a real number is money. */
test('an unknown amount is shown as the word, with no currency unit', () => {
  expect(formatAmount('미확인')).toBe('미확인');
  expect(formatAmount('미확인')).not.toContain('KRW');
  expect(formatAmount('금액 미확인')).toBe('금액 미확인');
});

test('an empty amount never becomes a bare currency code', () => {
  expect(formatAmount('')).toBe('');
  expect(formatAmount('   ')).toBe('');
});

test('a real number still formats as currency', () => {
  expect(formatAmount('1000000')).toContain('1,000,000');
  expect(formatAmount('1000000')).toContain('₩');
  expect(formatAmount('-1000')).toContain('1,000');
});

test('an explicitly currency-bearing non-number keeps what the caller passed', () => {
  // A caller that already spelled its own text is not rewritten.
  expect(formatAmount('완료')).toBe('완료');
});
