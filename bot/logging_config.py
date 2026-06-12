"""
bot/logging_config.py

Configures application-wide logging:
  - File handler  → logs/trading_bot.log (DEBUG+, rotating 5 MB × 3 backups)
  - Console handler → stderr (WARNING+ only, keeps CLI output clean)

Usage:
    from bot.logging_config import get_logger
    logger = get_logger(__name__)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# ── Constants ────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False  # prevent duplicate handler registration


def _configure_root_logger() -> None:
    """Set up the root logger once."""
    global _configured
    if _configured:
        return

    # Ensure logs/ directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # capture everything; handlers filter

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ── File handler (rotating) ───────────────────────────────────────────
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # ── Console handler ───────────────────────────────────────────────────
    console_handler = logging.StreamHandler()  # defaults to stderr
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, ensuring logging is configured first."""
    _configure_root_logger()
    return logging.getLogger(name)
