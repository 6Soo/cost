import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Button as PlushButton } from "./plush/button";
import { cn } from "../lib/cn";

export type ActionButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-busy"> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  pending?: boolean;
  pendingLabel?: string;
  "aria-busy"?: boolean;
  children: ReactNode;
};

const variantMap = {
  primary: "default",
  secondary: "secondary",
  ghost: "ghost",
  danger: "destructive",
} as const;

const sizeMap = {
  sm: "sm",
  md: "default",
  lg: "lg",
} as const;

export function ActionButton({
  variant = "primary",
  size = "md",
  pending = false,
  pendingLabel,
  disabled,
  type = "button",
  className,
  children,
  ...props
}: ActionButtonProps) {
  return (
    <PlushButton
      type={type}
      variant={variantMap[variant]}
      size={sizeMap[size]}
      className={cn("cost-action-button", className)}
      disabled={disabled || pending}
      aria-busy={pending || props["aria-busy"] || undefined}
      data-pending={pending || undefined}
      {...props}
    >
      {pending && <span aria-hidden="true" className="cost-spinner cost-spinner-inline" />}
      {pending && pendingLabel ? pendingLabel : children}
    </PlushButton>
  );
}
