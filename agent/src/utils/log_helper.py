"""UTC logging helper — one root configuration shared by every module."""

from __future__ import annotations

import logging
import os
import time

_FORMAT = "%(asctime)s UTC | %(levelname)-8s | %(name)s | %(message)s"


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime


def _configure_root() -> None:
    root = logging.getLogger()
    if not any(getattr(h, "_attendance_utc", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(_UTCFormatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
        handler._attendance_utc = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    # Read directly: config.py imports this module, so this module cannot depend on config.py.
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    # Azure SDKs log every HTTP request at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)
