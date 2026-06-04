from __future__ import annotations

from app.automation.kite_selenium import is_auto_login_configured, request_token_from_url


def test_request_token_from_url_extracts_token() -> None:
    url = "http://127.0.0.1:8000/kite/callback?status=success&request_token=abc123"

    assert request_token_from_url(url) == "abc123"


def test_auto_login_configured_requires_all_credentials(monkeypatch) -> None:
    monkeypatch.delenv("KITE_USER_ID", raising=False)
    monkeypatch.delenv("KITE_PASSWORD", raising=False)
    monkeypatch.delenv("KITE_TOTP_SECRET", raising=False)
    assert not is_auto_login_configured()

    monkeypatch.setenv("KITE_USER_ID", "AB1234")
    monkeypatch.setenv("KITE_PASSWORD", "secret")
    monkeypatch.setenv("KITE_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    assert is_auto_login_configured()
