from __future__ import annotations

from datetime import date

import pytest

from app.services.imerg_urls import IMERG_BASE_URL, imerg_filename, imerg_url, imerg_urls


def test_imerg_filename_and_url():
    day = date(2025, 12, 11)
    assert imerg_filename(day) == "3B-DAY-E.MS.MRG.3IMERG.20251211-S000000-E235959.V07B.nc4"
    assert imerg_url(day) == (
        IMERG_BASE_URL
        + "/2025/12/3B-DAY-E.MS.MRG.3IMERG.20251211-S000000-E235959.V07B.nc4"
    )


def test_imerg_urls_range_and_seasons():
    urls = imerg_urls(date(2023, 9, 30), date(2023, 10, 2))
    assert len(urls) == 3

    seasonal = imerg_urls(date(2023, 9, 30), date(2023, 10, 1), seasons_only=True)
    assert len(seasonal) == 1
    assert "/2023/10/" in seasonal[0]


def test_imerg_urls_rejects_reversed_range():
    with pytest.raises(ValueError):
        imerg_urls(date(2025, 1, 2), date(2025, 1, 1))
