r"""Switch which Google Sheet the dashboard pulls from - without editing files.

Today everything reads from ONE source: `sheet_source.txt` (see
`import_sheet.resolve_source`). This module adds a small *named registry* on
top of that, so you can save more than one sheet (e.g. "Amol ji Trading" and
a brand-new one you're testing), pick one from the Streamlit sidebar, and the
dashboard immediately re-downloads + rebuilds from it and picks up whatever
portfolios that sheet has - no restart, no touching a file by hand.

Registry lives at data/sheet_sources.json:  {"active": <label>, "sources": {label: url}}

Command line
------------
    uv run sheetchange.py                              # list saved sheets, mark the active one
    uv run sheetchange.py add "New Trading" <url>       # save a sheet under a label
    uv run sheetchange.py use "New Trading"             # switch to it + fetch + rebuild
    uv run sheetchange.py use <url>                      # switch straight to a url (auto-fetch)
    uv run sheetchange.py remove "New Trading"          # drop a saved sheet (not the active one)

Python
------
    from sheetchange import add_source, use_source, list_sources, active_label

    add_source("New Trading", "https://docs.google.com/spreadsheets/d/XXXX/edit")
    use_source("New Trading")          # downloads it, rebuilds data/csv/, refreshes portfolios
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import backend
import import_sheet

ROOT = Path(__file__).parent
REGISTRY_FILE = ROOT / "data" / "sheet_sources.json"
SOURCE_FILE = import_sheet.SOURCE_FILE      # sheet_source.txt - what import_sheet.py reads

_HEADER = (
    "# Source for import_sheet.py. First non-comment line is used.\n"
    "# Managed by sheetchange.py - use that instead of hand-editing this file.\n"
)


# --------------------------------------------------------------------------- #
# registry (label -> url), + which one is active
# --------------------------------------------------------------------------- #
def _load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        return {"active": None, "sources": {}}
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active": None, "sources": {}}
    data.setdefault("active", None)
    data.setdefault("sources", {})
    return data


def _save_registry(reg: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _bootstrap() -> dict:
    """First run: register whatever `sheet_source.txt` already points to as
    'Amol ji Trading', so the existing setup shows up as a normal entry."""
    reg = _load_registry()
    if reg["sources"]:
        return reg
    current = import_sheet.resolve_source([])
    if current:
        reg["sources"]["Amol ji Trading"] = current
        reg["active"] = "Amol ji Trading"
        _save_registry(reg)
    return reg


def list_sources() -> dict[str, str]:
    """{label: url} for every saved sheet."""
    return dict(_bootstrap()["sources"])


def active_label() -> str | None:
    return _bootstrap()["active"]


def active_url() -> str | None:
    reg = _bootstrap()
    label = reg["active"]
    return reg["sources"].get(label) if label else import_sheet.resolve_source([])


def add_source(label: str, url: str) -> None:
    """Save a sheet under a label. Doesn't switch to it or fetch anything -
    call `use_source(label)` for that."""
    label, url = label.strip(), url.strip()
    if not label or not url:
        raise ValueError("both a label and a url/id/path are required")
    reg = _bootstrap()
    reg["sources"][label] = url
    _save_registry(reg)


def remove_source(label: str) -> None:
    reg = _bootstrap()
    if label == reg.get("active"):
        raise ValueError(f"{label!r} is the active sheet - switch away from it first")
    reg["sources"].pop(label, None)
    _save_registry(reg)


# --------------------------------------------------------------------------- #
# switching
# --------------------------------------------------------------------------- #
def _write_source_file(url: str) -> None:
    SOURCE_FILE.write_text(f"{_HEADER}\n{url}\n", encoding="utf-8")


def use_source(label_or_url: str, *, fetch: bool = True) -> str:
    """Make `label_or_url` the active sheet: point sheet_source.txt at it,
    (optionally) download + rebuild data/csv/, and refresh the portfolio list
    so newly-added sheets (e.g. a fresh HPC39_11) show up right away.

    `label_or_url` can be a label already saved with `add_source`, or a raw
    url/id/path - in which case it's saved under itself so it shows up in
    `list_sources()` too.

    Returns the resolved url/path that is now active.
    """
    reg = _bootstrap()
    url = reg["sources"].get(label_or_url, label_or_url)
    label = label_or_url if label_or_url in reg["sources"] else url

    _write_source_file(url)
    reg["sources"].setdefault(label, url)
    reg["active"] = label
    _save_registry(reg)

    if fetch:
        import_sheet.run_once(url)
        backend.refresh_portfolio_ids()

    return url


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    if not argv:
        reg = _bootstrap()
        if not reg["sources"]:
            print("No sheets saved yet. Add one:\n  uv run sheetchange.py add <label> <url>")
            return 0
        print("Saved sheets:")
        for label, url in reg["sources"].items():
            mark = "*" if label == reg["active"] else " "
            print(f"  {mark} {label:<20} {url}")
        print("\n* = active (what the dashboard currently pulls from)")
        return 0

    cmd, *rest = argv
    try:
        if cmd == "add":
            if len(rest) < 2:
                print("usage: sheetchange.py add <label> <url>")
                return 1
            add_source(rest[0], " ".join(rest[1:]))
            print(f"saved {rest[0]!r}. Switch to it with:  uv run sheetchange.py use {rest[0]!r}")
        elif cmd == "use":
            if not rest:
                print("usage: sheetchange.py use <label|url>")
                return 1
            print(f"switching to {rest[0]!r} and fetching ...")
            use_source(" ".join(rest))
            print("done - data/csv/ rebuilt, portfolio list refreshed.")
        elif cmd == "remove":
            if not rest:
                print("usage: sheetchange.py remove <label>")
                return 1
            remove_source(rest[0])
            print(f"removed {rest[0]!r}")
        else:
            print(f"unknown command {cmd!r}. Use: add | use | remove (or no args to list)")
            return 1
    except (ValueError, SystemExit) as exc:
        print(f"! {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
