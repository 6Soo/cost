import { useEffect, useId, useRef, type ReactNode } from "react";
import { ActionButton } from "./ActionButton";

export type DrawerProps = {
  open: boolean;
  title: string;
  description?: string;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  className?: string;
};

export function Drawer({ open, title, description, onOpenChange, children, className }: DrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className={`cost-drawer${className ? ` ${className}` : ""}`}
      aria-labelledby={headingId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onOpenChange(false);
      }}
      onClose={() => onOpenChange(false)}
      onClick={(event) => {
        if (event.target === event.currentTarget) onOpenChange(false);
      }}
    >
      <div className="cost-drawer-content">
        <header className="cost-drawer-header">
          <div className="cost-drawer-heading">
            <h2 id={headingId}>{title}</h2>
            {description && <p id={descriptionId}>{description}</p>}
          </div>
          <ActionButton variant="ghost" size="sm" onClick={() => onOpenChange(false)} aria-label="닫기">닫기</ActionButton>
        </header>
        <div className="cost-drawer-body">{children}</div>
      </div>
    </dialog>
  );
}
