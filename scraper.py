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

# Extensible Seniority Taxonomy Rules (Evaluated in priority order)
SENIORITY_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "Executive / VP",
        re.compile(
            r"\b(vp|vice president|chief|cto|cio|cso|cpo|ceo|c-level|head of)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Director",
        re.compile(r"\b(director|dir\.?)\b", re.IGNORECASE),
    ),
    (
        "Manager",
        re.compile(
            r"\b(manager|mgr\.?|engineering manager|qa manager|product manager)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Supervisor / Lead",
        re.compile(
            r"\b(supervisor|team lead|tech lead|leader|lead)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Senior / Principal",
        re.compile(
            r"\b(senior|sr\.?|principal|staff|architect)\b",
            re.IGNORECASE,
        ),
    ),
]
DEFAULT_SENIORITY = "Specialist / Contributor"


def classify_seniority(title: str) -> str:
    """Classifies a job title into an extensible seniority tier."""
    if not title:
        return DEFAULT_SENIORITY
    for tier, pattern in SENIORITY_RULES:
        if pattern.search(title):
            return tier
    return DEFAULT_SENIORITY


SALARY_BRACKETS = [
    "< $80k",
    "$80k - $120k",
    "$120k - $160k",
    "$160k - $200k",
    "$200k+",
    "Unspecified",
]


def categorize_salary(
    min_amount: float | None,
    max_amount: float | None,
    interval: str | None = "yearly",
) -> tuple[float | None, float | None, str, str]:
    """Annualizes raw salary amounts and assigns a standardized salary bracket.

    NOTE FOR FUTURE ANALYTICS:
    Tracking historical min_salary, max_salary, interval, and date_posted week-to-week
    enables wage trend modeling and offer comparison across similar roles during interviews.
    """
    if min_amount is None and max_amount is None:
        return None, None, interval or "yearly", "Unspecified"

    multiplier = 1.0
    intv = (interval or "yearly").lower()
    if "hour" in intv:
        multiplier = 2080.0
    elif "month" in intv:
        multiplier = 12.0
    elif "week" in intv:
        multiplier = 52.0
    elif "day" in intv:
        multiplier = 260.0

    annual_min = float(min_amount) * multiplier if min_amount is not None else None
    annual_max = float(max_amount) * multiplier if max_amount is not None else None

    rep_salary = annual_max if annual_max is not None else annual_min
    if rep_salary is None:
        bracket = "Unspecified"
    elif rep_salary < 80000:
        bracket = "< $80k"
    elif rep_salary < 120000:
        bracket = "$80k - $120k"
    elif rep_salary < 160000:
        bracket = "$120k - $160k"
    elif rep_salary < 200000:
        bracket = "$160k - $200k"
    else:
        bracket = "$200k+"

    return annual_min, annual_max, intv, bracket


def parse_locations(raw: str) -> tuple[list[str], bool]:
    """Parses a location string into individual physical locations and a remote flag."""
    if not raw or not raw.strip():
        return [], False

    if ";" in raw or "|" in raw:
        chunks = re.split(r"[;|]", raw)
    else:
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

    valid_sites = {"linkedin", "indeed", "zip_recruiter", "glassdoor", "google"}
    active_sites = [s for s in sites if s in valid_sites]
    if not active_sites:
        active_sites = ["linkedin", "indeed", "google"]

    physical_locations, detected_remote = parse_locations(location)
    effective_remote = is_remote or detected_remote

    targets: list[tuple[str | None, bool]] = []
    if physical_locations:
        for loc in physical_locations:
            targets.append((loc, effective_remote))
    elif effective_remote:
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

                dedup_key = (
                    job_id if job_id else f"{title.lower()}::{company.lower()}::{loc.lower()}"
                )
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                raw_min = row.get("min_amount")
                raw_max = row.get("max_amount")
                interval = str(row.get("interval", "yearly")) if row.get("interval") else "yearly"
                currency = str(row.get("currency", "USD")) if row.get("currency") else "USD"

                annual_min, annual_max, salary_interval, salary_bracket = categorize_salary(
                    min_amount=float(raw_min) if raw_min is not None else None,
                    max_amount=float(raw_max) if raw_max is not None else None,
                    interval=interval,
                )

                salary_source = None
                if raw_min and raw_max:
                    salary_source = f"{currency} {raw_min} - {raw_max} / {interval}"
                elif raw_min:
                    salary_source = f"{currency} {raw_min} / {interval}"

                seniority_level = classify_seniority(title)

                job = {
                    "job_id": job_id,
                    "site": row.get("site", ""),
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary_source": salary_source,
                    "min_salary": annual_min,
                    "max_salary": annual_max,
                    "salary_interval": salary_interval,
                    "salary_bracket": salary_bracket,
                    "seniority_level": seniority_level,
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
