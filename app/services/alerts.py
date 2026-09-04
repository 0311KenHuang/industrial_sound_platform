"""Alert queries and state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ..core.database import db
from ..services.catalog import row_dict
from .workflow import recover_device_if_clear


ALERT_STATUSES = ("未处理", "处理中", "已关闭")


def list_alerts(
    status: Optional[str] = None,
    level: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """Return a paginated alert list using the existing response shape."""
    clauses, params = ["1=1"], []
    if status:
        clauses.append("status=?")
        params.append(status)
    if level:
        clauses.append("level=?")
        params.append(level)
    with db() as connection:
        rows = connection.execute(
            f"SELECT * FROM alerts WHERE {' AND '.join(clauses)} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        total = connection.execute(
            f"SELECT COUNT(*) FROM alerts WHERE {' AND '.join(clauses)}", params
        ).fetchone()[0]
    return {"items": [row_dict(row) for row in rows], "total": total}


def get_alert(alert_id: int) -> Dict[str, Any]:
    """Load an alert by id or raise the standard API 404 error."""
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM alerts WHERE id=?", (alert_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "告警不存在")
    return row_dict(row)


def handle_alert(
    alert_id: int,
    status: str,
    remark: str,
    actor: str,
) -> Dict[str, Any]:
    """Apply one forward-only alert transition and return the new state."""
    if status not in ALERT_STATUSES:
        raise HTTPException(400, "无效的告警状态")
    current = get_alert(alert_id)
    next_status = {
        "未处理": "处理中",
        "处理中": "已关闭",
        "已关闭": "已关闭",
    }[current["status"]]
    if status not in (current["status"], next_status):
        raise HTTPException(
            409,
            f"告警状态不能从“{current['status']}”回退到“{status}”，"
            f"下一步应为“{next_status}”",
        )
    if status == current["status"]:
        return current

    now = datetime.now().isoformat(timespec="seconds")
    with db() as connection:
        linked_order = connection.execute(
            "SELECT id,status FROM work_orders WHERE alert_id=? ORDER BY id LIMIT 1",
            (alert_id,),
        ).fetchone()
        if status == "已关闭" and linked_order and linked_order["status"] != "已关闭":
            raise HTTPException(
                409,
                "该告警已关联工单，请先完成维修并提交复检，不能直接关闭告警",
            )
        connection.execute(
            "UPDATE alerts SET status=?,handled_at=?,handled_by=?,handle_remark=? WHERE id=?",
            (status, now, actor, remark, alert_id),
        )
        if status == "已关闭":
            recover_device_if_clear(connection, current["device_id"], now)
    return get_alert(alert_id)
