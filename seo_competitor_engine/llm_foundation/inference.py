"""OpenAI-compatible local inference, isolated from the deterministic SEO engine."""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .contracts import SPECIALIST_OUTPUT
from .validate import validate_output
from .output_repair import repair_output
from .request_optimizer import prepare_request

TASKS = ('onpage', 'backlinks', 'technical', 'competition')


def load_config() -> dict:
    # dotenv optional; never persist or print the key.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    base_url = os.getenv('LLM_BASE_URL', '').strip()
    model = os.getenv('LLM_MODEL', '').strip()
    key = os.getenv('LLM_API_KEY', '').strip()
    if not base_url.startswith(('http://', 'https://')) or not model or not key:
        raise ValueError('Set LLM_BASE_URL, LLM_MODEL and LLM_API_KEY in .env or environment')
    return {'base_url': base_url, 'model': model, 'api_key': key}


def parse_json(text: str) -> dict:
    """Strict JSON only: no markdown fence, no extracted fragments."""
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Model response must be a JSON object')
    return value


def _diagnostic(path: Path | None, *, task: str, attempt: int, stage: str,
                response: str | None = None, finish_reason=None, usage=None,
                error_type: str = '') -> None:
    """Save failure-only diagnostics locally, never credentials or request inputs."""
    if path is None:
        return
    # A response may contain sensitive page text. Treat diagnostic files as private.
    payload = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'task': task, 'attempt': attempt, 'stage': stage,
        'error_type': error_type,
        'response_empty': not bool(response and response.strip()),
        'raw_response': response,
        'finish_reason': str(finish_reason) if finish_reason is not None else None,
        'usage': usage,
    }
    try:
        path.mkdir(parents=True, exist_ok=True)
        target = path / f'{task}_attempt_{attempt}_failure.json'
        write_json(target, payload)
    except OSError:
        # Diagnostic writing must never obscure the original inference failure.
        pass


def run_specialist(task: str, evidence: dict, *, client: Any, model: str,
                   skills: str, instructions: str, attempts: int = 2,
                   diagnostic_dir: Path | None = None) -> tuple[dict, dict]:
    if task not in TASKS:
        raise ValueError(f'Unknown specialist: {task}')
    if attempts < 1 or attempts > 3:
        raise ValueError('attempts must be between 1 and 3')
    request_evidence, system, prompt, estimated_tokens = prepare_request(task, evidence, skills=skills, instructions=instructions)
    last_error = None
    for i in range(attempts):
        content = None
        finish_reason = None
        usage = None
        stage = "api"
        try:
            result = client.chat.completions.create(
                model=model,
                messages=[{'role': 'system', 'content': system},
                          {'role': 'user', 'content': prompt}],
                temperature=0.1,
                timeout=240,
                max_tokens=int(os.getenv('LLM_SPECIALIST_OUTPUT_BUDGET', '1800')),
            )
            choice = result.choices[0]
            content = choice.message.content
            finish_reason = getattr(choice, 'finish_reason', None)
            raw_usage = getattr(result, 'usage', None)
            usage = {k: getattr(raw_usage, k, None) for k in
                     ('prompt_tokens', 'completion_tokens', 'total_tokens')} if raw_usage else None
            stage = 'response' 
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Empty model response')
            stage = 'json_parse'
            if finish_reason == 'length':
                raise ValueError('Response truncated (finish_reason=length)')
            parsed = parse_json(content)
            stage = 'schema_validation'
            parsed, repairs = repair_output(parsed, request_evidence, task)
            errors = validate_output(parsed, request_evidence)
            if parsed.get('task') != task:
                errors.append('Response task does not match requested specialist')
            if errors:
                raise ValueError('Invalid response: ' + '; '.join(errors[:5]))
            return parsed, {'task': task, 'attempts': i+1, 'status': 'validated',
                            'estimated_input_tokens': estimated_tokens, 'usage': usage, 'repairs': repairs}
        except (ValueError, json.JSONDecodeError, IndexError, AttributeError) as exc:
            last_error = str(exc)
            _diagnostic(diagnostic_dir, task=task, attempt=i+1, stage=stage,
                        response=content, finish_reason=finish_reason, usage=usage,
                        error_type=type(exc).__name__)
            # For schema errors, retry once with explicit corrective instruction.
            prompt += '\n\nPrevious response invalid. Return exactly one valid JSON object matching the schema. No prose.'
        except Exception as exc:
            # API errors are not swallowed or copied into output (may contain credentials).
            last_error = type(exc).__name__
            _diagnostic(diagnostic_dir, task=task, attempt=i+1, stage='api',
                        error_type=type(exc).__name__)
            if i + 1 < attempts:
                time.sleep(1)
    raise RuntimeError(f'{task} inference failed after {attempts} attempts: {last_error}')


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
