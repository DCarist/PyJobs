import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyjobs.services.scraper import fetch_jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="PyJobs Scraper CLI Testing Tool")
    parser.add_argument("--term", "-t", default="Software Engineer", help="Search keyword/term")
    parser.add_argument(
        "--location", "-l", default="Remote", help="Location (supports cities, states, remote)"
    )
    parser.add_argument(
        "--sites",
        "-s",
        nargs="+",
        default=["linkedin", "indeed"],
        help="Sites to scrape (linkedin, indeed, google, zip_recruiter, glassdoor)",
    )
    parser.add_argument(
        "--remote", "-r", action="store_true", help="Explicitly mark search as remote"
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=5, help="Number of results wanted per site"
    )

    args = parser.parse_args()

    print(f"\n[Scraper CLI] Searching for '{args.term}' in '{args.location}'...")
    print(f"Sites: {args.sites} | Remote: {args.remote} | Limit: {args.limit}")

    start_time = time.time()
    results = fetch_jobs(
        search_term=args.term,
        location=args.location,
        results_wanted=args.limit,
        sites=args.sites,
        is_remote=args.remote,
    )
    duration = time.time() - start_time

    print(f"\nScrape completed in {duration:.2f}s. Found {len(results)} jobs:\n")

    if not results:
        print("No jobs found matching criteria.")
        sys.exit(0)

    for i, job in enumerate(results, 1):
        site = job.get("site", "unknown").upper()
        title = job.get("title", "No title")
        company = job.get("company", "Unknown company")
        loc = job.get("location", "No location")
        sal = job.get("salary_source") or "No salary specified"
        print(f"  {i}. [{site}] {title}")
        print(f"     Company: {company} | Location: {loc}")
        print(f"     Salary:  {sal}")
        print(f"     URL:     {job.get('job_url', 'N/A')}\n")


if __name__ == "__main__":
    main()
