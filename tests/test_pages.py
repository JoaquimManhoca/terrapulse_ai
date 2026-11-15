from __future__ import annotations

import pytest


def test_pages_render(client):
    for path in ("/", "/porque", "/historico", "/sobre"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"TerraPulse AI" in response.data, path


def test_app_script_is_text_and_includes_feedback_followup(client):
    response = client.get("/static/js/app.js")

    assert response.status_code == 200
    assert b"\x00" not in response.data
    assert b"showDueFollowup" in response.data


def test_decision_page_is_decision_first_with_feedback_and_share(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="selector-banner selector-banner--compact"' in html
    assert 'id="change-context"' in html
    assert 'name="region"' in html
    assert 'name="crop"' in html
    assert 'class="decision-card' in html
    assert html.index('class="decision-card') < html.index('id="change-context"')
    assert 'class="feedback-card"' in html
    assert 'name="choice" value="planted"' in html
    assert 'name="choice" value="waited"' in html
    assert 'name="choice" value="not_helpful"' in html
    assert 'name="submission_id"' in html
    assert 'data-feedback-outcome' in html
    assert "não pedimos nome nem gps" in html.lower()
    assert 'https://wa.me/?text=' in html
    assert 'data-feedback' in html
    assert 'class="badge badge-real"' in html
    assert "Observações até:" in html
    assert 'class="decision-recommendation"' in html
    assert 'class="weather-art weather-art--' in html
    assert 'data-weather-probability' in html
    assert 'class="plan-days"' in html
    assert 'class="reason-list"' not in html
    assert 'class="sparkline"' not in html


def test_decision_selection_is_persisted(client):
    first = client.get("/?region=chimoio&crop=feijao")
    assert first.status_code == 200

    html = client.get("/").get_data(as_text=True)
    assert 'value="chimoio" selected' in html
    assert 'value="feijao" selected' in html
    assert "Chimoio" in html
    assert "Feijão" in html


def test_decision_unsupported_selection_shows_empty_state(client):
    response = client.get("/?region=chimoio&crop=milho")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="panel selector-empty"' in html
    assert 'class="decision-card' not in html
    assert "Ainda não há série de chuva" in html


def test_decision_invalid_selection_falls_back(client):
    html = client.get("/?region=atlantis&crop=banana").get_data(as_text=True)
    assert 'value="manica" selected' in html
    assert 'value="milho" selected' in html
    assert 'class="decision-card' in html


def test_why_page_contains_more_details(client):
    html = client.get("/porque").get_data(as_text=True)
    assert 'class="reason-list"' in html
    assert 'class="sparkline"' in html
    assert "Todos os sinais" in html


def test_language_switch(client):
    response = client.get("/?lang=chitewe")
    assert response.status_code == 200
    assert b'lang="chitewe"' in response.data
    assert "Sarudzo".encode() in response.data


def test_english_translates_every_page(client):
    expected = {
        "/": "Decision",
        "/porque": "Why this decision?",
        "/historico": "Rain history",
        "/analise": "Climate analysis",
        "/sobre": "About TerraPulse AI",
    }
    for path, text in expected.items():
        html = client.get(f"{path}?lang=en").get_data(as_text=True)
        assert 'lang="en"' in html, path
        assert text in html, path
        assert "Navegação principal" not in html, path


@pytest.mark.parametrize(
    "lang,expected",
    [
        (
            "chitewe",
            {
                "/": "Sarudzo yekudyara",
                "/porque": "Nei sarudzo iyi?",
                "/historico": "Nhoroondo yemvura",
                "/analise": "Ongororo yemamiriro ekunze",
                "/sobre": "Nezve TerraPulse AI",
            },
        ),
        (
            "sena",
            {
                "/": "Chisankho cha kudyala",
                "/porque": "Ngani chisankho ichi?",
                "/historico": "Mbiri ya mvura",
                "/analise": "Ongororo ya mamiriro ekunze",
                "/sobre": "Za TerraPulse AI",
            },
        ),
    ],
)
def test_local_languages_translate_every_page(client, lang, expected):
    for path, text in expected.items():
        html = client.get(f"{path}?lang={lang}").get_data(as_text=True)
        assert f'lang="{lang}"' in html, path
        assert text in html, path
        assert "Navegação principal" not in html, path


def test_english_translates_analysis_chart_labels(client):
    html = client.get("/analise?lang=en").get_data(as_text=True)
    assert "Total rainfall by rainy season, 1998 to 2024" in html
    assert "Rainfall (mm)" in html
    assert "IC 95%" not in html


def test_theme_toggle_defaults_to_light(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-theme="light"' in html
    assert 'data-theme-toggle' in html
    assert 'aria-label="Alternar tema claro/escuro"' in html


def test_decision_page_uses_30_day_plan_instead_of_7_day_forecast(
    client, app, monkeypatch
):
    from datetime import date, timedelta

    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = True
    today = date(2025, 1, 1)
    monkeypatch.setattr(decision_service, "_local_today", lambda: today)
    monkeypatch.setattr(
        decision_service,
        "fetch_open_meteo",
        lambda: {
            "source": "open-meteo",
            "rows": [
                {
                    "date": (today + timedelta(days=offset)).isoformat(),
                    "weather_code": 0,
                    "precip_mm": 0,
                    "probability_pct": 5,
                }
                for offset in range(4)
            ],
        },
    )

    html = client.get("/").get_data(as_text=True)

    assert 'class="weather-forecast"' not in html
    assert 'data-weather-day' not in html
    assert 'class="plan-days"' in html
    assert html.count("data-plan-day") == 30


def test_decision_page_renders_30_day_plan_and_trust(client, app, monkeypatch):
    from datetime import date, timedelta

    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = True
    today = date(2025, 1, 5)
    monkeypatch.setattr(decision_service, "_local_today", lambda: today)
    monkeypatch.setattr(
        decision_service,
        "fetch_open_meteo",
        lambda: {
            "source": "open-meteo",
            "rows": [
                {
                    "date": (today + timedelta(days=offset)).isoformat(),
                    "weather_code": 0,
                    "precip_mm": 0.0,
                    "probability_pct": 10,
                }
                for offset in range(16)
            ],
        },
    )

    html = client.get("/?lang=en").get_data(as_text=True)

    assert 'class="planting-plan"' in html
    assert 'class="plan-days"' in html
    assert 'class="plan-scroll-hint"' in html
    assert 'aria-current="date"' in html
    assert html.count("data-plan-day") == 30
    assert "30-day plan" in html
    assert "Data confidence and sources" in html
    assert "Average coverage (30 days)" in html


def test_stale_decision_page_hides_forecast(client, app, monkeypatch):
    from datetime import date

    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = True
    monkeypatch.setattr(decision_service, "_local_today", lambda: date(2025, 2, 1))

    def fail_forecast():
        raise AssertionError("stale data must not fetch a forecast")

    monkeypatch.setattr(decision_service, "fetch_open_meteo", fail_forecast)

    html = client.get("/").get_data(as_text=True)
    assert "Dados desatualizados" in html
    assert 'class="weather-forecast"' not in html
    assert "plan-note--warn" in html
    assert "Sem previs" in html
    assert 'data-plan-phase="climate"' in html


def test_security_headers_are_present(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert (
        response.headers["Referrer-Policy"]
        == "strict-origin-when-cross-origin"
    )
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "https://fonts.googleapis.com" in policy


def test_language_switch_does_not_redirect_offsite(client):
    response = client.get(
        "/language/chitewe",
        headers={"Referer": "https://evil.example/phishing"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_language_switch_returns_to_same_origin(client):
    response = client.get(
        "/language/chitewe",
        headers={"Referer": "http://localhost/porque"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/porque")


def test_language_switch_drops_old_lang_parameter(client):
    response = client.get(
        "/language/en",
        headers={"Referer": "http://localhost/analise?lang=pt&region=manica"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/analise?region=manica")


def test_manifest_and_service_worker(client):
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert b"TerraPulse" in manifest.data
    assert "max-age=86400" in manifest.headers["Cache-Control"]

    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers.get("Service-Worker-Allowed") == "/"
    assert worker.headers["Cache-Control"] == "no-cache"
    assert b"CACHE" in worker.data
