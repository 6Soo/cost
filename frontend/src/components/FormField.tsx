import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

export type FormFieldProps = {
  id: string;
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
};

export function FormField({ id, label, required = false, hint, error, children, className }: FormFieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
        id,
        required,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": describedBy,
      })
    : children;

  return (
    <div className={`cost-form-field${className ? ` ${className}` : ""}`}>
      <label htmlFor={id} className="cost-field-label">
        {label}{required && <span className="cost-required-marker" aria-hidden="true"> *</span>}
      </label>
      {control}
      {hint && <p id={hintId} className="cost-help-text">{hint}</p>}
      {error && <p id={errorId} className="cost-error-text" role="alert">{error}</p>}
    </div>
  );
}
