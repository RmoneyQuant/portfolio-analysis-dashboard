"""HPC39 portfolio dashboard - Streamlit UI.

Run:
    uv run streamlit run streamlit_app.py
    # opens http://localhost:8501

Reads the cleaned data straight from backend.py / calc.py / cashflow.py -
no separate API needed.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import backend
import calc
import cashflow as cf_mod
import import_sheet
import query as query_mod
import report
import sheetchange
from backend import portfolio_ids
from query import overview

XLSX = import_sheet.LOCAL_XLSX


def fetch_and_refresh() -> None:
    """Pull the latest Google Sheet, rewrite the CSVs, drop every cache.

    Also re-scans the CSVs for portfolio ids right away (not just on next
    `load()`), so a brand-new sheet (e.g. HPC39_11) shows up in this same
    run - no separate "Recompute" click needed.
    """
    import_sheet.run_once(import_sheet.resolve_source([]))
    calc._book = None
    query_mod._book = None
    cf_mod._book = None
    backend.refresh_portfolio_ids()
    st.cache_data.clear()

st.set_page_config(page_title="HPC39 Dashboard", page_icon="📊", layout="wide")


# --------------------------------------------------------------------------- #
# cached data access
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=300)
def _all_metrics() -> pd.DataFrame:
    return calc.metrics_all()


@st.cache_data(ttl=300)
def _metrics(pid: int) -> dict:
    return calc.metrics(pid)


@st.cache_data(ttl=300)
def _cashflow(pid: int) -> dict:
    return cf_mod.cashflow(pid)


@st.cache_data(ttl=300)
def _blocks(pid: int) -> pd.DataFrame:
    return calc.blocks(pid)


@st.cache_data(ttl=300)
def _positions(pid: int, block: str | None) -> pd.DataFrame:
    return calc.positions(pid, block)


@st.cache_data(ttl=300)
def _block_metrics(pid: int, block: str) -> dict:
    return calc.block_metrics(pid, block)


@st.cache_data(ttl=300)
def _overview(pid: int) -> pd.DataFrame:
    return overview(pid)


@st.cache_data(ttl=300)
def _pdf_report(pid: int) -> bytes:
    return report.build_portfolio_report(pid)


@st.cache_data(ttl=300)
def _pdf_report_all() -> bytes:
    return report.build_all_report()


@st.cache_data(ttl=300)
def _pdf_symbol_report(pid: int, symbol: str) -> bytes:
    return report.build_symbol_report(pid, symbol)


@st.cache_data(ttl=300)
def _totals() -> dict:
    ms = [calc.metrics(p) for p in portfolio_ids()]
    inv = sum(m["invested"] for m in ms)
    pnl = sum(m["total_pnl"] for m in ms)
    dep = sum(m["deposits"] for m in ms)
    wd = sum(m["withdrawals"] for m in ms)
    cap = sum(m["total_capital"] for m in ms)
    val = sum(m["total_value"] for m in ms)
    d_all: list = []
    a_all: list[float] = []
    for p in portfolio_ids():
        d, a = calc.cashflows(p)
        d_all += d
        a_all += a
    wdays = sum(m["invested"] * m["days"] for m in ms) / inv if inv else 0
    ret = pnl / inv if inv else float("nan")
    return {
        "deposits": dep,
        "withdrawals": wd,
        "invested": inv,
        "total_pnl": pnl,
        "current_value": inv + pnl,
        "total_capital": cap,
        "total_value": val,
        "return_pct": 100 * ret,
        "xirr_pct": 100 * calc.xirr(d_all, a_all),
        "cagr_pct": 100 * ((1 + ret) ** (365 / wdays) - 1) if wdays else float("nan"),
        "max_drawdown_pct": sum(m["invested"] * m["max_drawdown_pct"] for m in ms) / inv
        if inv
        else float("nan"),
        "max_drawdown_value": sum(m["max_drawdown_value"] for m in ms),
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def money(v) -> str:
    return "—" if v is None or v != v else f"₹{v:,.0f}"


def pct(v) -> str:
    return "—" if v is None or v != v else f"{v:,.2f}%"


_INT_COLS = {
    "qty", "days", "stocks", "n_deposits", "n_withdrawals",
    "winners", "losers", "rows", "cols", "trade_snapshots",
}


def _typed(df: pd.DataFrame):
    """(df, column_config) with numeric columns kept numeric so header-sort is
    numeric; text columns as string (alphabetical sort)."""
    df = df.copy()
    cfg: dict = {}
    for c in df.columns:
        lc = str(c).lower()
        if lc.endswith("_pct"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
            cfg[c] = st.column_config.NumberColumn(format="%.2f%%")
        elif c in calc._MONEY_COLS or lc in _INT_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            cfg[c] = st.column_config.NumberColumn(format="localized")
        else:
            df[c] = df[c].astype("string")
    return df, cfg


def show_df(df: pd.DataFrame, *, select: bool = False, key: str | None = None):
    """Render a table. With select=True, rows are single-click selectable and the
    selected row index (or None) is returned."""
    if df is None or df.empty:
        st.info("no rows")
        return None
    typed, cfg = _typed(df)
    if not select:
        st.dataframe(typed, width="stretch", hide_index=True, column_config=cfg)
        return None
    ev = st.dataframe(
        typed, width="stretch", hide_index=True, column_config=cfg, key=key,
        on_select="rerun", selection_mode="single-row",
    )
    rows = ev.selection.rows if ev and ev.selection else []
    return rows[0] if rows else None


def metric_dict(d: dict, drop: tuple[str, ...] = ()):
    """Metric/value rows. Click the ⓘ on a row to see how that value is derived."""
    for k, v in d.items():
        if k in drop:
            continue
        c1, c2, c3 = st.columns([3, 3, 1])
        c1.markdown(f"`{k}`")
        c2.write("—" if v is None else str(calc._fmt_value(k, v)))
        formula = calc.FORMULAS.get(k)
        if formula:
            with c3.popover("ⓘ"):
                st.caption(formula)


def symbol_panel(pid: int, symbol: str, context: str = ""):
    """Everything for one stock: headline metrics, P&L-per-rebalance chart,
    the block-by-block history, its broker-statement row and trade instruction.

    `context` disambiguates the download-button key when this is called from
    more than one tab in the same render (e.g. Rebalance history vs Holdings).
    """
    det = calc.symbol_detail(pid, symbol)
    hist = det["history"]
    head_c, dl_c = st.columns([4, 1])
    head_c.markdown(f"### {symbol}")
    if hist.empty:
        st.info("No rebalance-block history for this symbol.")
        return
    dl_c.download_button(
        "📥 Download PDF",
        data=_pdf_symbol_report(pid, symbol),
        file_name=f"HPC39_{pid}_{symbol}_report.pdf",
        mime="application/pdf",
        key=f"symbol_pdf_{context}_{pid}_{symbol}",
    )

    last = hist.iloc[-1]
    c = st.columns(5)
    c[0].metric("Qty", f"{last['qty']:,.0f}")
    c[1].metric("Invested", money(last["invested"]))
    c[2].metric("Current value", money(last["cur_value"]))
    c[3].metric("P&L", money(last["pnl"]), f"{last['return_pct']:.2f}%")
    c[4].metric("Rebalances held", str(len(hist)))

    st.markdown("**P&L by rebalance**")
    st.bar_chart(hist.set_index("rebalance")[["pnl"]], height=240)
    st.markdown("**Return % by rebalance**")
    st.line_chart(hist.set_index("rebalance")[["return_pct"]], height=200)

    st.markdown("**Per-rebalance history**")
    show_df(hist)

    if not det["trade"].empty:
        st.markdown("**Latest trade instruction**")
        show_df(det["trade"])
    if not det["statement"].empty:
        st.markdown("**Broker holdings statement**")
        show_df(det["statement"])


# --------------------------------------------------------------------------- #
# sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("HPC39 Dashboard")
view = st.sidebar.radio(
    "View",
    ["All portfolios"] + [f"HPC39_{p}" for p in portfolio_ids()],
)

if st.sidebar.button("Fetch latest from Google Sheet", type="primary"):
    with st.spinner("Downloading sheet and rebuilding CSVs…"):
        try:
            fetch_and_refresh()
            st.sidebar.success("Data refreshed")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Fetch failed: {exc}")
    st.rerun()

if st.sidebar.button("Recompute (no download)"):
    calc._book = query_mod._book = cf_mod._book = None
    backend.refresh_portfolio_ids()
    st.cache_data.clear()
    st.rerun()

try:
    _dt = datetime.fromtimestamp(XLSX.stat().st_mtime)
    st.sidebar.caption(f"Data as of {_dt:%Y-%m-%d %H:%M} - {XLSX.name}")
except OSError:
    st.sidebar.caption("No local workbook yet — click Fetch.")

with st.sidebar.expander(f"🔀 Sheet: {sheetchange.active_label() or 'unsaved'}"):
    saved = sheetchange.list_sources()
    labels = list(saved)
    current = sheetchange.active_label()
    pick = st.selectbox(
        "Switch to a saved sheet",
        labels,
        index=labels.index(current) if current in labels else 0,
    ) if labels else None

    if pick and st.button("Switch & fetch", key="switch_saved"):
        with st.spinner(f"Switching to {pick!r} and rebuilding CSVs…"):
            try:
                sheetchange.use_source(pick)
                calc._book = query_mod._book = cf_mod._book = None
                st.cache_data.clear()
                st.sidebar.success(f"Now on {pick!r}")
            except Exception as exc:  # noqa: BLE001
                st.sidebar.error(f"Switch failed: {exc}")
        st.rerun()

    st.caption("Working on a different trading sheet? Add its link:")
    new_label = st.text_input("Label", placeholder="e.g. New Trading", key="new_sheet_label")
    new_url = st.text_input(
        "Google Sheet link", placeholder="https://docs.google.com/spreadsheets/d/...",
        key="new_sheet_url",
    )
    if st.button("Add & switch", key="add_and_switch"):
        if not new_label.strip() or not new_url.strip():
            st.sidebar.error("Need both a label and a link.")
        else:
            with st.spinner(f"Fetching {new_label!r}…"):
                try:
                    sheetchange.add_source(new_label, new_url)
                    sheetchange.use_source(new_label)
                    calc._book = query_mod._book = cf_mod._book = None
                    st.cache_data.clear()
                    st.sidebar.success(f"Added and switched to {new_label!r}")
                except Exception as exc:  # noqa: BLE001
                    st.sidebar.error(f"Failed: {exc}")
            st.rerun()

st.sidebar.caption(f"Source: {import_sheet.resolve_source([])[:48]}")


# --------------------------------------------------------------------------- #
# ALL PORTFOLIOS
# --------------------------------------------------------------------------- #
if view == "All portfolios":
    title_c, dl_c = st.columns([4, 1])
    title_c.title("All portfolios")
    dl_c.write("")  # vertical spacer to align the button with the title
    dl_c.download_button(
        "📥 Download PDF (all)",
        data=_pdf_report_all(),
        file_name="HPC39_all_portfolios_report.pdf",
        mime="application/pdf",
    )
    t = _totals()

    c = st.columns(5)
    c[0].metric("Invested", money(t["invested"]))
    c[1].metric("Current value", money(t["current_value"]))
    c[2].metric("Total P&L", money(t["total_pnl"]), f"{t['return_pct']:.2f}%")
    c[3].metric("XIRR (pooled)", pct(t["xirr_pct"]))
    c[4].metric(
        "Max drawdown", money(t["max_drawdown_value"]), f"{t['max_drawdown_pct']:.2f}%"
    )

    c = st.columns(5)
    c[0].metric("Deposits", money(t["deposits"]))
    c[1].metric("Withdrawals", money(t["withdrawals"]))
    c[2].metric("CAGR", pct(t["cagr_pct"]))
    c[3].metric("Return", pct(t["return_pct"]))
    c[4].metric("Portfolios", str(len(portfolio_ids())))

    st.subheader("By portfolio")
    cols = [
        "portfolio", "invested", "total_capital", "current_value", "total_value",
        "total_pnl",
        "equity_return_pct", "equity_xirr_pct", "equity_cagr_pct",
        "total_return_pct", "total_xirr_pct", "total_cagr_pct",
        "max_drawdown_pct", "max_drawdown_value", "next_rebalance",
    ]
    tbl = _all_metrics().reindex(columns=cols).copy()   # tolerate a stale cache
    tbl["next_rebalance"] = tbl["next_rebalance"].astype(str)
    total_row = {
        "portfolio": "TOTAL",
        "invested": t["invested"], "current_value": t["current_value"],
        "total_capital": t["total_capital"], "total_value": t["total_value"],
        "total_pnl": t["total_pnl"], "total_return_pct": t["return_pct"],
        "total_xirr_pct": t["xirr_pct"], "total_cagr_pct": t["cagr_pct"],
        "max_drawdown_pct": t["max_drawdown_pct"],
        "max_drawdown_value": t["max_drawdown_value"],
    }
    tbl = pd.concat([tbl, pd.DataFrame([total_row])], ignore_index=True)
    show_df(tbl)

    st.caption(
        "**equity_*** = return on the equity settlement only.  "
        "**total_*** = the hedged portfolio (equity + PUT); capital includes the "
        "PUT premium, terminal includes the PUT's current value — matches the "
        "sheet's 'Hedged Portfolio' rows.  Net P&L is identical either way; only "
        "the base differs.  TOTAL row: money summed, return blended, XIRR pooled."
    )

    with st.expander("📊 vs NIFTY 500"):
        bench = _all_metrics().reindex(
            columns=[
                "portfolio", "entry_date", "as_of_date",
                "benchmark_start", "benchmark_end", "total_return_pct",
                "benchmark_pct", "alpha_pct",
                "benchmark_invested", "benchmark_value", "benchmark_pnl",
            ]
        ).copy()
        bench = bench.dropna(subset=["benchmark_pct"])
        if bench.empty:
            st.info(
                "No NIFTY 500 figures yet — this needs a matching row in the "
                "Sheet43 / strategy_returns sheet."
            )
        else:
            chart = bench.set_index("portfolio")[["total_return_pct", "benchmark_pct"]].rename(
                columns={
                    "total_return_pct": "Portfolio return %",
                    "benchmark_pct": "NIFTY 500 return %",
                }
            )
            st.bar_chart(chart, height=280, color=["#4C78A8", "#B0B0B0"])
            show_df(
                bench.rename(
                    columns={
                        "entry_date": "window_start", "as_of_date": "window_end",
                        "benchmark_start": "nifty_500_start", "benchmark_end": "nifty_500_end",
                    }
                ).sort_values("alpha_pct", ascending=False)
            )
            st.caption(
                "nifty_500_start/nifty_500_end = the NIFTY 500 index level at the start/end "
                "of each portfolio's window (window_start/window_end = its own entry → "
                "as-of date — Sheet43 gives index levels only, no dates of its own).  "
                "alpha_pct = portfolio return − NIFTY 500 return over that window; "
                "positive = beat the index."
            )

            st.markdown("**If the same capital had gone into NIFTY 500 instead**")
            totals_row = {
                "portfolio": "TOTAL",
                "benchmark_invested": bench["benchmark_invested"].sum(),
                "benchmark_value": bench["benchmark_value"].sum(),
                "benchmark_pnl": bench["benchmark_pnl"].sum(),
            }
            whatif = pd.concat(
                [
                    bench[["portfolio", "benchmark_invested", "benchmark_value", "benchmark_pnl"]],
                    pd.DataFrame([totals_row]),
                ],
                ignore_index=True,
            )
            show_df(whatif)
            st.caption(
                "benchmark_invested = same capital base as the portfolio (total_capital); "
                "benchmark_value/benchmark_pnl = what it would be worth / have earned "
                "tracking NIFTY 500 instead — compare against total_pnl in the table above."
            )


# --------------------------------------------------------------------------- #
# ONE PORTFOLIO
# --------------------------------------------------------------------------- #
else:
    pid = int(view.split("_")[1])
    m = _metrics(pid)
    cf = _cashflow(pid)

    title_c, dl_c = st.columns([4, 1])
    title_c.title(view)
    dl_c.write("")
    dl_c.download_button(
        "📥 Download PDF",
        data=_pdf_report(pid),
        file_name=f"{view}_report.pdf",
        mime="application/pdf",
    )
    _nr = m.get("next_rebalance")
    _dtn = m.get("days_to_next_rebalance")
    _reb = (
        f"  ·  next rebalance {_nr} (in {_dtn} days)"
        if _nr is not None
        else ""
    )
    st.caption(
        f"{m['entry_date']} → {m['as_of_date']}  ·  {m['days']} days"
        f"  ·  last rebalance {m.get('rebalance_date')}{_reb}"
    )

    c = st.columns(5)
    c[0].metric("Equity P&L", money(m["equity_pnl"]), f"{m['equity_return_pct']:.2f}%")
    c[1].metric("PUT (option) P&L", money(m["option_pnl"]))
    c[2].metric("Futures P&L", money(m.get("futures_pnl", 0)))
    c[3].metric("Hedged Net P&L", money(m["hedged_pnl"]), f"{m['total_return_pct']:.2f}%")
    c[4].metric("Full total P&L", money(m["total_pnl"]))

    st.subheader("📈 Equity curve")
    curve = calc.equity_curve(pid)
    if not curve.empty:
        st.line_chart(curve.set_index("date")["equity_value"], height=280)
        st.caption("Daily equity mark-to-market value (cash ledger's `holding`), entry to date.")
    else:
        st.info("No cash-ledger history available yet for an equity curve.")

    with st.expander("🛡️ Hedged portfolio (Equity + PUT)"):
        st.caption("capital = equity + day-1 PUT premium; terminal = equity value + PUT MTM")
        c = st.columns(5)
        c[0].metric("Hedged capital", money(m["total_capital"]))
        c[1].metric("Hedged terminal", money(m["total_value"]))
        c[2].metric("Hedged return", pct(m["total_return_pct"]))
        c[3].metric("Hedged XIRR", pct(m["total_xirr_pct"]))
        c[4].metric("Hedged CAGR", pct(m["total_cagr_pct"]))

    with st.expander("📈 Equity leg only"):
        st.caption("capital = equity settlement; terminal = equity holding value")
        c = st.columns(5)
        c[0].metric("Invested (equity)", money(m["invested"]))
        c[1].metric("Equity value", money(m["equity_value"]))
        c[2].metric("Equity return", pct(m["equity_return_pct"]))
        c[3].metric("Equity XIRR", pct(m["equity_xirr_pct"]))
        c[4].metric("Equity CAGR", pct(m["equity_cagr_pct"]))

    with st.expander("🛟 PUT hedge leg"):
        st.caption("capital = day-1 premium; terminal = current option MTM")
        c = st.columns(5)
        c[0].metric("PUT premium (day 1)", money(m["option_premium_paid"]))
        c[1].metric("PUT MTM now", money(m["premium_now"]))
        c[2].metric("Deposits", money(m["deposits"]))
        c[3].metric("Withdrawals", money(m["withdrawals"]))
        c[4].metric("Current value", money(m["current_value"]))

    with st.expander("📉 Risk & rebalance"):
        c = st.columns(5)
        c[0].metric(
            "Max drawdown", money(m["max_drawdown_value"]), f"{m['max_drawdown_pct']:.2f}%"
        )
        c[1].metric("Volatility", pct(m["volatility_pct"]))
        c[2].metric("Benchmark (NIFTY 500)", pct(m.get("benchmark_pct")))
        c[3].metric("Alpha", pct(m.get("alpha_pct")))
        c[4].metric(
            "Next rebalance",
            str(m.get("next_rebalance") or "—"),
            f"in {m['days_to_next_rebalance']} days" if m.get("days_to_next_rebalance") is not None else None,
        )

    with st.expander("📊 vs NIFTY 500"):
        if m.get("benchmark_pct") is None or m["benchmark_pct"] != m["benchmark_pct"]:
            st.info(
                "No NIFTY 500 figures yet for this portfolio — needs a matching row "
                "in the Sheet43 / strategy_returns sheet."
            )
        else:
            st.caption(
                f"Window (assumed): {m['entry_date']} → {m['as_of_date']}  ·  {m['days']} days — "
                "Sheet43 gives NIFTY 500 index levels only, no dates, so this is the "
                "portfolio's own entry → as-of window, not a date stated by that sheet."
            )
            c = st.columns(5)
            c[0].metric("Portfolio return", pct(m["total_return_pct"]))
            c[1].metric("NIFTY 500 return", pct(m["benchmark_pct"]))
            c[2].metric("Alpha", pct(m["alpha_pct"]))
            c[3].metric("NIFTY 500 start", f"{m['benchmark_start']:,.2f}")
            c[4].metric(
                "NIFTY 500 end",
                f"{m['benchmark_end']:,.2f}",
                f"{m['benchmark_end'] - m['benchmark_start']:+,.2f}",
            )
            chart = pd.DataFrame(
                {"return %": [m["total_return_pct"], m["benchmark_pct"]]},
                index=["Portfolio", "NIFTY 500"],
            )
            st.bar_chart(chart, height=220, color=["#4C78A8"])
            st.caption(
                "Alpha = portfolio return − NIFTY 500 return; positive = beat the index."
            )

            st.markdown("**If the same capital had gone into NIFTY 500 instead**")
            c = st.columns(3)
            c[0].metric("Notional invested", money(m["benchmark_invested"]))
            c[1].metric("Would be worth now", money(m["benchmark_value"]))
            c[2].metric("Hypothetical P&L", money(m["benchmark_pnl"]), pct(m["benchmark_pct"]))
            st.caption(
                "Same capital base as the portfolio (total_capital), scaled by NIFTY 500's "
                "own return over this window — compare `Hypothetical P&L` against the "
                "portfolio's `Full total P&L` above."
            )

    tab_perf, tab_cash, tab_reb, tab_hold, tab_ds = st.tabs(
        ["Performance", "Cashflow", "Rebalance history", "Holdings", "Datasets"]
    )

    with tab_perf:
        metric_dict(m)

    with tab_cash:
        st.caption(
            "Investor money in / out, from the change in deployed capital at each "
            "settlement batch. dividends / interest / fees / taxes are 0 - the "
            "ledgers don't itemise them."
        )
        metric_dict(cf)

    with tab_reb:
        blocks = _blocks(pid)
        show_df(blocks)
        dates = list(blocks["date"]) if not blocks.empty else []
        if dates:
            picked = st.selectbox("Open a rebalance date", dates)
            bm = _block_metrics(pid, picked)
            cc = st.columns(4)
            cc[0].metric("Invested", money(bm["invested"]))
            cc[1].metric("Current value", money(bm["current_value"]))
            cc[2].metric("Return", pct(bm["return_pct"]))
            cc[3].metric("Winners / losers", f"{bm['winners']} / {bm['losers']}")
            metric_dict(bm, drop=("portfolio",))
            st.markdown("**Holdings in this rebalance**  ·  click a row for that stock")
            bpos = _positions(pid, picked)
            i = show_df(bpos, select=True, key=f"blockpos_{pid}_{picked}")
            if i is not None:
                symbol_panel(pid, str(bpos.iloc[i]["symbol"]), context=f"block_{picked}")

    with tab_hold:
        st.caption("Latest rebalance block  ·  click a row to see that stock's full history + P&L graph.")
        pos = _positions(pid, None)
        i = show_df(pos, select=True, key=f"holdpos_{pid}")
        if i is not None:
            symbol_panel(pid, str(pos.iloc[i]["symbol"]), context="holdings")

    with tab_ds:
        st.caption("Every distinct dataset this portfolio holds.")
        show_df(_overview(pid))
