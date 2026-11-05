#!/usr/bin/env python3
"""Momentum Trader command line.

    python trader.py settings              # check settings.toml and print a summary
    python trader.py auth login            # log in to Schwab (opens your browser)
    python trader.py auth login --manual   # log in by copy-pasting URLs instead
    python trader.py auth status           # token age, account type, settled cash
    python trader.py auth logout           # delete the saved token from .env

More commands (scan, dashboard, backtest, run, kill) arrive in later phases.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from momentum_trader import envstore, schwab_auth
from momentum_trader.eventlog import log_error, log_event, setup_logging
from momentum_trader.paths import ENV_FILE, PROJECT_DIR
from momentum_trader.settings import SettingsError, load_settings


def _money(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "n/a"


def _print_accounts(accounts: list[dict]) -> None:
    for i, a in enumerate(accounts, 1):
        print(f"  [{i}] {a['masked_number']}  type={a['type']}  "
              f"cash={_money(a['cash_balance'])}  "
              f"available-to-trade(settled)={_money(a['cash_available_for_trading'])}  "
              f"unsettled={_money(a['unsettled_cash'])}")
        if a["closing_only_restricted"]:
            print("      !! Schwab has this account on CLOSING-ONLY restriction.")
        if a["type"] != "CASH":
            print("      !! Not a CASH account. This bot's settled-funds rules assume a cash account.")


def cmd_settings(_args) -> int:
    s = load_settings()
    print("settings.toml is valid.\n")
    print(f"  mode                 : {s.app.mode}"
          f"{'  (AUTO TRADING ACTIVE)' if s.auto_trading_active else ''}")
    print(f"  auto_trading_enabled : {s.app.auto_trading_enabled}")
    print(f"  dashboard            : http://{s.dashboard.host}:{s.dashboard.port}")
    print(f"  scanner              : ${s.scanner.min_price:g}-${s.scanner.max_price:g}, "
          f"float < {s.scanner.max_float_shares:,}, RVOL > {s.scanner.min_relative_volume:g}x, "
          f"short-interest flag {'ON' if s.scanner.require_short_interest_flag else 'off'} "
          f"(>= {s.scanner.min_short_interest_pct_float:g}% of float)")
    print(f"  exits                : target +{s.exit.profit_target_pct:g}%, "
          f"stop -{s.exit.stop_loss_pct:g}%, trail {s.exit.trailing_stop_pct:g}% "
          f"(arms at +{s.exit.trailing_activation_pct:g}%), flatten at {s.exit.flatten_at} ET")
    r = s.risk
    print(f"  risk (hard limits)   : ${r.max_position_dollars:,.2f}/position, "
          f"{r.max_account_pct_per_trade:g}% of account/trade, "
          f"daily loss stop ${r.max_daily_loss_dollars:,.2f}, "
          f"{r.max_trades_per_day} trades/day, {r.max_open_positions} open max")
    print("  always on            : limit orders only, settled cash only, flat overnight")
    if s.app.mode == "auto" and not s.app.auto_trading_enabled:
        print("\n  Note: mode is 'auto' but auto_trading_enabled is false -> nothing will be sent "
              "automatically.")
    return 0


def _env_is_gitignored() -> bool | None:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(ENV_FILE)],
                           cwd=PROJECT_DIR, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 128:  # not a git repo
        return None
    return r.returncode == 0


def cmd_auth_login(args) -> int:
    print("Starting Schwab login. Only the App Key/Secret from .env are used;\n"
          "your Schwab password is typed into Schwab's own website, never here.\n")
    client = schwab_auth.login(manual=args.manual)
    print("\nLogin OK. Token saved to .env.\n")
    accounts = schwab_auth.list_accounts(client)
    if not accounts:
        print("Schwab returned no linked accounts. Did you tick an account when approving?")
        return 1
    print("Linked accounts:")
    _print_accounts(accounts)
    if len(accounts) == 1:
        chosen = accounts[0]
    else:
        while True:
            pick = input(f"\nWhich account should the bot trade? [1-{len(accounts)}]: ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(accounts):
                chosen = accounts[int(pick) - 1]
                break
    schwab_auth.save_account_hash(chosen["hash"])
    print(f"\nSelected {chosen['masked_number']} ({chosen['type']}). Saved to .env.")
    print("Remember: Schwab tokens expire after 7 days -- run `auth login` again weekly.")
    return 0


def cmd_auth_status(_args) -> int:
    ok = True
    print("Security checks")
    ignored = _env_is_gitignored()
    if ignored is False:
        ok = False
        print("  !! .env is NOT git-ignored. Do not commit until this is fixed.")
    else:
        print(f"  .env git-ignored        : {'yes' if ignored else 'n/a (not a git repo)'}")
    print(f"  .env owner-only perms   : {'yes' if envstore.permissions_ok() else 'NO -- run: chmod 600 .env'}")

    creds = schwab_auth.load_credentials()
    print(f"  app key / secret        : present")
    print(f"  callback URL            : {creds.callback_url}")

    token = envstore.read_token()
    left = schwab_auth.token_seconds_left(token)
    print("\nToken")
    if left is None:
        print("  none saved -- run: python trader.py auth login")
        return 1
    if left <= 0:
        print("  EXPIRED -- run: python trader.py auth login")
        return 1
    warn = "  <-- re-login soon" if left < schwab_auth.REFRESH_WARNING_S else ""
    print(f"  refresh token expires in: {schwab_auth.describe_seconds(left)}{warn}")

    print("\nAccount (read-only API call)")
    client = schwab_auth.get_client()
    accounts = schwab_auth.list_accounts(client)
    selected = [a for a in accounts if a["hash"] == creds.account_hash]
    if not selected:
        print("  No trading account selected yet (or it changed). Run `auth login` again.")
        _print_accounts(accounts)
        return 1
    _print_accounts(selected)
    print("\nAuth is working." if ok else "\nAuth works, but fix the security warning above.")
    return 0 if ok else 1


def cmd_auth_logout(_args) -> int:
    envstore.clear_token()
    log_event("auth", "Schwab token removed from .env (logout)")
    print("Token removed from .env. Run `auth login` to log in again.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trader.py", description="Momentum Trader")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("settings", help="validate settings.toml").set_defaults(func=cmd_settings)

    auth = sub.add_parser("auth", help="Schwab login / token management")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_sub.add_parser("login", help="log in to Schwab and save the token to .env")
    login.add_argument("--manual", action="store_true",
                       help="copy-paste URLs instead of using a local callback server")
    login.set_defaults(func=cmd_auth_login)
    auth_sub.add_parser("status", help="check token and account").set_defaults(func=cmd_auth_status)
    auth_sub.add_parser("logout", help="delete the saved token").set_defaults(func=cmd_auth_logout)
    return p


def main(argv=None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SettingsError, schwab_auth.AuthError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:  # log everything unexpected, then show it
        log_error(f"Unhandled error in `{' '.join(sys.argv[1:])}`", exc)
        raise


if __name__ == "__main__":
    sys.exit(main())
