# Manual download targets

These reports are **gated** (form submission, email gate, or paid subscription) so the
fetch script can't pull them in CI. Download manually into `data/reports/<source>/<year>/`
when needed for triangulation.

## Free, gated (form / email submission)

| Source | Report | Form URL | Drop into |
|---|---|---|---|
| Cooper Fitch | KSA Salary Guide 2026 | https://cooperfitch.ae/2026-ksa-salary-guide/ | `data/reports/cooper_fitch/2026/` |
| Hays Middle East | Saudi Arabia Salary Guide 2026 | https://www.hays.ae/salary-guide | `data/reports/hays/2026/` |
| Hays Middle East | GCC Salary Guide 2026 (KSA chapter) | https://www.hays.ae/salary-guide | `data/reports/hays/2026/` |
| Robert Walters | Middle East Salary Survey 2026 (KSA section) | https://www.robertwalters.ae/our-services/saudi-arabia-salary-survey.html | `data/reports/robert_walters/2026/` |
| Michael Page | KSA Salary Guide 2026 | https://www.michaelpage.ae/advice/insights/salary-guides/1000 | `data/reports/michael_page/2026/` |
| PwC Middle East | Hopes & Fears 2025 — KSA Findings | https://www.pwc.com/m1/en/issues/upskilling/hopes-and-fears-2025/hopes-and-fears-ksa-2025.html | `data/reports/pwc/2025/` |
| Deloitte ME | Middle East Human Capital Trends 2025 (KSA cut) | https://www.deloitte.com/middle-east/en/services/consulting/collections/middle-east-human-capital-trends-2025.html | `data/reports/deloitte/2025/` |
| GulfTalent | Employment & Salary Trends in the Gulf (last public 2016) | https://www.gulftalent.com/resources/market-research-reports | `data/reports/gulf_talent/2016/` |
| Heidrick & Struggles | Board Monitor Saudi Arabia 2023 | https://www.heidrick.com/en/insights/boards-governance/boards-in-saudi-arabia-upping-their-game-for-growth | `data/reports/heidrick/2023/` |
| Mercer | KSA Executive & Board Remuneration Insights | https://www.mercer.com/en-sa/insights/total-rewards/saudi-arabia-executive-and-board-remuneration-insights/ | `data/reports/mercer/2024/` |
| BCG | Decoding Global Talent 2024 (KSA chapter) | https://www.bcg.com — search "Decoding Global Talent 2024" | `data/reports/bcg/2024/` |
| McKinsey (MGI) | Saudi Arabia Beyond Oil; Saudi Arabia's Next Generation | https://www.mckinsey.com/featured-insights/employment-and-growth/moving-saudi-arabias-economy-beyond-oil | `data/reports/mckinsey/2015/` |
| Oliver Wyman | KSA GenAI Workforce notes 2024 | https://www.oliverwyman.com/our-expertise/insights/2024/sep/how-ksa-is-using-generative-ai-to-transform-its-economy.html | `data/reports/oliver_wyman/2024/` |
| Roland Berger | The Rise of Entrepreneurship in Saudi Arabia | https://www.rolandberger.com/en/Insights/Publications/The-Rise-of-Entrepreneurship-in-Saudi-Arabia-A-Transformative-Landscape.html | `data/reports/roland_berger/2023/` |
| Adecco KSA | Workforce Evolution article series | https://www.adecco.com/en-sa/resources/article/saudi-arabias-workforce-evolution | `data/reports/adecco/2025/` |

## Paid / licensed (do NOT download without a contract)

| Source | Report | Why we mention it |
|---|---|---|
| Mercer | KSA Total Remuneration Survey (TRS) | Best benchmark; license required |
| PwC Middle East | PayWell Salary Report | Paid; complements Mercer |
| Aon (Radford McLagan) | Salary Increase & Turnover Study (KSA) | Paid |
| WTW | Salary Budget Planning Report (KSA) | Paid |
| Oxford Economics | Saudi Arabia Country Economic Forecast | Paid |
| S&P Global | Riyad Bank Saudi Arabia PMI (raw data) | Paid; free monthly press release only |
| Korn Ferry | Hay Group / Korn Ferry Pay | Paid |

## What the salary model does with these

For free PDFs that are placed into `data/reports/<source>/<year>/`, the v1 ingestion
path will parse extracted tables into the canonical `salary_observations` schema with
`source = "<source>_survey"` and a confidence prior tuned per source:

| source family | confidence prior |
|---|---|
| Hays / Cooper Fitch / Robert Walters / Michael Page bands | 0.75 |
| Mercer TRS (when licensed) | 0.92 |
| PwC Hopes & Fears (sentiment, not pay) | feature only, not target |
| Korn Ferry Workforce 2025 (sentiment) | feature only, not target |

PDF parsing is **not yet implemented** — the data layer's GOSI/Mercer/employee-survey
loader scaffolds in `data/sources/` are the integration point. When a PDF is dropped
here, add a parser that converts its tables to `salary_observations` rows and run
`make data` + `make iterate`. Citation per the publisher's terms is required when the
model attributes a number to a source.
