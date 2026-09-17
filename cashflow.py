"""Cash-flow metrics for a portfolio.

    uv run cashflow.py 10
    uv run cashflow.py hpc39_5
    uv run cashflow.py                 # all four portfolios

    from cashflow import cashflow, cashflow_all
    cf = cashflow(10)                  # dict

What it reports
--------------
deposits / withdrawals / net_invested
        real investor cash movements, from the change in the cash ledger's
        `net` at each settlement batch (see calc._investor_flows).
gross_buy_settlement / gross_sell_settlement
        total settlement debits / credits across rebalances (turnover, incl.
        rollovers) - context, not investor money.
option_premium_net / futures_mtm_net
        running P&L on the option and futures ledgers.
xirr_pct / cagr_pct
        money-weighted and simple annualised return (from calc.metrics) - the
        deposits/withdrawals above are exactly the cashflows the XIRR uses.
dividends / interest_income / brokerage / taxes / fees / transaction_costs
        scanned from ledger narrations by keyword. The current sheets only
        carry "Settlement Posting" / "Option Premium Bill" / "Future MTM Bill"
        rows, so these come out 0.00 - the classifier is here so they populate
        automatically if a detailed (contract-note level) ledger is imported.
"""

from __future__ import annotations

import sys

import pandas as pd

import calc
from backend import load, portfolio_ids

# narration keyword -> line-item category
LINE_ITEM_RULES: dict[str, tuple[str, ...]] = {
    "dividends": ("dividend", "div. "),
    "interest_income": ("interest", "int cr", "int.cr", "int credit"),
    "brokerage": ("brokerage", "brok "),
    "taxes": ("stt", "ctt", "gst", "stamp duty", "sebi", "securities transaction tax"),
    "fees": ("fee", "dp charge", "dp chg", "amc", "annual maintenance", "custody"),
    "transaction_costs": (
        "transaction charge", "exchange charge", "turnover charge", "clearing", "ipft"
    ),
}
_LINE_ITEMS = tuple(LINE_ITEM_RULES)

_MONEY = {
    "deposits", "withdrawals", "net_invested",
    "gross_buy_settlement", "gross_sell_settlement",
    "option_premium_net", "futures_mtm_net", *_LINE_ITEMS,
}
_PCT = {"xirr_pct", "cagr_pct"}

_book = None


def _get_book():
    global _book
    if _book is None:
        _book = load()
    return _book


def _num(s) -> pd.Series:
    if s is None:
        return pd.Series(dtype="float64")
    return pd.to_numeric(
        pd.Series(s).astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


def _resolve_pid(spec) -> int:
    import re

    for tok in re.split(r"[\s_\-]+", str(spec).strip()):
        m = re.fullmatch(r"(?:hpc39)?(\d{1,2})", tok, re.I)
        if m and int(m.group(1)) in portfolio_ids():
            return int(m.group(1))
    raise KeyError(f"no portfolio in {spec!r}; pick from {list(portfolio_ids())}")


def _classify(narration: str) -> str | None:
    low = narration.lower()
    for cat, keys in LINE_ITEM_RULES.items():
        if any(k in low for k in keys):
            return cat
    return None


def _leg_net(leg: pd.DataFrame | None) -> float:
    if leg is None or leg.empty:
        return 0.0
    row = leg.dropna(how="all").iloc[-1]
    if "net" in leg.columns:
        v = _num([row["net"]]).iloc[0]
        if pd.notna(v):
            return float(v)
    if {"premium", "dr"} <= set(leg.columns):
        prem, dr = _num([row["premium"]]).iloc[0], _num([row["dr"]]).iloc[0]
        if pd.notna(prem) and pd.notna(dr):
            return float(prem - dr)
    return 0.0


def cashflow(spec) -> dict:
    pid = _resolve_pid(spec)
    p = _get_book()[pid]

    cb = calc.cashflow_breakdown(pid)
    m = calc.metrics(pid)

    cl = calc._cash_ledger(pid)
    batch = cl[cl["bill_no"].ne(cl["bill_no"].shift())]
    gross_buy = float(_num(batch.get("dr")).fillna(0).sum())
    gross_sell = float(_num(batch.get("cr")).fillna(0).sum())

    items = {k: 0.0 for k in _LINE_ITEMS}
    hits = 0
    for leg in (p.cash_ledger, p.option_ledger, p.fo_ledger):
        if leg is None or "narration" not in leg.columns:
            continue
        cr = _num(leg["cr"] if "cr" in leg.columns else leg.get("credit")).fillna(0)
        dr = _num(leg["dr"] if "dr" in leg.columns else leg.get("debit")).fillna(0)
        cr = cr.reindex(leg.index, fill_value=0.0)
        dr = dr.reindex(leg.index, fill_value=0.0)
        for i, n in leg["narration"].items():
            cat = _classify(str(n))
            if cat:
                items[cat] += float(cr.get(i, 0.0) - dr.get(i, 0.0))
                hits += 1

    return {
        "portfolio": f"HPC39_{pid}",
        "deposits": cb["deposits"],
        "withdrawals": cb["withdrawals"],
        "net_invested": cb["net_invested"],
        "n_deposits": cb["n_deposits"],
        "n_withdrawals": cb["n_withdrawals"],
        "gross_buy_settlement": round(gross_buy, 2),
        "gross_sell_settlement": round(gross_sell, 2),
        "option_premium_net": round(_leg_net(p.option_ledger), 2),
        "futures_mtm_net": round(_leg_net(p.fo_ledger), 2),
        "xirr_pct": m["xirr_pct"],
        "cagr_pct": m["cagr_pct"],
        **{k: round(v, 2) for k, v in items.items()},
        "line_items_matched": hits,
    }


def cashflow_all() -> pd.DataFrame:
    return pd.DataFrame(cashflow(pid) for pid in portfolio_ids())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _fmt(key: str, v):
    if isinstance(v, float) and v != v:          # NaN
        return "n/a"
    if key in _PCT and isinstance(v, (int, float)):
        return f"{v:,.2f}%"
    if key in _MONEY and isinstance(v, (int, float)):
        return f"{v:,.2f}"
    return v


def main(argv: list[str]) -> int:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)

    if not argv:
        df = cashflow_all()
        for c in df.columns:
            df[c] = df[c].map(lambda v, c=c: _fmt(c, v))
        print(df.to_string(index=False))
        return 0

    try:
        cf = cashflow(" ".join(argv))
    except KeyError as exc:
        print(exc.args[0])
        return 1

    for k, v in cf.items():
        print(f"  {k:<22} {_fmt(k, v)}")
    if cf["line_items_matched"] == 0:
        print(
            "\n  note: dividends / interest / fees / taxes / brokerage / "
            "transaction_costs are 0 -\n"
            "        the current ledgers don't itemise them (only settlement "
            "and premium rows)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
