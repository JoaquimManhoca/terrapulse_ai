"""Shared NASA Earthdata helpers: authentication and collection coverage."""

from __future__ import annotations

import netrc
import os
from datetime import date
from functools import lru_cache

import requests
from harmony import Client

from ..config import Config

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"


def earthdata_client() -> Client:
    """Return a Harmony client using a token or the Earthdata ``.netrc``."""
    token = os.environ.get("EARTHDATA_TOKEN") or Config.EARTHDATA_TOKEN
    if token:
        return Client(token=token)

    netrc_path = os.environ.get("EARTHDATA_NETRC")
    try:
        credentials = netrc.netrc(netrc_path or None).authenticators(
            "urs.earthdata.nasa.gov"
        )
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        credentials = None

    if credentials and credentials[0] and credentials[2]:
        return Client(auth=(credentials[0], credentials[2]))

    raise RuntimeError(
        "Earthdata Login is not configured. Set EARTHDATA_TOKEN, or add an "
        "Earthdata entry for urs.earthdata.nasa.gov in %USERPROFILE%\\.netrc. "
        "If the file is elsewhere, set EARTHDATA_NETRC to its path. "
        "Never put credentials in source code."
    )


@lru_cache(maxsize=8)
def collection_coverage(collection_id: str) -> tuple[date, date] | None:
    """First/last granule dates of a CMR collection, or None when unknown."""
    try:
        latest = requests.get(
            CMR_GRANULES_URL,
            params={
                "collection_concept_id": collection_id,
                "page_size": 1,
                "sort_key": "-start_date",
            },
            timeout=60,
        )
        earliest = requests.get(
            CMR_GRANULES_URL,
            params={
                "collection_concept_id": collection_id,
                "page_size": 1,
                "sort_key": "start_date",
            },
            timeout=60,
        )
        last_day = date.fromisoformat(
            latest.json()["feed"]["entry"][0]["time_start"][:10]
        )
        first_day = date.fromisoformat(
            earliest.json()["feed"]["entry"][0]["time_start"][:10]
        )
    except Exception:  # noqa: BLE001 - coverage is advisory only
        return None
    return first_day, last_day
