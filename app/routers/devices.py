from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import current_user
from ..core.database import db
from ..schemas import DeviceRequest
from ..services.catalog import get_device, row_dict
from ..services.diagnoses import list_diagnoses


router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("")
def list_devices(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    device_type: Optional[str] = None,
    q: Optional[str] = None,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    clauses, params = ["is_active=1"], []
    if status:
        clauses.append("status=?")
        params.append(status)
    if device_type:
        clauses.append("device_type=?")
        params.append(device_type)
    if q:
        clauses.append("(id LIKE ? OR name LIKE ? OR location LIKE ?)")
        params.extend([f"%{q}%"] * 3)
    with db() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM devices WHERE {' AND '.join(clauses)}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM devices WHERE {' AND '.join(clauses)} "
            "ORDER BY id LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [row_dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("")
def create_device(
    request: DeviceRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with db() as connection:
            connection.execute(
                "INSERT INTO devices(id,name,wind_farm,province,city,county,device_type,model,line,location,install_date,rated_params,rated_power_kw,hub_height_m,rotor_diameter_m,latitude,longitude,status,health,last_seen,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request.id,
                    request.name,
                    request.wind_farm,
                    request.province,
                    request.city,
                    request.county,
                    request.device_type,
                    request.model,
                    request.line,
                    request.location,
                    request.install_date,
                    json.dumps(request.rated_params, ensure_ascii=False),
                    request.rated_power_kw,
                    request.hub_height_m,
                    request.rotor_diameter_m,
                    request.latitude,
                    request.longitude,
                    "online",
                    100,
                    now,
                    now,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "设备编号已存在") from exc
    return get_device(request.id)


@router.get("/{device_id}")
def device_detail(
    device_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    device = get_device(device_id)
    device["diagnostics"] = list_diagnoses(
        device_id=device_id, page=1, page_size=20, fault=None
    )["items"]
    return device


@router.put("/{device_id}")
def update_device(
    device_id: str,
    request: DeviceRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    get_device(device_id)
    if request.id != device_id:
        raise HTTPException(400, "设备编号创建后不可修改，以免历史诊断和工单失去关联")
    with db() as connection:
        connection.execute(
            "UPDATE devices SET name=?,wind_farm=?,province=?,city=?,county=?,device_type=?,model=?,line=?,location=?,install_date=?,rated_params=?,rated_power_kw=?,hub_height_m=?,rotor_diameter_m=?,latitude=?,longitude=? "
            "WHERE id=? AND is_active=1",
            (
                request.name,
                request.wind_farm,
                request.province,
                request.city,
                request.county,
                request.device_type,
                request.model,
                request.line,
                request.location,
                request.install_date,
                json.dumps(request.rated_params, ensure_ascii=False),
                request.rated_power_kw,
                request.hub_height_m,
                request.rotor_diameter_m,
                request.latitude,
                request.longitude,
                device_id,
            ),
        )
    return get_device(device_id)


@router.delete("/{device_id}")
def delete_device(
    device_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    get_device(device_id)
    now = datetime.now().isoformat(timespec="seconds")
    with db() as connection:
        connection.execute(
            "UPDATE devices SET is_active=0,status='offline',health=0,last_seen=? "
            "WHERE id=? AND is_active=1",
            (now, device_id),
        )
    return {"ok": True, "id": device_id, "soft_deleted": True}
