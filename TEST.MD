# Portfolio Performance Analysis

Analyzes a set of hedged equity portfolios (HPC39_5, HPC39_7, HPC39_8,
HPC39_10) — each an **equity basket + a rolling NIFTY PUT hedge** — and
benchmarks them against the **NIFTY 500** index.

Each portfolio has two ledgers:

| Ledger | Tracks | Key columns used |
| --- | --- | --- |
| **Cash ledger** (equity leg) | The equity basket: capital in/out, daily mark-to-market value, running P&L | dr, cr, net, holding, pnl |
| **FO ledger** (hedge leg) | The NIFTY PUT option(s): premium paid, daily option value, running P&L | dr (premium), premium (MTM value), net (P&L) |

---

## Scripts

| Script | Data source | Use |
| --- | --- | --- |
| **portfolio_analysis_gsheet.py** | **Live Google Sheet** (all 4 portfolios) | **Primary.** Run this for current numbers. |
| run_all_portfolios.py | Local CSV snapshots | Runs the 4 local-CSV scripts below. Older data. |
| portfolio_analysis.py | hpc39_10_*.csv | HPC39_10 only, from local CSV |
| portfolio_analysis_hpc39_{5,7,8}.py | hpc39_{5,7,8}_*.csv | One portfolio each, from local CSV |
| verify_all.py | Local CSVs + saved summary CSVs | Independent re-derivation to cross-check the local scripts |
| main.py | Upstox API | Refreshes nifty500_eod.csv (benchmark price history) |

bash
python portfolio_analysis_gsheet.py

Outputs (all regenerated on every run):

portfolio_performance_summary_gsheet.csv — since-inception, all 4 portfolios
portfolio_{monthly,quarterly,yearly}_summary_<PORTFOLIO>_gsheet.csv — per portfolio, per period
portfolio_{monthly,quarterly,yearly}_summary_ALL_gsheet.csv — all portfolios, per period

---

## Which date column is used

Every date-based calculation keys off the ledger's **Value Date** (4th column —
the actual settlement / effective date of a transaction), **not** the 1st-column
posting date (the day the entry was booked, usually T+1).

The loaders read both, then overwrite the working date field with value_date
so all downstream logic uses it automatically. The posting date is retained as
posting_date for reference.

*(The local-CSV scripts still use the posting date. Switching to value date
shifts most dates back ~1 trading day, which slightly changes XIRR/CAGR and can
move a cashflow across a month/quarter boundary in edge cases.)*

---

## Core definitions

For a leg (equity, hedge, or the combined portfolio):

| Term | Definition |
| --- | --- |
| **Cashflow** | A real movement of money in or out of the position, with its date. **Outflow** (money invested) = negative; **inflow** (money returned) = positive. |
| **Net Capital** | Total money actually put in, net of anything taken back out: Σ(outflows) − Σ(inflows) over all cashflows. |
| **Net Profit** | The ledger's own running P&L on the last row (pnl for equity, net for the hedge). Trusted directly rather than re-derived. |
| **Terminal Value** | What the position is worth on the last date. Equity leg: the ledger's own holding value (the real "if I sold today" amount). Hedge leg: the ledger's own premium (option MTM) value. |
| **Days held / Years held** | end_date − start_date in calendar days; years = days / 365. |

### How cashflows are recovered from the ledger

The ledgers repeat the same bill's dr/cr amount on **every row that bill is
active** — those repeats are not separate cashflows. Two methods extract the
real ones:

**net_delta** (used for HPC39_5, HPC39_7, HPC39_10) — a cashflow occurred
  only where the ledger's own running cash balance (net column) actually
  changes between consecutive rows. The change itself is the signed amount.
  Ground truth; robust to every repeat/relabel quirk seen.
**narration_dedup** (used for HPC39_8) — take the first row of each unique
  bill narration; ignore all later repeats. Verified equivalent for that
  ledger.

The **hedge leg** cashflow is always just the **real day-1 premium** (first
row's dr). Later "rolls" into new option series are internal repositioning
that the ledger's own premium/net columns already track continuously — no
fresh cash crosses in/out, so they are not added as cashflows.

---

## Formulas

Notation: cashflows are (dₜ, Cₜ) for t = 1..n (dates and signed amounts),
d₁ = first date, dₙ = last date. TV = Terminal Value, NC = Net Capital,
NP = Net Profit. Day counts use actual calendar days.

### 1. Total Return %

Total Return %  =  Net Profit / Net Capital  ×  100

The simple, un-annualized gain on capital deployed. Period-agnostic — a 25%
total return means the same number whether it took 3 months or 3 years.

### 2. CAGR % (Compound Annual Growth Rate)

                ⎛   TV  ⎞ ^ (365 / days_held)
CAGR %  =  ⎜  ─────  ⎟                        − 1     , ×100
                ⎝   NC  ⎠

The single annual growth rate that turns NC into TV over the period, if it
had compounded smoothly. **Point-to-point** — it uses only the start value, end
value, and elapsed time. It does **not** account for when interim
contributions or withdrawals happened.

If all capital went in on day 1 and nothing moved until the end, CAGR ≈ XIRR.
With mid-life cashflows, CAGR and XIRR diverge (see HPC39_5: CAGR ≈ 2.3%,
  XIRR ≈ 1.9%).
Returned as NaN if NC ≤ 0 or days_held ≤ 0.

### 3. XIRR % (Extended Internal Rate of Return)

The annualized, **money-weighted** rate r that makes the net present value of
all dated cashflows — including the Terminal Value as a final inflow on dₙ —
equal zero:

        n
        ⎲        Cₜ
  0  =  ⎳   ─────────────────
       t=1   (1 + r) ^ (Δₜ / 365)

where Δₜ = (dₜ − d₁) in calendar days, so each cashflow is discounted by how
long it was actually in play. The final term is (dₙ, +TV).

**Solved numerically** (no closed form): Newton–Raphson from an initial guess of
r = 0.10, iterating

r_new  =  r  −  NPV(r) / NPV′(r)

until r stops moving (|Δr| < 1e-10) or 100 iterations. If that doesn't
converge to NPV ≈ 0, it falls back to **bisection** on r ∈ [−0.9999, 10].
XIRR = r × 100.

Why XIRR is the primary metric: it's the only one here that correctly rewards or
penalizes the timing of every deposit and withdrawal. Total Return ignores
time entirely; CAGR ignores interim timing.

 **Short-window caveat.** Annualizing a large gain earned over a few weeks on a
 small capital base produces extreme XIRR/CAGR numbers (e.g. HPC39_10's PUT leg
 at 200%+). These are arithmetically correct but not meaningful as a
 "sustainable rate" — read the combined-portfolio, longer-period figures for
 that.

### 4. Return % per period (monthly / quarterly / yearly)

For a period p with an opening value Vₒ and closing value V_c (the leg's
value at the period boundaries), and the ledger's own running P&L at those
boundaries Pₒ, P_c:

Net Profit (period)  =  P_c − Pₒ            (change in the ledger's own P&L over the window)

Return % (period)    =  Net Profit (period) / Vₒ  ×  100

**Opening value** = the previous period's closing value (or, for the first
  period, the leg's value at its first ledger date).
Period **boundaries are anchored on the cash ledger's own trading dates**
  within each calendar month/quarter/year.
**Return % is suppressed (N/A)** for any period where the PUT position
  expired / reset to ≈ 0 — the opening value then isn't comparable capital, so a
  percentage would be nonsense. Net Profit for that period is still valid.
Periods with fewer than **10 trading days** in the ledger, or that the ledger
  doesn't fully span, are flagged in a **Remark** column as partial — their
  returns aren't comparable to a full period.

### 5. NIFTY 500 Benchmark

A "what if the same money went into the index instead" simulation. It replays
the **combined portfolio's exact dated cashflows** (equity leg cashflows + the
hedge leg's day-1 premium) into NIFTY 500 units:

For each cashflow (dₜ, Cₜ):
    price       = NIFTY 500 close on dₜ  (nearest trading day on/before dₜ)
    Δunits      = −Cₜ / price            (outflow Cₜ<0  → buy units;
                                          inflow  Cₜ>0  → sell units)
    units      += Δunits

Benchmark Terminal Value  =  units_held_at_end  ×  NIFTY 500 close on dₙ
Benchmark Net Capital     =  Σ(outflows) − Σ(inflows)          (same as the portfolio)
Benchmark Net Profit      =  Terminal Value − Net Capital

Then the benchmark's **Total Return %, CAGR %, and XIRR %** are computed with the
exact same formulas above, using the benchmark's own Terminal Value and the same
cashflow dates. This makes the comparison apples-to-apples: identical capital,
identical timing, only the instrument differs.

For the **per-period** benchmark, the portfolio's opening value for that period
is grown by the index's return over the same dates:

Benchmark closing (period)  =  Vₒ  ×  (NIFTY 500 close on period_end / NIFTY 500 close on period_start)

### 6. Combined Hedged Portfolio

Simply the two legs added together:

Net Capital (portfolio)     =  Net Capital (equity)    +  Net Capital (hedge)
Net Profit (portfolio)      =  Net Profit (equity)     +  Net Profit (hedge)
Terminal Value (portfolio)  =  Terminal Value (equity) +  Terminal Value (hedge)

For XIRR, the two legs' cashflow lists are **merged into one chronological
timeline** (plus the combined Terminal Value on the last date) and solved once.

---

## Metric comparison at a glance

| Metric | Annualized? | Accounts for cashflow timing? | Best for |
| --- | --- | --- | --- |
| **Total Return %** | No | No | "How much did I make on my money, total" |
| **CAGR %** | Yes | No (point-to-point) | Comparing periods of different length, when flows are roughly lump-sum |
| **XIRR %** | Yes | **Yes** (money-weighted) | The honest annualized return of a portfolio with deposits/withdrawals |

For these portfolios, **XIRR is the headline number**; CAGR is shown alongside as
a sanity check (they should be close unless interim flows were large and
oddly-timed); Total Return is the raw, time-blind figure.

---

## Output columns

### Since-inception summary (portfolio_performance_summary_gsheet.csv)

Portfolio, Strategy, Net Capital, Terminal Value, Net Profit, Total Return %, CAGR %, XIRR %

Strategy is one of: Hedged Portfolio (Equity+PUT), `Equity Leg Only
(Unhedged), PUT Hedge Leg Only`, NIFTY 500 Benchmark.

### Periodic breakdowns (portfolio_{monthly,quarterly,yearly}_summary_*)

Portfolio, Leg, Period, Start, End, Opening Value, Closing Value, Net Profit, Return %, Remark

Leg is one of: Equity Leg, PUT Hedge Leg, Hedged Portfolio, `NIFTY 500
Benchmark`. Period is YYYY-MM / YYYYQn / YYYY. Return % is N/A where
suppressed; Remark explains partial periods and PUT resets.

---

## Setup

bash
uv sync                      # install deps (pandas, requests, ...)
python portfolio_analysis_gsheet.py
The Google Sheet must be shared as **"Anyone with the link can view"** for the
CSV export URLs to work without authentication. Tab GIDs are hard-coded in
PORTFOLIOS at the top of portfolio_analysis_gsheet.py.

nifty500_eod.csv (benchmark prices) is read locally; refresh it with
python main.py (needs an Upstox API token set in the environment).

---

## How this dashboard's `calc.py` matches the spec above

`calc.metrics(pid)` now computes two tracks that line up with this document:

| this doc | `calc.py` field | definition |
| --- | --- | --- |
| Equity Net Capital | `invested` | \|last `net`\| of the cash ledger |
| Equity Terminal | `equity_value` | last `holding` |
| Equity Net Profit | `equity_pnl` | last `pnl` |
| Equity XIRR / CAGR / Return | `equity_xirr_pct` / `equity_cagr_pct` / `equity_return_pct` | equity cashflows + terminal = `equity_value` |
| PUT Net Capital | `option_premium_paid` | **first** row's dr (day-1 premium) |
| PUT Terminal | `premium_now` | last row's `premium` (MTM) |
| PUT Net Profit | `option_pnl` | last row's `net` (trusted) |
| Hedged Net Capital | `total_capital` | `invested + option_premium_paid` |
| Hedged Terminal | `total_value` | `equity_value + premium_now` |
| Hedged Net Profit | `hedged_pnl` | `equity_pnl + option_pnl` |
| Hedged XIRR / CAGR / Return | `total_xirr_pct` / `total_cagr_pct` / `total_return_pct` | merged equity flows + day-1 premium outflow + terminal = `total_value` |

**Reconciliation (2026-09 data — value_date, per-posting flows, inception-clamped start):**

| | Equity return / XIRR (calc / sheet) | Hedged return / XIRR (calc / sheet) |
| --- | --- | --- |
| HPC39_5  | 5.56/5.56 · **2.15 / 2.16** ✅ | 6.29/6.29 · **1.87 / 1.88** ✅ |
| HPC39_7  | 24.47/24.47 · **12.77 / 12.77** ✅ | 25.24/25.24 · **15.24 / 15.25** ✅ |
| HPC39_8  | 2.04/2.04 · **1.26 / 1.26** ✅ | 5.14/5.14 · **2.60 / 2.61** ✅ |
| HPC39_10 | 0.41/0.40 · **1.92 / 1.92** ✅ | 1.52/1.52 · **7.34 / 7.34** ✅ |

Capital, terminal, Net P&L, Return %, and **XIRR now all reconcile** for every
portfolio (≤ 0.01 pp).

### Now aligned to this spec

- **Value date** drives everything: `_cash_ledger` adds a `flow_date` column
  (`value_date`, falling back to `date`); all cashflow timing, the XIRR/CAGR window,
  and the drawdown window use it.
- **Start = max(first cashflow value date, `date_of_entry`)**. HPC39_5's cash
  ledger carries ~7 months of activity (from 2024-02-09) before its 2024-09-03
  inception; `_flows_from` folds that pre-history into a single opening deposit
  on 2024-09-03 (the ledger `net` balance as of that date). Without this
  HPC39_5's XIRR ran over 943 days instead of 736 → 1.60 % vs the sheet's 2.16 %.
  7/8/10 are unaffected (their first cashflow already is their inception).
- **Cashflow extraction** (`_investor_flows`): one dated flow per **distinct dr/cr
  posting per bill**, on its own value date (a bill's repeated dr/cr rows are
  dropped). If that set doesn't reconcile with the ledger's running `net`
  (rollover bills re-quote the same amount and get double-counted), it **falls
  back to net-delta**. In practice: per-posting for HPC39_5/8/10, net-delta for
  HPC39_7. This puts partial settlements (e.g. HPC39_5's +850,583.33 on
  2025-03-07) on their true date instead of folding them into the next batch.
- **Hedged terminal** = `equity holding + PUT premium (MTM)`; PUT rolls not fed as flows.
- **Hedged Net Capital** = `equity |net| + day-1 PUT premium`.

### Remaining gap — HPC39_5 only

1. **Futures leg** (`hpc39_5 nse fo nifty legder`). Its MTM cash settles through the
   HPC39_5 **cash ledger**, so a few of the equity cashflows we extract are actually
   futures margin, not equity rebalance cash. The spec's "Equity + PUT" model and ours
   both exclude the futures *P&L*, but our equity *flow list* is still slightly
   contaminated. → equity XIRR 1.60 vs 2.16.
2. **Dual settlements.** HPC39_5 re-settles on two bills each cycle (NU + NG),
   13 batches vs 8–9 elsewhere; batch splitting differs slightly from pure net-delta.
3. **Snapshot timing.** HPC39_5 trades the most, so its live-sheet numbers drift most
   between the pasted table and a fresh fetch.