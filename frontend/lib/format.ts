export function money(n: number | null | undefined, dp = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp });
}

export function pct(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n.toFixed(dp)}%`;
}

export function num(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-IN", { maximumFractionDigits: dp });
}

// tailwind text-color class for a signed value
export function tone(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "text-neutral-400";
  if (n > 0) return "text-emerald-600 dark:text-emerald-400";
  if (n < 0) return "text-rose-600 dark:text-rose-400";
  return "text-neutral-500";
}
