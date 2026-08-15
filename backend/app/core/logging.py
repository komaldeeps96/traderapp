"""Logging setup."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers[:] = [handler]

    # These libraries are chatty at INFO and drown out our own logs.
    for noisy in ("httpx", "httpcore", "websockets.client", "ib_async"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
