const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status} on ${path}: ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

// ---- shapes returned by api.py ------------------------------------------------

export type Metrics = {
  portfolio: string;
  entry_date: string | null;
  as_of_date: string | null;
  days: number | null;
  rebalance_date?: string | null;
  next_rebalance?: string | null;
  days_to_next_rebalance?: number | null;
  deposits: number;
  withdrawals: number;
  invested: number;
  option_premium_paid: number;
  total_capital: number;
  equity_value: number;
  equity_pnl: number;
  hedge_pnl: number;
  total_pnl: number;
  current_value: number;
  total_value: number;
  equity_return_pct: number;
  equity_xirr_pct: number | null;
  equity_cagr_pct: number | null;
  total_return_pct: number;
  total_xirr_pct: number | null;
  total_cagr_pct: number | null;
  return_pct: number;
  xirr_pct: number | null;
  cagr_pct: number | null;
  max_drawdown_pct: number | null;
  volatility_pct: number | null;
  sheet_profit?: number;
  sheet_capital?: number;
  sheet_return_pct?: number;
  benchmark_pct?: number;
  alpha_pct?: number;
};

export type Totals = Pick<
  Metrics,
  | "portfolio"
  | "deposits"
  | "withdrawals"
  | "invested"
  | "total_pnl"
  | "current_value"
  | "return_pct"
  | "xirr_pct"
  | "cagr_pct"
  | "max_drawdown_pct"
>;

export type Cashflow = {
  portfolio: string;
  deposits: number;
  withdrawals: number;
  net_invested: number;
  n_deposits: number;
  n_withdrawals: number;
  gross_buy_settlement: number;
  gross_sell_settlement: number;
  option_premium_net: number;
  futures_mtm_net: number;
  xirr_pct: number | null;
  cagr_pct: number | null;
  dividends: number;
  interest_income: number;
  brokerage: number;
  taxes: number;
  fees: number;
  transaction_costs: number;
  line_items_matched: number;
};

export type Position = {
  symbol: string;
  qty: number | null;
  buy_price: number | null;
  invested: number | null;
  cur_price: number | null;
  cur_value: number | null;
  pnl_pct: number | null;
  pnl: number | null;
  return_pct: number | null;
  days: number | null;
  cagr_pct: number | null;
  xirr_pct: number | null;
  weight_pct: number | null;
};

export type Block = {
  date: string;
  stocks: number;
  days: number | null;
  invested: number;
  current_value: number;
  pnl: number;
  return_pct: number;
  cagr_pct: number | null;
};

export type BlockMetrics = {
  portfolio: string;
  block: string;
  entry_date: string;
  as_of_date: string;
  days: number;
  n_stocks: number;
  winners: number;
  losers: number;
  invested: number;
  equity_value: number;
  equity_pnl: number;
  current_value: number;
  return_pct: number;
  cagr_pct: number | null;
  xirr_pct: number | null;
  best: string;
  worst: string;
};

export type OverviewRow = { dataset: string; rows: number; cols: number; columns: string };

export const getPortfolios = () =>
  api<{ portfolios: Metrics[]; totals: Totals }>("/api/portfolios");

export const getPortfolio = (pid: number | string) =>
  api<{ metrics: Metrics; cashflow: Cashflow; overview: OverviewRow[] }>(`/api/portfolio/${pid}`);

export const getPositions = (pid: number | string) =>
  api<Position[]>(`/api/portfolio/${pid}/positions`);

export const getBlocks = (pid: number | string) =>
  api<Block[]>(`/api/portfolio/${pid}/blocks`);

export const getBlock = (pid: number | string, date: string) =>
  api<{ metrics: BlockMetrics; positions: Position[] }>(`/api/portfolio/${pid}/block/${date}`);
