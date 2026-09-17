"""Portfolio performance metrics for the dashboard.

Everything is derived from the cleaned data in backend.py, so it recomputes
whenever the sheets are re-imported.

    from calc import metrics, metrics_all, positions, xirr

    metrics(10)          # dict of metrics for HPC39_10
    metrics_all()        # DataFrame, one row per portfolio
    positions(10)        # per-stock table (entry cost, current value, P&L)

Command line
------------
    uv run calc.py                 # metrics table for all portfolios
    uv run calc.py 10              # full metric breakdown for HPC39_10
    uv run calc.py 10 positions    # per-stock table for HPC39_10

Metric definitions
------------------
deposits        gross investor cash paid in over the life of the portfolio
withdrawals     gross investor cash taken out (at rebalances)
invested        capital currently deployed  = |net| on the last cash-ledger row
                ( = deposits - withdrawals )
equity_value    market value of the stock basket = last `holding`
equity_pnl      last `p&l`  ( = holding + net )
hedge_pnl       running P&L on the option / futures ledgers
total_pnl       equity_pnl + hedge_pnl
current_value   invested + total_pnl
return_pct      total_pnl / invested                 (simple, money-in-now basis)
xirr_pct        money-weighted annualised return from the dated cash movements
cagr_pct        (1 + return_pct) ** (365 / days) - 1
max_drawdown_pct  worst peak-to-trough dip of the daily return index
max_drawdown_value  same dip, in rupees ( = drop in cumulative p&l from its running peak )
volatility_pct  stdev of daily returns, annualised (x sqrt 252)
sheet_*         the figures the strategy_returns / performance sheets report
benchmark_pct   NIFTY 500 return over the same window (from strategy_returns)
alpha_pct       return_pct - benchmark_pct
"""

from __future__ import annotations

import math
import re
import sys
from datetime import date, datetime

import pandas as pd

from backend import load, portfolio_ids
from filter import CSV_DIR

_book = None


def _get_book():
    global _book
    if _book is None:
        _book = load()
    return _book


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce"
    )


def _as_date(v) -> date | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    ts = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(ts) else ts.date()


# --------------------------------------------------------------------------- #
# XIRR
# --------------------------------------------------------------------------- #
def xnpv(rate: float, days: list[float], amounts: list[float]) -> float:
    return sum(a / (1.0 + rate) ** (t / 365.0) for t, a in zip(days, amounts))


def xirr(dates: list, amounts: list[float]) -> float:
    """Annualised money-weighted return for dated cashflows. NaN if it can't solve."""
    pts = [
        (_as_date(d), float(a))
        for d, a in zip(dates, amounts)
        if _as_date(d) is not None and a is not None and math.isfinite(a)
    ]
    if len(pts) < 2 or all(a >= 0 for _, a in pts) or all(a <= 0 for _, a in pts):
        return float("nan")
    d0 = min(d for d, _ in pts)
    days = [float((d - d0).days) for d, _ in pts]
    amts = [a for _, a in pts]

    rate = 0.1
    for _ in range(100):                       # Newton
        f = xnpv(rate, days, amts)
        fp = (xnpv(rate + 1e-6, days, amts) - f) / 1e-6
        if not math.isfinite(fp) or abs(fp) < 1e-12:
            break
        step = f / fp
        rate -= step
        if rate <= -1:
            rate = -0.9999
        if abs(step) < 1e-9:
            return rate

    lo, hi = -0.9999, 100.0                     # bisection fallback
    flo, fhi = xnpv(lo, days, amts), xnpv(hi, days, amts)
    if not (math.isfinite(flo) and math.isfinite(fhi)) or (flo < 0) == (fhi < 0):
        return float("nan")                     # no sign change -> can't bracket a root
    for _ in range(300):
        mid = (lo + hi) / 2
        fmid = xnpv(mid, days, amts)
        if abs(fmid) < 1e-7 or (hi - lo) < 1e-10:
            return mid
        if (flo < 0) == (fmid < 0):
            lo, flo = mid, fmid
        else:
            hi = mid
    return (lo + hi) / 2


# --------------------------------------------------------------------------- #
# building blocks
# --------------------------------------------------------------------------- #
# All date-based maths (cashflow timing, XIRR, CAGR days, drawdown window) keys
# off the ledger's VALUE DATE - the effective settlement date - matching the
# reference methodology in TEST.MD. The posting date (T+1) is only a fallback.
def _flow_date_col(df: pd.DataFrame) -> list:
    vd = df["value_date"] if "value_date" in df.columns else [None] * len(df)
    dd = df["date"] if "date" in df.columns else [None] * len(df)
    return [
        _as_date(v) if _as_date(v) is not None else _as_date(d)
        for v, d in zip(vd, dd)
    ]


def _cash_ledger(pid: int) -> pd.DataFrame:
    cl = _get_book()[pid].cash_ledger.copy()
    for c in ("dr", "cr", "net", "holding", "p&l"):
        if c in cl.columns:
            cl[c] = _num(cl[c])
    cl = cl.dropna(subset=["net"]).reset_index(drop=True)
    cl["flow_date"] = _flow_date_col(cl)
    return cl


def _leg_pnl(leg: pd.DataFrame | None) -> float:
    """Running P&L on one derivative ledger (last row's `net`, or premium - dr)."""
    if leg is None or leg.empty:
        return 0.0
    row = leg.dropna(how="all").iloc[-1]
    if "net" in leg.columns and pd.notna(_num(pd.Series([row["net"]])).iloc[0]):
        return float(_num(pd.Series([row["net"]])).iloc[0])
    if {"premium", "dr"} <= set(leg.columns):
        prem = _num(pd.Series([row["premium"]])).iloc[0]
        dr = _num(pd.Series([row["dr"]])).iloc[0]
        if pd.notna(prem) and pd.notna(dr):
            return float(prem - dr)
    return 0.0


def _option_pnl(pid: int) -> float:
    return _leg_pnl(_get_book()[pid].option_ledger)


def _futures_pnl(pid: int) -> float:
    return _leg_pnl(_get_book()[pid].fo_ledger)


def _hedge_pnl(pid: int) -> float:
    """Running P&L on the option + futures ledgers together."""
    return _option_pnl(pid) + _futures_pnl(pid)


def _option_leg(pid: int) -> dict | None:
    """The current PUT hedge: premium paid (capital), current value, start date."""
    ol = _get_book()[pid].option_ledger
    if ol is None or ol.empty:
        return None
    clean_ol = ol.dropna(how="all")
    if clean_ol.empty:
        return None
    paid_col = "debit" if "debit" in ol.columns else "dr"
    # premium paid at inception = capital committed to the hedge
    paid = _num(pd.Series([clean_ol.iloc[0].get(paid_col)])).iloc[0]
    now = _num(pd.Series([clean_ol.iloc[-1].get("premium")])).iloc[0]
    if pd.isna(paid):
        return None
    first = clean_ol.iloc[0]
    start = _as_date(first.get("value_date")) or _as_date(first.get("date"))
    return {
        "paid": float(paid),
        "now": float(now) if pd.notna(now) else float(paid),
        "start": start,
    }


def _date_of_entry(pid: int) -> date | None:
    perf = _get_book().shared.get("performance")
    if perf is None:
        return None
    hit = perf[perf["admin"].astype(str).str.upper() == f"HPC39_{pid}"]
    return _as_date(hit.iloc[0].get("date_of_entry")) if len(hit) else None


def _entry_date(pid: int) -> date | None:
    """XIRR/CAGR start = first cashflow's value date, but not before the strategy's
    official inception (`date_of_entry` in the performance sheet). HPC39_5's ledger
    carries ~7 months of activity before its 2024-09-03 inception; that pre-history
    is folded into an opening balance (see `_flows_from`).
    """
    flows, _ = _investor_flows(pid)
    first = min(flows) if flows else None
    doe = _date_of_entry(pid)
    if first and doe:
        return max(first, doe)
    if first:
        return first
    if doe:
        return doe
    cl = _cash_ledger(pid)
    fd = [d for d in cl["flow_date"] if d is not None]
    return fd[0] if fd else None


def _flows_from(pid: int, start: date | None) -> tuple[list[date], list[float]]:
    """Investor flows, with everything before `start` collapsed into one opening
    deposit on `start` (the ledger's `net` balance as of that date)."""
    dates, amounts = _investor_flows(pid)
    if start is None:
        return dates, amounts
    pre = [(d, a) for d, a in zip(dates, amounts) if d < start]
    post = [(d, a) for d, a in zip(dates, amounts) if d >= start]
    if not pre:
        return dates, amounts
    cl = _cash_ledger(pid)
    before = [float(n) for n, d in zip(cl["net"], cl["flow_date"]) if d is not None and d < start]
    opening = before[-1] if before else sum(a for _, a in pre)
    d2 = [start] + [d for d, _ in post]
    a2 = [opening] + [a for _, a in post]
    return d2, a2


def _flows_per_posting(cl: pd.DataFrame) -> tuple[list, list[float]]:
    """One dated cashflow per row where the running `net` balance actually moves.

    A dr/cr is a real cashflow only if `net` changed on that row. Rows that just
    repeat a bill's dr/cr while `net` stays put (carry-forwards, and stray rows
    pasted from other portfolios) are ignored - bill number is not used at all.
    Amount = cr - dr; date = value date.
    """
    dates: list = []
    amounts: list[float] = []
    prev_net: float | None = None
    for _, r in cl.iterrows():
        net = float(r["net"])
        moved = prev_net is None or abs(net - prev_net) > 0.005
        prev_net = net
        if not moved:
            continue
        dr = round(float(r["dr"]), 2) if pd.notna(r["dr"]) else 0.0
        cr = round(float(r["cr"]), 2) if pd.notna(r["cr"]) else 0.0
        d = r["flow_date"]
        amt = cr - dr
        if d is not None and abs(amt) > 1.0:
            dates.append(d)
            amounts.append(amt)
    return dates, amounts


def _flows_net_delta(cl: pd.DataFrame) -> tuple[list, list[float]]:
    """The change in `net` at each settlement batch - robust to rollover repeats."""
    batches = cl[cl["bill_no"].ne(cl["bill_no"].shift())]
    dates: list = []
    amounts: list[float] = []
    prev = 0.0
    for _, r in batches.iterrows():
        net = float(r["net"])
        flow = net - prev
        prev = net
        if r["flow_date"] is not None and abs(flow) > 1.0:
            dates.append(r["flow_date"])
            amounts.append(flow)
    return dates, amounts


def _investor_flows(pid: int) -> tuple[list[date], list[float]]:
    """Real dated investor movements (no terminal). neg = deposit, pos = withdrawal.

    Prefer one dated cashflow per distinct dr/cr posting - it keeps partial
    settlements on their own value date. But if those postings don't reconcile
    with the ledger's own running `net` balance (rollover bills re-quote the
    same amount and get double-counted), fall back to the net-delta method.
    """
    cl = _cash_ledger(pid)
    last_net = float(cl["net"].iloc[-1])

    d, a = _flows_per_posting(cl)
    if abs(sum(a) - last_net) <= max(10_000.0, 0.001 * abs(last_net)):
        return d, a
    return _flows_net_delta(cl)


def equity_cashflows(pid: int) -> tuple[list[date], list[float]]:
    """Equity leg only: investor deposits/withdrawals + terminal = equity_value."""
    m = metrics(pid, _skip_xirr=True)
    dates, amounts = _flows_from(pid, m["entry_date"])
    return dates + [m["as_of_date"]], amounts + [m["equity_value"]]


def total_cashflows(pid: int) -> tuple[list[date], list[float]]:
    """Hedged portfolio (Equity + PUT): equity flows + day-1 PUT premium (outflow)
    + terminal = equity `holding` now + PUT `premium` (MTM) now.

    PUT rolls are NOT fed as cashflows - the option ledger's own premium column
    already tracks them continuously (matches the reference sheet's method).
    """
    m = metrics(pid, _skip_xirr=True)
    dates, amounts = _flows_from(pid, m["entry_date"])
    leg = _option_leg(pid)
    paid = leg["paid"] if leg else 0.0
    if paid:
        dates = dates + [leg["start"] or m["entry_date"]]
        amounts = amounts + [-paid]
    return dates + [m["as_of_date"]], amounts + [m["total_value"]]


def cashflows(pid: int) -> tuple[list[date], list[float]]:
    """Default = the hedged (total) cashflows."""
    return total_cashflows(pid)


def cashflow_breakdown(pid: int) -> dict:
    """Gross deposits / withdrawals / net invested, from inception onward.

    Uses the same flow list the XIRR does: activity before the portfolio's
    inception date is folded into a single opening deposit.
    """
    _, amounts = _flows_from(pid, _entry_date(pid))
    deps = [a for a in amounts if a < 0]
    wds = [a for a in amounts if a > 0]
    return {
        "deposits": round(-sum(deps), 2),
        "withdrawals": round(sum(wds), 2),
        "net_invested": round(-sum(deps) - sum(wds), 2),
        "n_deposits": len(deps),
        "n_withdrawals": len(wds),
    }


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def metrics(pid: int, _skip_xirr: bool = False) -> dict:
    if pid not in portfolio_ids():
        raise KeyError(f"unknown portfolio {pid!r}; pick from {list(portfolio_ids())}")

    book = _get_book()
    cl = _cash_ledger(pid)
    last = cl.iloc[-1]

    invested = abs(float(last["net"]))
    equity_value = float(last["holding"])
    equity_pnl = float(last["p&l"])
    option_pnl = _option_pnl(pid)
    futures_pnl = _futures_pnl(pid)
    hedge_pnl = option_pnl + futures_pnl
    total_pnl = equity_pnl + hedge_pnl
    current_value = invested + total_pnl

    cf = cashflow_breakdown(pid)

    entry = _entry_date(pid)
    as_of = last["flow_date"]                         # last value date
    days = (as_of - entry).days if entry and as_of else None

    meta = book[pid].meta
    reb_date = meta.get("rebalance_date")
    next_reb = meta.get("next_rebalance_date")
    days_to_next = (next_reb - as_of).days if next_reb and as_of else None

    leg = _option_leg(pid)
    premium_paid = leg["paid"] if leg else 0.0       # day-1 PUT premium = hedge capital
    premium_now = leg["now"] if leg else 0.0         # PUT current MTM value

    # hedged (Equity + PUT) track - matches the reference sheet's "Hedged" rows
    total_capital = invested + premium_paid
    total_value = equity_value + premium_now          # equity holding + PUT MTM
    hedged_pnl = equity_pnl + option_pnl              # equity + PUT only (no futures)

    def _cagr(terminal: float, capital: float) -> float:
        r = terminal / capital if capital else float("nan")
        return r ** (365 / days) - 1 if days and days > 0 and r > 0 else float("nan")

    equity_return = equity_pnl / invested if invested else float("nan")
    total_return = hedged_pnl / total_capital if total_capital else float("nan")
    equity_cagr = _cagr(equity_value, invested)          # (TV / NC) ^ (365/days) - 1
    total_cagr = _cagr(total_value, total_capital)

    # time-weighted daily return index -> drawdown + volatility (equity leg).
    # daily return = change in cumulative P&L / capital deployed that day; this
    # stays continuous across capital-add days (both p&l and net barely move).
    win = cl.copy()
    if entry:
        win = win[win["flow_date"].apply(lambda d: d is not None and d >= entry)]
    win = win[win["net"].abs() > 0]
    daily_ret = (win["p&l"].diff() / win["net"].abs()).dropna()
    daily_ret = daily_ret[daily_ret.abs() < 0.5]        # drop settlement-artefact spikes
    if len(daily_ret) > 5:
        idx = (1 + daily_ret).cumprod()
        dd = (idx / idx.cummax() - 1).min()
        vol = daily_ret.std() * math.sqrt(252)
        dd_value = float((win["p&l"] - win["p&l"].cummax()).min())
    else:
        dd = vol = dd_value = float("nan")

    m = {
        "portfolio": f"HPC39_{pid}",
        "entry_date": entry,
        "as_of_date": as_of,
        "days": days,
        "rebalance_date": reb_date,
        "next_rebalance": next_reb,
        "days_to_next_rebalance": days_to_next,
        "deposits": cf["deposits"],
        "withdrawals": cf["withdrawals"],
        "invested": round(invested, 2),
        "option_premium_paid": round(premium_paid, 2),
        "total_capital": round(total_capital, 2),
        "premium_now": round(premium_now, 2),
        "equity_value": round(equity_value, 2),
        "equity_pnl": round(equity_pnl, 2),
        "option_pnl": round(option_pnl, 2),
        "futures_pnl": round(futures_pnl, 2),
        "hedge_pnl": round(hedge_pnl, 2),
        "hedged_pnl": round(hedged_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "current_value": round(current_value, 2),
        "total_value": round(total_value, 2),
        # equity leg only
        "equity_return_pct": round(100 * equity_return, 3),
        "equity_cagr_pct": round(100 * equity_cagr, 3) if math.isfinite(equity_cagr) else float("nan"),
        "equity_xirr_pct": float("nan"),
        # hedged portfolio (equity + PUT) - matches the sheet's "Hedged" rows
        "total_return_pct": round(100 * total_return, 3),
        "total_cagr_pct": round(100 * total_cagr, 3) if math.isfinite(total_cagr) else float("nan"),
        "total_xirr_pct": float("nan"),
        # back-compat aliases -> the hedged (total) figures
        "return_pct": round(100 * total_return, 3),
        "cagr_pct": round(100 * total_cagr, 3) if math.isfinite(total_cagr) else float("nan"),
        "xirr_pct": float("nan"),
        "max_drawdown_pct": round(100 * dd, 3) if math.isfinite(dd) else float("nan"),
        "max_drawdown_value": round(dd_value, 2) if math.isfinite(dd_value) else float("nan"),
        "volatility_pct": round(100 * vol, 3) if math.isfinite(vol) else float("nan"),
    }

    if not _skip_xirr:
        m["equity_xirr_pct"] = round(100 * xirr(*equity_cashflows(pid)), 3)
        m["total_xirr_pct"] = round(100 * xirr(*total_cashflows(pid)), 3)
        m["xirr_pct"] = m["total_xirr_pct"]

    # what the summary sheets report, for the dashboard cards + reconciliation
    sr = book.shared.get("strategy_returns")
    if sr is not None:
        hit = sr[sr["strategy"].astype(str).str.upper() == f"HPC39_{pid}"]
        if len(hit):
            row = hit.iloc[0]
            m["sheet_profit"] = _num(pd.Series([row["profit"]])).iloc[0]
            m["sheet_capital"] = _num(pd.Series([row["capital"]])).iloc[0]
            m["sheet_return_pct"] = round(
                100 * _num(pd.Series([row["portfolio_return"]])).iloc[0], 3
            )
            m["benchmark_pct"] = round(
                100 * _num(pd.Series([row["nifty_500_return"]])).iloc[0], 3
            )
            m["alpha_pct"] = round(m["return_pct"] - m["benchmark_pct"], 3)
            m["benchmark_start"] = _num(pd.Series([row["nifty_500_start"]])).iloc[0]
            m["benchmark_end"] = _num(pd.Series([row["nifty_500_end"]])).iloc[0]
            # "what if the same capital had gone into NIFTY 500 instead" -
            # same capital base as return_pct/alpha_pct (total_capital), scaled
            # by the index's own return over this portfolio's window.
            m["benchmark_invested"] = m["total_capital"]
            m["benchmark_value"] = round(
                m["total_capital"] * (1 + m["benchmark_pct"] / 100), 2
            )
            m["benchmark_pnl"] = round(m["benchmark_value"] - m["total_capital"], 2)
    return m


def metrics_all() -> pd.DataFrame:
    return pd.DataFrame(metrics(pid) for pid in portfolio_ids())


# --------------------------------------------------------------------------- #
# equity curve
# --------------------------------------------------------------------------- #
def equity_curve(pid: int) -> pd.DataFrame:
    """Daily equity mark-to-market value, from entry to the latest ledger date.

    Columns: date, equity_value (= that day's cash-ledger `holding`).
    Same window as the drawdown/volatility calc in `metrics()` - from
    `_entry_date(pid)` onward, one row per cash-ledger settlement date.
    """
    cl = _cash_ledger(pid)
    entry = _entry_date(pid)
    win = cl.copy()
    if entry:
        win = win[win["flow_date"].apply(lambda d: d is not None and d >= entry)]
    win = win.dropna(subset=["holding", "flow_date"])
    out = win[["flow_date", "holding"]].rename(
        columns={"flow_date": "date", "holding": "equity_value"}
    )
    return out.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# per-stock breakdown
# --------------------------------------------------------------------------- #
_MIN_ANNUALISE_DAYS = 30        # below this, CAGR/XIRR are left as NaN


def positions(pid: int, block: str | None = None) -> pd.DataFrame:
    """One row per stock with entry cost, current value, P&L, and annualised return.

    block : a rebalance-date key (e.g. "2026-06-03"); default = latest block.

    Columns:
        qty, buy_price, invested, cur_price, cur_value
        pnl              cur_value - invested
        pnl_pct          the sheet's own p&l fraction, as %
        return_pct       100 * pnl / invested
        days             held since the block's rebalance date
        cagr_pct         (1 + return) ** (365/days) - 1
        xirr_pct         same, via the XIRR solver on [-invested, +cur_value]
        weight_pct       share of the block's current value
    """
    p = _get_book()[pid]
    blocks = p.holdings_blocks or {}
    key = block or (next(iter(blocks)) if blocks else None)
    h = blocks.get(key) if key else p.holdings
    if h is None or h.empty:
        return pd.DataFrame()

    h = h.copy()
    for c in ("qty", "buying_rate", "amount_at_entry", "actual_price", "amount_by_m2m", "p&l"):
        if c in h.columns:
            h[c] = _num(h[c])
    h = h.dropna(subset=["symbol"]).drop_duplicates("symbol", keep="last")

    entry = _as_date(key) if key else _entry_date(pid)
    as_of = metrics(pid, _skip_xirr=True)["as_of_date"]
    days = (as_of - entry).days if entry and as_of else None

    out = pd.DataFrame(
        {
            "symbol": h["symbol"].astype(str),
            "qty": h.get("qty"),
            "buy_price": h.get("buying_rate"),
            "invested": h.get("amount_at_entry"),
            "cur_price": h.get("actual_price"),
            "cur_value": h.get("amount_by_m2m"),
            "pnl_pct": (100 * h["p&l"]).round(3) if "p&l" in h.columns else None,
        }
    )
    out["pnl"] = out["cur_value"] - out["invested"]
    out["return_pct"] = (100 * out["pnl"] / out["invested"]).round(3)
    out["days"] = days if days else float("nan")

    r = out["pnl"] / out["invested"]
    if days and days >= _MIN_ANNUALISE_DAYS:
        out["cagr_pct"] = (100 * ((1 + r) ** (365 / days) - 1)).round(3)
        out["xirr_pct"] = [
            round(100 * xirr([entry, as_of], [-iv, cv]), 3)
            if pd.notna(iv) and pd.notna(cv) and iv > 0
            else float("nan")
            for iv, cv in zip(out["invested"], out["cur_value"])
        ]
    else:
        # annualising a <~1-month hold explodes and means nothing
        out["cagr_pct"] = out["xirr_pct"] = float("nan")

    out["weight_pct"] = (100 * out["cur_value"] / out["cur_value"].sum()).round(3)
    return out.sort_values("cur_value", ascending=False).reset_index(drop=True)


def symbol_history(pid: int, symbol: str) -> pd.DataFrame:
    """One row per rebalance block that held `symbol` (oldest first):
    date, qty, buy_price, invested, cur_price, cur_value, pnl, return_pct.
    """
    sym = str(symbol).strip().upper()
    rows = []
    for label, blk in reversed(list(_get_book()[pid].holdings_blocks.items())):
        hit = blk[blk["symbol"].astype(str).str.strip().str.upper() == sym]
        if hit.empty:
            continue
        r = hit.iloc[-1]

        def g(col):
            v = pd.to_numeric(
                str(r.get(col)).replace(",", ""), errors="coerce"
            )
            return float(v) if pd.notna(v) else float("nan")

        inv, cv = g("amount_at_entry"), g("amount_by_m2m")
        rows.append({
            "rebalance": label,
            "qty": g("qty"),
            "buy_price": g("buying_rate"),
            "invested": round(inv, 2),
            "cur_price": g("actual_price"),
            "cur_value": round(cv, 2),
            "pnl": round(cv - inv, 2),
            "return_pct": round(100 * (cv - inv) / inv, 3) if inv else float("nan"),
        })
    return pd.DataFrame(rows)


def symbol_detail(pid: int, symbol: str) -> dict:
    """Everything the dashboard shows for one stock: block history + its rows in
    the broker statement and the latest trade-instruction sheet."""
    sym = str(symbol).strip().upper()
    p = _get_book()[pid]

    def _match(df):
        if df is None or df.empty or "symbol" not in df.columns:
            return pd.DataFrame()
        return df[df["symbol"].astype(str).str.strip().str.upper() == sym].reset_index(drop=True)

    return {
        "symbol": sym,
        "history": symbol_history(pid, sym),
        "statement": _match(p.holdings_statement),
        "trade": _match(p.latest_trades if p.trades else None),
    }


# fields that only exist at the whole-portfolio level (cash ledger / hedge legs /
# strategy sheet / daily series) and cannot be scoped to one rebalance block
_PORTFOLIO_ONLY = (
    "deposits", "withdrawals", "hedge_pnl", "total_pnl", "max_drawdown_pct",
    "max_drawdown_value", "volatility_pct", "sheet_profit", "sheet_capital",
    "sheet_return_pct", "benchmark_pct", "alpha_pct", "benchmark_start", "benchmark_end",
    "benchmark_invested", "benchmark_value", "benchmark_pnl",
)


def block_metrics(pid: int, block: str | None = None) -> dict:
    """The metrics panel for ONE rebalance block of a holdings sheet.

    A block is a dated snapshot, so only the equity figures that can be summed
    from its rows are available. See `_PORTFOLIO_ONLY` for what needs the whole
    portfolio (`metrics(pid)`) instead.
    """
    if pid not in portfolio_ids():
        raise KeyError(f"unknown portfolio {pid!r}; pick from {list(portfolio_ids())}")
    blocks = _get_book()[pid].holdings_blocks or {}
    key = block or (next(iter(blocks), None))
    if key is None:
        raise KeyError(f"HPC39_{pid} has no dated holdings blocks")
    if key not in blocks:
        hit = [k for k in blocks if k.startswith(key)]
        if not hit:
            raise KeyError(f"HPC39_{pid} has no block {key!r}; have {list(blocks)}")
        key = hit[0]

    pos = positions(pid, key)
    entry = _as_date(key)
    as_of = metrics(pid, _skip_xirr=True)["as_of_date"]
    days = (as_of - entry).days if entry and as_of else None

    invested = float(pos["invested"].sum())
    current_value = float(pos["cur_value"].sum())
    pnl = current_value - invested
    ret = pnl / invested if invested else float("nan")

    ann = days and days >= _MIN_ANNUALISE_DAYS
    cagr = (1 + ret) ** (365 / days) - 1 if ann and ret > -1 else float("nan")
    xr = xirr([entry, as_of], [-invested, current_value]) if ann else float("nan")

    rp = pos["return_pct"].dropna()
    if len(rp):
        best = pos.loc[rp.idxmax()]
        worst = pos.loc[rp.idxmin()]
        best_s = f"{best['symbol']} {best['return_pct']:.1f}%"
        worst_s = f"{worst['symbol']} {worst['return_pct']:.1f}%"
    else:
        best_s = worst_s = None                # block has no marked-to-market rows

    return {
        "portfolio": f"HPC39_{pid}",
        "block": key,
        "entry_date": entry,
        "as_of_date": as_of,
        "days": days,
        "n_stocks": len(pos),
        "winners": int((pos["pnl"] > 0).sum()),
        "losers": int((pos["pnl"] < 0).sum()),
        "invested": round(invested, 2),
        "equity_value": round(current_value, 2),
        "equity_pnl": round(pnl, 2),
        "current_value": round(current_value, 2),
        "return_pct": round(100 * ret, 3),
        "cagr_pct": round(100 * cagr, 3) if math.isfinite(cagr) else float("nan"),
        "xirr_pct": round(100 * xr, 3) if math.isfinite(xr) else float("nan"),
        "best": best_s,
        "worst": worst_s,
    }


# --------------------------------------------------------------------------- #
# display formatting (strings for humans - keeps the data functions numeric)
# --------------------------------------------------------------------------- #
_MONEY_COLS = {
    "deposits", "withdrawals", "invested", "option_premium_paid", "premium_now",
    "total_capital", "equity_value", "equity_pnl", "option_pnl", "futures_pnl",
    "hedge_pnl", "hedged_pnl", "total_pnl", "current_value", "total_value",
    "sheet_profit", "sheet_capital", "buy_price", "cur_price", "cur_value", "pnl",
    "max_drawdown_value", "benchmark_invested", "benchmark_value", "benchmark_pnl",
}


def _fmt_value(key: str, v):
    if isinstance(v, float) and math.isnan(v):
        return "n/a"
    if key.endswith("_pct") and isinstance(v, (int, float)):
        return f"{v:,.2f}%"
    if key in _MONEY_COLS and isinstance(v, (int, float)):
        return f"{v:,.2f}"
    if key in ("qty", "days") and isinstance(v, (int, float)):
        return f"{v:,.0f}"
    if key in ("benchmark_start", "benchmark_end") and isinstance(v, (int, float)):
        return f"{v:,.2f}"
    return v


# --------------------------------------------------------------------------- #
# formula lookup - shown in the dashboard's "ⓘ" popover on each metric
# --------------------------------------------------------------------------- #
FORMULAS: dict[str, str] = {
    "deposits": "gross investor cash paid in, from dated deposit postings on the "
                "cash ledger (net-delta method if per-posting dates don't reconcile).",
    "withdrawals": "gross investor cash taken out, same dated-posting method as deposits.",
    "net_invested": "deposits − withdrawals, over the portfolio's life.",
    "n_deposits": "count of distinct dated deposit postings.",
    "n_withdrawals": "count of distinct dated withdrawal postings.",
    "invested": "capital currently deployed = |net| on the last cash-ledger row "
                "( = deposits − withdrawals ).",
    "option_premium_paid": "the option ledger's day-1 Debit = capital committed to the PUT hedge.",
    "premium_now": "the option ledger's last row's Premium column = the PUT's current MTM value.",
    "total_capital": "invested + option_premium_paid  (equity capital + hedge capital).",
    "equity_value": "market value of the stock basket = last cash-ledger row's `holding`.",
    "equity_pnl": "last cash-ledger row's `p&l`  ( = holding + net ).",
    "option_pnl": "option ledger's last row's `net`  ( = Premium − Debit + Credit ) — the "
                  "PUT leg's current running P&L, not a sum of the ledger's rows.",
    "futures_pnl": "same as option_pnl, but on the futures/NIFTY ledger.",
    "hedge_pnl": "option_pnl + futures_pnl  (the hedge sleeve alone, no equity).",
    "hedged_pnl": "equity_pnl + option_pnl  (equity + PUT only, no futures) — matches the "
                  "reference sheet's 'Hedged Portfolio' P&L.",
    "total_pnl": "equity_pnl + hedge_pnl  (equity + PUT + futures — the true bottom line).",
    "current_value": "invested + total_pnl.",
    "total_value": "equity_value + premium_now  (equity MTM + PUT MTM — the hedged terminal value).",
    "equity_return_pct": "equity_pnl / invested.",
    "equity_cagr_pct": "(equity_value / invested) ** (365/days) − 1  (needs ≥30 days held).",
    "equity_xirr_pct": "money-weighted annualised return, solved from the dated equity cashflows "
                       "(deposits/withdrawals + terminal = equity_value).",
    "total_return_pct": "hedged_pnl / total_capital.",
    "total_cagr_pct": "(total_value / total_capital) ** (365/days) − 1  (needs ≥30 days held).",
    "total_xirr_pct": "money-weighted annualised return on the hedged cashflows (equity flows + "
                      "day-1 PUT premium outflow + terminal = total_value).",
    "return_pct": "= total_return_pct  (back-compat alias for the hedged view).",
    "cagr_pct": "= total_cagr_pct  (back-compat alias).",
    "xirr_pct": "= total_xirr_pct  (back-compat alias).",
    "max_drawdown_pct": "worst peak-to-trough dip of the daily return index built from "
                        "(P&L change ÷ capital deployed) each day, compounded.",
    "max_drawdown_value": "same dip in rupees = worst (cumulative p&l − its running peak) "
                          "over the same window.",
    "volatility_pct": "stdev of that daily-return series, annualised ( × √252 ).",
    "sheet_profit": "looked up, not computed — the `Profit` cell for this portfolio's row "
                    "in the Sheet43 / strategy_returns summary sheet.",
    "sheet_capital": "looked up, not computed — the `Capital` cell, same source row.",
    "sheet_return_pct": "looked up, not computed — the `Portfolio Return` cell, same source row.",
    "benchmark_pct": "looked up, not computed — the `NIFTY 500 Return` cell, same source row.",
    "alpha_pct": "return_pct − benchmark_pct  (+ve = portfolio beat NIFTY 500 over this window).",
    "benchmark_start": "looked up, not computed — the `NIFTY 500 Start` cell, same source row "
                       "(index level at the start of this portfolio's comparison window).",
    "benchmark_end": "looked up, not computed — the `NIFTY 500 End` cell, same source row "
                     "(index level as of the sheet's last update).",
    "benchmark_invested": "= total_capital  (the same capital, hypothetically put into "
                          "NIFTY 500 instead, for a like-for-like comparison with alpha_pct).",
    "benchmark_value": "benchmark_invested × (1 + benchmark_pct/100) — what that capital "
                       "would be worth today if it had tracked NIFTY 500 instead.",
    "benchmark_pnl": "benchmark_value − benchmark_invested — the rupee P&L of that "
                     "hypothetical NIFTY 500 investment (compare against total_pnl).",
    "days": "as_of_date − entry_date (or − the rebalance block's date, in a block panel).",
    "days_to_next_rebalance": "next_rebalance − as_of_date.",
    "entry_date": "the portfolio's first cash-ledger flow date.",
    "as_of_date": "the last (most recent) cash-ledger row's value date.",
    "n_stocks": "row count of the block's holdings.",
    "winners": "count of stocks in the block with pnl > 0.",
    "losers": "count of stocks in the block with pnl < 0.",
    "best": "the stock with the highest return_pct in this block.",
    "worst": "the stock with the lowest return_pct in this block.",
}


def format_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with % signs / thousands separators for printing only."""
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(lambda v, c=col: _fmt_value(c, v))
    return out


# --------------------------------------------------------------------------- #
# rebalance-block listing + interactive drill-down
# --------------------------------------------------------------------------- #
def _resolve_pid(token: str) -> int | None:
    """Accept 5/7/8/10, hpc39_10, or a holdings-sheet number like 12 / 12_hpc39_10."""
    m = re.search(r"hpc39_?(\d+)", token, re.I)
    if m and int(m.group(1)) in portfolio_ids():
        return int(m.group(1))
    if token.isdigit():
        n = int(token)
        if n in portfolio_ids():
            return n
        for pat in (f"{n}_hpc39_*.csv", f"{n:02d}_hpc39_*.csv"):
            for f in CSV_DIR.glob(pat):
                mm = re.search(r"hpc39_(\d+)", f.stem)
                if mm and int(mm.group(1)) in portfolio_ids():
                    return int(mm.group(1))
    return None


def blocks(pid: int) -> pd.DataFrame:
    """One row per rebalance block: date, #stocks, invested, value, return, cagr."""
    rows = []
    for key in _get_book()[pid].holdings_blocks:
        pos = positions(pid, key)
        inv = float(pos["invested"].sum())
        cv = float(pos["cur_value"].sum())
        days = pos["days"].iloc[0] if len(pos) else float("nan")
        ret = (cv - inv) / inv if inv else float("nan")
        ann = days and days >= _MIN_ANNUALISE_DAYS and inv
        cagr = (cv / inv) ** (365 / days) - 1 if ann else float("nan")
        rows.append({
            "date": key,
            "stocks": len(pos),
            "days": int(days) if days == days else None,
            "invested": round(inv, 2),
            "current_value": round(cv, 2),
            "pnl": round(cv - inv, 2),
            "return_pct": round(100 * ret, 3),
            "cagr_pct": round(100 * cagr, 3) if math.isfinite(cagr) else float("nan"),
        })
    return pd.DataFrame(rows)


def _interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _explore_blocks(pid: int) -> None:
    bl = blocks(pid)
    if bl.empty:
        print(f"\nHPC39_{pid} has no dated rebalance blocks.")
        return
    print(f"\nRebalance dates in this sheet (HPC39_{pid}):")
    print(format_display(bl).to_string(index=False))
    if not _interactive():
        return

    dates = list(bl["date"])
    while True:
        pick = input("\nEnter a rebalance date to open it (blank to quit): ").strip()
        if not pick:
            break
        hit = [d for d in dates if d.startswith(pick)]
        if not hit:
            print(f"  no block for {pick!r}; choose from {dates}")
            continue
        key = hit[0]
        print()
        for k, v in block_metrics(pid, key).items():
            print(f"  {k:<16} {_fmt_value(k, v)}")
        print("\n  holdings:")
        cols = ["symbol", "invested", "cur_value", "return_pct", "cagr_pct", "weight_pct"]
        print(format_display(positions(pid, key)[cols]).to_string(index=False))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    args = [a.lower() for a in argv]
    pid = next((p for a in args if (p := _resolve_pid(a)) is not None), None)
    if pid is None and any(a.isdigit() or a.startswith("hpc39") for a in args):
        print(f"unknown portfolio; pick from {list(portfolio_ids())} "
              "(or a holdings-sheet number like 12)")
        return 1

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)

    if pid is None:
        print(format_display(metrics_all()).to_string(index=False))
        return 0

    blk = next((a for a in args if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", a)), None)

    if "positions" in args or "stocks" in args:
        print(format_display(positions(pid, blk)).to_string(index=False))
        return 0

    if blk:                                    # metrics for one rebalance block
        try:
            bm = block_metrics(pid, blk)
        except KeyError as exc:
            print(exc.args[0])
            return 1
        for k, v in bm.items():
            print(f"  {k:<16} {_fmt_value(k, v)}")
        print(
            "\n  (block-level; for deposits/withdrawals, hedge_pnl, drawdown,\n"
            "   volatility, benchmark/alpha and sheet_* run  calc.py "
            f"{pid}  for the whole portfolio)"
        )
        return 0

    if "blocks" in args or "rebalances" in args:
        _explore_blocks(pid)
        return 0

    # bare portfolio: the whole-portfolio review, then offer the date drill-down
    for k, v in metrics(pid).items():
        print(f"  {k:<18} {_fmt_value(k, v)}")
    if _interactive():
        _explore_blocks(pid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
