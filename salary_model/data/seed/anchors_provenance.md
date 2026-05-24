# Anchor provenance

Bundled values in `src/salary_model/data/anchors.py` are *not* invented. They are coarse
but realistic anchors derived from publicly published Saudi statistics. This file is the
audit trail; update it whenever you change an anchor.

| Anchor                          | Source                              | URL                                                                                       | As-of   |
|---------------------------------|-------------------------------------|-------------------------------------------------------------------------------------------|---------|
| Region base multipliers         | GASTAT Regional Statistics 2024     | https://www.stats.gov.sa/en                                                                | 2024-Q4 |
| Sector median monthly base wage | GASTAT Labor Market Bulletin 2024-Q3 | https://www.stats.gov.sa/en/814                                                            | 2024-Q3 |
| Sector log-sigma                | Derived from GASTAT LFS quartiles    | https://www.stats.gov.sa/en/814                                                            | 2024    |
| Ownership lifts (PIF / MNC)     | Composite: Mercer TRS KSA + Hays Salary Guide GCC (free editions) + Cooper Fitch GCC | https://www.cooperfitch.ae | 2024 |
| Saudization (Nitaqat) shares    | HRSD Labor Market Statistics         | https://www.hrsd.gov.sa/en/services/labor-market-stats                                     | 2024    |
| Female labor share by family    | GASTAT LFS gender breakdown + ILO    | https://www.stats.gov.sa/en/814  +  https://ilostat.ilo.org                                | 2023-2024 |
| National CPI YoY                | GASTAT CPI release                  | https://www.stats.gov.sa/en/cpi                                                            | 2024 avg |
| SAMA policy rate                | SAMA Monthly Bulletin                | https://www.sama.gov.sa/en-US/EconomicReports/Pages/MonthlyStatistics.aspx                 | 2025-Q1 |
| SAR/USD                         | SAMA (pegged)                        | https://www.sama.gov.sa                                                                    | static  |
| Brent 3M avg                    | World Bank Commodity Markets tracker | https://www.worldbank.org/en/research/commodity-markets                                    | 2024 avg |
| Gender gap residual             | World Bank WDI + ILO KSA factsheet   | https://databank.worldbank.org + https://ilostat.ilo.org                                   | 2023    |

## How the anchors flow into the data

The synthetic generator at `src/salary_model/data/synthetic.py` multiplies these anchors
together to produce a realistic monthly base wage for each observation, then adds
allowances (housing, transport, variable) under the canonical KSA conventions in
`src/salary_model/data/normalize.py`.

If you swap a bundled anchor for a live API result, update the live fetcher in
`src/salary_model/data/sources/` and **keep this table current with the as-of date and
URL** so audit reviews can trace any number end-to-end.
