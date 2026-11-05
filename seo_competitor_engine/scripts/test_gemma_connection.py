"""Single-request health check for the configured OpenAI-compatible Gemma server.

Run from seo_competitor_engine project root:
    python -m scripts.test_gemma_connection

No SEO collectors, DataForSEO, Lighthouse, or specialist analysis is invoked.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Callable


def get_config(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Load .env if available, then use environment values; never expose API key."""
    if environ is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
        except ImportError:
            pass
        environ = os.environ
    values = {name: environ.get(name, '').strip() for name in
              ('LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY')}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError('Missing required configuration: ' + ', '.join(missing))
    if not values['LLM_BASE_URL'].startswith(('http://', 'https://')):
        raise ValueError('LLM_BASE_URL must begin with http:// or https://')
    return values


def probe(client: Any, model: str, *, timeout: float = 45,
          clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Make exactly one small completion call; do not retry on timeout/errors."""
    start = clock()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': 'Reply with only the word READY'}],
            max_tokens=32,
            temperature=0,
            timeout=timeout,
        )
        duration = round(clock() - start, 2)
        content = (response.choices[0].message.content or '').strip()
        finish_reason = getattr(response.choices[0], 'finish_reason', None)
        ready = content == 'READY'
        return {
            'available': ready,
            'status': 'ready' if ready else 'unexpected_response',
            'duration_seconds': duration,
            'model': model,
            'response': content[:160],
            'finish_reason': finish_reason,
            'message': 'Gemma responded successfully.' if ready else
                       'Endpoint responded, but the model did not return READY.',
        }
    except Exception as exc:
        duration = round(clock() - start, 2)
        # Keep diagnostics generic: HTTP exception bodies may contain internal URLs.
        name = type(exc).__name__
        status_code = getattr(exc, 'status_code', None)
        if status_code == 504 or name in ('APITimeoutError', 'TimeoutError'):
            category = 'timeout'
        elif status_code == 401 or status_code == 403:
            category = 'authentication_or_permission'
        elif status_code == 404:
            category = 'model_or_route_not_found'
        elif status_code == 429:
            category = 'rate_limited'
        elif status_code is not None:
            category = 'http_error'
        elif name in ('APIConnectionError', 'ConnectionError', 'ConnectError'):
            category = 'connection_error'
        else:
            category = 'request_error'
        return {
            'available': False,
            'status': category,
            'duration_seconds': duration,
            'model': model,
            'error_type': name,
            'http_status': status_code,
            'message': 'The configured model did not complete the readiness check.',
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Check Gemma availability with one small OpenAI-compatible request (no SEO data collection).')
    parser.add_argument('--timeout', type=float, default=45,
                        help='Client request timeout in seconds (default: 45).')
    parser.add_argument('--config-only', action='store_true',
                        help='Check configuration without contacting the model.')
    parser.add_argument('--json', action='store_true',
                        help='Print machine-readable JSON.')
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.timeout > 600:
        parser.error('--timeout must be between 0 and 600 seconds')
    try:
        config = get_config()
    except ValueError as exc:
        result = {'available': False, 'status': 'configuration_error', 'message': str(exc)}
        _display(result, args.json)
        return 2
    if args.config_only:
        result = {'available': None, 'status': 'configuration_ok',
                  'model': config['LLM_MODEL'],
                  'message': 'Configuration found; no model request was made.'}
        _display(result, args.json)
        return 0
    try:
        from openai import OpenAI
    except ImportError:
        result = {'available': False, 'status': 'dependency_missing',
                  'message': 'Install the openai Python package in your project virtual environment.'}
        _display(result, args.json)
        return 2
    # Disable SDK retries: one invocation means exactly one request.
    client = OpenAI(base_url=config['LLM_BASE_URL'], api_key=config['LLM_API_KEY'],
                    timeout=args.timeout, max_retries=0)
    result = probe(client, config['LLM_MODEL'], timeout=args.timeout)
    _display(result, args.json)
    return 0 if result['available'] else 1


def _display(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print('Gemma check:', result['status'])
        if 'model' in result:
            print('Model:', result['model'])
        if 'duration_seconds' in result:
            print('Duration:', result['duration_seconds'], 'seconds')
        if 'response' in result:
            print('Response:', result['response'])
        if result.get('http_status'):
            print('HTTP status:', result['http_status'])
        print(result['message'])


if __name__ == '__main__':
    sys.exit(main())
