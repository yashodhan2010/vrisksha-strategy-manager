from __future__ import annotations

import os
import time
from urllib.parse import parse_qs, urlparse

from app import config
from app.execution.kite_session import get_login_url


def request_token_from_url(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    tokens = query.get("request_token")
    return tokens[0] if tokens else None


def is_auto_login_configured() -> bool:
    return bool(_auto_login_credentials())


def capture_request_token(timeout_seconds: int = config.SELENIUM_LOGIN_TIMEOUT_SECONDS) -> str:
    """Open Kite login and wait until the redirect URL contains request_token."""
    auto_token = capture_request_token_auto(timeout_seconds)
    if auto_token:
        return auto_token

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


def capture_request_token_auto(timeout_seconds: int = config.SELENIUM_LOGIN_TIMEOUT_SECONDS) -> str | None:
    credentials = _auto_login_credentials()
    if credentials is None:
        return None
    user_id, password, totp_secret = credentials
    try:
        import pyotp
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise ImportError("selenium and pyotp are required. Run pip install -r requirements.txt.") from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    options.add_argument("--disable-extensions")
    options.add_argument("--log-level=3")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(timeout_seconds)
    wait = WebDriverWait(driver, timeout_seconds)
    try:
        driver.get(get_login_url())

        user_id_field = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']#userid, input#userid"))
        )
        user_id_field.clear()
        user_id_field.send_keys(user_id)

        password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']#password, input#password")
        password_field.clear()
        password_field.send_keys(password)

        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "input[type='number'], input[type='text']#userid, input[label='External TOTP'], input.su-input-field",
                )
            )
        )
        time.sleep(1)
        totp_field = _first_visible_input(driver)
        if totp_field is None:
            raise ValueError("Could not find visible Kite TOTP input field.")

        totp_code = pyotp.TOTP(totp_secret).now()
        totp_field.clear()
        totp_field.send_keys(totp_code)

        time.sleep(1)
        for button in driver.find_elements(By.CSS_SELECTOR, "button[type='submit']"):
            if button.is_displayed():
                button.click()
                break

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            token = request_token_from_url(driver.current_url)
            if token:
                return token
            error = _visible_login_error(driver)
            if error:
                raise ValueError(f"Kite login error: {error}")
            time.sleep(1)
        raise ValueError(f"Timed out waiting for Kite redirect. Current URL: {driver.current_url}")
    finally:
        driver.quit()


def _auto_login_credentials() -> tuple[str, str, str] | None:
    user_id = os.getenv("KITE_USER_ID", "").strip()
    password = os.getenv("KITE_PASSWORD", "").strip()
    totp_secret = os.getenv("KITE_TOTP_SECRET", "").strip().replace(" ", "")
    if not user_id or not password or not totp_secret:
        return None
    return user_id, password, totp_secret


def _first_visible_input(driver: object) -> object | None:
    from selenium.webdriver.common.by import By

    for field in driver.find_elements(By.CSS_SELECTOR, "input[type='number'], input[type='text'], input.su-input-field"):
        if field.is_displayed():
            return field
    return None


def _visible_login_error(driver: object) -> str | None:
    from selenium.webdriver.common.by import By

    for element in driver.find_elements(By.CSS_SELECTOR, ".error-message, .status-message.error, .su-message"):
        if element.is_displayed() and element.text.strip():
            return element.text.strip()
    return None
