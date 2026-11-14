from __future__ import annotations

from datetime import date

import pandas as pd

from app.ml.onset import detect_onsets, latest_wet_event


def _series(values, start="2024-10-01"):
    index = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=index, dtype=float)


def test_false_onset_detected():
    values = [0] * 10 + [5, 10, 10] + [0] * 20
    onsets = detect_onsets(_series(values))
    assert len(onsets) == 1
    assert onsets[0].onset_date == date(2024, 10, 13)
    assert onsets[0].window_mm == 25.0
    assert onsets[0].false_onset is True


def test_true_onset_not_flagged():
    values = [0] * 10 + [5, 10, 10] + [5] * 21
    onsets = detect_onsets(_series(values))
    assert len(onsets) == 1
    assert onsets[0].false_onset is False


def test_no_onset_when_dry():
    assert detect_onsets(_series([0] * 60)) == []


def test_latest_wet_event_flags_drying_window():
    values = [0] * 10 + [5, 10, 10] + [0] * 20
    event = latest_wet_event(_series(values, start="2024-11-01"), lookback_days=30)
    assert event is not None
    assert event.false_onset is True
    assert event.dry_streak_after >= 7
