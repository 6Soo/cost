export type LoadingProps = { label?: string; size?: "sm" | "md"; className?: string };

export function Loading({ label = "불러오는 중", size = "md", className }: LoadingProps) {
  return (
    <div className={`cost-loading${className ? ` ${className}` : ""}`} role="status" aria-live="polite" aria-atomic="true">
      <span aria-hidden="true" className={`cost-spinner cost-spinner-${size}`} />
      <span>{label}</span>
    </div>
  );
}
