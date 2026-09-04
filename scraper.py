from jobspy import scrape_jobs
import pandas as pd
from typing import List, Dict

def fetch_jobs(search_term: str, location: str, distance_miles: int = 50, results_wanted: int = 15) -> List[Dict]:
    """
    Scrapes jobs using jobspy across multiple sites.
    """
    try:
        jobs_df = scrape_jobs(
            site_name=["indeed", "linkedin", "zip_recruiter", "glassdoor"],
            search_term=search_term,
            location=location,
            distance=distance_miles,
            results_wanted=results_wanted,
            country_employer="usa" # Assuming USA for now, can be extended
        )
        
        if jobs_df is None or jobs_df.empty:
            return []
            
        # Convert to list of dicts, replacing NaNs with None
        jobs_df = jobs_df.where(pd.notnull(jobs_df), None)
        
        # jobspy returns columns like: id, site, job_url, title, company, location, 
        # job_type, date_posted, interval, min_amount, max_amount, currency, is_remote, emails, description
        
        jobs_list = []
        for _, row in jobs_df.iterrows():
            salary_source = None
            if row.get('min_amount') and row.get('max_amount'):
                interval = row.get('interval', 'yearly')
                currency = row.get('currency', 'USD')
                salary_source = f"{currency} {row['min_amount']} - {row['max_amount']} / {interval}"
            elif row.get('min_amount'):
                interval = row.get('interval', 'yearly')
                currency = row.get('currency', 'USD')
                salary_source = f"{currency} {row['min_amount']} / {interval}"
                
            job = {
                "job_id": str(row.get('id', '')),
                "site": row.get('site', ''),
                "title": row.get('title', ''),
                "company": row.get('company', ''),
                "location": row.get('location', ''),
                "salary_source": salary_source,
                "job_url": row.get('job_url', ''),
                "description": row.get('description', ''),
                "date_posted": row.get('date_posted')
            }
            jobs_list.append(job)
            
        return jobs_list
    except Exception as e:
        print(f"Error scraping jobs: {e}")
        return []
