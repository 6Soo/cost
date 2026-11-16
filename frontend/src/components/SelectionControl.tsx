import { useId, type ComponentProps, type ReactNode } from "react";
import { Checkbox as PlushCheckbox } from "./plush/checkbox";
import { RadioGroup as PlushRadioGroup, RadioGroupItem } from "./plush/radio-group";
import { Switch as PlushSwitch } from "./plush/switch";
import { cn } from "../lib/cn";

type SelectionLabelProps = {
  label: string;
  description?: string;
  error?: string;
  children: ReactNode;
  id: string;
};

function SelectionLabel({ label, description, error, children, id }: SelectionLabelProps) {
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  return (
    <label htmlFor={id} className="cost-selection-row">
      {children}
      <span className="cost-selection-copy">
        <span className="cost-selection-label">{label}</span>
        {description && <span id={descriptionId} className="cost-help-text">{description}</span>}
        {error && <span id={errorId} className="cost-error-text">{error}</span>}
      </span>
    </label>
  );
}

export type CheckboxProps = Omit<ComponentProps<typeof PlushCheckbox>, "id" | "aria-describedby"> & {
  label: string;
  id?: string;
  description?: string;
  error?: string;
  "aria-describedby"?: string;
};

export function Checkbox({ label, id: suppliedId, description, error, className, ...props }: CheckboxProps) {
  const generatedId = useId();
  const id = suppliedId ?? `cost-checkbox-${generatedId}`;
  const describedBy = [props["aria-describedby"], description && `${id}-description`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ") || undefined;
  return (
    <SelectionLabel id={id} label={label} description={description} error={error}>
      <PlushCheckbox
        id={id}
        className={cn("cost-selection-control", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...props}
      />
    </SelectionLabel>
  );
}

export type SwitchProps = Omit<ComponentProps<typeof PlushSwitch>, "id" | "aria-describedby"> & {
  label: string;
  id?: string;
  description?: string;
  error?: string;
  "aria-describedby"?: string;
};

export function Switch({ label, id: suppliedId, description, error, className, ...props }: SwitchProps) {
  const generatedId = useId();
  const id = suppliedId ?? `cost-switch-${generatedId}`;
  const describedBy = [props["aria-describedby"], description && `${id}-description`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ") || undefined;
  return (
    <SelectionLabel id={id} label={label} description={description} error={error}>
      <PlushSwitch
        id={id}
        className={cn("cost-selection-control", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...props}
      />
    </SelectionLabel>
  );
}

export type RadioOption = { value: string; label: string; description?: string; disabled?: boolean };
export type RadioGroupProps = {
  options: RadioOption[];
  value: string;
  onChange: (value: string) => void;
  name: string;
  label: string;
  disabled?: boolean;
  className?: string;
};

export function RadioGroup({ options, value, onChange, name, label, disabled, className }: RadioGroupProps) {
  const groupId = useId();
  return (
    <fieldset className={cn("cost-radio-fieldset", className)}>
      <legend id={`${groupId}-label`} className="cost-field-label">{label}</legend>
      <PlushRadioGroup
        aria-labelledby={`${groupId}-label`}
        name={name}
        value={value}
        onValueChange={onChange}
        disabled={disabled}
        className="cost-radio-options"
      >
        {options.map((option, index) => {
          const id = `${groupId}-${index}`;
          return (
            <label key={option.value} htmlFor={id} className="cost-radio-option">
              <RadioGroupItem id={id} value={option.value} disabled={disabled || option.disabled} />
              <span className="cost-selection-copy">
                <span className="cost-selection-label">{option.label}</span>
                {option.description && <span className="cost-help-text">{option.description}</span>}
              </span>
            </label>
          );
        })}
      </PlushRadioGroup>
    </fieldset>
  );
}
