import type { ComponentProps } from "react";
import { Input as PlushInput } from "./plush/input";
import { cn } from "../lib/cn";

export type InputProps = ComponentProps<typeof PlushInput> & { invalid?: boolean };

export function Input({ invalid = false, className, ...props }: InputProps) {
  return (
    <PlushInput
      className={cn("cost-input", className)}
      aria-invalid={invalid || props["aria-invalid"] || undefined}
      {...props}
    />
  );
}
