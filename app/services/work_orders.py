"""Work-order queries, creation and state transitions."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import HTTPException

from ..core.database import db
from ..schemas import WorkOrderRequest, WorkOrderTransition
from ..signal import FAULTS
from .catalog import get_device, lookup_maintainer, mask_phone, row_dict


SmsSender = Callable[[int, str, Union[str, Dict[str, Any]]], Dict[str, Any]]
SmsSerializer = Callable[[sqlite3.Row], Dict[str, Any]]


class WorkOrderService:
    """Own work-order persistence while receiving SMS delivery as a callback."""

    def __init__(
        self,
        sms_sender: Optional[SmsSender] = None,
        sms_serializer: Optional[SmsSerializer] = None,
    ) -> None:
        self.sms_sender = sms_sender
        self.sms_serializer = sms_serializer

    def _send_sms(
        self,
        order_id: int,
        event_type: str,
        triggered_by: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.sms_sender is None:
            raise RuntimeError("工单服务尚未配置短信发送器")
        return self.sms_sender(order_id, event_type, triggered_by)

    def _serialize_sms(self, row: sqlite3.Row) -> Dict[str, Any]:
        if self.sms_serializer is not None:
            return self.sms_serializer(row)
        # This fallback is only used during unusual direct service usage.  It
        # still masks the phone number instead of leaking the stored value.
        item = dict(row)
        masked = mask_phone(item.pop("phone", None))
        item["phone"] = masked
        item["phone_masked"] = masked
        item["message_id"] = item.get("id")
        return item

    def create_order(
        self,
        request: WorkOrderRequest,
        user: Dict[str, Any],
        status: str = "待分配",
    ) -> Dict[str, Any]:
        get_device(request.device_id)
        now = datetime.now().isoformat(timespec="seconds")
        existing_id = None
        order_id = None
        assigned_on_create = False
        with db() as connection:
            # Serialize lookup and insert so two quick clicks cannot create a
            # second work order for the same alert.
            connection.execute("BEGIN IMMEDIATE")
            diagnosis_id = request.diagnosis_id
            maintainer = None
            if request.assignee_id is not None:
                maintainer = lookup_maintainer(
                    connection, request.assignee_id, require_active=True
                )
            if request.alert_id is not None:
                alert = connection.execute(
                    "SELECT id,diagnosis_id,device_id,status FROM alerts WHERE id=?",
                    (request.alert_id,),
                ).fetchone()
                if not alert:
                    raise HTTPException(404, "关联告警不存在")
                if alert["device_id"] != request.device_id:
                    raise HTTPException(400, "告警与设备不匹配")
                if diagnosis_id is None:
                    diagnosis_id = alert["diagnosis_id"]
                elif diagnosis_id != alert["diagnosis_id"]:
                    raise HTTPException(400, "告警与诊断记录不匹配")
                existing = connection.execute(
                    "SELECT id FROM work_orders WHERE alert_id=? ORDER BY id ASC LIMIT 1",
                    (request.alert_id,),
                ).fetchone()
                if existing:
                    existing_id = existing["id"]
            if diagnosis_id is not None:
                diagnosis = connection.execute(
                    "SELECT id,device_id FROM diagnoses WHERE id=?", (diagnosis_id,)
                ).fetchone()
                if not diagnosis:
                    raise HTTPException(404, "关联诊断记录不存在")
                if diagnosis["device_id"] != request.device_id:
                    raise HTTPException(400, "诊断记录与设备不匹配")
            if existing_id is None:
                order_code = f"WO-{datetime.now():%Y%m%d%H%M%S}-{secrets.randbelow(1000):03d}"
                assignee_name = (
                    maintainer["name"]
                    if maintainer
                    else (request.assignee.strip() or "待分配")
                )
                effective_status = (
                    "处理中" if maintainer and status == "待分配" else status
                )
                cursor = connection.execute(
                    "INSERT INTO work_orders(order_code,diagnosis_id,alert_id,device_id,title,description,priority,status,assignee,assignee_id,recheck_status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        order_code,
                        diagnosis_id,
                        request.alert_id,
                        request.device_id,
                        request.title,
                        request.description,
                        request.priority,
                        effective_status,
                        assignee_name,
                        request.assignee_id,
                        "not_required",
                        user["username"],
                        now,
                    ),
                )
                order_id = cursor.lastrowid
                assigned_on_create = maintainer is not None
                connection.execute(
                    "INSERT INTO work_order_logs(work_order_id,operator_id,action,from_status,to_status,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        order_id,
                        user["username"],
                        "创建并分配" if maintainer else "创建",
                        None,
                        effective_status,
                        "系统创建并分配工单" if maintainer else "系统创建工单",
                        now,
                    ),
                )
                if diagnosis_id is not None:
                    connection.execute(
                        "UPDATE diagnoses SET work_order_id=? WHERE id=?",
                        (order_id, diagnosis_id),
                    )
                if request.alert_id is not None:
                    connection.execute(
                        "UPDATE alerts SET status='处理中' WHERE id=? AND status!='已关闭'",
                        (request.alert_id,),
                    )
        target_id = existing_id if existing_id is not None else order_id
        notifications: List[Dict[str, Any]] = []
        if assigned_on_create and target_id is not None:
            notifications.append(self._send_sms(target_id, "assigned", user))
        return self.get_order(target_id, notifications)

    def list_orders(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        assignee_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        for field, value in (
            ("status", status),
            ("priority", priority),
            ("assignee", assignee),
        ):
            if value:
                clauses.append(f"{field}=?")
                params.append(value)
        if assignee_id is not None:
            clauses.append("assignee_id=?")
            params.append(assignee_id)
        with db() as connection:
            rows = connection.execute(
                f"SELECT * FROM work_orders WHERE {' AND '.join(clauses)} "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
            total = connection.execute(
                f"SELECT COUNT(*) FROM work_orders WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()[0]
            items = []
            for row in rows:
                item = row_dict(row)
                maintainer = (
                    connection.execute(
                        "SELECT name,phone FROM maintainers WHERE id=?",
                        (row["assignee_id"],),
                    ).fetchone()
                    if row["assignee_id"] is not None
                    else None
                )
                item["assignee_name"] = (
                    maintainer["name"] if maintainer else row["assignee"]
                )
                item["assignee_phone_masked"] = (
                    mask_phone(maintainer["phone"]) if maintainer else None
                )
                item["recheck_required"] = row["status"] == "已完成" and row[
                    "recheck_status"
                ] in ("pending", "failed")
                items.append(item)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def _compact_diagnosis(
        row: Optional[sqlite3.Row],
    ) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        report = {}
        try:
            parsed = json.loads(row["report"] or "{}")
            if isinstance(parsed, dict):
                report = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return {
            "id": row["id"],
            "fault": row["fault"],
            "fault_label": report.get(
                "fault_label", FAULTS.get(row["fault"], {}).get("label", row["fault"])
            ),
            "confidence": row["confidence"],
            "severity": row["severity"],
            "model_version": row["model_version"],
            "summary": report.get("summary", ""),
            "created_at": row["created_at"],
            "report_url": f"/api/diagnostics/{row['id']}/report",
        }

    @staticmethod
    def _compact_alert(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        return {
            "id": row["id"],
            "alert_code": row["alert_code"],
            "status": row["status"],
            "level": row["level"],
            "severity": row["severity"],
            "title": row["title"],
            "created_at": row["created_at"],
        }

    def get_order(
        self,
        order_id: int,
        notifications: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        with db() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders WHERE id=?", (order_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "工单不存在")
            logs = connection.execute(
                "SELECT * FROM work_order_logs WHERE work_order_id=? ORDER BY id",
                (order_id,),
            ).fetchall()
            maintainer = (
                connection.execute(
                    "SELECT * FROM maintainers WHERE id=?", (row["assignee_id"],)
                ).fetchone()
                if row["assignee_id"] is not None
                else None
            )
            diagnosis_row = (
                connection.execute(
                    "SELECT * FROM diagnoses WHERE id=?", (row["diagnosis_id"],)
                ).fetchone()
                if row["diagnosis_id"] is not None
                else None
            )
            alert_row = (
                connection.execute(
                    "SELECT * FROM alerts WHERE id=?", (row["alert_id"],)
                ).fetchone()
                if row["alert_id"] is not None
                else None
            )
            recheck_row = connection.execute(
                "SELECT * FROM diagnoses WHERE work_order_id=? AND id!=? "
                "ORDER BY id DESC LIMIT 1",
                (order_id, row["diagnosis_id"] or -1),
            ).fetchone()
            sms_rows = connection.execute(
                "SELECT sm.*, m.name AS maintainer_name FROM sms_messages sm "
                "LEFT JOIN maintainers m ON m.id=sm.maintainer_id "
                "WHERE sm.work_order_id=? ORDER BY sm.id DESC",
                (order_id,),
            ).fetchall()
        result = row_dict(row)
        result["assignee_name"] = maintainer["name"] if maintainer else row["assignee"]
        result["assignee_phone_masked"] = (
            mask_phone(maintainer["phone"]) if maintainer else None
        )
        result["diagnosis"] = self._compact_diagnosis(diagnosis_row)
        result["alert"] = self._compact_alert(alert_row)
        result["recheck_status"] = row["recheck_status"]
        result["recheck_required"] = row["status"] == "已完成" and (
            row["recheck_status"] in ("pending", "failed")
            or bool(alert_row and alert_row["status"] != "已关闭")
        )
        result["recheck_diagnosis"] = self._compact_diagnosis(recheck_row)
        result["sms_messages"] = [self._serialize_sms(item) for item in sms_rows]
        result["sms_notifications"] = notifications or []
        result["logs"] = [row_dict(item) for item in logs]
        return result

    def process_order(
        self,
        order_id: int,
        request: WorkOrderTransition,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        valid = ("待分配", "处理中", "已完成", "已关闭")
        if request.status not in valid:
            raise HTTPException(400, "无效的工单状态")
        current = self.get_order(order_id)
        next_status = {
            "待分配": "处理中",
            "处理中": "已完成",
            "已完成": "已关闭",
            "已关闭": "已关闭",
        }.get(current["status"])
        if next_status is None:
            raise HTTPException(409, f"工单当前状态“{current['status']}”不受支持")
        if request.status not in (current["status"], next_status):
            raise HTTPException(
                409,
                f"工单状态不能从“{current['status']}”回退或跳转到“{request.status}”，"
                f"下一步应为“{next_status}”",
            )
        now = datetime.now().isoformat(timespec="seconds")
        notifications: List[Dict[str, Any]] = []
        status_changed = request.status != current["status"]
        assignment_changed = False
        with db() as connection:
            order = connection.execute(
                "SELECT * FROM work_orders WHERE id=?", (order_id,)
            ).fetchone()
            if not order:
                raise HTTPException(404, "工单不存在")
            target_assignee_id = order["assignee_id"]
            target_assignee = order["assignee"]
            if request.assignee_id is not None:
                assignment_changed = request.assignee_id != order["assignee_id"]
                maintainer = lookup_maintainer(
                    connection,
                    request.assignee_id,
                    require_active=assignment_changed,
                )
                target_assignee_id = request.assignee_id
                target_assignee = maintainer["name"]
            elif request.assignee and order["assignee_id"] is None:
                target_assignee = request.assignee.strip() or order["assignee"]
                assignment_changed = target_assignee != order["assignee"]
            if request.status == current["status"] and not assignment_changed:
                return self.get_order(order_id)
            alert = (
                connection.execute(
                    "SELECT id,status FROM alerts WHERE id=?", (order["alert_id"],)
                ).fetchone()
                if order["alert_id"] is not None
                else None
            )
            if request.status == "已关闭" and alert and alert["status"] != "已关闭":
                raise HTTPException(409, "请先完成复检，复检通过后才能关闭关联工单")
            recheck_status = order["recheck_status"]
            if request.status == "已完成" and alert and alert["status"] != "已关闭":
                recheck_status = "pending"
            if request.status == "已完成" and not alert:
                recheck_status = "not_required"
            if request.status == "已关闭" and alert and alert["status"] == "已关闭":
                recheck_status = "passed"
            completed_at = order["completed_at"]
            if request.status in ("已完成", "已关闭") and not completed_at:
                completed_at = now
            connection.execute(
                "UPDATE work_orders SET status=?,assignee=?,assignee_id=?,recheck_status=?,completed_at=? WHERE id=?",
                (
                    request.status,
                    target_assignee,
                    target_assignee_id,
                    recheck_status,
                    completed_at,
                    order_id,
                ),
            )
            if request.status == "已完成" and alert and alert["status"] == "未处理":
                connection.execute(
                    "UPDATE alerts SET status='处理中' WHERE id=?", (alert["id"],)
                )
            if assignment_changed:
                connection.execute(
                    "INSERT INTO work_order_logs(work_order_id,operator_id,action,from_status,to_status,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        order_id,
                        user["username"],
                        "改派",
                        current["status"],
                        request.status,
                        request.remark or "工单负责人已更新",
                        now,
                    ),
                )
            elif status_changed:
                connection.execute(
                    "INSERT INTO work_order_logs(work_order_id,operator_id,action,from_status,to_status,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        order_id,
                        user["username"],
                        "状态变更",
                        current["status"],
                        request.status,
                        request.remark,
                        now,
                    ),
                )
        if assignment_changed and request.assignee_id is not None:
            notifications.append(self._send_sms(order_id, "assigned", user))
        elif (
            request.status != current["status"]
            and current["status"] == "待分配"
            and current.get("assignee_id") is not None
        ):
            notifications.append(self._send_sms(order_id, "assigned", user))
        if status_changed and request.status == "已完成":
            notifications.append(self._send_sms(order_id, "completed", user))
        if status_changed and request.status == "已关闭":
            notifications.append(self._send_sms(order_id, "closed", user))
        return self.get_order(order_id, notifications)
