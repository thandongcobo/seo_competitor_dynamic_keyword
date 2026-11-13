from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from collectors import dataforseo_client as client_module


@pytest.fixture
def isolated_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(client_module, "ROOT", tmp_path)
    monkeypatch.setattr(client_module, "settings", SimpleNamespace(dataforseo_login="", dataforseo_password=""))
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    return tmp_path


class MockResponse:
    status_code = 200

    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


def test_missing_credentials_fail_before_http(isolated_credentials, monkeypatch):
    transmissions = []
    monkeypatch.setattr(client_module.requests, "request", lambda *args, **kwargs: transmissions.append(args))
    with pytest.raises(client_module.DataForSEOError, match="Missing DataForSEO credentials"):
        client_module.DataForSEOClient()
    assert transmissions == []


def test_client_refreshes_credentials_from_restored_env_file(isolated_credentials, monkeypatch):
    (isolated_credentials / ".env").write_text(
        "DATAFORSEO_LOGIN=test-login\nDATAFORSEO_PASSWORD=test-password\n", encoding="utf-8"
    )
    events = []
    body = {"status_code": 20000, "status_message": "Ok.", "cost": 0.01, "tasks": []}
    transmissions = []

    def fake_request(method, url, *, auth, json, headers, timeout):
        transmissions.append((method, url, auth, json, timeout))
        return MockResponse(body)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    result = client_module.DataForSEOClient(event_callback=events.append).post(
        "/v3/dataforseo_labs/google/ranked_keywords/live", [{"target": "example.test"}]
    )
    assert result == body
    assert transmissions == [("POST", "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live",
                              ("test-login", "test-password"), [{"target": "example.test"}], 90)]
    assert [event["event"] for event in events] == ["transmission_started", "http_response", "api_response"]


def test_http_authentication_failure_is_reported(isolated_credentials, monkeypatch):
    (isolated_credentials / ".env").write_text(
        "DATAFORSEO_LOGIN=test-login\nDATAFORSEO_PASSWORD=test-password\n", encoding="utf-8"
    )
    events = []
    monkeypatch.setattr(client_module.requests, "request", lambda *a, **k: MockResponse({}, 401))
    with pytest.raises(requests.HTTPError, match="401"):
        client_module.DataForSEOClient(event_callback=events.append).get("/v3/user/data")
    assert [event["event"] for event in events] == ["transmission_started", "http_response"]


def test_api_error_response_is_reported(isolated_credentials, monkeypatch):
    (isolated_credentials / ".env").write_text(
        "DATAFORSEO_LOGIN=test-login\nDATAFORSEO_PASSWORD=test-password\n", encoding="utf-8"
    )
    body = {"status_code": 40200, "status_message": "Insufficient funds", "cost": 0.0, "tasks": []}
    events = []
    monkeypatch.setattr(client_module.requests, "request", lambda *a, **k: MockResponse(body))
    with pytest.raises(client_module.DataForSEOError, match="40200"):
        client_module.DataForSEOClient(event_callback=events.append).get("/v3/user/data")
    assert events[-1]["event"] == "api_response" and events[-1]["api_status"] == 40200


def test_timeout_marks_transmission_outcome_unknown(isolated_credentials, monkeypatch):
    (isolated_credentials / ".env").write_text(
        "DATAFORSEO_LOGIN=test-login\nDATAFORSEO_PASSWORD=test-password\n", encoding="utf-8"
    )
    events = []

    def timeout(*args, **kwargs):
        raise requests.Timeout("request timed out")

    monkeypatch.setattr(client_module.requests, "request", timeout)
    with pytest.raises(requests.Timeout):
        client_module.DataForSEOClient(event_callback=events.append).get("/v3/user/data")
    assert [event["event"] for event in events] == ["transmission_started", "transmission_outcome_unknown"]


def test_empty_keyword_results_are_a_valid_api_response(isolated_credentials, monkeypatch):
    (isolated_credentials / ".env").write_text(
        "DATAFORSEO_LOGIN=test-login\nDATAFORSEO_PASSWORD=test-password\n", encoding="utf-8"
    )
    body = {"status_code": 20000, "status_message": "Ok.", "cost": 0.01,
            "tasks": [{"status_code": 20000, "result_count": 0, "result": []}]}
    monkeypatch.setattr(client_module.requests, "request", lambda *a, **k: MockResponse(body))
    result = client_module.DataForSEOClient().post(
        "/v3/dataforseo_labs/google/ranked_keywords/live", [{"target": "example.test"}]
    )
    assert result["status_code"] == 20000
    assert result["tasks"][0]["result_count"] == 0
    assert result["tasks"][0]["result"] == []
