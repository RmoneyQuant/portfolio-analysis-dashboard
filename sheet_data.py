"""Load the workbook data for editing / analysis.

    from sheet_data import load, load_sheet, SHEETS

    book = load()                 # dict: sheet name -> DataFrame (raw grid, no header)
    df = load_sheet("Sheet43")    # one sheet, with its real header row parsed
    df = load_sheet("hpc39_5", header=2)   # override which row is the header

Data source is the local copy at data/sheet.xlsx. Run `import_sheet.py`
first to create/refresh it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

XLSX = Path(__file__).parent / "data" / "sheet.xlsx"


def _excel_file() -> pd.ExcelFile:
    if not XLSX.exists():
        raise FileNotFoundError(
            f"{XLSX} not found - run `uv run import_sheet.py` first."
        )
    return pd.ExcelFile(XLSX)


SHEETS: list[str] = _excel_file().sheet_names if XLSX.exists() else []


def load(header: int | None = None) -> dict[str, pd.DataFrame]:
    """Every sheet as a DataFrame. header=None (default) keeps the raw grid."""
    xl = _excel_file()
    return {name: xl.parse(name, header=header) for name in xl.sheet_names}


def load_sheet(name: str, header: int | None = 0) -> pd.DataFrame:
    """A single sheet. Pass header=None for the raw grid, or an int row index."""
    return _excel_file().parse(name, header=header)


if __name__ == "__main__":
    for name, df in load().items():
        print(f"{name!r:45} {df.shape[0]:>4} rows x {df.shape[1]:>2} cols")
