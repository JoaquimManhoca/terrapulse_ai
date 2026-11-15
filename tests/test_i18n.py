from __future__ import annotations

from string import Formatter

import pytest

from app.i18n import (
    LANGUAGES,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    get_catalog,
    translate,
)


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
        "decision.share",
        "feedback.title",
        "selector.change_title",
        "common.mixed_note",
        "forecast.title",
        "forecast.sunny",
        "theme.toggle",
        "theme.switch_to_dark",
        "theme.switch_to_light",
    ):
        assert key in catalog
        assert catalog[key]


def test_every_catalog_is_complete():
    reference = set(TRANSLATIONS["pt"])
    for lang in SUPPORTED_LANGUAGES:
        catalog = TRANSLATIONS[lang]
        assert set(catalog) == reference, lang
        assert all(catalog[key] for key in reference), lang


def test_placeholders_match_reference():
    formatter = Formatter()
    for key, reference in TRANSLATIONS["pt"].items():
        expected = {
            field
            for _, field, _, _ in formatter.parse(reference)
            if field is not None
        }
        for lang in SUPPORTED_LANGUAGES:
            actual = {
                field
                for _, field, _, _ in formatter.parse(TRANSLATIONS[lang][key])
                if field is not None
            }
            assert actual == expected, (lang, key)


def test_language_override_is_used():
    assert translate("state.plant_now", "chitewe") == "Dyara zvino"
    assert translate("common.last_14_days", "chitewe") == "mazuva 14 apfuura"
    assert translate("common.last_14_days", "en") == "last 14 days"


def test_missing_key_returns_key():
    assert translate("does.not.exist", "pt") == "does.not.exist"


def test_review_status_is_honest():
    assert LANGUAGES["pt"]["reviewed"] is True
    assert LANGUAGES["en"]["reviewed"] is True
    assert LANGUAGES["chitewe"]["reviewed"] is False
    assert LANGUAGES["sena"]["reviewed"] is False
