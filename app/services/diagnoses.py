"""Read-only diagnosis queries shared by device and diagnosis endpoints."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from ..core.database import db
from .catalog import row_dict


def list_diagnoses(
    device_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    fault: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a paginated diagnosis list using the existing API shape."""
    clauses, params = ["1=1"], []
    if device_id:
        clauses.append("device_id=?")
        params.append(device_id)
    if fault:
        clauses.append("fault=?")
        params.append(fault)
    with db() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM diagnoses WHERE {' AND '.join(clauses)}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM diagnoses WHERE {' AND '.join(clauses)} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [row_dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
