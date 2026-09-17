"""In-memory data layer for the four HPC39 portfolios.

Loads every sheet from data/csv/, cleans it (via filter.load_clean), and groups
it by portfolio. Nothing is persisted - it all lives in memory for other code
to import.

    from backend import load

    book = load()

    book[10].holdings              # cleaned DataFrame
    book[10].cash_ledger
    book[10].option_ledger
    book[10].fo_ledger             # None unless the portfolio has one
    book[10].backtest
    book[10].trades                # list[TradeSnapshot], every rebalance, oldest first
    book[10].latest_trades         # newest snapshot as a DataFrame
    book[10].meta                  # {'money_allocated': ..., 'rebalance_date': ...}

    book.shared['rebalance_dates']     # cross-portfolio sheets
    book.shared['performance']
    book.summary()                     # one-row-per-portfolio overview
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from filter import CSV_DIR, _parse_dates, load_clean

_PID_RE = re.compile(r"hpc39[_ ]?(\d+)", re.I)


def discover_portfolio_ids(csv_dir: Path = CSV_DIR) -> tuple[int, ...]:
    """Every HPC39_<N> id with at least one CSV in `csv_dir` right now.

    Scanned from the filenames actually on disk rather than hardcoded, so a
    brand-new sheet (e.g. a fresh 'HPC39_11' tab added to the source workbook,
    then pulled in by `import_sheet.export_csvs`) is picked up automatically -
    no code change needed.
    """
    ids = {int(m.group(1)) for f in csv_dir.glob("*.csv") if (m := _PID_RE.search(f.stem))}
    return tuple(sorted(ids))


PORTFOLIO_IDS: tuple[int, ...] = discover_portfolio_ids()


def refresh_portfolio_ids(csv_dir: Path = CSV_DIR) -> tuple[int, ...]:
    """Re-scan `csv_dir` and update the module-level PORTFOLIO_IDS in place.

    Called by `load()`, and by the dashboard right after a fetch, so every
    module that reads `PORTFOLIO_IDS` sees new portfolios without a restart.
    """
    global PORTFOLIO_IDS
    PORTFOLIO_IDS = discover_portfolio_ids(csv_dir)
    return PORTFOLIO_IDS


def portfolio_ids() -> tuple[int, ...]:
    """Live read of PORTFOLIO_IDS. Prefer this over importing the constant
    directly - a plain `from backend import PORTFOLIO_IDS` freezes at whatever
    the list was when that module was first imported."""
    return PORTFOLIO_IDS

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = re.compile(r"_(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)

_SHARED_NAMES = {
    "demo": "demo",
    "pc": "performance",
    "rebalance_dates": "rebalance_dates",
    "sheet43": "strategy_returns",
    "sheet44": "stock_valuation",
}


# --------------------------------------------------------------------------- #
# data classes
# --------------------------------------------------------------------------- #
@dataclass
class TradeSnapshot:
    portfolio: int
    source_sheet: str
    label: str                       # month token from the sheet name, e.g. "jul"
    data: pd.DataFrame

    def __repr__(self) -> str:  # noqa: D105
        return (
            f"TradeSnapshot(portfolio={self.portfolio}, label={self.label!r}, "
            f"rows={len(self.data)}, source={self.source_sheet!r})"
        )


@dataclass
class Portfolio:
    id: int
    holdings: pd.DataFrame | None = None
    holdings_statement: pd.DataFrame | None = None
    holdings_blocks: dict = field(default_factory=dict)   # date -> DataFrame, newest first
    cash_ledger: pd.DataFrame | None = None
    option_ledger: pd.DataFrame | None = None
    fo_ledger: pd.DataFrame | None = None
    backtest: pd.DataFrame | None = None
    trades: list[TradeSnapshot] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def latest_trades(self) -> pd.DataFrame | None:
        return self.trades[-1].data if self.trades else None


@dataclass
class Book:
    portfolios: dict[int, Portfolio]
    shared: dict[str, pd.DataFrame]

    def __getitem__(self, pid: int) -> Portfolio:
        return self.portfolios[pid]

    def __iter__(self):
        return iter(self.portfolios.values())

    def summary(self) -> pd.DataFrame:
        rows = []
        for pid, p in self.portfolios.items():
            rows.append(
                {
                    "portfolio": f"HPC39_{pid}",
                    "holdings": 0 if p.holdings is None else len(p.holdings),
                    "statement": 0
                    if p.holdings_statement is None
                    else len(p.holdings_statement),
                    "cash_ledger": 0 if p.cash_ledger is None else len(p.cash_ledger),
                    "option_ledger": 0
                    if p.option_ledger is None
                    else len(p.option_ledger),
                    "fo_ledger": 0 if p.fo_ledger is None else len(p.fo_ledger),
                    "backtest": 0 if p.backtest is None else len(p.backtest),
                    "trade_snapshots": len(p.trades),
                    "money_allocated": p.meta.get("money_allocated"),
                    "rebalance_date": p.meta.get("rebalance_date"),
                    "next_rebalance": p.meta.get("next_rebalance_date"),
                }
            )
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# classification helpers
# --------------------------------------------------------------------------- #
def _portfolio_of(stem: str) -> int | None:
    m = _PID_RE.search(stem)
    return int(m.group(1)) if m else None


def _classify(stem: str) -> str:
    s = stem.lower().replace(" ", "_")
    if "backtest" in s:
        return "backtest"
    if "cash_ledger" in s:
        return "cash_ledger"
    if "nifty_legder" in s or "nifty_ledger" in s:
        return "fo_ledger"
    if "option" in s or "nse_fo" in s:
        return "option_ledger"
    if "trade_instruction" in s or "tradinginstruction" in s:
        return "trades"
    return "holdings"


def _month_label(stem: str) -> str:
    m = _MONTH_RE.search(stem)
    return m.group(1).lower() if m else ""


def _sheet_index(path: Path) -> int:
    head = path.stem.split("_", 1)[0]
    return int(head) if head.isdigit() else 0


def _shared_key(stem: str) -> str:
    base = re.sub(r"^\d+_", "", stem).lower()
    return _SHARED_NAMES.get(base, base)


def _looks_datish(name: str) -> bool:
    return bool(re.search(r"\d", name)) and any(c in name for c in "-:/")


# --------------------------------------------------------------------------- #
# per-sheet cleaning
# --------------------------------------------------------------------------- #
_LEDGER_HEAD = ("date", "narration", "bill_no", "value_date")
_LEDGER_KINDS = ("cash_ledger", "fo_ledger", "option_ledger", "backtest")


def _clean_named(path: Path, kind: str):
    """Return the cleaned DataFrame, or (main, side_table) for holdings sheets."""
    df = load_clean(path)

    if kind in ("holdings", "trades") and len(df.columns):
        first = df.columns[0]
        if first in ("col_0", "date") or _looks_datish(first):
            df = df.rename(columns={first: "symbol"})
        if "symbol" in df.columns:
            sym = df["symbol"].astype(str).str.strip()
            df = df[df["symbol"].notna() & (sym != "") & (sym.str.lower() != "nan")]

    if kind in _LEDGER_KINDS:
        df = _normalise_ledger(df)

    if kind == "holdings":
        extra = [c for c in df.columns if re.fullmatch(r"col_\d+", str(c))]
        statement = _tidy_statement(df[extra]) if extra else None
        blocks = _holdings_blocks(path)
        latest = (
            next(iter(blocks.values()))
            if blocks
            else df.drop(columns=extra).reset_index(drop=True)
        )
        return latest, statement, blocks

    return df.reset_index(drop=True)


_HOLDING_BLOCK_COLS = [
    "symbol", "qty", "buying_rate", "changed_qty",
    "amount_at_entry", "actual_price", "amount_by_m2m", "p&l",
]


def _holdings_blocks(path: Path) -> dict[str, pd.DataFrame]:
    """Split a holdings sheet into its dated rebalance blocks (newest first).

    Each block starts on a row whose 2nd cell is 'Qty' and 1st cell is a date;
    it ends at the next such header or the next section divider
    ('Total cash to be allocated' / 'Target rebalance date').
    """
    raw = pd.read_csv(path, header=None, dtype=str)
    starts: list[tuple[int, str]] = []
    dividers: list[int] = []
    for i, r in raw.iterrows():
        c0 = "" if pd.isna(r.get(0)) else str(r[0]).strip()
        c1 = "" if pd.isna(r.get(1)) else str(r[1]).strip()
        if c1.lower() == "qty" and pd.notna(pd.to_datetime(c0, errors="coerce")):
            starts.append((i, pd.to_datetime(c0).date().isoformat()))
        elif re.match(r"(total cash to be allocated|target rebalance date)", c0, re.I):
            dividers.append(i)

    boundaries = sorted({s[0] for s in starts} | set(dividers) | {len(raw)})

    blocks: dict[str, pd.DataFrame] = {}
    for row, label in starts:
        end = next(b for b in boundaries if b > row)
        chunk = raw.iloc[row + 1 : end, :8].copy()
        chunk.columns = _HOLDING_BLOCK_COLS
        chunk["symbol"] = chunk["symbol"].astype(str).str.strip()
        chunk = chunk[
            chunk["symbol"].ne("")
            & chunk["symbol"].str.lower().ne("nan")
            & ~chunk["symbol"].str.contains(r"\d{4}-\d\d-\d\d", na=False)
        ]
        for c in _HOLDING_BLOCK_COLS[1:]:
            chunk[c] = pd.to_numeric(
                chunk[c].astype(str).str.replace(",", "", regex=False), errors="coerce"
            )
        chunk = chunk.dropna(subset=_HOLDING_BLOCK_COLS[1:], how="all")
        if not chunk.empty:
            blocks[label] = chunk.reset_index(drop=True)

    return dict(sorted(blocks.items(), reverse=True))


_STATEMENT_SCHEMAS = {
    8: ["client_code", "holder", "scrip_code", "symbol", "isin", "qty", "close_rate", "value"],
    6: ["scrip_code", "symbol", "isin", "qty", "close_rate", "value"],
}


def _dedupe(names: list[str]) -> list[str]:
    out, seen = [], {}
    for j, raw in enumerate(names):
        name = str(raw).strip().lower().replace(" ", "_").replace(".", "_")
        if not name or name == "nan":
            name = f"col_{j}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _tidy_statement(sub: pd.DataFrame) -> pd.DataFrame | None:
    """Clean the broker holdings-statement block that sits beside some sheets."""
    sub = sub.dropna(axis=0, how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if sub.empty:
        return None

    hints = {"client", "scrip", "isin", "close", "rate", "symbol", "stock",
             "name", "value", "qty", "variance", "code"}
    row0 = " ".join(str(v) for v in sub.iloc[0]).lower()
    is_header = sum(h in row0 for h in hints) >= 3
    if is_header:
        # the statement is exactly the columns the embedded header names
        keep = [
            j for j, v in enumerate(sub.iloc[0])
            if str(v).strip() and str(v).strip().lower() != "nan"
        ]
        sub = sub.iloc[:, keep]
        sub.columns = _dedupe(list(sub.iloc[0]))
        sub = sub.iloc[1:].reset_index(drop=True)
    elif sub.shape[1] in _STATEMENT_SCHEMAS:
        sub.columns = _STATEMENT_SCHEMAS[sub.shape[1]]
    else:
        sub.columns = [f"col_{j}" for j in range(sub.shape[1])]

    for j in range(sub.shape[1]):
        col = sub.iloc[:, j].astype(str).str.replace(",", "", regex=False)
        conv = pd.to_numeric(col, errors="coerce")
        if conv.notna().mean() > 0.8:
            sub[sub.columns[j]] = conv
    return sub.dropna(axis=0, how="all").reset_index(drop=True)


def _normalise_ledger(df: pd.DataFrame) -> pd.DataFrame:
    """Give the ledger/backtest sheets a consistent schema.

    Their first columns (date / narration / bill no / value date) are often
    blank-headed and land as col_0..col_3; 'dr.1' is really the credit column;
    'premimum'/'preminum' are typos for premium.
    """
    ren: dict[str, str] = {}
    for i, name in enumerate(_LEDGER_HEAD):
        c = f"col_{i}"
        if c in df.columns and name not in df.columns:
            ren[c] = name
    if "dr_1" in df.columns and "cr" not in df.columns:
        ren["dr_1"] = "cr"
    for typo in ("premimum", "preminum"):
        if typo in df.columns:
            ren[typo] = "premium"
    df = df.rename(columns=ren)

    for c in ("date", "value_date"):
        if c in df.columns and not pd.api.types.is_datetime64_any_dtype(df[c]):
            parsed = _parse_dates(df[c].astype(str).str.strip())
            if parsed.notna().mean() >= 0.7:
                df[c] = parsed.dt.date
    return df


def _extract_meta(path: Path, kind: str) -> dict:
    """Pull the metadata cells above the header of a holdings sheet.

    money_allocated       'Total cash to be allocated'
    rebalance_date        'Rebalance Date'          - the current block's date
    next_rebalance_date   'Target rebalance date'   - the upcoming rebalance
    """
    meta: dict = {}
    try:
        raw = pd.read_csv(path, header=None, dtype=str, nrows=4).fillna("")
    except Exception:
        return meta
    flat = [str(v).strip() for v in raw.to_numpy().ravel() if str(v).strip()]
    for i, cell in enumerate(flat[:-1]):
        low = cell.lower()
        nxt = flat[i + 1]
        if ("cash to be allocated" in low or "money allocated" in low) and "money_allocated" not in meta:
            num = pd.to_numeric(nxt.replace(",", ""), errors="coerce")
            if pd.notna(num):
                meta["money_allocated"] = float(num)
        if low == "rebalance date" and "rebalance_date" not in meta:
            dt = pd.to_datetime(nxt, errors="coerce")
            if pd.notna(dt):
                meta["rebalance_date"] = dt.date()
        if low == "target rebalance date" and "next_rebalance_date" not in meta:
            dt = pd.to_datetime(nxt, errors="coerce")
            if pd.notna(dt):
                meta["next_rebalance_date"] = dt.date()
    return meta


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def load(csv_dir: Path = CSV_DIR) -> Book:
    ids = refresh_portfolio_ids(csv_dir)          # pick up any newly added sheet
    portfolios = {pid: Portfolio(pid) for pid in ids}
    shared: dict[str, pd.DataFrame] = {}

    for path in sorted(csv_dir.glob("*.csv"), key=_sheet_index):
        pid = _portfolio_of(path.stem)
        if pid not in ids:
            shared[_shared_key(path.stem)] = load_clean(path)
            continue

        kind = _classify(path.stem)
        p = portfolios[pid]
        cleaned = _clean_named(path, kind)

        if kind == "holdings":
            p.holdings, p.holdings_statement, p.holdings_blocks = cleaned
        elif kind == "trades":
            p.trades.append(
                TradeSnapshot(pid, path.stem, _month_label(path.stem), cleaned)
            )
        else:
            setattr(p, kind, cleaned)

        p.meta.update(_extract_meta(path, kind))

    for p in portfolios.values():
        p.trades.sort(
            key=lambda t: (_MONTHS.get(t.label, 0), _sheet_index(Path(t.source_sheet)))
        )

    return Book(portfolios, shared)


if __name__ == "__main__":
    book = load()
    print(book.summary().to_string(index=False))
    print("\nshared sheets:", list(book.shared))
    for p in book:
        labels = [t.label or "(none)" for t in p.trades]
        print(f"  HPC39_{p.id}: trade snapshots -> {labels}")
