"""Statistical climate analysis: Mann-Kendall, Sen's slope, t-tests, CIs.

Pure statistics helpers used by the climate trends endpoint. Every series
is a sequence of numbers ordered in time (e.g. one value per rainy season).
NaN values are dropped before any statistic is computed; if too few points
remain, each function returns ``None`` and the caller reports
``insufficient_data``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

MIN_POINTS = 4
DEFAULT_CONFIDENCE = 0.95


def _clean(values) -> np.ndarray:
    series = np.asarray(values, dtype=float)
    return series[~np.isnan(series)]


def mann_kendall(values, alpha: float = 0.05) -> dict | None:
    """Mann-Kendall trend test (two-sided, normal approximation).

    Returns the S statistic, tie-corrected variance, Z score, two-sided
    p-value and the trend label at ``alpha``.
    """
    x = _clean(values)
    n = x.size
    if n < MIN_POINTS:
        return None

    s = 0
    for k in range(n - 1):
        s += int(np.sum(np.sign(x[k + 1 :] - x[k])))

    _unique, counts = np.unique(x, return_counts=True)
    tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    if var_s <= 0:
        z = 0.0
    elif s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0

    p_value = 2.0 * stats.norm.sf(abs(z))
    if p_value >= alpha:
        trend = "no_trend"
    elif z > 0:
        trend = "increasing"
    else:
        trend = "decreasing"

    return {
        "n": int(n),
        "s": s,
        "var_s": round(var_s, 3),
        "z": round(z, 4),
        "p_value": round(float(p_value), 6),
        "alpha": alpha,
        "trend": trend,
        "confidence": round(1.0 - alpha, 2),
    }


def sens_slope(values, alpha: float = 0.05) -> dict | None:
    """Theil-Sen slope estimator with a two-sided confidence interval.

    The slope is the median of the pairwise slopes; the CI follows the
    classical Sen (1968) rank method (as in pymannkendall).
    """
    x = _clean(values)
    n = x.size
    if n < MIN_POINTS:
        return None

    slopes = []
    for i in range(n - 1):
        diff = x[i + 1 :] - x[i]
        idx = np.arange(1, n - i)
        slopes.extend((diff / idx).tolist())
    slopes_arr = np.sort(np.asarray(slopes, dtype=float))
    slope = float(np.median(slopes_arr))

    # Var(S) as in the Mann-Kendall test, computed on the original series.
    s = 0
    for k in range(n - 1):
        s += int(np.sum(np.sign(x[k + 1 :] - x[k])))
    _unique, counts = np.unique(x, return_counts=True)
    tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    big_n = slopes_arr.size
    c_alpha = stats.norm.ppf(1 - alpha / 2) * math.sqrt(var_s)
    lower = int(max(0, math.floor((big_n - c_alpha) / 2)))
    upper = int(min(big_n - 1, math.ceil((big_n + c_alpha) / 2)))

    return {
        "n": int(n),
        "slope": round(slope, 4),
        "ci_low": round(float(slopes_arr[lower]), 4),
        "ci_high": round(float(slopes_arr[upper]), 4),
        "alpha": alpha,
        "confidence": round(1.0 - alpha, 2),
    }


def mean_confidence_interval(
    values, confidence: float = DEFAULT_CONFIDENCE
) -> dict | None:
    """Mean with a Student-t confidence interval."""
    x = _clean(values)
    n = x.size
    if n < 2:
        return None
    mean = float(np.mean(x))
    sem = float(stats.sem(x))
    low, high = stats.t.interval(confidence, df=n - 1, loc=mean, scale=sem)
    return {
        "n": int(n),
        "mean": round(mean, 3),
        "ci_low": round(float(low), 3),
        "ci_high": round(float(high), 3),
        "std_error": round(sem, 3),
        "confidence": confidence,
    }


def welch_ttest(
    values_a, values_b, confidence: float = DEFAULT_CONFIDENCE
) -> dict | None:
    """Welch t-test comparing two samples (unequal variances)."""
    a = _clean(values_a)
    b = _clean(values_b)
    if a.size < 2 or b.size < 2:
        return None

    result = stats.ttest_ind(a, b, equal_var=False)
    mean_diff = float(np.mean(a) - np.mean(b))
    se_diff = math.sqrt(
        float(np.var(a, ddof=1)) / a.size + float(np.var(b, ddof=1)) / b.size
    )
    t_crit = stats.t.ppf(
        1 - (1 - confidence) / 2, df=float(result.df or (a.size + b.size - 2))
    )
    alpha = 1 - confidence
    return {
        "n_a": int(a.size),
        "n_b": int(b.size),
        "mean_a": round(float(np.mean(a)), 3),
        "mean_b": round(float(np.mean(b)), 3),
        "difference": round(mean_diff, 3),
        "difference_ci_low": round(float(mean_diff - t_crit * se_diff), 3),
        "difference_ci_high": round(float(mean_diff + t_crit * se_diff), 3),
        "t_statistic": round(float(result.statistic), 4),
        "degrees_of_freedom": round(float(result.df), 2) if result.df else None,
        "p_value": round(float(result.pvalue), 6),
        "alpha": round(alpha, 3),
        "significant": bool(result.pvalue < alpha),
        "confidence": confidence,
    }
