"""Offline tests: never contact Gemma."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'test_gemma_connection.py'
spec = importlib.util.spec_from_file_location('gemma_connection_check', SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeClient:
    def __init__(self, answer='READY', error=None):
        self.calls = 0
        self.answer = answer
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs['max_tokens'] == 32
        assert kwargs['timeout'] == 45
        if self.error:
            raise self.error
        choice = SimpleNamespace(message=SimpleNamespace(content=self.answer), finish_reason='stop')
        return SimpleNamespace(choices=[choice])


def test_ready_one_request():
    client = FakeClient()
    result = mod.probe(client, 'test-model', clock=lambda: 100)
    assert result['available'] and result['status'] == 'ready'
    assert client.calls == 1


def test_unexpected_response_is_not_ready():
    client = FakeClient('hello')
    result = mod.probe(client, 'test-model')
    assert not result['available'] and result['status'] == 'unexpected_response'
    assert client.calls == 1


def test_timeout_reports_failure_without_retry():
    class APITimeoutError(Exception):
        pass
    client = FakeClient(error=APITimeoutError('timed out'))
    result = mod.probe(client, 'test-model')
    assert result['status'] == 'timeout' and client.calls == 1


def test_http_504_reports_timeout():
    class FakeHttpError(Exception):
        status_code = 504
    client = FakeClient(error=FakeHttpError('gateway'))
    assert mod.probe(client, 'test-model')['status'] == 'timeout'


def test_missing_config_does_not_expose_key():
    with pytest.raises(ValueError, match='LLM_MODEL'):
        mod.get_config({'LLM_BASE_URL': 'http://example.test/v1/', 'LLM_API_KEY': 'secret'})


def test_valid_config():
    c = mod.get_config({'LLM_BASE_URL': 'http://example.test/v1/', 'LLM_API_KEY': 'secret', 'LLM_MODEL': 'gemma'})
    assert c['LLM_MODEL'] == 'gemma'
