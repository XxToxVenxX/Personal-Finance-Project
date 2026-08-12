import logging
from pathlib import Path

from pipeline_config import LOG_FILE_PATH, LOG_LEVEL, LOG_TO_CONSOLE

PIPELINE_LOGGER_NAME = "finance_pipeline"
LOG_FILE_FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
LOG_CONSOLE_FORMAT = "%(message)s"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_pipeline_logging():
    logger = logging.getLogger(PIPELINE_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    logger.propagate = False

    log_file_path = Path(LOG_FILE_PATH)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FILE_FORMAT, LOG_TIMESTAMP_FORMAT))
    logger.addHandler(file_handler)

    if LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(LOG_CONSOLE_FORMAT))
        logger.addHandler(console_handler)

    return logger


def get_pipeline_logger():
    return logging.getLogger(PIPELINE_LOGGER_NAME)