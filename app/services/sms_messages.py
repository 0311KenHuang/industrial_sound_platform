"""SMS message records and provider orchestration."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException

from ..core.database import db
from ..sms import SmsProviderUnavailable, get_sms_provider, render_message
from .catalog import mask_phone


SMS_STATUSES = {"pending", "sent", "failed"}
SMS_EVENTS = {"assigned", "completed", "closed"}
SMS_EVENT_LABELS = {
    "assigned": "工单分配",
    "completed": "维修完成",
    "closed": "复检通过并关闭",
}


def sms_display_status(
    status: str,
    delivery_mode: Optional[str],
    error_message: Optional[str] = None,
) -> str:
    if status == "sent":
        return "消息已发送（演示通道）" if delivery_mode == "demo" else "消息已发送"
    if status == "failed":
        return f"短信发送失败：{error_message}" if error_message else "短信发送失败"
    if status == "pending":
        return "短信发送中"
    return "未发送"


def _sms_failure_mode() -> tuple[str, str]:
    mode = os.getenv("SOUNDNET_SMS_MODE", "demo").strip().lower()
    return (
        ("demo", "demo")
        if mode in ("", "demo", "offline")
        else (mode or "unconfigured", "real")
    )


class SmsMessageService:
    """Persist, send and retry work-order SMS messages."""

    def message_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        raw_phone = item.pop("phone", None)
        masked = mask_phone(raw_phone)
        item["phone"] = masked
        item["phone_masked"] = masked
        item["event_label"] = SMS_EVENT_LABELS.get(
            item.get("event_type"), item.get("event_type")
        )
        item["delivery_label"] = (
            "演示通道" if item.get("delivery_mode") == "demo" else "真实通道"
        )
        item["display_status"] = sms_display_status(
            item.get("status", ""),
            item.get("delivery_mode"),
            item.get("error_message"),
        )
        item["message_id"] = item.get("id")
        item.pop("template_params", None)
        return item

    def _load_message(self, message_id: int) -> Optional[sqlite3.Row]:
        with db() as connection:
            return connection.execute(
                """
                SELECT sm.*, m.name AS maintainer_name
                FROM sms_messages sm
                LEFT JOIN maintainers m ON m.id=sm.maintainer_id
                WHERE sm.id=?
                """,
                (message_id,),
            ).fetchone()

    def send_work_order_sms(
        self,
        order_id: int,
        event_type: str,
        triggered_by: Union[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create/send one idempotent work-order notification."""
        if event_type not in SMS_EVENTS:
            raise ValueError(f"不支持的短信事件：{event_type}")
        actor = (
            triggered_by.get("username", "system")
            if isinstance(triggered_by, dict)
            else str(triggered_by)
        )
        with db() as connection:
            order = connection.execute(
                "SELECT wo.*, d.name AS device_name "
                "FROM work_orders wo LEFT JOIN devices d ON d.id=wo.device_id "
                "WHERE wo.id=?",
                (order_id,),
            ).fetchone()
            if not order:
                raise HTTPException(404, "工单不存在")
            if order["assignee_id"] is None:
                return {
                    "status": "skipped",
                    "display_status": "未发送：工单没有关联维检人员",
                    "reason": "没有 assignee_id",
                    "event_type": event_type,
                    "event_label": SMS_EVENT_LABELS[event_type],
                }
            maintainer = connection.execute(
                "SELECT * FROM maintainers WHERE id=?", (order["assignee_id"],)
            ).fetchone()
            if not maintainer or not maintainer["phone"]:
                return {
                    "status": "skipped",
                    "display_status": "未发送：维检人员没有可用手机号",
                    "reason": "手机号不存在",
                    "event_type": event_type,
                    "event_label": SMS_EVENT_LABELS[event_type],
                }
            params = {
                "order_code": order["order_code"],
                "title": order["title"],
                "device_name": order["device_name"] or order["device_id"],
                "priority": order["priority"],
            }
            content = render_message(event_type, params)
            idempotency_key = (
                f"work-order:{order_id}:{event_type}:{order['assignee_id']}"
            )
            existing = connection.execute(
                "SELECT sm.*, m.name AS maintainer_name FROM sms_messages sm "
                "LEFT JOIN maintainers m ON m.id=sm.maintainer_id "
                "WHERE sm.idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return self.message_dict(existing)
            try:
                provider = get_sms_provider()
                provider_name = provider.name
                delivery_mode = provider.delivery_mode
                provider_error = None
            except SmsProviderUnavailable as exc:
                provider = None
                provider_name = "unconfigured"
                delivery_mode = "real"
                provider_error = str(exc)
            now = datetime.now().isoformat(timespec="seconds")
            try:
                cursor = connection.execute(
                    "INSERT INTO sms_messages(work_order_id,maintainer_id,event_type,phone,content,template_params,provider,delivery_mode,status,idempotency_key,triggered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        order_id,
                        maintainer["id"],
                        event_type,
                        maintainer["phone"],
                        content,
                        json.dumps(params, ensure_ascii=False),
                        provider_name,
                        delivery_mode,
                        "pending",
                        idempotency_key,
                        actor,
                        now,
                    ),
                )
                message_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT sm.*, m.name AS maintainer_name FROM sms_messages sm "
                    "LEFT JOIN maintainers m ON m.id=sm.maintainer_id "
                    "WHERE sm.idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return self.message_dict(existing)
                raise

        if provider_error:
            with db() as connection:
                connection.execute(
                    "UPDATE sms_messages SET status='failed',error_message=?,sent_at=NULL WHERE id=?",
                    (provider_error, message_id),
                )
        else:
            try:
                provider_result = provider.send(
                    maintainer["phone"], event_type, params, idempotency_key
                )
                send_status = "sent" if provider_result.status == "sent" else "failed"
                error_message = provider_result.error_message
                if send_status == "failed" and not error_message:
                    error_message = "短信供应商返回失败"
                provider_name = provider_result.provider or provider_name
                delivery_mode = provider_result.delivery_mode or delivery_mode
                provider_message_id = provider_result.provider_message_id
            except Exception as exc:
                send_status = "failed"
                error_message = str(exc) or "短信供应商调用失败"
                provider_message_id = None
            with db() as connection:
                connection.execute(
                    "UPDATE sms_messages SET provider=?,delivery_mode=?,status=?,provider_message_id=?,error_message=?,sent_at=? WHERE id=?",
                    (
                        provider_name,
                        delivery_mode,
                        send_status,
                        provider_message_id,
                        error_message,
                        datetime.now().isoformat(timespec="seconds")
                        if send_status == "sent"
                        else None,
                        message_id,
                    ),
                )
        row = self._load_message(message_id)
        return self.message_dict(row)

    def retry_message(
        self,
        message_id: int,
        triggered_by: Union[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        actor = (
            triggered_by.get("username", "system")
            if isinstance(triggered_by, dict)
            else str(triggered_by)
        )
        row = self._load_message(message_id)
        if not row:
            raise HTTPException(404, "短信记录不存在")
        if row["status"] != "failed":
            raise HTTPException(409, "只有发送失败的短信可以重试")
        try:
            params = json.loads(row["template_params"] or "{}")
            if not isinstance(params, dict):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            error_message = "短信模板参数已损坏，无法重试"
            with db() as connection:
                connection.execute(
                    "UPDATE sms_messages SET error_message=?,triggered_by=? WHERE id=?",
                    (error_message, actor, message_id),
                )
            return self.message_dict(self._load_message(message_id))
        try:
            provider = get_sms_provider()
            provider_name = provider.name
            delivery_mode = provider.delivery_mode
            result = provider.send(
                row["phone"], row["event_type"], params, row["idempotency_key"]
            )
            status = "sent" if result.status == "sent" else "failed"
            error_message = result.error_message or (
                "短信供应商返回失败" if status == "failed" else None
            )
            provider_message_id = result.provider_message_id
            provider_name = result.provider or provider_name
            delivery_mode = result.delivery_mode or delivery_mode
        except Exception as exc:
            status = "failed"
            error_message = str(exc) or "短信供应商调用失败"
            provider_message_id = None
            provider_name, delivery_mode = _sms_failure_mode()
        with db() as connection:
            connection.execute(
                "UPDATE sms_messages SET provider=?,delivery_mode=?,status=?,provider_message_id=?,error_message=?,triggered_by=?,sent_at=? WHERE id=?",
                (
                    provider_name,
                    delivery_mode,
                    status,
                    provider_message_id,
                    error_message,
                    actor,
                    datetime.now().isoformat(timespec="seconds")
                    if status == "sent"
                    else None,
                    message_id,
                ),
            )
        return self.message_dict(self._load_message(message_id))

    def list_messages(
        self,
        work_order_id: Optional[int] = None,
        status: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        clauses, params = ["1=1"], []
        if work_order_id is not None:
            clauses.append("sm.work_order_id=?")
            params.append(work_order_id)
        if status:
            if status not in SMS_STATUSES:
                raise HTTPException(400, "无效的短信状态")
            clauses.append("sm.status=?")
            params.append(status)
        if created_from:
            clauses.append("sm.created_at>=?")
            params.append(
                created_from if "T" in created_from else f"{created_from}T00:00:00"
            )
        if created_to:
            clauses.append("sm.created_at<=?")
            params.append(
                created_to if "T" in created_to else f"{created_to}T23:59:59"
            )
        with db() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM sms_messages sm WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT sm.*, m.name AS maintainer_name
                FROM sms_messages sm
                LEFT JOIN maintainers m ON m.id=sm.maintainer_id
                WHERE {' AND '.join(clauses)}
                ORDER BY sm.id DESC LIMIT ? OFFSET ?
                """,
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "items": [self.message_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_message(self, message_id: int) -> Dict[str, Any]:
        row = self._load_message(message_id)
        if not row:
            raise HTTPException(404, "短信记录不存在")
        return self.message_dict(row)
