from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import truststore
except ImportError:
    truststore = None

import requests

# Use the Windows/system certificate store so corporate CA certificates
# trusted by Chrome/Edge are also trusted by Python HTTPS requests.
# The dependency is installed by setup.bat for normal project use; keeping
# this import optional allows offline unit tests to run in minimal environments.
if truststore is not None:
    truststore.inject_into_ssl()

from config.settings import ROOT, settings
from dotenv import dotenv_values

BASE_URL = "https://api.dataforseo.com"


class DataForSEOError(RuntimeError):
    pass


class DataForSEOClient:
    def __init__(self, login: str | None = None, password: str | None = None, timeout: int = 90,
                 event_callback=None):
        # A dashboard can remain open after credentials are added to .env.
        # Settings is initialized once at process startup, so refresh only the
        # DataForSEO credential source when each client is constructed. Process
        # environment values keep precedence; the .env values are a fallback.
        file_values = dotenv_values(ROOT / ".env")
        self.login = login if login is not None else _credential("DATAFORSEO_LOGIN", settings.dataforseo_login, file_values)
        self.password = password if password is not None else _credential("DATAFORSEO_PASSWORD", settings.dataforseo_password, file_values)
        self.timeout = timeout
        self.event_callback = event_callback
        if not self.login or not self.password:
            raise DataForSEOError(
                "Missing DataForSEO credentials. Copy .env.example to .env and add DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD."
            )

    def _emit_event(self, event: str, **details) -> None:
        if self.event_callback:
            self.event_callback({'event': event, **details})

    def _request(self, method: str, path: str, *, payload: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        self._emit_event('transmission_started')
        try:
            response = requests.request(
                method,
                url,
                auth=(self.login, self.password),
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except Exception:
            self._emit_event('transmission_outcome_unknown')
            raise
        self._emit_event('http_response', http_status=getattr(response, 'status_code', None))
        response.raise_for_status()
        data = response.json()
        self._emit_event('api_response', api_status=data.get('status_code'),
                         reported_cost_usd=data.get('cost'))
        if data.get("status_code") not in (20000, None):
            raise DataForSEOError(f"DataForSEO error {data.get('status_code')}: {data.get('status_message')}")
        return data

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", path, payload=payload)


def _credential(name: str, configured_value: str, file_values: dict[str, Any]) -> str:
    if name in os.environ:
        return os.environ[name]
    value = file_values.get(name)
    if value is not None:
        return str(value)
    return configured_value or ""


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
