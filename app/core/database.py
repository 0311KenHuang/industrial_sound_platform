import sqlite3

from .config import DATA_DIR, DB_PATH


def db() -> sqlite3.Connection:
    """Open a configured SQLite connection for one unit of work."""
    DATA_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
