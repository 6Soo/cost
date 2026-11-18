const NUMERIC_AMOUNT = /^([+-]?)(\d+)(?:\.(\d+))?$/;

/** A non-numeric value is a state word ("미확인"), not money. Appending a
 * currency unit would turn an unknown into a claimed figure ("미확인 KRW"),
 * so the caller's own text is returned unchanged (SPEC §11.2.1 계약 4,
 * GGL-014: an unknown amount is never shown as an amount). */
export function formatAmount(value: string, currency = "KRW", locale = "ko-KR"): string {
  const text = String(value ?? "").trim();
  const match = NUMERIC_AMOUNT.exec(text);
  if (!match) return text;

  const [, sign, integer, fraction] = match;
  const signedInteger = `${sign === "-" ? "-" : ""}${integer}`;
  try {
    const formatter = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
    const integerParts = formatter.formatToParts(BigInt(signedInteger));
    if (!fraction) return integerParts.map((part) => part.value).join("");

    const decimal = new Intl.NumberFormat(locale).formatToParts(1.1).find((part) => part.type === "decimal")?.value ?? ".";
    const lastIntegerIndex = integerParts.reduce((last, part, index) => part.type === "integer" ? index : last, -1);
    integerParts.splice(lastIntegerIndex + 1, 0, { type: "decimal", value: decimal }, { type: "fraction", value: fraction });
    return integerParts.map((part) => part.value).join("");
  } catch {
    return text;
  }
}
