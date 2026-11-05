"""Read and update the project's .env file safely.

Your Schwab app key, secret and OAuth token all live in `.env`. This module:
  * reads it with python-dotenv,
  * updates individual keys in place (keeping your comments and order),
  * writes atomically (temp file + rename) so a crash can't corrupt it,
  * locks the file so the dashboard and the bot can't write it at the same time,
  * sets owner-only permissions (chmod 600) on macOS/Linux.

The OAuth token is stored base64-encoded JSON in SCHWAB_TOKEN so it fits on one
line with no quoting problems.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import tempfile
from pathlib import Path

from dotenv import dotenv_values

from .paths import ENV_FILE

TOKEN_KEY = "SCHWAB_TOKEN"
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_+/=:.\-@]*$")
_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


@contextlib.contextmanager
def _locked(path: Path):
    """Exclusive lock on a sidecar lock file (best effort on Windows)."""
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a+") as fh:
        try:
            import fcntl  # macOS / Linux
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        except ImportError:  # Windows
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    return {k: (v or "") for k, v in dotenv_values(path).items()}


def _format_value(value: str) -> str:
    if _SAFE_VALUE.match(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env(updates: dict[str, str | None], path: Path = ENV_FILE) -> None:
    """Set (or, with value None, blank out) keys in .env, preserving everything else."""
    for key in updates:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"Invalid env key: {key!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        remaining = dict(updates)
        out: list[str] = []
        for line in lines:
            m = _KEY_LINE.match(line)
            if m and m.group(1) in remaining:
                key = m.group(1)
                value = remaining.pop(key)
                out.append(f"{key}={_format_value(value or '')}")
            else:
                out.append(line)
        for key, value in remaining.items():
            out.append(f"{key}={_format_value(value or '')}")

        fd, tmp = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out) + "\n")
            _restrict_permissions(Path(tmp))
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
    _restrict_permissions(path)


def _restrict_permissions(path: Path) -> None:
    with contextlib.suppress(OSError, NotImplementedError):
        os.chmod(path, 0o600)


def permissions_ok(path: Path = ENV_FILE) -> bool:
    """True if no one but the owner can read .env (always True on Windows)."""
    if os.name == "nt" or not path.exists():
        return True
    return (path.stat().st_mode & 0o077) == 0


# ---- token helpers ---------------------------------------------------------

def encode_token(token: dict) -> str:
    raw = json.dumps(token, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_token(value: str) -> dict:
    return json.loads(base64.b64decode(value.encode("ascii")).decode("utf-8"))


def read_token(path: Path = ENV_FILE) -> dict | None:
    value = read_env(path).get(TOKEN_KEY, "")
    if not value:
        return None
    try:
        return decode_token(value)
    except (ValueError, json.JSONDecodeError):
        return None


def write_token(token: dict, path: Path = ENV_FILE) -> None:
    update_env({TOKEN_KEY: encode_token(token)}, path)


def clear_token(path: Path = ENV_FILE) -> None:
    update_env({TOKEN_KEY: None}, path)
