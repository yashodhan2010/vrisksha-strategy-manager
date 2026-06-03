from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app import config
from app.execution.kite_session import get_login_url


def request_token_from_url(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    tokens = query.get("request_token")
    return tokens[0] if tokens else None


def capture_request_token(timeout_seconds: int = config.SELENIUM_LOGIN_TIMEOUT_SECONDS) -> str:
    """Open Kite login and wait until the redirect URL contains request_token."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise ImportError("selenium is required. Run pip install -r requirements.txt.") from exc

    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(get_login_url())

        def token_is_available(browser: webdriver.Chrome) -> str | bool:
            return request_token_from_url(browser.current_url) or False

        token = WebDriverWait(driver, timeout_seconds).until(token_is_available)
        return str(token)
    finally:
        driver.quit()
