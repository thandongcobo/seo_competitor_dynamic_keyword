# Stage 2 - Gemma response diagnostics

Copy `llm_foundation/inference.py` to the existing project's `llm_foundation/inference.py` (back up the original first). Copy `tests/test_inference_diagnostics.py` to `tests/`.

The existing CLI continues to work without changes. To enable response capture, add `diagnostic_dir=Path('output/results/aviator/llm_outputs/diagnostics')` to the existing `run_specialist(...)` call in `scripts/run_llm_specialist.py` and ensure `from pathlib import Path` is imported. This optional parameter is backward compatible.

Run: `python -m pytest -q tests/test_inference_diagnostics.py`

Run: `python -m scripts.run_llm_specialist --keyword aviator --task onpage`

Inspect: `output/results/aviator/llm_outputs/diagnostics/onpage_attempt_1_failure.json` and `onpage_attempt_2_failure.json` if failures occur.

Diagnostic files may contain model-returned sensitive text. Do not commit them or share without review. The original successfully validated JSON is never modified by this module on failure.
