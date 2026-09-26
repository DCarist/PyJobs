# Changelog

## v0.2.2

### Added
- Search profiles can search within a 10-mile radius.
- Curation filters for seniority, salary bracket, source board, and discovery profile support multiple selections; those selections are reflected in shareable URLs and exports. Salary filtering continues to support unspecified pay.
- Added a company directory and company profiles based on observed saved-job and application data. Company profiles show associated jobs and applications, support multiple observed physical sites and user-editable site addresses, and can link to Google Maps driving directions from an optional home location.
- Added an optional home location for directions, kept separate from the search target.
- The Windows `run.bat` launcher can offer a fast-forward update from `origin/main` on clean `main` checkouts, then relaunch. Development branches never check for updates.

### Changed
- Equivalent US city/state location labels (for example, with or without a trailing country) now share one location group.
- Existing local databases are upgraded at startup with company/site and home-location fields; existing job and application records are associated with company profiles where possible. Company sites are seeded from observed posting locations, not inferred addresses.
- Updated the feed's company presentation and company-directory activity counts; the directory can hide inactive profiles.

### Fixed
- Improved curation state restoration for filtered page loads and reset behavior, and aligned exported results with feed filters.
- Improved handling and recovery of company identities associated with saved jobs and applications.
