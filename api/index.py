"""Chicago Data Explorer — FastAPI backend.

Queries the City of Chicago's open data portal (Socrata) with SoQL,
aggregates results (server-side where possible, pandas where reshaping
is needed), and serves a small JSON API consumed by the dashboard.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

SOCRATA_BASE = "https://data.cityofchicago.org/resource"

# Real dataset IDs from data.cityofchicago.org
DATASETS = {
    "food_inspections": "4ijn-s7e5",
    "crimes": "ijzp-q8t2",
    "requests_311": "v6vf-nfxy",
}

CACHE_TTL_SECONDS = 600  # 10 minutes
_cache: dict[str, tuple[float, Any]] = {}

app = FastAPI(title="Chicago Data Explorer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time() + CACHE_TTL_SECONDS, value)


async def soql(dataset: str, params: dict[str, str]) -> list[dict]:
    """Run a SoQL query against a Socrata dataset with caching."""
    cache_key = dataset + "|" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    headers = {}
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token

    url = f"{SOCRATA_BASE}/{dataset}.json"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach the Chicago data portal: {exc}") from exc

    if res.status_code != 200:
        raise HTTPException(502, f"Data portal error ({res.status_code}): {res.text[:200]}")

    data = res.json()
    _cache_set(cache_key, data)
    return data


def _iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT00:00:00")


@app.get("/", include_in_schema=False)
async def dashboard() -> HTMLResponse:
    """Serve the dashboard page from the function itself.

    Serving the HTML from FastAPI (rather than relying on platform
    static-file routing) keeps the deployment to a single, predictable
    entry point.
    """
    page = Path(__file__).parent / "dashboard.html"
    if not page.exists():
        raise HTTPException(500, "dashboard.html is missing from the deployment bundle")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "datasets": DATASETS}


@app.get("/api/food-inspections")
async def food_inspections(days: int = Query(90, ge=7, le=365)) -> dict:
    """Inspection outcomes and most-inspected facility types over a window."""
    since = _iso_days_ago(days)

    results = await soql(
        DATASETS["food_inspections"],
        {
            "$select": "results, count(*) as count",
            "$where": f"inspection_date > '{since}'",
            "$group": "results",
            "$order": "count DESC",
        },
    )
    facilities = await soql(
        DATASETS["food_inspections"],
        {
            "$select": "facility_type, count(*) as count",
            "$where": f"inspection_date > '{since}' AND facility_type IS NOT NULL",
            "$group": "facility_type",
            "$order": "count DESC",
            "$limit": "8",
        },
    )

    total = sum(int(r["count"]) for r in results)
    return {
        "window_days": days,
        "total_inspections": total,
        "outcomes": [{"label": r.get("results") or "Unknown", "count": int(r["count"])} for r in results],
        "top_facility_types": [
            {"label": f["facility_type"].title(), "count": int(f["count"])} for f in facilities
        ],
    }


@app.get("/api/crimes")
async def crimes(months: int = Query(6, ge=2, le=24)) -> dict:
    """Monthly counts for the most-reported crime types, pivoted with pandas."""
    since = _iso_days_ago(months * 30)

    rows = await soql(
        DATASETS["crimes"],
        {
            "$select": "date_trunc_ym(date) as month, primary_type, count(*) as count",
            "$where": f"date > '{since}'",
            "$group": "month, primary_type",
            "$order": "month",
            "$limit": "5000",
        },
    )
    if not rows:
        return {"window_months": months, "months": [], "series": []}

    df = pd.DataFrame(rows)
    df["count"] = df["count"].astype(int)

    top_types = (
        df.groupby("primary_type")["count"].sum().sort_values(ascending=False).head(5).index
    )
    pivot = (
        df[df["primary_type"].isin(top_types)]
        .pivot_table(index="month", columns="primary_type", values="count", fill_value=0)
        .sort_index()
        .astype(int)
    )

    return {
        "window_months": months,
        "months": [m[:7] for m in pivot.index.tolist()],
        "series": [
            {"label": crime_type.title(), "data": pivot[crime_type].tolist()}
            for crime_type in pivot.columns
        ],
    }


@app.get("/api/requests-311")
async def requests_311(days: int = Query(30, ge=7, le=180)) -> dict:
    """Most common 311 service request types over a window."""
    since = _iso_days_ago(days)

    rows = await soql(
        DATASETS["requests_311"],
        {
            "$select": "sr_type, count(*) as count",
            "$where": f"created_date > '{since}'",
            "$group": "sr_type",
            "$order": "count DESC",
            "$limit": "10",
        },
    )

    total = sum(int(r["count"]) for r in rows)
    return {
        "window_days": days,
        "total_requests": total,
        "top_types": [{"label": r["sr_type"], "count": int(r["count"])} for r in rows],
    }
