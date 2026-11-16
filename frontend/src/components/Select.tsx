import type { SelectHTMLAttributes } from "react";
import { cn } from "../lib/cn";

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean };

export function Select({ invalid = false, className, children, ...props }: SelectProps) {
  return (
    <select
      className={cn("cost-input w-full min-w-0 px-3 py-2", className)}
      aria-invalid={invalid || props["aria-invalid"] || undefined}
      {...props}
    >
      {children}
    </select>
  );
}
