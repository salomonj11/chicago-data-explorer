# Chicago Data Explorer

Live civic-data dashboard for the City of Chicago. A **Python / FastAPI** backend queries the [Chicago open data portal](https://data.cityofchicago.org) with SoQL (Socrata's SQL dialect), aggregates the results, and serves a small JSON API consumed by a Chart.js dashboard.

**Live demo:** [chicago-data-explorer.vercel.app](#) <!-- update after deploying -->

## What it shows

- **Reported crime, monthly** — top 5 crime categories over a 6–24 month window, grouped by month server-side and pivoted with pandas
- **Food inspection outcomes** — pass/fail breakdown over 30–180 days
- **Top 311 service requests** — most common request types over 7–90 days

All three panels query real datasets (`ijzp-q8t2`, `4ijn-s7e5`, `v6vf-nfxy`) live, with each card citing its dataset ID.

## Tech stack

- **Python 3.12 + FastAPI** — typed endpoints, query validation, async I/O
- **SoQL** — aggregation is pushed to the data source (`$select … count(*)`, `$group`, `$where`) so the API transfers kilobytes, not megabytes
- **pandas** — pivots the monthly crime data from long to wide format for charting
- **httpx** — async HTTP client
- **Vanilla JS + Chart.js** — no frontend framework; one static page
- **Vercel** — Python serverless function + static hosting

## Architecture decisions

- **Push aggregation upstream.** Rather than downloading raw rows and crunching them in Python, the SoQL queries group and count on Socrata's side. The crime endpoint is the exception: it pulls grouped month × type rows and uses pandas to pivot and rank the top categories — the reshape that SoQL can't express cleanly.
- **In-memory TTL cache (10 min).** City data updates daily; there's no reason to hit the portal on every page load. Cache keys are derived from the full query, so different windows cache independently.
- **Graceful degradation.** Portal outages return a 502 with a readable message; each dashboard card renders its own error state and can be retried independently.
- **No API keys required.** Socrata allows anonymous queries (throttled). An optional `SOCRATA_APP_TOKEN` env var raises the rate limit.

## Project layout

```
api/
├── index.py       # FastAPI app: dashboard at /, plus /api/health, /api/crimes, /api/food-inspections, /api/requests-311
└── dashboard.html # Dashboard page (Chart.js), served by the function itself
vercel.json        # Routes everything to the Python function
requirements.txt
```

## Run locally

```bash
git clone https://github.com/salomonj11/chicago-data-explorer.git
cd chicago-data-explorer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt uvicorn
uvicorn api.index:app --reload
```

Then open `http://127.0.0.1:8000/` for the dashboard — or `http://127.0.0.1:8000/api/crimes?months=6` to hit the API directly.

## Deploy (Vercel)

1. Push this repo to GitHub
2. Import it at [vercel.com/new](https://vercel.com/new) — no environment variables needed
3. Deploy

## License

MIT. Data © City of Chicago.
