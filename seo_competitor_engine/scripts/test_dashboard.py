from __future__ import annotations

from scripts.serve_dashboard import dashboard_state


def main() -> None:
    state = dashboard_state()
    assert "meta" in state
    assert "ranking" in state
    assert "files" in state
    print("PASS: dashboard state can be generated without external API calls")


if __name__ == "__main__":
    main()
