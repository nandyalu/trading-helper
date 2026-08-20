"""Logging that survives the container.

``logging.basicConfig`` writes to stdout and nowhere else, which means the
entire history lives in Docker's log for one container. Recreate the container
— a rebuild, a compose change, a volume swap — and every line is gone.

That is not a theoretical loss. On 2026-08-20 two positions were found holding
no exits, and the run that placed them had already been erased, so why the
exits never rested had to be reconstructed from prices and ledger rows instead
of read from the line the code had already written. The app logged the answer
and then threw it away.

So logs go to the data volume as well as to stdout. Same directory as the
database, which is the one place already guaranteed to persist, and the same
rotation policy regardless of how the container is managed.

Rotation is by size rather than by day: a quiet weekend would otherwise
retire six mostly-empty files and push a busy Monday out of the window.
"""
import logging
import logging.handlers
import os

# Beside trading.db, in the volume that already survives a rebuild.
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")
LOG_FILE = os.path.join(LOG_DIR, "trading-bot.log")

# Ten files of 5 MB. At the volume this app produces — a few hundred lines a
# day, plus a burst per analysis — that is comfortably more than a month, which
# is longer than the trade horizon it exists to explain.
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 10

# Timestamp, level, logger, message. The logger name is what makes a line
# searchable: every module here is named trading-bot.<something>.
FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"


def configure(level: int = logging.INFO) -> str | None:
    """Attach a rotating file handler to the root logger, beside stdout.

    Returns the path being written to, or None when the directory could not be
    created — a filesystem that refuses the log must not stop the app from
    trading. Idempotent: calling it twice does not double every line.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            return getattr(handler, "baseFilename", None)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        # Deliberately not raising. Losing the log is bad; refusing to start
        # because of it is worse.
        logging.getLogger("trading-bot.logsetup").exception(
            "Could not open %s — logging to stdout only", LOG_FILE
        )
        return None

    handler.setFormatter(logging.Formatter(FORMAT))
    handler.setLevel(level)
    root.addHandler(handler)
    if root.level > level:
        root.setLevel(level)
    return handler.baseFilename
