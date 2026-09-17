"""One easy front door: search -> get fixed data -> filter.

Everything is cleaned by backend.py / filter.py first, so what you get back is
already correct (real dates, numeric columns, consistent headers).

Command line
------------
    uv run query.py                         # show everything you can ask for
    uv run query.py hpc39_5                 # OVERVIEW: every dataset this portfolio holds
    uv run query.py hpc39_10 holdings
    uv run query.py hpc39_5 2026-06-03      # the holdings block for one rebalance date
    uv run query.py hpc39_5 2026-06-03 -m  # metrics panel for that block (return, cagr, xirr)
    uv run query.py hpc39_5 -m             # metrics panel for the whole portfolio
    uv run query.py hpc39_5 cash ledger  -w "net < -20000000"  -s date
    uv run query.py hpc39_7 trades  -w "action == SELL and targetweight > 0"
    uv run query.py hpc39_10 holdings  -w "p&l > 0"  -s p&l --desc --top 10
    uv run query.py hpc39_10 trades jun     # a specific rebalance snapshot
    uv run query.py performance             # a shared sheet
    uv run query.py 18                      # any sheet by its number
    ... add  --save  to write the result to data/clean/

A holdings sheet is a stack of dated rebalance blocks; `hpc39_5 holdings` gives
the latest, `hpc39_5 <YYYY-MM-DD>` gives that block, `hpc39_5` alone lists them all.

Python
------
    from query import get, where

    df = get("hpc39_10 holdings")
    df = where(df, "p&l > 0 and actual_price > 1000")
    df = where(df, "narration contains NG6145")
    df = where(df, "action in SELL,BUY")

`where` conditions:  col == v | col != v | col > v | col >= v | col < v |
col <= v | col contains text | col in a,b,c | col not in a,b,c
joined with `and`. Column names match case-insensitively and by prefix.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from backend import _MONTHS, load, portfolio_ids
from filter import CLEAN_DIR, CSV_DIR, load_clean
from filter import search as _csv_search

_TYPES = (
    "holdings", "holdings_statement", "cash_ledger", "option_ledger",
    "fo_ledger", "backtest", "trades",
)
_TYPE_ALIASES = {
    "holding": "holdings", "holdings": "holdings", "stock": "holdings", "stocks": "holdings",
    "position": "holdings", "positions": "holdings",
    "statement": "holdings_statement", "holdings_statement": "holdings_statement",
    "valuation": "holdings_statement",
    "cash": "cash_ledger", "cashledger": "cash_ledger", "cash_ledger": "cash_ledger",
    "ledger": "cash_ledger",
    "option": "option_ledger", "options": "option_ledger", "optionledger": "option_ledger",
    "option_ledger": "option_ledger",
    "fo": "fo_ledger", "future": "fo_ledger", "futures": "fo_ledger", "fo_ledger": "fo_ledger",
    "nifty": "fo_ledger",
    "backtest": "backtest",
    "trade": "trades", "trades": "trades", "instruction": "trades", "instructions": "trades",
}

_book = None


def _get_book():
    global _book
    if _book is None:
        _book = load()
    return _book


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def options() -> str:
    """Human-readable list of everything `get` accepts right now."""
    b = _get_book()
    lines = ["Portfolios:"]
    for pid in portfolio_ids():
        p = b[pid]
        have = [t for t in _TYPES if t != "trades" and getattr(p, t) is not None]
        if p.trades:
            snaps = ",".join(s.label or "v" + str(i) for i, s in enumerate(p.trades))
            have.append(f"trades[{snaps}]")
        lines.append(f"  hpc39_{pid:<3} {' '.join(have)}")
    lines.append("Shared sheets:")
    lines.append("  " + ", ".join(sorted(b.shared)))
    lines.append("Any sheet by name or number, e.g. `18` or `hpc39_5 nse fo optionledger`")
    return "\n".join(lines)


def search(term: str) -> list[str]:
    """Return the `get` specs that match `term` (portfolio+type combos and sheets)."""
    t = term.lower().strip()
    hits: list[str] = []
    for pid in portfolio_ids():
        p = _get_book()[pid]
        for kind in _TYPES:
            label = f"hpc39_{pid} {kind}"
            if t in label.replace("_", " ") or t in label:
                if kind == "trades" and p.trades or getattr(p, kind, None) is not None:
                    hits.append(label)
    hits += [k for k in _get_book().shared if t in k]
    hits += [f.stem for f in _csv_search(term)]
    return sorted(dict.fromkeys(hits))


# --------------------------------------------------------------------------- #
# get  (search + fix)
# --------------------------------------------------------------------------- #
def _drop_junk_cols(df: pd.DataFrame, threshold: float = 0.9) -> pd.DataFrame:
    """Drop unidentified `col_N` columns that are almost entirely empty."""
    junk = [
        c
        for c in df.columns
        if re.fullmatch(r"col_\d+", str(c)) and df[c].isna().mean() >= threshold
    ]
    return df.drop(columns=junk) if junk else df


def get(spec: str, tidy: bool = True) -> pd.DataFrame:
    """Fetch one cleaned table. See module docstring for the accepted forms.

    tidy=True also drops unnamed `col_N` columns that are almost all empty.
    """
    df = _get_raw(spec)
    return _drop_junk_cols(df) if tidy else df


def _holdings_sheet_pid(nondate_tokens: list[str]) -> int | None:
    """If the (non-date) tokens uniquely name a holdings CSV, return its portfolio id."""
    if not nondate_tokens:
        return None
    matches = _csv_search(" ".join(nondate_tokens))
    if len(matches) != 1:
        return None
    m = re.fullmatch(r"\d+_hpc39_(\d+)", matches[0].stem)
    return int(m.group(1)) if m and int(m.group(1)) in portfolio_ids() else None


def _get_raw(spec: str) -> pd.DataFrame:
    tokens = str(spec).strip().split()          # whitespace only - keep 2026-06-03 intact
    low = [t.lower() for t in tokens]

    pid, rest = None, []
    for t in low:
        m = re.fullmatch(r"(?:hpc39_?)?(\d{1,2})", t)
        if m and int(m.group(1)) in portfolio_ids() and pid is None:
            pid = int(m.group(1))
        else:
            rest.append(t)

    kind = next((_TYPE_ALIASES[t] for t in rest if t in _TYPE_ALIASES), None)
    label = next((t for t in rest if t in _MONTHS), None)
    datelabel = next((t for t in rest if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", t)), None)

    if pid is not None:
        if kind is None and datelabel is None:
            return overview(pid)
        if kind is None:
            kind = "holdings"                      # a bare date means a holdings block
        return _from_portfolio(pid, kind, label, datelabel)

    if kind is not None:
        raise KeyError(
            f"Which portfolio? add one of {list(portfolio_ids())}, e.g. `hpc39_10 {kind}`"
        )

    # a holdings sheet named by file / number: overview, or one rebalance block
    nondate = [t for t in low if t != datelabel]
    sheet_pid = _holdings_sheet_pid(nondate)
    if sheet_pid is not None:
        if datelabel:
            return _from_portfolio(sheet_pid, "holdings", None, datelabel)
        return overview(sheet_pid)

    # a shared sheet?
    joined = "_".join(rest) or "_".join(low)
    shared = _get_book().shared
    if joined in shared:
        return shared[joined].copy()
    near = [k for k in shared if joined and joined in k]
    if len(near) == 1:
        return shared[near[0]].copy()

    # any raw sheet by name / number
    matches = _csv_search(" ".join(tokens))
    if len(matches) == 1:
        return load_clean(matches[0])
    if not matches:
        raise KeyError(f"Nothing matches {spec!r}.\n\n{options()}")
    raise KeyError(f"{spec!r} matches several sheets: {[m.stem for m in matches]}")


def _from_portfolio(
    pid: int, kind: str, label: str | None, datelabel: str | None = None
) -> pd.DataFrame:
    p = _get_book()[pid]
    if kind == "trades":
        if not p.trades:
            raise KeyError(f"HPC39_{pid} has no trade instructions")
        if label:
            for snap in p.trades:
                if snap.label == label:
                    return snap.data.copy()
            have = [s.label or "(none)" for s in p.trades]
            raise KeyError(f"HPC39_{pid} has no {label!r} snapshot; have {have}")
        return p.latest_trades.copy()

    if kind == "holdings" and datelabel:
        hits = [k for k in p.holdings_blocks if k.startswith(datelabel)]
        if not hits:
            raise KeyError(
                f"HPC39_{pid} has no holdings block for {datelabel!r}; "
                f"have {list(p.holdings_blocks)}"
            )
        return p.holdings_blocks[hits[0]].copy()

    df = getattr(p, kind)
    if df is None:
        raise KeyError(f"HPC39_{pid} has no {kind}")
    return df.copy()


def overview(pid: int) -> pd.DataFrame:
    """Every distinct dataset held for one portfolio - the 'show me all of it' view."""
    p = _get_book()[pid]
    rows: list[dict] = []

    def add(name, df):
        if df is not None and not df.empty:
            cols = ", ".join(map(str, df.columns))
            rows.append({"dataset": name, "rows": len(df), "cols": df.shape[1],
                         "columns": cols if len(cols) <= 70 else cols[:67] + "..."})

    for lbl, blk in p.holdings_blocks.items():
        add(f"holdings @ {lbl}", blk)
    add("holdings_statement", p.holdings_statement)
    add("cash_ledger", p.cash_ledger)
    add("option_ledger", p.option_ledger)
    add("fo_ledger", p.fo_ledger)
    add("backtest", p.backtest)
    for i, snap in enumerate(p.trades):
        add(f"trades[{snap.label or i}]", snap.data)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# where  (filter)
# --------------------------------------------------------------------------- #
def where(df: pd.DataFrame, expr: str) -> pd.DataFrame:
    """Return rows of `df` matching `expr` (conditions joined by ` and `)."""
    if not expr or not expr.strip():
        return df
    mask = pd.Series(True, index=df.index)
    for clause in re.split(r"\s+and\s+", expr.strip(), flags=re.I):
        mask &= _clause_mask(df, clause.strip())
    return df[mask].reset_index(drop=True)


def _resolve_col(df: pd.DataFrame, name: str) -> str:
    name = name.strip().strip("\"'").lower()
    exact = {c.lower(): c for c in df.columns}
    if name in exact:
        return exact[name]
    hits = [c for c in df.columns if c.lower().startswith(name)] or [
        c for c in df.columns if name in c.lower()
    ]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(
        f"column {name!r} not found / ambiguous. Columns: {list(df.columns)}"
    )


def _clause_mask(df: pd.DataFrame, clause: str) -> pd.Series:
    for op, kind in ((r"not\s+in", "notin"), (r"in", "in"), (r"contains", "contains")):
        m = re.match(rf"^(.+?)\s+{op}\s+(.+)$", clause, flags=re.I)
        if m:
            col = _resolve_col(df, m.group(1))
            val = m.group(2).strip().strip("\"'")
            s = df[col].astype(str).str.strip().str.lower()
            if kind == "contains":
                return df[col].astype(str).str.contains(val, case=False, na=False)
            items = [x.strip().lower() for x in val.split(",") if x.strip()]
            return ~s.isin(items) if kind == "notin" else s.isin(items)

    norm = re.sub(r"\s*(>=|<=|!=|==|=|>|<)\s*", r" \1 ", clause).strip()
    parts = norm.split(None, 2)
    if len(parts) < 3:
        raise ValueError(f"can't parse condition {clause!r} - use  column OP value")
    cname, op, raw = parts
    col = _resolve_col(df, cname)
    val = raw.strip().strip("\"'")
    num = pd.to_numeric(pd.Series([val]), errors="coerce").iloc[0]
    numeric_col = pd.to_numeric(df[col], errors="coerce")

    if op in (">", ">=", "<", "<="):
        if pd.isna(num):
            raise ValueError(f"{raw!r} is not a number (needed for {op})")
        return {
            ">": numeric_col > num,
            ">=": numeric_col >= num,
            "<": numeric_col < num,
            "<=": numeric_col <= num,
        }[op]
    if op in ("==", "="):
        if not pd.isna(num):
            return numeric_col == num
        return df[col].astype(str).str.strip().str.lower() == val.lower()
    if op == "!=":
        if not pd.isna(num):
            return numeric_col != num
        return df[col].astype(str).str.strip().str.lower() != val.lower()
    raise ValueError(f"unknown operator {op!r}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _safe(spec: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", spec).strip("_")


def _print_metrics(spec: str) -> int:
    """`--metrics`: portfolio panel, or block panel when the spec carries a date."""
    import calc

    toks = spec.split()
    date = next((t for t in toks if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", t)), None)
    pid = None
    for t in toks:
        m = re.fullmatch(r"(?:hpc39_?)?(\d{1,2})", t, re.I)
        if m and int(m.group(1)) in portfolio_ids():
            pid = int(m.group(1))
            break
    if pid is None:                                  # maybe a holdings-sheet name/number
        pid = _holdings_sheet_pid([t for t in toks if t != date])
    if pid is None:
        print(f"--metrics needs a portfolio (hpc39_5/7/8/10); got {spec!r}")
        return 1
    try:
        panel = calc.block_metrics(pid, date) if date else calc.metrics(pid)
    except KeyError as exc:
        print(exc.args[0])
        return 1
    for k, v in panel.items():
        print(f"  {k:<18} {calc._fmt_value(k, v)}")
    if date:
        print("  (block-level - deposits/withdrawals, hedge_pnl, drawdown, "
              "volatility, benchmark/alpha,\n   sheet_* need the whole portfolio: "
              f"drop the date)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="query.py",
        description="Search, fix and filter the portfolio data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("spec", nargs="*", help="e.g. hpc39_10 holdings  |  performance  |  18")
    ap.add_argument("-w", "--where", default="", help='filter, e.g. "p&l > 0 and action == SELL"')
    ap.add_argument("-s", "--sort", default="", help="sort by this column")
    ap.add_argument("--desc", action="store_true", help="sort descending")
    ap.add_argument("--top", type=int, default=0, help="only the first N rows (after sort)")
    ap.add_argument("--cols", default="", help="comma-separated columns to keep")
    ap.add_argument("--full", action="store_true", help="print every row")
    ap.add_argument("--raw", action="store_true", help="keep near-empty unnamed col_N columns")
    ap.add_argument("--save", action="store_true", help="write result to data/clean/")
    ap.add_argument("-m", "--metrics", action="store_true",
                    help="show the metrics panel for the matched portfolio / dated block")
    args = ap.parse_args(argv)

    spec = " ".join(args.spec).strip()
    if not spec:
        print(options())
        return 0

    if args.metrics:
        return _print_metrics(spec)

    try:
        df = get(spec, tidy=not args.raw)
        if args.where:
            df = where(df, args.where)
        if args.cols:
            keep = [_resolve_col(df, c) for c in args.cols.split(",") if c.strip()]
            df = df[keep]
        if args.sort:
            df = df.sort_values(_resolve_col(df, args.sort), ascending=not args.desc)
        if args.top:
            df = df.head(args.top)
    except (KeyError, ValueError) as exc:
        print(exc)
        return 1

    df = df.reset_index(drop=True)
    with pd.option_context("display.max_rows", None if args.full else 25,
                           "display.width", None, "display.max_columns", None):
        print(df if args.full or len(df) <= 25 else df.head(25))
    print(f"\n{len(df)} rows x {len(df.columns)} cols")
    if not args.full and len(df) > 25:
        print("(showing first 25 - add --full for all)")

    if args.save:
        CLEAN_DIR.mkdir(parents=True, exist_ok=True)
        out = CLEAN_DIR / f"query_{_safe(spec)}.csv"
        df.to_csv(out, index=False)
        print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
