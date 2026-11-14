"""Deterministic rainfall data for isolated tests; never imported by the app."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

_MONTHLY_PROBABILITY = {
    1: 0.46,
    2: 0.42,
    3: 0.33,
    4: 0.16,
    5: 0.07,
    6: 0.03,
    7: 0.03,
    8: 0.02,
    9: 0.05,
    10: 0.11,
    11: 0.29,
    12: 0.43,
}

_MONTHLY_MEAN_MM = {
    1: 12.5,
    2: 11.0,
    3: 8.0,
    4: 4.0,
    5: 2.0,
    6: 1.2,
    7: 1.1,
    8: 1.0,
    9: 1.8,
    10: 3.5,
    11: 7.0,
    12: 11.0,
}


def generate_test_rainfall(
    start: date,
    end: date,
    seed: int = 42,
) -> pd.DataFrame:
    """Return a repeatable, test-only daily rainfall series."""
    if end < start:
        raise ValueError("end must be on or after start")

    rng = np.random.default_rng(seed)
    days = pd.date_range(start=start, end=end, freq="D")
    years = sorted({ts.year for ts in days})
    year_factor = {
        year: float(rng.lognormal(mean=0.0, sigma=0.18))
        for year in years
    }

    rows = []
    for day in days:
        factor = year_factor[day.year]
        probability = min(0.95, _MONTHLY_PROBABILITY[day.month] * factor)
        if rng.random() < probability:
            scale = (_MONTHLY_MEAN_MM[day.month] * factor) / 1.7
            amount = min(float(rng.gamma(shape=1.7, scale=scale)), 90.0)
        else:
            amount = 0.0
        rows.append((day.date(), round(amount, 1)))

    return pd.DataFrame(rows, columns=["day", "precip_mm"])
