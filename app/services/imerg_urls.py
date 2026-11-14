"""Build GES DISC URLs for GPM IMERG Early Daily granules."""

from __future__ import annotations

from datetime import date, timedelta

IMERG_BASE_URL = "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDE.07"
RAINY_MONTHS = {10, 11, 12, 1, 2, 3}


def imerg_filename(day: date) -> str:
    return f"3B-DAY-E.MS.MRG.3IMERG.{day:%Y%m%d}-S000000-E235959.V07B.nc4"


def imerg_url(day: date, base_url: str = IMERG_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/{day:%Y}/{day:%m}/{imerg_filename(day)}"


def imerg_urls(
    start: date,
    end: date,
    base_url: str = IMERG_BASE_URL,
    seasons_only: bool = False,
) -> list[str]:
    if end < start:
        raise ValueError("end must be on or after start")

    urls: list[str] = []
    day = start
    while day <= end:
        if not seasons_only or day.month in RAINY_MONTHS:
            urls.append(imerg_url(day, base_url))
        day += timedelta(days=1)
    return urls
