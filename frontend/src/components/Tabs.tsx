import { useId } from "react";
import { Tabs as PlushTabs, TabsList, TabsTrigger } from "./plush/tabs";

export type TabItem = { id: string; label: string; disabled?: boolean };
export type TabsProps = {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
};

export function Tabs({ items, value, onChange, ariaLabel, className }: TabsProps) {
  const id = useId();
  return (
    <PlushTabs value={value} onValueChange={onChange} className={className}>
      <TabsList aria-label={ariaLabel} className="cost-tabs-list">
        {items.map((item) => (
          <TabsTrigger key={item.id} id={`${id}-${item.id}`} value={item.id} disabled={item.disabled}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </PlushTabs>
  );
}
