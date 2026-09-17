"""Downloadable PDF reports - one portfolio, or all of them in one file.

Used by the dashboard's "Download PDF" buttons (see streamlit_app.py), and
usable standalone:

    uv run report.py 10                # writes HPC39_10_report.pdf
    uv run report.py                    # writes all_portfolios_report.pdf
    uv run report.py 10 RELIANCE        # writes HPC39_10_RELIANCE_report.pdf

    from report import build_portfolio_report, build_all_report, build_symbol_report
    pdf_bytes = build_portfolio_report(10)
    pdf_bytes = build_symbol_report(10, "RELIANCE")

The PDF core fonts (Helvetica) are Latin-1 only, so money is printed as
"Rs. 1,234.56" rather than "₹" - the rupee sign has no glyph in them.
"""

from __future__ import annotations

import sys
from datetime import datetime

from fpdf import FPDF

import calc
from backend import portfolio_ids

_BLUE = (76, 120, 168)
_GREY = (150, 150, 150)
_LIGHT_GREY = (235, 235, 235)


class _ReportPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*_GREY)
        self.cell(0, 6, "HPC39 Dashboard - auto-generated report", align="C")


# --------------------------------------------------------------------------- #
# formatting (Latin-1 safe - no rupee sign, no unicode arrows)
# --------------------------------------------------------------------------- #
def _money(v) -> str:
    if v is None or v != v:
        return "n/a"
    return f"Rs. {v:,.0f}"


def _pct(v) -> str:
    if v is None or v != v:
        return "n/a"
    return f"{v:,.2f}%"


# --------------------------------------------------------------------------- #
# a small hand-drawn line chart (no matplotlib dependency)
# --------------------------------------------------------------------------- #
def _line_chart(pdf: FPDF, dates: list, values: list, x: float, y: float, w: float, h: float) -> None:
    pdf.set_draw_color(*_GREY)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h)

    if len(values) < 2:
        pdf.set_xy(x, y + h / 2 - 3)
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(w, 6, "not enough data for a chart", align="C")
        return

    vmin, vmax = min(values), max(values)
    vspan = (vmax - vmin) or 1.0
    n = len(values)
    px = lambda i: x + w * i / (n - 1)
    py = lambda v: y + h - h * (v - vmin) / vspan

    pdf.set_draw_color(*_BLUE)
    pdf.set_line_width(0.5)
    for i in range(n - 1):
        pdf.line(px(i), py(values[i]), px(i + 1), py(values[i + 1]))

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(x, y + h + 1)
    pdf.cell(w / 2, 4, str(dates[0]))
    pdf.set_xy(x + w / 2, y + h + 1)
    pdf.cell(w / 2, 4, str(dates[-1]), align="R")
    pdf.set_xy(x - 24, y - 2)
    pdf.cell(22, 4, _money(vmax), align="R")
    pdf.set_xy(x - 24, y + h - 4)
    pdf.cell(22, 4, _money(vmin), align="R")
    pdf.set_text_color(0, 0, 0)


# --------------------------------------------------------------------------- #
# building blocks shared by both report types
# --------------------------------------------------------------------------- #
def _ensure_space(pdf: FPDF, needed: float) -> None:
    """Force a page break if `needed` mm of body space isn't left on this
    page. Needed for chart drawing - `rect()`/`line()` don't respect
    `set_auto_page_break` the way `cell()`/`ln()` do, so a chart placed near
    the bottom of a page would otherwise get silently cut off / scattered
    across pages."""
    if pdf.get_y() + needed > pdf.page_break_trigger:
        pdf.add_page()


def _section_title(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(*_LIGHT_GREY)
    pdf.cell(0, 8, text, fill=True)
    pdf.ln(10)


def _kv_table(pdf: FPDF, rows: list[tuple[str, str]], cols: int = 2) -> None:
    """rows of (label, value); laid out `cols` pairs per line."""
    pdf.set_font("Helvetica", "", 9)
    per_col_w = 190 / cols
    for i in range(0, len(rows), cols):
        chunk = rows[i : i + cols]
        for label, value in chunk:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(90, 90, 90)
            pdf.cell(per_col_w * 0.45, 6, label)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(per_col_w * 0.55, 6, value)
        pdf.ln(6)
    pdf.ln(2)


def _fmt_cell(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _draw_table(pdf: FPDF, df, font_size: int = 7, max_rows: int = 60) -> None:
    """A bordered table for an arbitrary DataFrame - column widths sized to
    content, long tables truncated with a note (keeps the PDF a sane size)."""
    if df is None or df.empty:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "No data.")
        pdf.ln(8)
        return

    cols = list(df.columns)
    shown = df.head(max_rows)
    lens = [
        min(max(len(str(c)), shown[c].astype(str).str.len().max() if len(shown) else 0), 22)
        for c in cols
    ]
    total_chars = sum(lens) or 1
    total_w = 190.0
    widths = [max(14.0, total_w * l / total_chars) for l in lens]
    scale = total_w / sum(widths)
    widths = [w * scale for w in widths]

    pdf.set_font("Helvetica", "B", font_size)
    pdf.set_fill_color(*_LIGHT_GREY)
    for c, w in zip(cols, widths):
        pdf.cell(w, 6, str(c)[:22], border=1, fill=True)
    pdf.ln(6)

    pdf.set_font("Helvetica", "", font_size)
    for _, row in shown.iterrows():
        for c, w in zip(cols, widths):
            pdf.cell(w, 6, _fmt_cell(row[c])[:22], border=1)
        pdf.ln(6)

    if len(df) > max_rows:
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(*_GREY)
        pdf.cell(0, 6, f"... {len(df) - max_rows} more rows not shown")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)
    pdf.ln(4)


def _portfolio_page(pdf: FPDF, pid: int) -> None:
    m = calc.metrics(pid)
    curve = calc.equity_curve(pid)

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"HPC39_{pid} - Portfolio Report")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_GREY)
    pdf.cell(0, 6, f"Generated {datetime.now():%Y-%m-%d %H:%M}")
    pdf.ln(10)
    pdf.set_text_color(0, 0, 0)

    _section_title(pdf, "Summary")
    _kv_table(
        pdf,
        [
            ("Window", f"{m['entry_date']} to {m['as_of_date']} ({m['days']} days)"),
            ("Invested", _money(m["invested"])),
            ("Current value", _money(m["current_value"])),
            ("Total P&L", _money(m["total_pnl"])),
            ("Return", _pct(m["total_return_pct"])),
            ("XIRR", _pct(m["total_xirr_pct"])),
            ("CAGR", _pct(m["total_cagr_pct"])),
            ("Max drawdown", f"{_money(m['max_drawdown_value'])} ({_pct(m['max_drawdown_pct'])})"),
            ("Volatility", _pct(m["volatility_pct"])),
        ],
    )

    _section_title(pdf, "P&L breakdown")
    _kv_table(
        pdf,
        [
            ("Equity P&L", _money(m["equity_pnl"])),
            ("PUT (option) P&L", _money(m["option_pnl"])),
            ("Futures P&L", _money(m.get("futures_pnl", 0))),
            ("Hedge P&L (option+futures)", _money(m["hedge_pnl"])),
            ("Hedged Net P&L (equity+PUT)", _money(m["hedged_pnl"])),
            ("Full total P&L", _money(m["total_pnl"])),
        ],
    )

    _section_title(pdf, "Hedged portfolio (Equity + PUT)")
    _kv_table(
        pdf,
        [
            ("Hedged capital", _money(m["total_capital"])),
            ("Hedged terminal", _money(m["total_value"])),
            ("Hedged return", _pct(m["total_return_pct"])),
            ("Hedged XIRR", _pct(m["total_xirr_pct"])),
            ("Hedged CAGR", _pct(m["total_cagr_pct"])),
        ],
    )

    _section_title(pdf, "Equity leg only")
    _kv_table(
        pdf,
        [
            ("Invested (equity)", _money(m["invested"])),
            ("Equity value", _money(m["equity_value"])),
            ("Equity return", _pct(m["equity_return_pct"])),
            ("Equity XIRR", _pct(m["equity_xirr_pct"])),
            ("Equity CAGR", _pct(m["equity_cagr_pct"])),
        ],
    )

    _section_title(pdf, "PUT hedge leg")
    _kv_table(
        pdf,
        [
            ("PUT premium (day 1)", _money(m["option_premium_paid"])),
            ("PUT MTM now", _money(m["premium_now"])),
            ("Deposits", _money(m["deposits"])),
            ("Withdrawals", _money(m["withdrawals"])),
            ("Current value", _money(m["current_value"])),
        ],
    )

    _section_title(pdf, "Risk & rebalance")
    _kv_table(
        pdf,
        [
            ("Max drawdown", f"{_money(m['max_drawdown_value'])} ({_pct(m['max_drawdown_pct'])})"),
            ("Volatility", _pct(m["volatility_pct"])),
            ("Benchmark (NIFTY 500)", _pct(m.get("benchmark_pct"))),
            ("Alpha", _pct(m.get("alpha_pct"))),
            ("Next rebalance", str(m.get("next_rebalance") or "-")),
        ],
    )

    _ensure_space(pdf, 10 + 65)      # title + chart, so it isn't orphaned/cut
    _section_title(pdf, "Equity curve")
    if not curve.empty:
        _line_chart(
            pdf, curve["date"].tolist(), curve["equity_value"].tolist(),
            x=35, y=pdf.get_y() + 2, w=155, h=55,
        )
        pdf.ln(65)
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 8, "No cash-ledger history available.")
        pdf.ln(10)

    if m.get("benchmark_pct") == m.get("benchmark_pct"):  # not NaN
        _section_title(pdf, "vs NIFTY 500")
        _kv_table(
            pdf,
            [
                ("Portfolio return", _pct(m["total_return_pct"])),
                ("NIFTY 500 return", _pct(m["benchmark_pct"])),
                ("Alpha", _pct(m["alpha_pct"])),
                ("NIFTY 500 start -> end", f"{m['benchmark_start']:,.2f} -> {m['benchmark_end']:,.2f}"),
                ("Notional invested", _money(m["benchmark_invested"])),
                ("Would be worth (NIFTY)", _money(m["benchmark_value"])),
                ("Hypothetical P&L (NIFTY)", _money(m["benchmark_pnl"])),
            ],
        )


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def build_portfolio_report(pid: int) -> bytes:
    """PDF for one portfolio: summary metrics, equity curve, NIFTY 500 comparison."""
    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    _portfolio_page(pdf, pid)
    return bytes(pdf.output())


def build_symbol_report(pid: int, symbol: str) -> bytes:
    """PDF for one stock in one portfolio: latest snapshot, P&L-by-rebalance
    chart, full rebalance history, broker statement rows, latest trade row."""
    det = calc.symbol_detail(pid, symbol)
    hist = det["history"]

    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"{det['symbol']} - HPC39_{pid} Stock Report")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_GREY)
    pdf.cell(0, 6, f"Generated {datetime.now():%Y-%m-%d %H:%M}")
    pdf.ln(10)
    pdf.set_text_color(0, 0, 0)

    if hist.empty:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 8, "No rebalance-block history for this symbol.")
        return bytes(pdf.output())

    last = hist.iloc[-1]
    _section_title(pdf, "Latest snapshot")
    _kv_table(
        pdf,
        [
            ("Qty", f"{last['qty']:,.0f}"),
            ("Invested", _money(last["invested"])),
            ("Current value", _money(last["cur_value"])),
            ("P&L", _money(last["pnl"])),
            ("Return", _pct(last["return_pct"])),
            ("Rebalances held", str(len(hist))),
        ],
    )

    _ensure_space(pdf, 10 + 60)
    _section_title(pdf, "P&L by rebalance")
    _line_chart(
        pdf, hist["rebalance"].tolist(), hist["pnl"].tolist(),
        x=35, y=pdf.get_y() + 2, w=155, h=50,
    )
    pdf.ln(60)

    _section_title(pdf, "Per-rebalance history")
    _draw_table(pdf, hist[["rebalance", "qty", "buy_price", "invested", "cur_price", "cur_value", "pnl", "return_pct"]])

    if not det["statement"].empty:
        _section_title(pdf, "Broker holdings statement")
        _draw_table(pdf, det["statement"])

    if not det["trade"].empty:
        _section_title(pdf, "Latest trade instruction")
        _draw_table(pdf, det["trade"])

    return bytes(pdf.output())


def build_all_report() -> bytes:
    """One PDF: an overview page (all portfolios + TOTAL), then one page per
    portfolio (same content as `build_portfolio_report`)."""
    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "All Portfolios - Overview")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_GREY)
    pdf.cell(0, 6, f"Generated {datetime.now():%Y-%m-%d %H:%M}")
    pdf.ln(10)
    pdf.set_text_color(0, 0, 0)

    ids = portfolio_ids()
    ms = [calc.metrics(p) for p in ids]
    inv = sum(m["invested"] for m in ms)
    pnl = sum(m["total_pnl"] for m in ms)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*_LIGHT_GREY)
    headers = ["Portfolio", "Invested", "Current value", "Total P&L", "Return", "Alpha"]
    widths = [30, 38, 38, 38, 23, 23]
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, h, border=1, fill=True)
    pdf.ln(7)
    pdf.set_font("Helvetica", "", 9)
    for m in ms:
        row = [
            m["portfolio"], _money(m["invested"]), _money(m["current_value"]),
            _money(m["total_pnl"]), _pct(m["total_return_pct"]), _pct(m.get("alpha_pct")),
        ]
        for v, w in zip(row, widths):
            pdf.cell(w, 7, v, border=1)
        pdf.ln(7)
    pdf.set_font("Helvetica", "B", 9)
    total_row = ["TOTAL", _money(inv), _money(inv + pnl), _money(pnl), "-", "-"]
    for v, w in zip(total_row, widths):
        pdf.cell(w, 7, v, border=1)
    pdf.ln(12)

    for pid in ids:
        _portfolio_page(pdf, pid)

    return bytes(pdf.output())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        pid, symbol = int(argv[0]), argv[1]
        out = f"HPC39_{pid}_{symbol}_report.pdf"
        with open(out, "wb") as f:
            f.write(build_symbol_report(pid, symbol))
    elif argv:
        pid = int(argv[0])
        out = f"HPC39_{pid}_report.pdf"
        with open(out, "wb") as f:
            f.write(build_portfolio_report(pid))
    else:
        out = "all_portfolios_report.pdf"
        with open(out, "wb") as f:
            f.write(build_all_report())
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
