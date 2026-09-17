import { getPortfolios, type Metrics, type Totals } from "@/lib/api";
import { DataTable, type Col } from "@/components/DataTable";
import { StatGrid } from "@/components/StatGrid";
import { Section } from "@/components/Section";
import { money, pct } from "@/lib/format";

export const dynamic = "force-dynamic";

type Row = Metrics & { pidNum: string };

const cols: Col<Row>[] = [
  { key: "portfolio", label: "Portfolio", kind: "text", href: (r) => `/portfolio/${r.pidNum}` },
  { key: "deposits", label: "Deposits", kind: "money" },
  { key: "withdrawals", label: "Withdrawals", kind: "money" },
  { key: "invested", label: "Invested", kind: "money" },
  { key: "current_value", label: "Current value", kind: "money" },
  { key: "total_pnl", label: "P&L", kind: "money", signed: true },
  { key: "return_pct", label: "Return", kind: "pct", signed: true },
  { key: "xirr_pct", label: "XIRR", kind: "pct", signed: true },
  { key: "cagr_pct", label: "CAGR", kind: "pct", signed: true },
  { key: "max_drawdown_pct", label: "Max DD", kind: "pct", signed: true },
];

export default async function Home() {
  const { portfolios, totals } = await getPortfolios();

  const rows: Row[] = portfolios.map((p) => ({ ...p, pidNum: p.portfolio.replace("HPC39_", "") }));
  const totalRow: Row = { ...(totals as Totals as Metrics), pidNum: "" } as Row;

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight">Portfolios</h1>
      <p className="text-sm text-neutral-500 mt-1">
        Four HPC39 strategies. Click a portfolio for its cashflow, rebalance history and holdings.
      </p>

      <Section title="Combined (all four)">
        <StatGrid
          stats={[
            { label: "Invested", value: money(totals.invested) },
            { label: "Current value", value: money(totals.current_value) },
            { label: "Total P&L", value: money(totals.total_pnl), signed: totals.total_pnl },
            { label: "Deposits", value: money(totals.deposits) },
            { label: "Withdrawals", value: money(totals.withdrawals) },
            { label: "Return", value: pct(totals.return_pct), signed: totals.return_pct },
            { label: "XIRR (pooled)", value: pct(totals.xirr_pct), signed: totals.xirr_pct },
            { label: "CAGR", value: pct(totals.cagr_pct), signed: totals.cagr_pct },
            { label: "Max drawdown", value: pct(totals.max_drawdown_pct), signed: totals.max_drawdown_pct },
          ]}
        />
      </Section>

      <Section title="By portfolio">
        <DataTable cols={cols} rows={[...rows, totalRow]} highlightLast />
      </Section>
    </div>
  );
}
