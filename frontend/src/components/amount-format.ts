const NUMERIC_AMOUNT = /^([+-]?)(\d+)(?:\.(\d+))?$/;

export function formatAmount(value: string, currency = "KRW", locale = "ko-KR"): string {
  const match = NUMERIC_AMOUNT.exec(value.trim());
  if (!match) return `${value} ${currency}`.trim();

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
    return `${value} ${currency}`.trim();
  }
}
