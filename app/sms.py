"""SMS providers and message templates for work-order notifications.

The default provider is deliberately offline.  A real provider can implement
the same interface later without changing work-order state transitions.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


MESSAGE_TEMPLATES = {
    "assigned": "【声网先知】工单 {order_code} 已分配给您：{title}。设备：{device_name}，优先级：{priority}，请及时处理。",
    "completed": "【声网先知】工单 {order_code} 已标记维修完成，待复检。设备：{device_name}。",
    "closed": "【声网先知】工单 {order_code} 已复检通过并关闭。设备：{device_name}。",
}


class SmsProvider(Protocol):
    name: str
    delivery_mode: str

    def send(
        self,
        phone: str,
        event_type: str,
        template_params: Mapping[str, Any],
        idempotency_key: str,
    ) -> "SmsSendResult":
        ...


@dataclass(frozen=True)
class SmsSendResult:
    status: str
    provider: str
    delivery_mode: str
    provider_message_id: str | None = None
    error_message: str | None = None


class SmsProviderUnavailable(RuntimeError):
    """Raised when real sending was requested without a configured provider."""


def render_message(event_type: str, template_params: Mapping[str, Any]) -> str:
    try:
        template = MESSAGE_TEMPLATES[event_type]
    except KeyError as exc:
        raise ValueError(f"不支持的短信事件：{event_type}") from exc
    try:
        return template.format_map(template_params)
    except KeyError as exc:
        raise ValueError(f"短信模板缺少参数：{exc.args[0]}") from exc


class DemoSmsProvider:
    name = "demo"
    delivery_mode = "demo"

    def send(
        self,
        phone: str,
        event_type: str,
        template_params: Mapping[str, Any],
        idempotency_key: str,
    ) -> SmsSendResult:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
        return SmsSendResult(
            status="sent",
            provider=self.name,
            delivery_mode=self.delivery_mode,
            provider_message_id=f"DEMO-{digest}",
        )


def get_sms_provider() -> SmsProvider:
    """Return the configured provider, with an explicit offline default.

    No concrete external vendor is selected yet.  Setting a non-demo mode must
    fail visibly instead of silently claiming that a real SMS was sent.
    """
    mode = os.getenv("SOUNDNET_SMS_MODE", "demo").strip().lower()
    if mode in ("", "demo", "offline"):
        return DemoSmsProvider()
    raise SmsProviderUnavailable("未配置真实短信供应商，当前只能使用演示短信通道")
