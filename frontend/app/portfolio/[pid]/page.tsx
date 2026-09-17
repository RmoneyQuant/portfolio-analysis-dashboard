import Link from "next/link";
import { notFound } from "next/navigation";
import { getPortfolio, getBlocks, getPositions, type Block, type Position } from "@/lib/api";
import { DataTable, type Col } from "@/components/DataTable";
import { StatGrid } from "@/components/StatGrid";
import { Section } from "@/components/Section";
import { money, pct } from "@/lib/format";

export const dynamic = "force-dynamic";

const VALID = ["5", "7", "8", "10"];

const blockCols = (pid: string): Col<Block>[] => [
  { key: "date", label: "Rebalance date", kind: "text", href: (r) => `/portfolio/${pid}/${r.date}` },
  { key: "stocks", label: "Stocks", kind: "num", dp: 0 },
  { key: "days", label: "Days", kind: "num", dp: 0 },
  { key: "invested", label: "Invested", kind: "money" },
  { key: "current_value", label: "Value", kind: "money" },
  { key: "pnl", label: "P&L", kind: "money", signed: true },
  { key: "return_pct", label: "Return", kind: "pct", signed: true },
  { key: "cagr_pct", label: "CAGR", kind: "pct", signed: true },
];

const posCols: Col<Position>[] = [
  { key: "symbol", label: "Symbol", kind: "text" },
  { key: "qty", label: "Qty", kind: "num", dp: 0 },
  { key: "invested", label: "Invested", kind: "money" },
  { key: "cur_value", label: "Value", kind: "money" },
  { key: "pnl", label: "P&L", kind: "money", signed: true },
  { key: "return_pct", label: "Return", kind: "pct", signed: true },
  { key: "weight_pct", label: "Weight", kind: "pct" },
];

export default async function PortfolioPage({ params }: { params: { pid: string } }) {
  if (!VALID.includes(params.pid)) notFound();

  const [{ metrics: m, cashflow: cf, overview }, blocks, positions] = await Promise.all([
    getPortfolio(params.pid),
    getBlocks(params.pid),
    getPositions(params.pid),
  ]);

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">{m.portfolio}</h1>
        <span className="text-sm text-neutral-500">
          {m.entry_date} → {m.as_of_date} · {m.days} days
        </span>
      </div>

      <Section title="Performance">
        <StatGrid
          stats={[
            { label: "Invested", value: money(m.invested) },
            { label: "Current value", value: money(m.current_value) },
            { label: "Total P&L", value: money(m.total_pnl), signed: m.total_pnl },
            { label: "Equity P&L", value: money(m.equity_pnl), signed: m.equity_pnl },
            { label: "Hedge P&L", value: money(m.hedge_pnl), signed: m.hedge_pnl },
            { label: "Return", value: pct(m.return_pct), signed: m.return_pct },
            { label: "XIRR", value: pct(m.xirr_pct), signed: m.xirr_pct },
            { label: "CAGR", value: pct(m.cagr_pct), signed: m.cagr_pct },
            { label: "Max drawdown", value: pct(m.max_drawdown_pct), signed: m.max_drawdown_pct },
            { label: "Volatility", value: pct(m.volatility_pct) },
            { label: "Benchmark", value: pct(m.benchmark_pct ?? null), signed: m.benchmark_pct ?? null },
            { label: "Alpha", value: pct(m.alpha_pct ?? null), signed: m.alpha_pct ?? null },
          ]}
        />
      </Section>

      <Section title="Cashflow" subtitle="Investor money in / out, from the change in deployed capital at each settlement.">
        <StatGrid
          cols={3}
          stats={[
            { label: "Deposits", value: money(cf.deposits) },
            { label: "Withdrawals", value: money(cf.withdrawals) },
            { label: "Net invested", value: money(cf.net_invested) },
            { label: "# Deposits", value: String(cf.n_deposits) },
            { label: "# Withdrawals", value: String(cf.n_withdrawals) },
            { label: "Option premium (net)", value: money(cf.option_premium_net), signed: cf.option_premium_net },
            { label: "Futures MTM (net)", value: money(cf.futures_mtm_net), signed: cf.futures_mtm_net },
            { label: "Gross buy settle", value: money(cf.gross_buy_settlement) },
            { label: "Gross sell settle", value: money(cf.gross_sell_settlement) },
            { label: "XIRR", value: pct(cf.xirr_pct), signed: cf.xirr_pct },
            { label: "CAGR", value: pct(cf.cagr_pct), signed: cf.cagr_pct },
            { label: "Dividends / fees / tax", value: cf.line_items_matched === 0 ? "not itemised" : money(0) },
          ]}
        />
      </Section>

      <Section title={`Sheet-reported (${cf.portfolio})`} subtitle="From strategy_returns — a static snapshot, for reconciliation.">
        <StatGrid
          cols={3}
          stats={[
            { label: "Sheet profit", value: money(m.sheet_profit ?? null), signed: m.sheet_profit ?? null },
            { label: "Sheet capital", value: money(m.sheet_capital ?? null) },
            { label: "Sheet return", value: pct(m.sheet_return_pct ?? null), signed: m.sheet_return_pct ?? null },
          ]}
        />
      </Section>

      <Section title="Rebalance history" subtitle="Each dated block held in the holdings sheet. Click a date for its holdings.">
        <DataTable cols={blockCols(params.pid)} rows={blocks} />
      </Section>

      <Section title="Latest holdings">
        <DataTable cols={posCols} rows={positions} />
      </Section>

      <Section title="Datasets in this portfolio">
        <ul className="text-sm text-neutral-500 grid gap-1 sm:grid-cols-2">
          {overview.map((o) => (
            <li key={o.dataset} className="font-mono">
              {o.dataset} · {o.rows}×{o.cols}
            </li>
          ))}
        </ul>
      </Section>

      <p className="mt-8 text-sm">
        <Link href="/" className="text-blue-600 dark:text-blue-400 hover:underline">
          ← all portfolios
        </Link>
      </p>
    </div>
  );
}
