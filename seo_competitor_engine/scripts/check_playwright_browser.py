from __future__ import annotations

from pathlib import Path
from config.settings import settings


def main() -> None:
    path = settings.playwright_browser_path
    if not path:
        raise SystemExit(
            "FAIL: No Chrome/Edge executable found. Set PLAYWRIGHT_BROWSER_PATH in .env."
        )
    if not Path(path).exists():
        raise SystemExit(f"FAIL: Browser path does not exist: {path}")
    print(f"PASS: Playwright will use installed browser: {path}")


if __name__ == "__main__":
    main()
