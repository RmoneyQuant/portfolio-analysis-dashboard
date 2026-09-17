import { tone } from "@/lib/format";

export type Stat = { label: string; value: string; signed?: number | null };

export function StatGrid({ stats, cols = 4 }: { stats: Stat[]; cols?: number }) {
  return (
    <div
      className="grid gap-3"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${cols === 4 ? 180 : 150}px, 1fr))` }}
    >
      {stats.map((s) => (
        <div
          key={s.label}
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-3 py-2"
        >
          <div className="text-xs uppercase tracking-wide text-neutral-500">{s.label}</div>
          <div className={`mt-1 text-lg font-semibold tabular-nums ${s.signed !== undefined ? tone(s.signed) : ""}`}>
            {s.value}
          </div>
        </div>
      ))}
    </div>
  );
}
