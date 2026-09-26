# PyJobs 0.2.2

PyJobs 0.2.2 adds multi-value job curation and company profiles, alongside a selectable 10-mile search-profile radius.

## Highlights

- Filter the feed by multiple seniority levels, salary brackets, job boards, and discovery profiles. Filter state can be shared in the URL, restored on reload, and applied to exports.
- Browse company profiles assembled from observed saved jobs and applications. Profiles show associated activity and observed physical work sites; site addresses are editable, and driving directions can use an optional home location.
- Store a home location independently from the search target. Google Maps directions are external links; no address is automatically geocoded or inferred.
- Group equivalent US city/state location labels together.
- On clean `main` checkouts, `run.bat` offers an optional fast-forward update from `origin/main` before starting. Development branches do not check, and offline, modified, or diverged checkouts keep their installed version. This follows main-branch commits, not release tags.

## Upgrade

On startup, PyJobs applies its SQLite schema updates and associates eligible existing saved jobs and applications with company profiles. Observed physical posting locations may seed company sites; street addresses remain blank until entered. The new home location is optional and is not populated from existing search locations. Keep a backup of your local database before upgrading, as with any application update.

## Verification

The unified quality gate passed (Ruff, Ty, Biome, 136 pytest tests). The updater also fast-forwarded a temporary `main` checkout from a local Git remote in a smoke run; no production remote was changed.
