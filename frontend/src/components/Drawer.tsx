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
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
        )].filter((element) => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls.at(-1);
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
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
