import Link from "next/link";
import { notFound } from "next/navigation";
import { getBlock, type Position } from "@/lib/api";
import { DataTable, type Col } from "@/components/DataTable";
import { StatGrid } from "@/components/StatGrid";
import { Section } from "@/components/Section";
import { money, pct } from "@/lib/format";

export const dynamic = "force-dynamic";

const VALID = ["5", "7", "8", "10"];

const posCols: Col<Position>[] = [
  { key: "symbol", label: "Symbol", kind: "text" },
  { key: "qty", label: "Qty", kind: "num", dp: 0 },
  { key: "buy_price", label: "Buy", kind: "num" },
  { key: "cur_price", label: "Now", kind: "num" },
  { key: "invested", label: "Invested", kind: "money" },
  { key: "cur_value", label: "Value", kind: "money" },
  { key: "pnl", label: "P&L", kind: "money", signed: true },
  { key: "return_pct", label: "Return", kind: "pct", signed: true },
  { key: "cagr_pct", label: "CAGR", kind: "pct", signed: true },
  { key: "weight_pct", label: "Weight", kind: "pct" },
];

export default async function BlockPage({ params }: { params: { pid: string; date: string } }) {
  if (!VALID.includes(params.pid)) notFound();

  let data;
  try {
    data = await getBlock(params.pid, params.date);
  } catch {
    notFound();
  }
  const { metrics: b, positions } = data;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">
          {b.portfolio} · rebalance {b.block}
        </h1>
        <span className="text-sm text-neutral-500">
          {b.entry_date} → {b.as_of_date} · {b.days} days
        </span>
      </div>

      <Section title="Block performance" subtitle="Equity-only: summed from this block's stock rows. Cash-ledger, hedge and benchmark figures live at the portfolio level.">
        <StatGrid
          stats={[
            { label: "Stocks", value: String(b.n_stocks) },
            { label: "Winners / losers", value: `${b.winners} / ${b.losers}` },
            { label: "Invested", value: money(b.invested) },
            { label: "Current value", value: money(b.current_value) },
            { label: "P&L", value: money(b.equity_pnl), signed: b.equity_pnl },
            { label: "Return", value: pct(b.return_pct), signed: b.return_pct },
            { label: "CAGR", value: pct(b.cagr_pct), signed: b.cagr_pct },
            { label: "XIRR", value: pct(b.xirr_pct), signed: b.xirr_pct },
            { label: "Best", value: b.best, signed: 1 },
            { label: "Worst", value: b.worst, signed: -1 },
          ]}
        />
      </Section>

      <Section title="Holdings in this rebalance">
        <DataTable cols={posCols} rows={positions} />
      </Section>

      <p className="mt-8 text-sm">
        <Link href={`/portfolio/${params.pid}`} className="text-blue-600 dark:text-blue-400 hover:underline">
          ← {b.portfolio}
        </Link>
      </p>
    </div>
  );
}
