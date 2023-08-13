"""
Root package
"""
import sys
import logging
from pathlib import Path

__version__ = '0.0.0'


def get_package_root():
    """
    Returns:
        str: root path of this package
    """
    return Path(__file__).parents[2]


def _get_logger():
    formatter = logging.Formatter('[%(asctime)s] %(name)s / %(levelname)s -- %(message)s')

    logger = logging.getLogger('wolverine')
    logger.setLevel(logging.DEBUG)
    # ensure we don't create a new handler each time the package is reloaded
    if len(logger.handlers) == 0:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


log = _get_logger()

