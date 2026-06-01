from __future__ import annotations

from pathlib import Path

from app.execution.kite_session import save_access_token_to_env


def test_save_access_token_to_env_adds_token_and_date(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("KITE_API_KEY=abc\n", encoding="utf-8")

    save_access_token_to_env("token123", env_path)

    content = env_path.read_text(encoding="utf-8")
    assert "KITE_API_KEY=abc" in content
    assert "KITE_ACCESS_TOKEN=token123" in content
    assert "KITE_ACCESS_TOKEN_DATE=" in content

