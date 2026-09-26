# Preview-export price and session evidence

Retrieved on 2026-09-24.

- `ind_close_all_07012020.csv`: NSE daily index close file from
  https://nsearchives.nseindia.com/content/indices/ind_close_all_07012020.csv
  (also checked at the `archives.nseindia.com` hostname). Nifty 500 on 2020-01-07
  closed at 9805.4. This fills a day absent from both the stored data and a fresh
  Kite response. Stored in SQLite with source `NSE_ARCHIVE`, not as a synthetic
  zero return or an interpolated price.
- `nifty500-yahoo-20200107.json`: independent Yahoo chart response, retained as
  corroboration only. Its unadjusted close rounds to 9805.4. It was not ingested.
  URL: https://query1.finance.yahoo.com/v8/finance/chart/%5ECRSLDX?period1=1578268800&period2=1578528000&interval=1d

Both benchmark series were refreshed from Kite for 2016-01-01 through 2026-09-24.
Saved live Dual Momentum holdings were refreshed for 2026-07-20 through 2026-08-11.
No strategy or rebalance run was created by those price fetches.

Session evidence is encoded in `app/data/session_evidence.py` from NSE cash-market
circulars CMTR71775 (2026 holiday list), CMTR72260 (January 15 holiday), and
CMTR72349 (February 1 special live session). Source URLs and the independent
expected session dates are embedded in exported live manifests. Evidence is
explicitly bounded to 2026-01-01 through 2026-09-24; it does not assert completeness
for earlier years or later dates.
