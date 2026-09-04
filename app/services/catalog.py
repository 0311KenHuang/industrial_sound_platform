"""Shared device and maintainer data access helpers.

This module intentionally contains small, side-effect-free helpers only.  The
HTTP routers own request/response concerns while workflow code can reuse the
same validation and serialization rules without importing ``main``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ..core.database import db


def row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a SQLite row and decode the JSON columns used by the API."""
    item = dict(row)
    for key in ("rated_params", "features"):
        if key in item and isinstance(item[key], str):
            try:
                item[key] = json.loads(item[key])
            except Exception:
                pass
    return item


def get_device(device_id: str, include_inactive: bool = False) -> Dict[str, Any]:
    """Load an active device by id, or raise the API's standard 404 error."""
    active_clause = "" if include_inactive else " AND is_active=1"
    with db() as connection:
        row = connection.execute(
            f"SELECT * FROM devices WHERE id=?{active_clause}", (device_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "设备不存在")
    return row_dict(row)


def normalize_phone(phone: str) -> str:
    """Normalize and validate a mainland China mobile number."""
    value = re.sub(r"[\s-]+", "", str(phone or ""))
    if value.startswith("+86"):
        value = value[3:]
    elif value.startswith("0086"):
        value = value[4:]
    if not re.fullmatch(r"1[3-9]\d{9}", value):
        raise HTTPException(422, "手机号格式无效，仅支持中国大陆 11 位手机号")
    return value


def mask_phone(phone: Optional[str]) -> str:
    """Return the display-safe form of a phone number."""
    value = str(phone or "")
    if len(value) == 11 and value.isdigit():
        return f"{value[:3]}****{value[-4:]}"
    if len(value) > 4:
        return "*" * max(4, len(value) - 4) + value[-4:]
    return "****"


def maintainer_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Serialize a maintainer without exposing the stored phone number."""
    item = dict(row)
    masked = mask_phone(item.pop("phone", None))
    # Keep the existing ``phone`` key for frontend compatibility while making
    # the masking contract explicit through ``phone_masked`` as well.
    item["phone"] = masked
    item["phone_masked"] = masked
    if "is_active" in item:
        item["is_active"] = bool(item["is_active"])
    return item


def lookup_maintainer(
    connection: sqlite3.Connection,
    maintainer_id: int,
    require_active: bool = False,
) -> sqlite3.Row:
    """Load a maintainer and optionally require it to be active."""
    if maintainer_id <= 0:
        raise HTTPException(422, "维检人员编号无效")
    row = connection.execute(
        "SELECT * FROM maintainers WHERE id=?", (maintainer_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "维检人员不存在")
    if require_active and not row["is_active"]:
        raise HTTPException(409, "该维检人员已停用，不能新建或改派工单")
    return row
