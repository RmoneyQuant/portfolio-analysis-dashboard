r"""Import every sheet from the source workbook into this project as raw CSVs.

Source can be a local .xlsx OR a Google Sheet (URL or bare id). Resolution order:
    1. a command-line argument            uv run import_sheet.py <url|id|path>
    2. the SHEET_SOURCE environment var
    3. the file  ./sheet_source.txt       (first non-comment line)
    4. the default local path below

Google Sheets must be shared "Anyone with the link -> Viewer" for the direct
download to work (it uses the .xlsx export endpoint, no auth, no extra deps).
For a private sheet use a service account instead - see README / ask.

    uv run import_sheet.py                              # use configured source
    uv run import_sheet.py https://docs.google.com/...  # one-off from a URL
    uv run import_sheet.py --loop 30                    # re-import every 30 min

Outputs (all under ./data):
    data/sheet.xlsx           - the downloaded / copied workbook
    data/csv/<NN_name>.csv    - one raw CSV per sheet (no header parsing)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_SOURCE = r"C:\Users\muskan\Downloads\sheet.xlsx"
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CSV_DIR = DATA_DIR / "csv"
LOCAL_XLSX = DATA_DIR / "sheet.xlsx"
SOURCE_FILE = ROOT / "sheet_source.txt"

_GID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def resolve_source(argv: list[str]) -> str:
    for a in argv:
        if not a.startswith("-"):
            return a
    if os.environ.get("SHEET_SOURCE"):
        return os.environ["SHEET_SOURCE"].strip()
    if SOURCE_FILE.exists():
        for line in SOURCE_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return DEFAULT_SOURCE


def sheet_id(source: str) -> str | None:
    """Return a Google Sheets id if `source` is a Sheets URL or a bare id."""
    m = _GID_RE.search(source)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{30,}", source):   # looks like a bare id
        return source
    return None


def fetch_workbook(source: str) -> None:
    """Put the current workbook at LOCAL_XLSX (download from Sheets, or copy a file)."""
    DATA_DIR.mkdir(exist_ok=True)
    gid = sheet_id(source)
    if gid:
        url = f"https://docs.google.com/spreadsheets/d/{gid}/export?format=xlsx"
        print(f"downloading Google Sheet {gid} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (trusted host)
            data = r.read()
        if data[:2] != b"PK":  # xlsx is a zip; HTML back == not shared / wrong id
            raise SystemExit(
                "Download did not return an .xlsx. The sheet is probably not shared "
                "as 'Anyone with the link -> Viewer', or the id is wrong."
            )
        LOCAL_XLSX.write_bytes(data)
        print(f"  saved {len(data):,} bytes -> {LOCAL_XLSX.relative_to(ROOT)}")
        return

    src = Path(source).expanduser()
    if not src.exists():
        raise SystemExit(f"Source not found: {src}")
    shutil.copy2(src, LOCAL_XLSX)
    print(f"copied {src} -> {LOCAL_XLSX.relative_to(ROOT)}")


def export_csvs() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in CSV_DIR.glob("*.csv")}
    written: set[str] = set()

    xl = pd.ExcelFile(LOCAL_XLSX)
    print(f"{len(xl.sheet_names)} sheets\n")
    for i, sheet in enumerate(xl.sheet_names):
        df = xl.parse(sheet, header=None)          # raw grid, nothing dropped
        out = CSV_DIR / f"{i:02d}_{safe(sheet)}.csv"
        df.to_csv(out, index=False, header=False)
        written.add(out.name)
        print(f"  {sheet!r:45} {df.shape[0]:>4} x {df.shape[1]:>2}  -> {out.name}")

    for stale in existing - written:               # sheet renamed/removed upstream
        (CSV_DIR / stale).unlink()
        print(f"  removed stale {stale}")

    print(f"\n{datetime.now():%Y-%m-%d %H:%M}  ->  {len(written)} CSVs in "
          f"{CSV_DIR.relative_to(ROOT)}")


def run_once(source: str) -> None:
    fetch_workbook(source)
    export_csvs()


def main(argv: list[str]) -> None:
    source = resolve_source(argv)
    if "--loop" in argv:
        minutes = float(argv[argv.index("--loop") + 1])
        print(f"loop mode: re-importing every {minutes} min  (Ctrl+C to stop)\n")
        while True:
            try:
                run_once(source)
            except Exception as exc:               # keep the loop alive
                print(f"  ! {exc}")
            time.sleep(minutes * 60)
    else:
        run_once(source)


if __name__ == "__main__":
    main(sys.argv[1:])
