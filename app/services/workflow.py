"""Small workflow state helpers shared by diagnosis and alert handling."""

from __future__ import annotations

import sqlite3


def recover_device_if_clear(
    connection: sqlite3.Connection,
    device_id: str,
    now: str,
) -> bool:
    """Recover a device only when no active alert or unfinished order remains."""
    active_alert = connection.execute(
        "SELECT 1 FROM alerts WHERE device_id=? AND status!='已关闭' LIMIT 1",
        (device_id,),
    ).fetchone()
    unfinished_order = connection.execute(
        """
        SELECT 1 FROM work_orders
        WHERE device_id=?
          AND (status IN ('待分配','处理中')
               OR (status='已完成' AND recheck_status='pending'))
        LIMIT 1
        """,
        (device_id,),
    ).fetchone()
    if active_alert or unfinished_order:
        connection.execute(
            "UPDATE devices SET last_seen=? WHERE id=?", (now, device_id)
        )
        return False
    connection.execute(
        "UPDATE devices SET status='online',health=96,last_seen=? WHERE id=?",
        (now, device_id),
    )
    return True
