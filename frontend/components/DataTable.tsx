import Link from "next/link";
import { money, pct, num, tone } from "@/lib/format";

export type Col<T> = {
  key: keyof T & string;
  label: string;
  kind?: "money" | "pct" | "num" | "text";
  dp?: number;
  signed?: boolean; // colour by sign
  href?: (row: T) => string;
  align?: "left" | "right";
};

function render<T>(row: T, col: Col<T>) {
  const v = row[col.key] as unknown as number | string | null;
  if (v === null || v === undefined) return "—";
  if (col.kind === "money") return money(v as number, col.dp ?? 0);
  if (col.kind === "pct") return pct(v as number, col.dp ?? 2);
  if (col.kind === "num") return num(v as number, col.dp ?? 2);
  return String(v);
}

export function DataTable<T extends Record<string, unknown>>({
  cols,
  rows,
  highlightLast,
}: {
  cols: Col<T>[];
  rows: T[];
  highlightLast?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-sm">
        <thead className="bg-neutral-100 dark:bg-neutral-900 text-neutral-500">
          <tr>
            {cols.map((c) => (
              <th
                key={c.key}
                className={`px-3 py-2 font-medium ${c.align === "left" || c.kind === "text" ? "text-left" : "text-right"}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              className={
                "border-t border-neutral-100 dark:border-neutral-800 " +
                (highlightLast && i === rows.length - 1
                  ? "bg-neutral-50 dark:bg-neutral-900 font-semibold"
                  : "hover:bg-neutral-50 dark:hover:bg-neutral-900/60")
              }
            >
              {cols.map((c) => {
                const content = render(row, c);
                const signedVal = c.signed ? (row[c.key] as unknown as number) : undefined;
                const cls =
                  `px-3 py-2 tabular-nums ${c.align === "left" || c.kind === "text" ? "text-left" : "text-right"} ` +
                  (signedVal !== undefined ? tone(signedVal) : "");
                return (
                  <td key={c.key} className={cls}>
                    {c.href ? (
                      <Link href={c.href(row)} className="text-blue-600 dark:text-blue-400 hover:underline">
                        {content}
                      </Link>
                    ) : (
                      content
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
