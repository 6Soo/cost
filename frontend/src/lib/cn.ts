export type ClassValue =
  | string
  | number
  | null
  | undefined
  | false
  | readonly ClassValue[]
  | { readonly [className: string]: unknown };

function collect(value: ClassValue, output: string[]): void {
  if (!value) return;
  if (typeof value === "string" || typeof value === "number") {
    output.push(String(value));
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collect(item, output);
    return;
  }
  if (typeof value === "object") {
    for (const [className, enabled] of Object.entries(value)) {
      if (enabled) output.push(className);
    }
  }
}

export function cn(...values: ClassValue[]): string {
  const output: string[] = [];
  for (const value of values) collect(value, output);
  return output.join(" ");
}
