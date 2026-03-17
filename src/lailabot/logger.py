import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(
    log_dir: str = "~/.lailabot/logs",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 9,  # ~3 days at reasonable usage
) -> logging.Logger:
    log_dir = os.path.expanduser(log_dir)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("lailabot")
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers to allow reconfiguration
    for h in logger.handlers[:]:
        logger.removeHandler(h)
        h.close()

    handler = RotatingFileHandler(
        os.path.join(log_dir, "lailabot.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
