"""Customisations on the loguru logger."""

import sys

from loguru import logger

from pi_rec.config import get_settings

settings = get_settings()

logger.remove(0)
logger.add(
    settings.logging.log_file_path,
    level="DEBUG",
    rotation="500 mb",
    enqueue=True,
    backtrace=True,
    diagnose=True,
)
logger.add(sys.stderr, level="DEBUG")
