from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.auth import current_user
from ..core.database import db
from ..schemas import MaintainerRequest, MaintainerUpdateRequest
from ..services.catalog import (
    lookup_maintainer,
    maintainer_dict,
    normalize_phone,
)


router = APIRouter(prefix="/api/maintainers", tags=["maintainers"])


@router.get("")
def list_maintainers(
    include_inactive: bool = True,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    clauses, params = ["1=1"], []
    if not include_inactive:
        clauses.append("is_active=1")
    if q:
        clauses.append("(name LIKE ? OR team LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    with db() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM maintainers WHERE {' AND '.join(clauses)}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM maintainers WHERE {' AND '.join(clauses)} "
            "ORDER BY is_active DESC,id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [maintainer_dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("")
def create_maintainer(
    request: MaintainerRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise HTTPException(422, "维检人员姓名不能为空")
    phone = normalize_phone(request.phone)
    now = datetime.now().isoformat(timespec="seconds")
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO maintainers(name,phone,team,is_active,created_at) VALUES(?,?,?,?,?)",
            (name, phone, request.team.strip(), int(request.is_active), now),
        )
        row = connection.execute(
            "SELECT * FROM maintainers WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    return maintainer_dict(row)


@router.put("/{maintainer_id}")
def update_maintainer(
    maintainer_id: int,
    request: MaintainerUpdateRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    with db() as connection:
        current = lookup_maintainer(connection, maintainer_id)
        name = current["name"] if request.name is None else request.name.strip()
        if not name:
            raise HTTPException(422, "维检人员姓名不能为空")
        phone = current["phone"] if request.phone is None else normalize_phone(request.phone)
        team = current["team"] if request.team is None else request.team.strip()
        is_active = current["is_active"] if request.is_active is None else int(request.is_active)
        connection.execute(
            "UPDATE maintainers SET name=?,phone=?,team=?,is_active=? WHERE id=?",
            (name, phone, team, is_active, maintainer_id),
        )
        row = connection.execute(
            "SELECT * FROM maintainers WHERE id=?", (maintainer_id,)
        ).fetchone()
    return maintainer_dict(row)


@router.delete("/{maintainer_id}")
def delete_maintainer(
    maintainer_id: int,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    with db() as connection:
        lookup_maintainer(connection, maintainer_id)
        connection.execute(
            "UPDATE maintainers SET is_active=0 WHERE id=?", (maintainer_id,)
        )
        row = connection.execute(
            "SELECT * FROM maintainers WHERE id=?", (maintainer_id,)
        ).fetchone()
    result = maintainer_dict(row)
    result["soft_deleted"] = True
    result["updated_at"] = now
    return result
