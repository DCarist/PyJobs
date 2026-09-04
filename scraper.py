import logging
import os
import re
from typing import Any

import pandas as pd
from jobspy import scrape_jobs

logger = logging.getLogger("pyjobs.scraper")

US_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}

REMOTE_KEYWORDS = {"remote", "hybrid", "anywhere", "work from home", "wfh"}


def parse_locations(raw: str) -> tuple[list[str], bool]:
    """Parses a location string into individual physical locations and a remote flag.

    Supports formats like:
      - 'Philadelphia' -> (['Philadelphia'], False)
      - 'Philadelphia, PA' -> (['Philadelphia, PA'], False)
      - 'Philadelphia, PA, Remote' -> (['Philadelphia, PA'], True)
      - 'Philadelphia, PA; New York, NY' -> (['Philadelphia, PA', 'New York, NY'], False)
      - 'Remote' -> ([], True)
    """
    if not raw or not raw.strip():
        return [], False

    # Check for explicit multi-location delimiters first
    if ";" in raw or "|" in raw:
        chunks = re.split(r"[;|]", raw)
    else:
        # Split on commas and reconstruct City, State abbreviations
        raw_chunks = [c.strip() for c in raw.split(",") if c.strip()]
        chunks = []
        i = 0
        while i < len(raw_chunks):
            chunk = raw_chunks[i]
            if i + 1 < len(raw_chunks) and raw_chunks[i + 1].upper() in US_STATES:
                chunks.append(f"{chunk}, {raw_chunks[i + 1].upper()}")
                i += 2
            else:
                chunks.append(chunk)
                i += 1

    locations: list[str] = []
    has_remote = False
    for c in chunks:
        c_clean = c.strip()
        if not c_clean:
            continue
        if c_clean.lower() in REMOTE_KEYWORDS:
            has_remote = True
        else:
            locations.append(c_clean)

    return locations, has_remote


def fetch_jobs(
    search_term: str,
    location: str,
    distance_miles: int = 50,
    results_wanted: int = 20,
    sites: list[str] | None = None,
    is_remote: bool = False,
    proxies: list[str] | str | None = None,
) -> list[dict[str, Any]]:
    """Scrapes jobs across specified sites with multi-location and remote handling."""
    if not sites:
        sites = ["linkedin", "indeed", "google"]

    # Filter to valid supported site names
    valid_sites = {"linkedin", "indeed", "zip_recruiter", "glassdoor", "google"}
    active_sites = [s for s in sites if s in valid_sites]
    if not active_sites:
        active_sites = ["linkedin", "indeed", "google"]

    physical_locations, detected_remote = parse_locations(location)
    effective_remote = is_remote or detected_remote

    # Determine location search targets
    targets: list[tuple[str | None, bool]] = []
    if physical_locations:
        for loc in physical_locations:
            targets.append((loc, effective_remote))
    elif effective_remote:
        # Remote only without specific city
        targets.append((None, True))
    else:
        targets.append((location or None, False))

    proxy_config = proxies or os.environ.get("JOBSPY_PROXIES")

    combined_jobs: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for target_loc, target_remote in targets:
        try:
            jobs_df = scrape_jobs(
                site_name=active_sites,
                search_term=search_term,
                location=target_loc,
                distance=distance_miles,
                is_remote=target_remote,
                results_wanted=results_wanted,
                country_indeed="usa",
                proxies=proxy_config,
            )

            if jobs_df is None or jobs_df.empty:
                continue

            jobs_df = jobs_df.where(pd.notnull(jobs_df), None)

            for _, row in jobs_df.iterrows():
                job_id = str(row.get("id", ""))
                title = str(row.get("title", ""))
                company = str(row.get("company", ""))
                loc = str(row.get("location", ""))

                # Deduplication key across multiple site/location batches
                dedup_key = (
                    job_id if job_id else f"{title.lower()}::{company.lower()}::{loc.lower()}"
                )
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                salary_source = None
                if row.get("min_amount") and row.get("max_amount"):
                    interval = row.get("interval", "yearly")
                    currency = row.get("currency", "USD")
                    salary_source = (
                        f"{currency} {row['min_amount']} - {row['max_amount']} / {interval}"
                    )
                elif row.get("min_amount"):
                    interval = row.get("interval", "yearly")
                    currency = row.get("currency", "USD")
                    salary_source = f"{currency} {row['min_amount']} / {interval}"

                job = {
                    "job_id": job_id,
                    "site": row.get("site", ""),
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary_source": salary_source,
                    "job_url": row.get("job_url", ""),
                    "description": row.get("description", ""),
                    "date_posted": row.get("date_posted"),
                }
                combined_jobs.append(job)

        except Exception as e:
            logger.error(
                "Error scraping location '%s' on sites %s: %s",
                target_loc,
                active_sites,
                e,
            )

    return combined_jobs
