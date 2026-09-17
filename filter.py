"""Fix + filter data from the sheets imported into data/csv/.

Search a sheet by (part of) its name, clean it up, optionally filter rows,
and save the result to data/clean/.

Command line:
    uv run filter.py                       # prompts for a sheet name
    uv run filter.py hpc39_10 cash ledger  # search terms as arguments
    uv run filter.py 18                     # the leading number works too

In code:
    from filter import search, load_clean, filter_rows

    path = search("hpc39_10 cash ledger")[0]
    df   = load_clean(path)
    df   = filter_rows(df, date_col="date", date_from="2026-08-01")
    df   = filter_rows(df, column="cr", min_val=1)          # only credit entries
    df   = filter_rows(df, column="narration", contains="NG6145")
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
CSV_DIR = ROOT / "data" / "csv"
CLEAN_DIR = ROOT / "data" / "clean"


# --------------------------------------------------------------------------- #
# find a sheet by name
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def search(query: str = "") -> list[Path]:
    """CSV files whose name contains every whitespace-separated term in `query`."""
    files = sorted(CSV_DIR.glob("*.csv"))
    terms = [_norm(t) for t in query.split() if t.strip()]
    if not terms:
        return files
    return [f for f in files if all(t in _norm(f.stem) for t in terms)]


# --------------------------------------------------------------------------- #
# fix / clean one sheet
# --------------------------------------------------------------------------- #
def _looks_numeric(v: str) -> bool:
    try:
        float(str(v).replace(",", "").replace("%", ""))
        return True
    except ValueError:
        return False


def _detect_header_row(path: Path, max_scan: int = 20) -> int:
    """Guess which row holds the column names (metadata rows often sit above it)."""
    raw = pd.read_csv(path, header=None, dtype=str, nrows=max_scan)
    best_row, best_score = 0, -1.0
    for i in range(len(raw)):
        cells = [str(v).strip() for v in raw.iloc[i] if pd.notna(v) and str(v).strip()]
        if len(cells) < 2:
            continue
        text_cells = sum(1 for c in cells if not _looks_numeric(c))
        score = text_cells - 0.25 * i          # prefer text-heavy, earlier rows
        if score > best_score:
            best_row, best_score = i, score
    return best_row


def load_clean(path: str | Path, header_row: int | None = None) -> pd.DataFrame:
    """Read a sheet CSV and tidy it up.

    - drops metadata rows above the real header (auto-detected, or pass header_row)
    - drops fully empty rows and columns, and leftover 'Unnamed' columns
    - normalises column names to snake_case
    - parses *date* columns to real dates
    - converts mostly-numeric text columns to numbers
    """
    path = Path(path)
    hdr = _detect_header_row(path) if header_row is None else header_row

    df = pd.read_csv(path, header=hdr, dtype=str, keep_default_na=True)
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")

    df.columns = [
        str(c).strip().lower().replace(" ", "_").replace(".", "_")
        for c in df.columns
    ]
    # Rename blank/"unnamed" headers instead of dropping them - the column may
    # still hold data (common when the sheet's first columns have no header).
    # Empty ones were already removed by the dropna(axis=1) above.
    df.columns = [
        f"col_{i}" if (c.startswith("unnamed") or c in ("", "nan")) else c
        for i, c in enumerate(df.columns)
    ]

    for col in df.columns:
        series = df[col].astype(str).str.strip()
        if "date" in col:
            dates = _parse_dates(series)
            if dates.notna().mean() >= 0.7:        # column really is dates
                df[col] = dates.dt.date
                continue
            # otherwise it's a mislabelled column (e.g. "index_price_on_entry_date")
            # - fall through and treat it as numeric
        conv = pd.to_numeric(series.str.replace(",", "", regex=False), errors="coerce")
        if conv.notna().mean() >= 0.8:          # column is essentially numeric
            df[col] = conv

    return df.reset_index(drop=True)


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse ISO (YYYY-MM-DD...) values, then retry the leftovers as day-first."""
    iso = pd.to_datetime(series, errors="coerce", format="ISO8601")
    missing = iso.isna() & series.ne("") & series.str.lower().ne("nan")
    if missing.any():
        with warnings.catch_warnings():
            # the leftovers are the messy dd-mm-yyyy rows; per-element parsing is fine
            warnings.simplefilter("ignore", UserWarning)
            dmy = pd.to_datetime(series[missing], errors="coerce", dayfirst=True)
        iso = iso.copy()
        iso.loc[missing] = dmy
    return iso


# --------------------------------------------------------------------------- #
# filter rows
# --------------------------------------------------------------------------- #
def filter_rows(
    df: pd.DataFrame,
    *,
    column: str | None = None,
    equals=None,
    contains: str | None = None,
    min_val=None,
    max_val=None,
    date_col: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    dropna_in: str | list[str] | None = None,
) -> pd.DataFrame:
    """Return the subset of `df` matching whichever conditions are given."""
    out = df

    if column is not None:
        if equals is not None:
            out = out[out[column] == equals]
        if contains is not None:
            out = out[out[column].astype(str).str.contains(contains, case=False, na=False)]
        if min_val is not None:
            out = out[pd.to_numeric(out[column], errors="coerce") >= min_val]
        if max_val is not None:
            out = out[pd.to_numeric(out[column], errors="coerce") <= max_val]

    if date_col is not None:
        as_dt = pd.to_datetime(out[date_col], errors="coerce")
        if date_from is not None:
            out = out[as_dt >= pd.to_datetime(date_from)]
        if date_to is not None:
            as_dt = pd.to_datetime(out[date_col], errors="coerce")
            out = out[as_dt <= pd.to_datetime(date_to)]

    if dropna_in is not None:
        cols = [dropna_in] if isinstance(dropna_in, str) else dropna_in
        out = out.dropna(subset=cols)

    return out.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _choose(matches: list[Path]) -> Path | None:
    if not matches:
        print("No sheet matches that name. Available sheets:")
        for f in sorted(CSV_DIR.glob("*.csv")):
            print(f"  {f.stem}")
        return None
    if len(matches) == 1:
        return matches[0]
    print("Multiple matches:")
    for i, f in enumerate(matches):
        print(f"  [{i}] {f.stem}")
    pick = input("Pick a number: ").strip() or "0"
    try:
        return matches[int(pick)]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return None


def main(argv: list[str]) -> None:
    query = " ".join(argv) or input("Sheet name to search: ").strip()
    path = _choose(search(query))
    if path is None:
        return

    print(f"\nLoading {path.name} ...")
    df = load_clean(path)
    print(df.head(15).to_string())
    print(f"\n{len(df)} rows x {len(df.columns)} cols")
    print("columns:", list(df.columns))

    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out = CLEAN_DIR / path.name
    df.to_csv(out, index=False)
    print(f"\nCleaned sheet saved -> {out.relative_to(ROOT)}")
    print("Edit filter_rows(...) in filter.py to narrow it further.")


if __name__ == "__main__":
    main(sys.argv[1:])
