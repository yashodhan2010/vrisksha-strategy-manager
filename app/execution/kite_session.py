from __future__ import annotations

from datetime import date
from pathlib import Path

from app import config


def get_login_url() -> str:
    """Return the Kite manual login URL without automating credentials."""
    if not config.KITE_API_KEY:
        raise ValueError("KITE_API_KEY is not configured.")
    from kiteconnect import KiteConnect

    return str(KiteConnect(api_key=config.KITE_API_KEY).login_url())


def exchange_request_token(request_token: str) -> str:
    """Exchange a manually obtained request_token for an access_token."""
    api_secret = __import__("os").getenv("KITE_API_SECRET", "")
    if not config.KITE_API_KEY:
        raise ValueError("KITE_API_KEY is not configured.")
    if not api_secret:
        raise ValueError("KITE_API_SECRET is not configured.")
    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    session = kite.generate_session(request_token.strip(), api_secret=api_secret)
    access_token = session.get("access_token")
    if not access_token:
        raise ValueError("Kite did not return an access token.")
    return str(access_token)


def is_saved_access_token_for_today() -> bool:
    return bool(config.KITE_ACCESS_TOKEN and config.KITE_ACCESS_TOKEN_DATE == date.today().isoformat())


def get_kite_client(access_token: str | None = None) -> object:
    if not config.KITE_API_KEY:
        raise ValueError("KITE_API_KEY is not configured.")
    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    token = access_token or config.KITE_ACCESS_TOKEN
    if token:
        kite.set_access_token(token)
    return kite


def validate_saved_access_token() -> tuple[bool, str]:
    """Verify today's saved Kite access token by calling profile()."""
    if not is_saved_access_token_for_today():
        return False, "No saved Kite access token for today."
    try:
        profile = get_kite_client().profile()
    except Exception as exc:
        return False, f"Saved Kite access token is invalid: {exc}"
    user_name = profile.get("user_name") or profile.get("user_id") or "user"
    return True, f"Saved Kite access token is valid for {user_name}."


def save_access_token_to_env(access_token: str, env_path: str | Path = ".env") -> None:
    """Persist KITE_ACCESS_TOKEN in the local .env file."""
    path = Path(env_path)
    token_date = date.today().isoformat()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacements = {
        "KITE_ACCESS_TOKEN": access_token,
        "KITE_ACCESS_TOKEN_DATE": token_date,
    }
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in replacements:
            output.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    config.KITE_ACCESS_TOKEN = access_token
    config.KITE_ACCESS_TOKEN_DATE = token_date
