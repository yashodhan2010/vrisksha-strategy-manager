from __future__ import annotations

from pathlib import Path
from datetime import date

from app import config
from app.execution import kite_session
from app.execution.kite_session import save_access_token_to_env, validate_saved_access_token


def test_save_access_token_to_env_adds_token_and_date(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("KITE_API_KEY=abc\n", encoding="utf-8")

    save_access_token_to_env("token123", env_path)

    content = env_path.read_text(encoding="utf-8")
    assert "KITE_API_KEY=abc" in content
    assert "KITE_ACCESS_TOKEN=token123" in content
    assert "KITE_ACCESS_TOKEN_DATE=" in content
    assert config.KITE_ACCESS_TOKEN == "token123"


def test_validate_saved_access_token_checks_profile(monkeypatch) -> None:
    class FakeKite:
        def profile(self) -> dict[str, str]:
            return {"user_name": "Test User"}

    monkeypatch.setattr(config, "KITE_ACCESS_TOKEN", "token123")
    monkeypatch.setattr(config, "KITE_ACCESS_TOKEN_DATE", date.today().isoformat())
    monkeypatch.setattr(kite_session, "get_kite_client", lambda: FakeKite())

    valid, message = validate_saved_access_token()

    assert valid
    assert "Test User" in message


def test_validate_saved_access_token_rejects_invalid_profile(monkeypatch) -> None:
    class FakeKite:
        def profile(self) -> dict[str, str]:
            raise RuntimeError("bad token")

    monkeypatch.setattr(config, "KITE_ACCESS_TOKEN", "token123")
    monkeypatch.setattr(config, "KITE_ACCESS_TOKEN_DATE", date.today().isoformat())
    monkeypatch.setattr(kite_session, "get_kite_client", lambda: FakeKite())

    valid, message = validate_saved_access_token()

    assert not valid
    assert "bad token" in message
