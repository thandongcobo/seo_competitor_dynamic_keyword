from __future__ import annotations

import json
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

from config.settings import settings

BASE_URL = "https://api.dataforseo.com"


class DataForSEOError(RuntimeError):
    pass


class DataForSEOClient:
    def __init__(self, login: str | None = None, password: str | None = None, timeout: int = 90):
        self.login = login or settings.dataforseo_login
        self.password = password or settings.dataforseo_password
        self.timeout = timeout
        if not self.login or not self.password:
            raise DataForSEOError(
                "Missing DataForSEO credentials. Copy .env.example to .env and add DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD."
            )

    def _request(self, method: str, path: str, *, payload: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        response = requests.request(
            method,
            url,
            auth=(self.login, self.password),
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status_code") not in (20000, None):
            raise DataForSEOError(f"DataForSEO error {data.get('status_code')}: {data.get('status_message')}")
        return data

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", path, payload=payload)


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
