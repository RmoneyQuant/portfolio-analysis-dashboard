r"""Smoke test for calc.py - run it to check the metrics still add up.

    uv run test_calc.py
    # or:  .venv\Scripts\python.exe test_calc.py

Exit code 0 = all checks passed, 1 = something is off.
Also runs under pytest if you have it (`uv run pytest test_calc.py`).
"""

from __future__ import annotations

import math
import sys

import pandas as pd

from backend import PORTFOLIO_IDS
from calc import (
    cashflows,
    equity_cashflows,
    format_display,
    metrics,
    metrics_all,
    positions,
    total_cashflows,
    xirr,
)

SUMMARY_COLS = [
    "portfolio", "deposits", "withdrawals", "invested", "total_pnl",
    "current_value", "return_pct", "xirr_pct", "cagr_pct", "max_drawdown_pct",
]

# cashflow sums are line items summed independently of the `net` running balance;
# 2-decimal sheet rounding over ~15 flows (and one known ~Rs.94 sheet mismatch in
# HPC39_8) means a reconciliation can be off by a few hundred rupees.
RECON_TOL = 250.0

PROBLEMS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        PROBLEMS.append(msg)


def test_xirr_known_value() -> None:
    # +10% a year: -100 today, +110 in exactly one year
    from datetime import date

    r = xirr([date(2025, 1, 1), date(2026, 1, 1)], [-100.0, 110.0])
    check(abs(r - 0.10) < 1e-3, f"xirr sanity: expected ~0.10, got {r:.5f}")


def test_xirr_unsolvable_is_nan() -> None:
    from datetime import date

    r = xirr([date(2025, 1, 1), date(2026, 1, 1)], [100.0, 110.0])  # all positive
    check(math.isnan(r), f"xirr with no sign change should be NaN, got {r}")


def test_metrics_identities() -> None:
    for pid in PORTFOLIO_IDS:
        m = metrics(pid)
        tag = m["portfolio"]

        check(
            abs(m["current_value"] - (m["invested"] + m["total_pnl"])) < 1.0,
            f"{tag}: current_value != invested + total_pnl",
        )
        check(
            abs(m["total_pnl"] - (m["equity_pnl"] + m["hedge_pnl"])) < 1.0,
            f"{tag}: total_pnl != equity_pnl + hedge_pnl",
        )
        check(m["invested"] > 0, f"{tag}: invested should be positive")
        check(
            m["entry_date"] is not None and m["as_of_date"] is not None and m["days"] > 0,
            f"{tag}: bad date window ({m['entry_date']} -> {m['as_of_date']})",
        )
        check(
            math.isfinite(m["return_pct"]) and -100 < m["return_pct"] < 500,
            f"{tag}: return_pct out of range ({m['return_pct']})",
        )
        check(
            math.isfinite(m["xirr_pct"]) and -100 < m["xirr_pct"] < 200,
            f"{tag}: xirr_pct out of range ({m['xirr_pct']})",
        )
        check(
            (m["return_pct"] > 0) == (m["xirr_pct"] > 0),
            f"{tag}: return_pct and xirr_pct disagree on sign "
            f"({m['return_pct']} vs {m['xirr_pct']})",
        )
        check(
            m["max_drawdown_pct"] <= 0 and m["max_drawdown_pct"] > -95,
            f"{tag}: max_drawdown_pct looks wrong ({m['max_drawdown_pct']})",
        )


def test_cashflows_reconcile() -> None:
    for pid in PORTFOLIO_IDS:
        m = metrics(pid)
        # equity flows + equity terminal  ->  equity_pnl
        _, eq = equity_cashflows(pid)
        check(
            abs(sum(eq) - m["equity_pnl"]) < RECON_TOL,
            f"{m['portfolio']}: equity cashflows {sum(eq):,.2f} != equity_pnl "
            f"{m['equity_pnl']:,.2f}",
        )
        # total flows sum to the hedged terminal P&L (= total_value - total_capital);
        # for a never-rolled PUT that also equals total_pnl
        _, tot = total_cashflows(pid)
        check(
            abs(sum(tot) - (m["total_value"] - m["total_capital"])) < RECON_TOL,
            f"{m['portfolio']}: total cashflows {sum(tot):,.2f} != "
            f"total_value - total_capital {m['total_value'] - m['total_capital']:,.2f}",
        )
        check(cashflows(pid) == total_cashflows(pid), f"{m['portfolio']}: cashflows != total")


def test_hedged_capital_identities() -> None:
    for pid in PORTFOLIO_IDS:
        m = metrics(pid)
        tag = m["portfolio"]
        check(
            abs(m["total_capital"] - (m["invested"] + m["option_premium_paid"])) < 1.0,
            f"{tag}: total_capital != invested + option_premium_paid",
        )
        check(
            abs(m["total_value"] - (m["equity_value"] + m["premium_now"])) < 1.0,
            f"{tag}: total_value != equity_value + premium_now",
        )
        check(
            abs(m["hedged_pnl"] - (m["equity_pnl"] + m["option_pnl"])) < 1.0,
            f"{tag}: hedged_pnl != equity_pnl + option_pnl",
        )
        check(
            abs(m["total_pnl"] - (m["hedged_pnl"] + m["futures_pnl"])) < 1.0,
            f"{tag}: total_pnl != hedged_pnl + futures_pnl",
        )
        check(
            abs(m["total_return_pct"] - 100 * m["hedged_pnl"] / m["total_capital"]) < 0.01,
            f"{tag}: total_return_pct != hedged_pnl / total_capital",
        )
        for k in ("equity_return_pct", "equity_xirr_pct", "equity_cagr_pct",
                  "total_return_pct", "total_xirr_pct", "total_cagr_pct"):
            v = m[k]
            check(v != v or -100 < v < 400, f"{tag}: {k} out of range ({v})")
        check(m["xirr_pct"] == m["total_xirr_pct"], f"{tag}: xirr_pct alias != total_xirr_pct")


def _split_flows(pid: int):
    """(deposits, withdrawals, terminal) from the EQUITY cashflows.

    Everything before the terminal is a real investor movement:
    negative = deposit (money in), positive = withdrawal (money out).
    """
    _, amounts = equity_cashflows(pid)
    real, terminal = amounts[:-1], amounts[-1]
    deposits = [a for a in real if a < 0]
    withdrawals = [a for a in real if a > 0]
    return deposits, withdrawals, terminal


def test_breakdown_matches_metrics() -> None:
    for pid in PORTFOLIO_IDS:
        m = metrics(pid)
        deposits, withdrawals, _ = _split_flows(pid)
        check(
            abs(m["deposits"] - (-sum(deposits))) < 1.0,
            f"HPC39_{pid}: metrics deposits {m['deposits']:,.2f} "
            f"!= flows {-sum(deposits):,.2f}",
        )
        check(
            abs(m["withdrawals"] - sum(withdrawals)) < 1.0,
            f"HPC39_{pid}: metrics withdrawals {m['withdrawals']:,.2f} "
            f"!= flows {sum(withdrawals):,.2f}",
        )
        check(
            abs((m["deposits"] - m["withdrawals"]) - m["invested"]) < RECON_TOL,
            f"HPC39_{pid}: deposits - withdrawals != invested",
        )


def test_deposits_and_withdrawals() -> None:
    for pid in PORTFOLIO_IDS:
        m = metrics(pid)
        tag = m["portfolio"]
        deposits, withdrawals, terminal = _split_flows(pid)
        _, amounts = equity_cashflows(pid)

        gross_dep = -sum(deposits)          # positive: total money put in
        gross_wd = sum(withdrawals)         # positive: total money taken out
        net_invested = gross_dep - gross_wd

        check(len(deposits) >= 1, f"{tag}: no deposit found")
        check(all(a < 0 for a in deposits), f"{tag}: a deposit is not negative")
        check(all(a > 0 for a in withdrawals), f"{tag}: a withdrawal is not positive")
        check(
            len(deposits) + len(withdrawals) + 1 == len(amounts),
            f"{tag}: flow count mismatch "
            f"({len(deposits)}+{len(withdrawals)}+1 != {len(amounts)})",
        )
        check(amounts[0] < 0, f"{tag}: first cashflow should be a deposit")
        check(
            abs(net_invested - m["invested"]) < RECON_TOL,
            f"{tag}: deposits - withdrawals ({net_invested:,.2f}) "
            f"!= invested ({m['invested']:,.2f})",
        )
        check(
            gross_dep >= gross_wd,
            f"{tag}: withdrawals ({gross_wd:,.2f}) exceed deposits ({gross_dep:,.2f})",
        )
        check(
            abs((terminal - net_invested) - m["equity_pnl"]) < RECON_TOL,
            f"{tag}: terminal - net_invested ({terminal - net_invested:,.2f}) "
            f"!= equity_pnl ({m['equity_pnl']:,.2f})",
        )
        check(
            abs(terminal - m["equity_value"]) < RECON_TOL,
            f"{tag}: terminal flow ({terminal:,.2f}) != equity_value "
            f"({m['equity_value']:,.2f})",
        )


def test_positions() -> None:
    for pid in PORTFOLIO_IDS:
        pos = positions(pid)
        tag = f"HPC39_{pid}"
        check(not pos.empty, f"{tag}: positions() returned nothing")
        check(pos["symbol"].is_unique, f"{tag}: duplicate symbols in positions()")
        check(
            abs(pos["weight_pct"].sum() - 100.0) < 0.5,
            f"{tag}: position weights sum to {pos['weight_pct'].sum():.2f}, not 100",
        )
        # pnl column must equal cur_value - invested row by row (NaN-safe)
        row_err = (pos["pnl"] - (pos["cur_value"] - pos["invested"])).abs().fillna(0).max()
        check(row_err < 0.01, f"{tag}: pnl column != cur_value - invested (max {row_err})")


def test_metrics_all_shape() -> None:
    df = metrics_all()
    check(len(df) == len(PORTFOLIO_IDS), f"metrics_all has {len(df)} rows")
    check("xirr_pct" in df.columns, "metrics_all missing xirr_pct column")


def portfolio_totals() -> dict:
    """One combined row across all portfolios.

    - money columns: plain sum
    - return_pct   : blended  = 100 * sum(total_pnl) / sum(invested)
    - xirr_pct     : pooled - every portfolio's dated cashflows in one XIRR
    - cagr_pct     : from the blended return over the invested-weighted avg days
    - max_drawdown : invested-weighted average (approx; a true figure needs a
                     combined daily equity curve)
    """
    ms = [metrics(pid) for pid in PORTFOLIO_IDS]
    dep = sum(m["deposits"] for m in ms)
    wd = sum(m["withdrawals"] for m in ms)
    inv = sum(m["invested"] for m in ms)
    pnl = sum(m["total_pnl"] for m in ms)
    cv = sum(m["current_value"] for m in ms)
    ret = 100 * pnl / inv if inv else float("nan")

    all_dates: list = []
    all_amts: list[float] = []
    for pid in PORTFOLIO_IDS:
        d, a = cashflows(pid)
        all_dates += d
        all_amts += a
    pooled_xirr = 100 * xirr(all_dates, all_amts)

    wdays = sum(m["invested"] * m["days"] for m in ms) / inv if inv else 0
    cagr = 100 * ((1 + ret / 100) ** (365 / wdays) - 1) if wdays > 0 else float("nan")
    dd = sum(m["invested"] * m["max_drawdown_pct"] for m in ms) / inv if inv else float("nan")

    return {
        "portfolio": "TOTAL",
        "deposits": round(dep, 2),
        "withdrawals": round(wd, 2),
        "invested": round(inv, 2),
        "total_pnl": round(pnl, 2),
        "current_value": round(cv, 2),
        "return_pct": round(ret, 3),
        "xirr_pct": round(pooled_xirr, 3),
        "cagr_pct": round(cagr, 3),
        "max_drawdown_pct": round(dd, 3),
    }


def test_totals_reconcile() -> None:
    t = portfolio_totals()
    check(
        abs((t["deposits"] - t["withdrawals"]) - t["invested"]) < RECON_TOL,
        f"TOTAL: deposits - withdrawals ({t['deposits'] - t['withdrawals']:,.2f}) "
        f"!= invested ({t['invested']:,.2f})",
    )
    check(
        abs((t["invested"] + t["total_pnl"]) - t["current_value"]) < 10.0,
        "TOTAL: invested + total_pnl != current_value",
    )
    check(
        math.isfinite(t["xirr_pct"]) and -100 < t["xirr_pct"] < 200,
        f"TOTAL: xirr_pct out of range ({t['xirr_pct']})",
    )
    check(
        -95 < t["max_drawdown_pct"] <= 0,
        f"TOTAL: max_drawdown_pct looks wrong ({t['max_drawdown_pct']})",
    )


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"  ran  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            PROBLEMS.append(f"{t.__name__} raised {exc!r}")

    print()
    summary = metrics_all()[SUMMARY_COLS]
    summary = pd.concat(
        [summary, pd.DataFrame([portfolio_totals()])[SUMMARY_COLS]], ignore_index=True
    )
    print(format_display(summary).to_string(index=False))
    print("  TOTAL: money cols summed; return blended; xirr pooled; "
          "cagr from blended return; drawdown invested-weighted (approx)")
    print()

    if PROBLEMS:
        print(f"FAILED ({len(PROBLEMS)}):")
        for p in PROBLEMS:
            print("  -", p)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
 