import type { HTMLAttributes } from "react";
import { formatAmount } from "./amount-format";

export type AmountProps = HTMLAttributes<HTMLSpanElement> & { value: string; currency?: string; locale?: string };

export function Amount({ value, currency = "KRW", locale = "ko-KR", className, ...props }: AmountProps) {
  return (
    <span className={`cost-amount${className ? ` ${className}` : ""}`} dir="ltr" {...props}>
      {formatAmount(value, currency, locale)}
    </span>
  );
}
