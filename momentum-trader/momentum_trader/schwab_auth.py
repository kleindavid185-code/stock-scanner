"""Schwab Trader API authentication (OAuth 2) via the schwab-py library.

How Schwab auth works, in plain English:
  1. You register an "app" at developer.schwab.com and get an App Key + Secret.
  2. `login()` sends you to Schwab's website to log in and approve the app.
  3. Schwab hands back an access token (valid 30 min) and a refresh token
     (valid 7 days). schwab-py silently swaps the refresh token for new access
     tokens, and every time it does we save the result to .env.
  4. After 7 days the refresh token dies and you must run `login` again.
     Schwab does not allow extending this -- it is a Schwab security rule.

The token is ONLY ever stored in .env (never a separate file, never in code).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from . import envstore
from .eventlog import log_error, log_event
from .paths import DATA_DIR, ENV_FILE

REFRESH_TOKEN_LIFETIME_S = 7 * 24 * 3600
REFRESH_WARNING_S = 24 * 3600  # warn when less than a day is left

# schwab-py requires a token_path argument even when we supply our own write
# function (it then never uses it). We point it at a harmless path in data/
# -- never at .env -- so nothing could ever overwrite your .env with raw JSON.
_UNUSED_TOKEN_PATH = str(DATA_DIR / "unused-token-path-tokens-live-in-dotenv")


class AuthError(RuntimeError):
    """Something about Schwab credentials or tokens needs your attention."""


@dataclass(frozen=True)
class Credentials:
    app_key: str
    app_secret: str
    callback_url: str
    account_hash: str


def load_credentials(env_path=ENV_FILE) -> Credentials:
    if not env_path.exists():
        raise AuthError(
            f"No .env file found at {env_path}.\n"
            "Copy .env.example to .env and fill in SCHWAB_APP_KEY, "
            "SCHWAB_APP_SECRET and SCHWAB_CALLBACK_URL.")
    env = envstore.read_env(env_path)
    missing = [k for k in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL")
               if not env.get(k, "").strip()]
    if missing:
        raise AuthError(f"Missing in .env: {', '.join(missing)}")
    return Credentials(
        app_key=env["SCHWAB_APP_KEY"].strip(),
        app_secret=env["SCHWAB_APP_SECRET"].strip(),
        callback_url=env["SCHWAB_CALLBACK_URL"].strip(),
        account_hash=env.get("SCHWAB_ACCOUNT_HASH", "").strip(),
    )


def check_callback_url(url: str, manual: bool) -> list[str]:
    """Return a list of problems with the callback URL (empty = fine)."""
    problems = []
    p = urlparse(url)
    if p.scheme != "https":
        problems.append("Callback URL must start with https://")
    if not manual:
        if p.hostname != "127.0.0.1":
            problems.append("For the browser login flow the callback host must be 127.0.0.1 "
                            "(not 'localhost'). Use --manual for any other callback URL.")
        if p.port is None:
            problems.append("For the browser login flow the callback URL needs a port, "
                            "e.g. https://127.0.0.1:8182")
    return problems


# ---- token age ---------------------------------------------------------------

def token_seconds_left(token: dict | None, now: float | None = None) -> float | None:
    """Seconds until the 7-day refresh token expires (None if no token)."""
    if not token or "creation_timestamp" not in token:
        return None
    now = time.time() if now is None else now
    return token["creation_timestamp"] + REFRESH_TOKEN_LIFETIME_S - now


def describe_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {rem // 60}m"


# ---- clients ------------------------------------------------------------------

def _import_schwab():
    try:
        import schwab  # noqa: F401
        from schwab import auth
    except ImportError as exc:
        raise AuthError("schwab-py is not installed. Run: pip install -r requirements.txt") from exc
    return auth


def _token_writer(env_path):
    def write(token, *args, **kwargs):
        envstore.write_token(token, env_path)
        log_event("auth", "Schwab token saved to .env (refreshed or new)")
    return write


def login(manual: bool = False, env_path=ENV_FILE):
    """Run the interactive Schwab OAuth login and save the token to .env."""
    creds = load_credentials(env_path)
    problems = check_callback_url(creds.callback_url, manual)
    if problems:
        raise AuthError("Callback URL problem:\n  - " + "\n  - ".join(problems))
    auth = _import_schwab()
    log_event("auth", "Starting Schwab login", flow="manual" if manual else "browser")
    try:
        if manual:
            client = auth.client_from_manual_flow(
                creds.app_key, creds.app_secret, creds.callback_url, _UNUSED_TOKEN_PATH,
                token_write_func=_token_writer(env_path))
        else:
            client = auth.client_from_login_flow(
                creds.app_key, creds.app_secret, creds.callback_url, _UNUSED_TOKEN_PATH,
                token_write_func=_token_writer(env_path), interactive=True)
    except Exception as exc:
        log_error("Schwab login failed", exc)
        raise AuthError(f"Schwab login failed: {exc}") from exc
    log_event("auth", "Schwab login succeeded")
    return client


def get_client(env_path=ENV_FILE):
    """Build an API client from the token in .env (no browser needed)."""
    creds = load_credentials(env_path)
    token = envstore.read_token(env_path)
    if token is None:
        raise AuthError("No Schwab token in .env yet. Run: python trader.py auth login")
    left = token_seconds_left(token)
    if left is not None and left <= 0:
        raise AuthError("Your Schwab token is older than 7 days and has expired. "
                        "Run: python trader.py auth login")
    if left is not None and left < REFRESH_WARNING_S:
        log_event("auth", "Schwab token expires soon -- run `auth login` before it does",
                  level=30, expires_in=describe_seconds(left))
    auth = _import_schwab()
    return auth.client_from_access_functions(
        creds.app_key, creds.app_secret,
        token_read_func=lambda: envstore.read_token(env_path),
        token_write_func=_token_writer(env_path))


# ---- accounts (read-only) -------------------------------------------------------

def _mask(account_number: str) -> str:
    return "****" + account_number[-3:] if account_number else "?"


def list_accounts(client) -> list[dict]:
    """Linked accounts with type and balances. Read-only; places no orders."""
    resp = client.get_account_numbers()
    resp.raise_for_status()
    accounts = []
    for entry in resp.json():
        acct_resp = client.get_account(entry["hashValue"])
        acct_resp.raise_for_status()
        sa = acct_resp.json().get("securitiesAccount", {})
        bal = sa.get("currentBalances", {})
        accounts.append({
            "masked_number": _mask(entry.get("accountNumber", "")),
            "hash": entry["hashValue"],
            "type": sa.get("type", "UNKNOWN"),
            "closing_only_restricted": sa.get("isClosingOnlyRestricted"),
            "cash_balance": bal.get("cashBalance"),
            "cash_available_for_trading": bal.get("cashAvailableForTrading"),
            "unsettled_cash": bal.get("unsettledCash"),
            "liquidation_value": bal.get("liquidationValue"),
        })
    return accounts


def save_account_hash(account_hash: str, env_path=ENV_FILE) -> None:
    envstore.update_env({"SCHWAB_ACCOUNT_HASH": account_hash}, env_path)
    log_event("auth", "Trading account selected and saved to .env")
