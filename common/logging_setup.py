"""
logging_setup.py
The one place that decides how this project's log files are written.

Every job (python -m middleware.<job>) and the API's own loggers write a
rotating file named after an entry in logfiles.LOG_NAMES, in LOG_DIR. The
API's Logs page reads those same files, so the name, folder and rotation
count all come from logfiles - add a new log by adding its name to
logfiles.LOG_NAMES, nowhere else.

    from common.logging_setup import setup_job_logging
    setup_job_logging("sweep")                       # a command-line job

    from common.logging_setup import setup_named_logger
    setup_named_logger("api.staging", "staging")     # a logger inside the API
"""
import logging
from logging.handlers import RotatingFileHandler

from . import logfiles

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 5_000_000  # rotate at about 5 MB; logfiles.MAX_BACKUPS copies are kept


def make_file_handler(log_name):
    """A rotating-file handler for logs/<log_name>.log, already formatted."""
    path = logfiles.log_path(log_name)  # also rejects names not in LOG_NAMES
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=logfiles.MAX_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def setup_job_logging(log_name):
    """Root logging for a command-line job: INFO to the console and to
    <log_name>.log. Call once, from the job's __main__ block."""
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(), make_file_handler(log_name)],
    )


def setup_named_logger(logger_name, log_name):
    """A dedicated logger that writes only to <log_name>.log (it does not also
    reach the root logger). For loggers inside the long-running API process,
    which has no console to watch. Safe to call more than once."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(make_file_handler(log_name))
    return logger
