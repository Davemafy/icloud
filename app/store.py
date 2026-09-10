"""Compatibility shim. Production state is persisted in SQLite via app.db.DB."""
from .db import DB

STORE = DB
