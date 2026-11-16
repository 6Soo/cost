import type { ReactNode } from "react";

export type EmptyStateProps = { title: string; description?: string; action?: ReactNode; className?: string };

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <section className={`cost-empty-state${className ? ` ${className}` : ""}`}>
      <h2 className="cost-empty-title">{title}</h2>
      {description && <p className="cost-empty-description">{description}</p>}
      {action && <div className="cost-empty-action">{action}</div>}
    </section>
  );
}
