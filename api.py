"""JSON API over the portfolio data - powers the Next.js frontend in ./frontend.

Run:
    uv run uvicorn api:app --reload --port 8000

Endpoints (all under /api):
    GET /api/health
    GET /api/portfolios                      overview of all 4 + TOTAL row
    GET /api/portfolio/{pid}                 metrics + cashflow for one portfolio
    GET /api/portfolio/{pid}/positions       latest per-stock table
    GET /api/portfolio/{pid}/cashflow        deposits / withdrawals / xirr / cagr ...
    GET /api/portfolio/{pid}/blocks          one row per rebalance date
    GET /api/portfolio/{pid}/block/{date}    metrics + holdings for that rebalance
    GET /api/shared/{name}                   a shared sheet (performance, strategy_returns, ...)
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import calc
import cashflow as cashflow_mod
from backend import load, portfolio_ids
from query import overview as portfolio_overview

app = FastAPI(title="HPC39 Portfolio API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# JSON-safe conversion (dates -> iso, NaN -> null, numpy -> python)
# --------------------------------------------------------------------------- #
def clean(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return [clean(r) for r in obj.to_dict(orient="records")]
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if hasattr(obj, "item"):                     # numpy scalar
        v = obj.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    if obj is pd.NaT or (obj is not None and obj != obj):
        return None
    return obj


def _pid(pid: int) -> int:
    if pid not in portfolio_ids():
        raise HTTPException(404, f"portfolio {pid} not found; have {list(portfolio_ids())}")
    return pid


def _totals() -> dict:
    ms = [calc.metrics(p) for p in portfolio_ids()]
    inv = sum(m["invested"] for m in ms)
    pnl = sum(m["total_pnl"] for m in ms)
    dep = sum(m["deposits"] for m in ms)
    wd = sum(m["withdrawals"] for m in ms)
    all_d: list = []
    all_a: list[float] = []
    for p in portfolio_ids():
        d, a = calc.cashflows(p)
        all_d += d
        all_a += a
    wdays = sum(m["invested"] * m["days"] for m in ms) / inv if inv else 0
    ret = pnl / inv if inv else float("nan")
    return {
        "portfolio": "TOTAL",
        "deposits": round(dep, 2),
        "withdrawals": round(wd, 2),
        "invested": round(inv, 2),
        "total_pnl": round(pnl, 2),
        "current_value": round(inv + pnl, 2),
        "return_pct": round(100 * ret, 3),
        "xirr_pct": round(100 * calc.xirr(all_d, all_a), 3),
        "cagr_pct": round(100 * ((1 + ret) ** (365 / wdays) - 1), 3) if wdays else None,
        "max_drawdown_pct": round(
            sum(m["invested"] * m["max_drawdown_pct"] for m in ms) / inv, 3
        ) if inv else None,
    }


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "portfolios": list(portfolio_ids())}


@app.get("/api/portfolios")
def portfolios() -> dict:
    return clean({
        "portfolios": [calc.metrics(p) for p in portfolio_ids()],
        "totals": _totals(),
    })


@app.get("/api/portfolio/{pid}")
def portfolio(pid: int) -> dict:
    _pid(pid)
    return clean({
        "metrics": calc.metrics(pid),
        "cashflow": cashflow_mod.cashflow(pid),
        "overview": portfolio_overview(pid),
    })


@app.get("/api/portfolio/{pid}/positions")
def positions(pid: int) -> list:
    _pid(pid)
    return clean(calc.positions(pid))


@app.get("/api/portfolio/{pid}/cashflow")
def cashflow(pid: int) -> dict:
    _pid(pid)
    return clean(cashflow_mod.cashflow(pid))


@app.get("/api/portfolio/{pid}/blocks")
def blocks(pid: int) -> list:
    _pid(pid)
    return clean(calc.blocks(pid))


@app.get("/api/portfolio/{pid}/block/{block_date}")
def block(pid: int, block_date: str) -> dict:
    _pid(pid)
    try:
        return clean({
            "metrics": calc.block_metrics(pid, block_date),
            "positions": calc.positions(pid, block_date),
        })
    except KeyError as exc:
        raise HTTPException(404, exc.args[0]) from exc


@app.get("/api/shared/{name}")
def shared(name: str) -> list:
    book = load()
    if name not in book.shared:
        raise HTTPException(404, f"no shared sheet {name!r}; have {list(book.shared)}")
    return clean(book.shared[name])
