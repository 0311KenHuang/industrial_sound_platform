from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from ..core.auth import current_user
from ..schemas import AlertHandleRequest
from ..services.alerts import get_alert, handle_alert, list_alerts


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def alerts(
    status: Optional[str] = None,
    level: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return list_alerts(status, level, page, page_size)


@router.get("/{alert_id}")
def alert_detail(
    alert_id: int,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return get_alert(alert_id)


@router.put("/{alert_id}/handle")
def update_alert(
    alert_id: int,
    request: AlertHandleRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return handle_alert(alert_id, request.status, request.remark, user["username"])


@router.patch("/{alert_id}/ack")
def acknowledge_alert(
    alert_id: int,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return handle_alert(alert_id, "处理中", "已确认告警", user["username"])
