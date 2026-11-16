import type { ReactNode } from "react";
import { EmptyState } from "./EmptyState";
import { cn } from "../lib/cn";

export type TableColumn<T> = {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  align?: "start" | "center" | "end";
  className?: string;
};

export type DataTableProps<T> = {
  columns: TableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => string;
  caption: string;
  emptyState?: ReactNode;
  className?: string;
};

function alignClass(align: TableColumn<unknown>["align"]): string {
  if (align === "end") return "text-right";
  if (align === "center") return "text-center";
  return "text-left";
}

export function DataTable<T>({ columns, rows, getRowKey, caption, emptyState, className }: DataTableProps<T>) {
  return (
    <div className={cn("cost-table-wrap", className)}>
      <table className="cost-data-table">
        <caption className="cost-visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={cn(alignClass(column.align), column.className)}>{column.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={getRowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} className={cn(alignClass(column.align), column.className)}>{column.cell(row)}</td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={Math.max(columns.length, 1)} className="cost-table-empty-cell">
                {emptyState ?? <EmptyState title="표시할 항목이 없습니다." />}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
