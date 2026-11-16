import type { ReactNode } from "react";
import { ActionButton } from "./ActionButton";

export type NoticeTone = "info" | "success" | "warning" | "error";
export type InlineNoticeProps = {
  tone: NoticeTone;
  title: string;
  children?: ReactNode;
  action?: { label: string; onClick: () => void };
  className?: string;
};

export function InlineNotice({ tone, title, children, action, className }: InlineNoticeProps) {
  return (
    <section
      className={`cost-notice cost-notice-${tone}${className ? ` ${className}` : ""}`}
      role={tone === "error" ? "alert" : "status"}
      aria-atomic="true"
      data-tone={tone}
    >
      <div className="cost-notice-copy">
        <p className="cost-notice-title">{title}</p>
        {children && <div className="cost-notice-description">{children}</div>}
      </div>
      {action && <ActionButton variant="secondary" size="sm" onClick={action.onClick}>{action.label}</ActionButton>}
    </section>
  );
}
