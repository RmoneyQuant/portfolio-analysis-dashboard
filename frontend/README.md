# HPC39 Dashboard — frontend

Next.js 14 (App Router, TypeScript, Tailwind) UI over the portfolio data.
It reads everything from the FastAPI server in [`../api.py`](../api.py).

## Run

**1. Start the API** (from the repo root, needs `uv`):

```bash
uv run uvicorn api:app --reload --port 8000
```

Check it: <http://localhost:8000/api/portfolios> and docs at <http://localhost:8000/docs>.

**2. Start the frontend** (needs Node.js ≥ 18 — install from <https://nodejs.org> if `node -v` fails):

```bash
cd frontend
cp .env.local.example .env.local     # points at http://localhost:8000
npm install
npm run dev
```

Open <http://localhost:3000>.

## Pages

| Route | Shows |
|---|---|
| `/` | All four portfolios + the combined TOTAL row — deposits, withdrawals, invested, value, return, XIRR, CAGR, drawdown |
| `/portfolio/[pid]` | One portfolio: full performance panel, cashflow breakdown, sheet-reported figures, rebalance history, latest holdings, dataset list |
| `/portfolio/[pid]/[date]` | One rebalance block: equity metrics + the per-stock holdings for that date |

`pid` is `5`, `7`, `8`, or `10`. Dates are `YYYY-MM-DD` rebalance keys shown on the portfolio page.

## Data flow

```
Excel sheet ─▶ import_sheet.py ─▶ data/csv/*.csv
                                     │
             backend.py / calc.py / cashflow.py  (clean + compute)
                                     │
                                  api.py  (FastAPI, JSON)
                                     │
                          frontend/ (Next.js, this app)
```

Re-run `uv run import_sheet.py` after the workbook changes; the API recomputes on each request (`cache: "no-store"`).
