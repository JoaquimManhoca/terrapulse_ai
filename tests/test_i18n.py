from __future__ import annotations

import pytest

from app.i18n import LANGUAGES, SUPPORTED_LANGUAGES, get_catalog, translate


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_catalog_has_core_keys(lang):
    catalog = get_catalog(lang)
    for key in (
        "app.name",
        "nav.decision",
        "state.plant_now",
        "state.wait",
        "state.high_risk",
        "decision.action_wait",
        "decision.listen",
        "decision.mixed_badge",
        "common.mixed_note",
        "forecast.title",
        "forecast.sunny",
        "theme.toggle",
        "theme.switch_to_dark",
        "theme.switch_to_light",
    ):
        assert key in catalog
        assert catalog[key]


def test_fallback_to_portuguese():
    assert translate("state.plant_now", "chitewe") == "Dyara zvino"
    assert translate("common.last_14_days", "chitewe") == "últimos 14 dias"


def test_missing_key_returns_key():
    assert translate("does.not.exist", "pt") == "does.not.exist"


def test_review_status_is_honest():
    assert LANGUAGES["pt"]["reviewed"] is True
    assert LANGUAGES["chitewe"]["reviewed"] is False
    assert LANGUAGES["sena"]["reviewed"] is False
