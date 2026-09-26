from __future__ import annotations

import re

from pyjobs.services.scraper import US_STATES


def canonicalize_location(raw: str) -> str:
    """Normalize known US city/state labels without inventing a location."""
    cleaned = " ".join(raw.split())
    physical = re.sub(r"\s*\((?:Hybrid|On-site)\)$", "", cleaned, flags=re.IGNORECASE)
    parts = [part.strip() for part in physical.split(",")]
    if len(parts) in (2, 3) and parts[0] and parts[1].upper() in US_STATES:
        if len(parts) == 2 or parts[2].casefold() in ("us", "usa", "united states"):
            return f"{parts[0]}, {parts[1].upper()}, US"
    return cleaned
