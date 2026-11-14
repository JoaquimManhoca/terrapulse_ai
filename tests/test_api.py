from __future__ import annotations


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["observations"] > 0
    assert payload["real_observations"] == payload["observations"]
    assert payload["synthetic_observations"] == 0
    assert payload["data_status"] == "real"


def test_decision_contract(client):
    response = client.get("/api/decision")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["state"] in {"PLANT_NOW", "WAIT", "PLANT_IN_DAYS", "HIGH_RISK"}
    assert 0 <= payload["confidence"] <= 1
    assert payload["model_version"] == "heuristic-v0"
    assert isinstance(payload["reasons"], list) and payload["reasons"]
    assert payload["data_status"] == "real"
    assert "onset_21d" in payload["probabilities"]
    assert payload["probabilities"]["onset_21d"] is None


def test_history_endpoint(client):
    response = client.get("/api/history?days=30")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["days"] <= 30
    assert isinstance(payload["series"], list)


def test_climatology_endpoint(client):
    response = client.get("/api/climatology")
    assert response.status_code == 200
    payload = response.get_json()
    assert "monthly" in payload and "yearly" in payload


def test_ingest_endpoint_on_empty_directory(client):
    response = client.post("/api/admin/ingest")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ingested"] == 0
    assert payload["updated"] == 0
    assert payload["days"] == 0
