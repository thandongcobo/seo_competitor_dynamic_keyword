import json
import socket
from types import SimpleNamespace

import pytest

from collectors import playwright_collector as collector
from monitoring import store
from scripts import investigation_collection


class FakeRequest:
    def __init__(self, url, method="GET", failure=None, is_navigation=False, frame=None):
        self.url = url
        self.method = method
        self.failure = failure
        self._is_navigation = is_navigation
        self.frame = frame

    def is_navigation_request(self):
        return self._is_navigation


class FakeResponse:
    def __init__(self, url, status, request=None, status_text="", headers=None):
        self.url = url
        self.status = status
        self.request = request or FakeRequest(url)
        self.status_text = status_text
        self.headers = headers or {}


class FakeConsoleMessage:
    type = "error"
    text = "Authorization: Bearer ConsoleSecret"
    location = {"url": "https://cdn.example/app.js?token=ConsoleSecret", "lineNumber": 7, "columnNumber": 3}


class FakePageError(Exception):
    message = "Client exception password=PageSecret"


class FakePage:
    url = "https://www.hollywoodbets.net/betting/21/lucky-numbers/countries"

    def __init__(self):
        self.handlers = {}
        self.main_status = 200
        self.main_frame = object()
        self.goto_error = None

    def on(self, name, callback):
        self.handlers.setdefault(name, []).append(callback)

    def emit(self, name, value=None):
        for callback in self.handlers.get(name, []):
            callback(value)

    def route(self, *_args):
        pass

    def goto(self, *_args, **_kwargs):
        if hasattr(self, "fake_lifecycle"):
            assert self.fake_lifecycle["active"] is True
        if self.goto_error is not None:
            raise self.goto_error
        main_request = FakeRequest(self.url, is_navigation=True, frame=self.main_frame)
        self.emit("response", FakeResponse(self.url, self.main_status, request=main_request))
        self.emit("domcontentloaded")
        failed_url = "https://user:pass@cdn.example/data?token=NetworkSecret&q=lucky"
        self.emit("requestfailed", FakeRequest(failed_url, failure="net::ERR_FAILED"))
        self.emit("response", FakeResponse(
            "https://api.example/data?api_key=HttpSecret", 503, status_text="Service Unavailable",
            headers={"Set-Cookie": "session=HeaderSecret", "Authorization": "Bearer HeaderSecret"}))
        self.emit("console", FakeConsoleMessage())
        self.emit("pageerror", FakePageError())
        self.emit("load")
        return FakeResponse(self.url, self.main_status, request=main_request, status_text="OK")

    def screenshot(self, *, path, **_kwargs):
        if hasattr(self, "fake_lifecycle"):
            assert self.fake_lifecycle["active"] is True
        from pathlib import Path
        Path(path).write_bytes(b"fake screenshot")

    def content(self):
        if hasattr(self, "fake_lifecycle"):
            assert self.fake_lifecycle["active"] is True
        return "<html><body>Incomplete fixture</body></html>"


class FakeContext:
    def __init__(self, page, lifecycle):
        self.page = page
        self.lifecycle = lifecycle
        self.close_error = None

    def new_page(self):
        return self.page

    def close(self):
        assert self.lifecycle["active"] is True
        self.lifecycle["closed"].append("context")
        if self.close_error:
            raise self.close_error


class FakeBrowser:
    def __init__(self, context, lifecycle):
        self.context = context
        self.lifecycle = lifecycle
        self.close_error = None

    def new_context(self, **_kwargs):
        return self.context

    def close(self):
        assert self.lifecycle["active"] is True
        self.lifecycle["closed"].append("browser")
        if self.close_error:
            raise self.close_error


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, **_kwargs):
        return self.browser


class FakePlaywrightManager:
    def __init__(self, playwright, lifecycle):
        self.playwright = playwright
        self.lifecycle = lifecycle

    def __enter__(self):
        self.lifecycle["active"] = True
        return self.playwright

    def __exit__(self, *_args):
        self.lifecycle["active"] = False
        return False


class FakeRoute:
    def __init__(self, url, method="GET"):
        self.request = FakeRequest(url, method=method)
        self.action = None

    def abort(self, reason):
        self.action = ("abort", reason)

    def continue_(self):
        self.action = ("continue", None)


def _dns_record(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr


def test_public_request_guard_continues_public_host_without_rejection(monkeypatch):
    monkeypatch.setattr(store.socket, "getaddrinfo", lambda *_args, **_kwargs: [_dns_record("8.8.8.8")])
    diagnostics = collector._new_diagnostics("https://www.example.test/")
    route = FakeRoute("https://www.example.test/path")

    collector._public_request_route(set(), diagnostics)(route)

    assert route.action == ("continue", None)
    assert diagnostics["request_guard_rejections"] == []


@pytest.mark.parametrize(("url", "dns_result", "category"), [
    ("https://api.example.test/path", socket.gaierror("mock DNS failure"), "dns_resolution_failed"),
    ("https://api.example.test/path", [_dns_record("10.1.2.3")], "non_public_dns_address"),
    ("https://api.example.test/path", [_dns_record("8.8.8.8"), _dns_record("fd00::1")],
     "non_public_dns_address"),
    ("https://api.example.test/path", [_dns_record("not-an-ip")], "invalid_dns_result"),
    ("http://127.0.0.1/path", None, "url_policy_rejected"),
    ("https://user:PasswordSecret@localhost/path?token=QuerySecret", None, "url_policy_rejected"),
    ("file://api.example.test/path?token=QuerySecret", None, "scheme_rejected"),
])
def test_public_request_guard_rejects_and_records_safe_category(monkeypatch, url, dns_result, category):
    def fake_getaddrinfo(*_args, **_kwargs):
        if isinstance(dns_result, BaseException):
            raise dns_result
        return dns_result

    monkeypatch.setattr(store.socket, "getaddrinfo", fake_getaddrinfo)
    diagnostics = collector._new_diagnostics("https://www.example.test/")
    route = FakeRoute(url, method="gEt")

    collector._public_request_route(set(), diagnostics)(route)

    assert route.action == ("abort", "blockedbyclient")
    assert len(diagnostics["request_guard_rejections"]) == 1
    record = diagnostics["request_guard_rejections"][0]
    assert record["hostname"] in {"api.example.test", "localhost", "127.0.0.1"}
    assert record["method"] == "GET"
    assert record["category"] == category
    assert record["timestamp"]
    assert record["originated_from_request_guard"] is True
    serialized = json.dumps(record)
    for secret in ("PasswordSecret", "QuerySecret", "8.8.8.8", "10.1.2.3", "fd00::1"):
        assert secret not in serialized


def _install_fake_crawl(monkeypatch, tmp_path, *, complete):
    page = FakePage()
    lifecycle = {"active": False, "closed": []}
    context = FakeContext(page, lifecycle)
    browser = FakeBrowser(context, lifecycle)
    page.fake_context = context
    page.fake_browser = browser
    page.fake_lifecycle = lifecycle
    monkeypatch.setattr(collector, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collector, "settings", SimpleNamespace(
        playwright_browser_path="mock-browser", location_coordinate="-26.2,28.0,10",
        language_code="en", playwright_navigation_timeout_ms=60000,
        playwright_render_timeout_seconds=45))
    monkeypatch.setattr(collector, "sync_playwright", lambda: FakePlaywrightManager(
        type("FakePlaywright", (), {"chromium": FakeChromium(browser)})(), lifecycle))
    monkeypatch.setattr(collector, "_looks_like_sign_in_wall", lambda _page: False)
    monkeypatch.setattr(collector, "_wait_for_meaningful_render", lambda *_args: (
        {"requested_url": page.url, "final_url": page.url, "status_code": 200,
         "seo_content_word_count": 100 if complete else 0}, complete, False,
        "standardized_visible_main_candidate" if complete else "standardized_main_content_not_confirmed",
        5, 3.0 if complete else 45.0))
    monkeypatch.setattr(collector, "_full_page_inventory", lambda _page, _blocks=None: {})
    monkeypatch.setattr(collector, "_load_lazy_content", lambda _page: 0)
    return page


def test_successful_capture_closes_resources_before_runtime_exit(tmp_path, monkeypatch):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=True)
    result = collector.crawl_page(page.url, public_only=True)
    assert result["extraction_status"] == "complete"
    assert page.fake_lifecycle == {"active": False, "closed": ["context", "browser"]}


def test_navigation_exception_closes_resources_while_runtime_is_active(tmp_path, monkeypatch):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=True)
    page.goto_error = RuntimeError("navigation failed")
    with pytest.raises(RuntimeError, match="navigation failed"):
        collector.crawl_page(page.url, public_only=True)
    assert page.fake_lifecycle == {"active": False, "closed": ["context", "browser"]}


@pytest.mark.parametrize("resource", ["context", "browser"])
def test_cleanup_errors_are_reported_and_other_resource_still_closes(tmp_path, monkeypatch, resource):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=True)
    failing = page.fake_context if resource == "context" else page.fake_browser
    failing.close_error = RuntimeError(f"{resource} close failed")
    with pytest.raises(RuntimeError, match=f"{resource} close failed"):
        collector.crawl_page(page.url, public_only=True)
    assert page.fake_lifecycle["active"] is False
    assert page.fake_lifecycle["closed"] == ["context", "browser"]


def test_cleanup_errors_do_not_replace_original_capture_failure(tmp_path, monkeypatch):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=True)
    page.goto_error = ValueError("original navigation failure")
    page.fake_context.close_error = RuntimeError("context cleanup failure")
    page.fake_browser.close_error = RuntimeError("browser cleanup failure")
    with pytest.raises(ValueError, match="original navigation failure"):
        collector.crawl_page(page.url, public_only=True)
    assert page.fake_lifecycle["active"] is False
    assert page.fake_lifecycle["closed"] == ["context", "browser"]


def test_incomplete_capture_saves_sanitized_browser_diagnostics(tmp_path, monkeypatch):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=False)
    page.main_status = 503

    result = collector.crawl_page(page.url, public_only=True)
    assert result["extraction_status"] == "incomplete"
    assert result["crawl_failed"] is True
    assert result["content_quality_reason"] == "standardized_main_content_not_confirmed"

    reference = result["diagnostic_reference"]
    assert result["diagnostic_metadata"] == str(tmp_path / reference)
    assert result["diagnostic_html"].endswith("page.html")
    assert result["diagnostic_screenshot"].endswith("page.png")
    metadata_path = tmp_path / reference
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert record["requested_url"] == page.url
    assert record["final_url"] == page.url
    assert record["main_navigation_status"] == 503
    assert record["milestones"]["dom_content_loaded_at"]
    assert record["milestones"]["load_at"]
    assert record["milestones"]["readiness_check_started_at"]
    assert record["milestones"]["readiness_check_completed_at"]
    assert record["extraction_completeness_reason"] == "incomplete:standardized_main_content_not_confirmed"
    assert record["readiness_samples"] == 5
    assert record["readiness_duration_seconds"] == 45.0
    assert record["extraction_status"] == "incomplete"
    assert record["duration_seconds"] >= 0
    assert record["failed_requests"][0]["url"] == (
        "https://cdn.example/data?token=%5BREDACTED%5D&q=%5BVALUE%5D")
    assert record["http_errors"] and all(error["status"] == 503 for error in record["http_errors"])
    assert record["console_errors"][0]["message"] == "Authorization=[REDACTED]"
    assert record["page_exceptions"][0]["message"] == "Client exception password=[REDACTED]"
    serialized = json.dumps(record)
    for secret in ("ConsoleSecret", "NetworkSecret", "HttpSecret", "PageSecret", "HeaderSecret", "user:pass"):
        assert secret not in serialized
    assert "headers" not in record
    assert record["saved_files"]["html"] == "page.html"
    assert record["saved_files"]["screenshot"] == "page.png"
    assert page.fake_lifecycle == {"active": False, "closed": ["context", "browser"]}


def test_incomplete_capture_diagnostic_survives_cleanup_errors(tmp_path, monkeypatch):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=False)
    page.fake_context.close_error = RuntimeError("context cleanup failure")
    page.fake_browser.close_error = RuntimeError("browser cleanup failure")

    result = collector.crawl_page(page.url, public_only=True)

    assert result["extraction_status"] == "incomplete"
    assert result["content_quality_reason"] == "standardized_main_content_not_confirmed"
    metadata = json.loads((tmp_path / result["diagnostic_reference"]).read_text(encoding="utf-8"))
    assert metadata["extraction_completeness_reason"] == (
        "incomplete:standardized_main_content_not_confirmed")
    assert metadata["cleanup_errors"] == [
        "RuntimeError: context cleanup failure", "RuntimeError: browser cleanup failure"]
    assert page.fake_lifecycle == {"active": False, "closed": ["context", "browser"]}


def test_successful_crawl_does_not_write_failure_diagnostics(tmp_path, monkeypatch):
    page = _install_fake_crawl(monkeypatch, tmp_path, complete=True)
    result = collector.crawl_page(page.url, public_only=True)
    assert result["extraction_status"] == "complete"
    assert result["crawl_failed"] is False
    assert "diagnostic_reference" not in result
    assert list(tmp_path.rglob("metadata.json")) == []


def test_each_diagnostic_attempt_uses_a_new_record_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "DATA_DIR", tmp_path)
    page = FakePage()
    first = collector._save_diagnostics(page, page.url, "incomplete:first", collector._new_diagnostics(page.url))
    first_path = tmp_path / first["diagnostic_reference"]
    before = first_path.read_text(encoding="utf-8")
    second = collector._save_diagnostics(page, page.url, "incomplete:second", collector._new_diagnostics(page.url))
    assert first["diagnostic_reference"] != second["diagnostic_reference"]
    assert first_path.read_text(encoding="utf-8") == before


def test_saved_incomplete_capture_remains_rejected_and_keeps_reference():
    from pathlib import Path
    fixture = json.loads(Path("tests/fixtures/playwright_incomplete_capture.json").read_text(encoding="utf-8"))
    item = {"keyword": "lucky numbers", "target": fixture["requested_url"], "side": "ours"}
    with pytest.raises(ValueError, match="Playwright capture incomplete: standardized_main_content_not_confirmed") as caught:
        investigation_collection._run_playwright(item, lambda _item: fixture)
    assert caught.value.diagnostic_reference == fixture["diagnostic_reference"]


def test_successful_capture_does_not_gain_failure_diagnostics():
    target = "https://trail.example/products/road-shoe"
    item = {"keyword": "synthetic trail shoes", "target": target, "side": "ours"}
    fixture = {"keyword": item["keyword"], "requested_url": target, "ranking_url": target,
               "final_url": target, "extraction_status": "complete", "crawl_failed": False,
               "blocked": False, "title": "Synthetic page", "headings": [], "links": []}
    result, cost = investigation_collection._run_playwright(item, lambda _item: fixture)
    assert cost is None
    assert result["extraction_status"] == "complete"
    assert "diagnostic_reference" not in result
    assert "failed_requests" not in result


def test_diagnostic_text_redacts_quoted_credentials_and_urls():
    message = '{"password": "two word secret", "url": "https://u:p@api.example/x?key=keysecret"}'
    safe = collector._sanitize_diagnostic_text(message)
    assert "two word secret" not in safe
    assert "keysecret" not in safe
    assert "u:p@" not in safe
    assert "password=[REDACTED]" in safe
