"""Tests for the statistical climate analysis (Mann-Kendall, Sen, t-test)."""

from __future__ import annotations

import numpy as np
from scipy import stats as sps

from app.services import climate_analysis as ca
from app.services.season_series import _season_year


def test_mann_kendall_detects_increasing_trend():
    result = ca.mann_kendall([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    assert result is not None
    assert result["trend"] == "increasing"
    assert result["p_value"] < 0.05
    assert result["z"] > 0


def test_mann_kendall_detects_decreasing_trend():
    result = ca.mann_kendall([7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    assert result["trend"] == "decreasing"
    assert result["p_value"] < 0.05
    assert result["z"] < 0


def test_mann_kendall_constant_series_is_no_trend():
    # all values identical: S = 0, var_s = 0 -> z = 0 -> p = 1
    result = ca.mann_kendall([5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    assert result["trend"] == "no_trend"
    assert result["z"] == 0.0
    assert result["p_value"] == 1.0


def test_mann_kendall_noise_is_no_trend():
    rng = np.random.default_rng(7)
    result = ca.mann_kendall(rng.normal(10.0, 1.0, size=60).tolist())
    assert result["trend"] == "no_trend"
    assert result["p_value"] > 0.05


def test_mann_kendall_insufficient_data():
    assert ca.mann_kendall([1.0, 2.0, 3.0]) is None


def test_mann_kendall_drops_nan():
    result = ca.mann_kendall([np.nan, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    assert result is not None
    assert result["n"] == 7
    assert result["trend"] == "increasing"


def test_sen_slope_recovers_linear_rate():
    y = [10.0 + 2.5 * i for i in range(12)]
    result = ca.sens_slope(y)
    assert abs(result["slope"] - 2.5) < 1e-6
    assert result["ci_low"] <= 2.5 <= result["ci_high"]


def test_sen_slope_flat_series_is_zero():
    result = ca.sens_slope([5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    assert result["slope"] == 0.0
    assert result["ci_low"] == 0.0
    assert result["ci_high"] == 0.0


def test_sen_slope_insufficient_data():
    assert ca.sens_slope([1.0, 2.0, 3.0]) is None


def test_mean_confidence_interval_matches_scipy():
    values = [12.0, 14.0, 13.2, 15.1, 11.8, 14.9, 13.5]
    result = ca.mean_confidence_interval(values)
    mean = float(np.mean(values))
    sem = float(sps.sem(values))
    low, high = sps.t.interval(0.95, df=len(values) - 1, loc=mean, scale=sem)
    assert result["mean"] == round(mean, 3)
    assert result["ci_low"] == round(float(low), 3)
    assert result["ci_high"] == round(float(high), 3)
    assert result["ci_low"] < mean < result["ci_high"]


def test_mean_confidence_interval_needs_two_points():
    assert ca.mean_confidence_interval([3.0]) is None


def test_welch_ttest_detects_difference():
    recent = [40.0, 42.0, 38.5, 41.0, 39.5, 42.5, 40.5]
    baseline = [25.0, 24.0, 26.5, 23.5, 25.5, 24.5]
    result = ca.welch_ttest(recent, baseline)
    assert result["significant"] is True
    assert result["p_value"] < 0.001
    assert result["difference"] > 0
    assert result["difference_ci_low"] > 0


def test_welch_ttest_identical_means_not_significant():
    sample = [10.0, 11.0, 10.5, 9.8, 10.2, 10.9, 10.1]
    result = ca.welch_ttest(sample, sample)
    assert result["significant"] is False
    assert result["p_value"] > 0.05
    assert result["difference"] == 0.0


def test_welch_ttest_matches_scipy():
    a = [5.0, 6.0, 5.5, 6.5, 5.8, 6.2]
    b = [3.0, 4.0, 3.5, 2.8, 3.9]
    expected = sps.ttest_ind(a, b, equal_var=False)
    result = ca.welch_ttest(a, b)
    assert result["t_statistic"] == round(float(expected.statistic), 4)
    assert result["p_value"] == round(float(expected.pvalue), 6)


def test_welch_ttest_insufficient_data():
    assert ca.welch_ttest([1.0], [2.0]) is None


def test_season_year_mapping():
    assert _season_year(__import__("pandas").Timestamp("2023-11-05")) == 2023
    assert _season_year(__import__("pandas").Timestamp("2024-02-05")) == 2023
    assert _season_year(__import__("pandas").Timestamp("2024-07-05")) is None
