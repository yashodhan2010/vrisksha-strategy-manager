from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import config

LOG_FILES = {
    "app": "app.log",
    "scheduler": "scheduler.log",
    "execution": "execution.log",
    "backtest": "backtest.log",
}


def configure_logging() -> None:
    config.ensure_runtime_directories()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        for name in LOG_FILES.values():
            handler = RotatingFileHandler(
                Path(config.LOG_DIR) / name,
                maxBytes=1_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            handler.setFormatter(formatter)
            root.addHandler(handler)

    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)

