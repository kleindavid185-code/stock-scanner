"""Every file location the bot uses, in one place.

All paths are inside this project folder, so the bot never reads or writes
anything belonging to your other scanner.
"""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = PROJECT_DIR / "settings.toml"
ENV_FILE = PROJECT_DIR / ".env"
LOG_DIR = PROJECT_DIR / "logs"
DATA_DIR = PROJECT_DIR / "data"
